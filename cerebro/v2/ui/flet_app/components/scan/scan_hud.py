"""Scan progress HUD for the dashboard home page."""

from __future__ import annotations

import asyncio
import logging
import re
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Optional, Set

import flet as ft
import flet.canvas as cv

from cerebro.engines.scan_stage import ScanStage
from cerebro.v2.ui.flet_app.pill_button_styles import (
    pill_filled_accent,
    pill_outlined_button_style,
    pill_text_button_style,
)
from cerebro.v2.ui.flet_app.theme import ThemeTokens

if TYPE_CHECKING:
    from cerebro.v2.ui.flet_app.services.state_bridge import StateBridge

_log = logging.getLogger(__name__)

_BAR_SLICES: int = 200
_BAR_HEIGHT: int = 28
_BAR_WIDTH: int = 520
_BAR_MARKER_TTL: float = 0.30


@dataclass
class ScanHUDCallbacks:
    on_cancel_scan: Callable[[ft.ControlEvent], None]
    on_pause_scan: Callable[[ft.ControlEvent], None]
    on_view_results: Callable[[ft.ControlEvent], None]
    on_view_partial_results: Callable[[ft.ControlEvent], None]
    on_home: Callable[[ft.ControlEvent], None]
    on_request_page_update: Callable[[], None]
    on_sync_pause_scan_hero_button: Callable[[], None]
    on_persist_incomplete_scan: Callable[..., None]
    on_show_snackbar: Callable[..., None]
    on_handle_repeated_io_failure: Callable[[str], None]
    on_set_main_panels_visible: Callable[[bool], None]
    on_show_cancelled_status: Callable[[], None]
    on_show_cancelled_results_banner: Callable[[str], None]
    on_hide_cancelled_results_banner: Callable[[], None]
    on_abort_scan_session: Callable[[], None]
    get_was_cancelled: Callable[[], bool]
    set_was_cancelled: Callable[[bool], None]
    get_cancel_complete_handled: Callable[[], bool]
    set_cancel_complete_handled: Callable[[bool], None]
    get_cancel_user_dismissed_choice: Callable[[], bool]
    set_cancel_user_dismissed_choice: Callable[[bool], None]
    get_cancel_watchdog_token: Callable[[], int]
    bump_cancel_watchdog_token: Callable[[], None]
    get_scan_accept_progress: Callable[[], bool]
    set_scan_accept_progress: Callable[[bool], None]
    get_scan_network_warn_shown: Callable[[], bool]
    set_scan_network_warn_shown: Callable[[bool], None]
    get_pending_partial_results: Callable[[], list]
    set_pending_partial_results: Callable[[list], None]
    get_pending_partial_mode: Callable[[], str]
    set_pending_partial_mode: Callable[[str], None]
    get_last_incomplete_persist_ts: Callable[[], float]
    set_last_incomplete_persist_ts: Callable[[float], None]


class ScanHUD(ft.Container):
    """Progress ring, timers, dual-phase card, chunk bar, and cancel fork UI."""

    _RING_INDETERMINATE_STAGES = frozenset({
        ScanStage.DISCOVERING,
        ScanStage.GROUPING_BY_SIZE,
        ScanStage.TIER_A_PREFILTER,
    })

    def __init__(
        self,
        bridge: "StateBridge",
        tokens: ThemeTokens,
        callbacks: ScanHUDCallbacks,
    ) -> None:
        super().__init__(expand=True, alignment=ft.Alignment(0, -0.25), visible=False)
        self._bridge = bridge
        self._t = tokens
        self._callbacks = callbacks
        self._scan_hud_snap: dict = {}
        self._scan_hud_stop = threading.Event()
        self._scan_timer_thread: Optional[threading.Thread] = None
        self._speed_points: deque[tuple[float, int]] = deque(maxlen=60)
        self._eta_smoothed_seconds: Optional[float] = None
        self._eta_last_stage: str = ""
        self._eta_last_update_ts: float = 0.0
        self._scan_timer_active: bool = False
        self._scan_elapsed_start: float = 0.0
        self._last_progress_elapsed_seconds: float = 0.0
        self._scan_files_catalogued: int = 0
        self._bar_slices: int = 0
        self._bar_active_markers: Set[int] = set()
        self._bar_is_complete: bool = False
        self._bar_last_dupes: int = 0
        self._headline_pulse_tick: int = 0
        self._counter_help_tip_base = (
            "Duplicate detection only reads files whose size matches at least one other file in "
            "the scan. With the hash cache on, comparison progress counts each candidate twice "
            "(cache prep plus content hashing)."
        )
        self._build_ui()

    @staticmethod
    def _safe_update(ctrl: ft.Control | None) -> None:
        if ctrl is None:
            return
        try:
            if ctrl.page is not None:
                ctrl.update()
        except RuntimeError:
            pass

    def _build_ui(self) -> None:
        t = self._t
        s = t.spacing
        _phase_track_w = 560
        self._phase_prep_status = ft.Text(
            "Step 1 · Indexing — starting…",
            size=t.typography.size_sm,
            weight=ft.FontWeight.W_600,
            color=t.colors.fg2,
            width=_phase_track_w,
        )
        self._phase_hash_title = ft.Text(
            "Step 2 — Compare contents (hash)",
            size=t.typography.size_sm,
            weight=ft.FontWeight.W_600,
            color=t.colors.fg_muted,
        )
        self._phase_hash_bar = ft.ProgressBar(
            width=_phase_track_w,
            bar_height=8,
            color="#00BFA5",
            bgcolor=t.colors.bg3,
            value=None,
        )
        self._phase_hash_caption = ft.Text(
            "Waiting — runs after step 1 finishes.",
            size=t.typography.size_xs,
            color=t.colors.fg_muted,
        )
        self._autosave_hint = ft.Text(
            "Interrupted scans checkpoint about every 15s while work is in flight — "
            "you can close the app and resume from Home.",
            size=t.typography.size_xs,
            color=t.colors.fg_muted,
            italic=True,
            width=_phase_track_w,
        )
        self._scan_phase_card = ft.Container(
            content=ft.Column(
                [
                    self._phase_prep_status,
                    ft.Container(height=s.xs),
                    self._phase_hash_title,
                    self._phase_hash_bar,
                    self._phase_hash_caption,
                    ft.Container(height=s.xs),
                    self._autosave_hint,
                ],
                spacing=s.xs,
                tight=True,
                horizontal_alignment=ft.CrossAxisAlignment.START,
            ),
            width=600,
            padding=s.md,
            border_radius=12,
            border=ft.border.all(1, ft.Colors.with_opacity(0.35, t.colors.border)),
            bgcolor=ft.Colors.with_opacity(0.08, t.colors.bg3),
        )
        self._progress_detail = ft.Text(
            "",
            color=t.colors.fg_muted,
            size=t.typography.size_xs,
            text_align=ft.TextAlign.CENTER,
        )

        # Circular scan progress view — swaps in over main content during active scan
        self._ring_default_color = "#00BFA5"
        self._ring = ft.ProgressRing(
            width=80,
            height=80,
            stroke_width=7,
            color=self._ring_default_color,
            value=None,  # indeterminate until first progress callback
        )
        self._ring_label = ft.Text(
            "Preparing scan…",
            size=t.typography.size_xl,
            weight=ft.FontWeight.BOLD,
            color=t.colors.fg,
            text_align=ft.TextAlign.CENTER,
            animate_opacity=ft.Animation(800, ft.AnimationCurve.EASE_IN_OUT),
        )
        self._ring_phase_label = ft.Text(
            "",
            size=t.typography.size_sm,
            color=t.colors.fg_muted,
            text_align=ft.TextAlign.CENTER,
            width=520,
        )
        self._scan_mode_run_label = ft.Text(
            "",
            size=t.typography.size_sm,
            color=t.colors.fg2,
            text_align=ft.TextAlign.CENTER,
            width=520,
        )
        self._ring_counter = ft.Text(
            "Processed: 0 / 0",
            size=t.typography.size_md,
            color=t.colors.fg2,
            font_family="Courier New",
            text_align=ft.TextAlign.CENTER,
        )
        self._counter_help_tip_base = (
            "Duplicate detection only reads files whose size matches at least one other file in "
            "the scan. With the hash cache on, comparison progress counts each candidate twice "
            "(cache prep plus content hashing)."
        )
        self._ring_counter_tip = ft.IconButton(
            icon=ft.icons.Icons.INFO_OUTLINE,
            tooltip=self._counter_help_tip_base,
            icon_size=18,
            icon_color=t.colors.fg_muted,
            visible=False,
            padding=ft.padding.only(left=2),
            style=ft.ButtonStyle(padding=0),
        )
        self._ring_counter_row = ft.Row(
            [
                self._ring_counter,
                self._ring_counter_tip,
            ],
            alignment=ft.MainAxisAlignment.CENTER,
            spacing=2,
            vertical_alignment=ft.CrossAxisAlignment.START,
            tight=True,
        )
        self._hash_algo_label = ft.Text(
            "",
            size=t.typography.size_xs,
            color=t.colors.fg_muted,
            text_align=ft.TextAlign.CENTER,
            visible=False,
        )
        self._scan_elapsed_timer_icon = ft.Icon(
            ft.icons.Icons.TIMER_OUTLINED,
            size=20,
            color=t.colors.accent,
        )
        self._scan_elapsed_clock = ft.Text(
            "0:00",
            size=t.typography.size_xxl,
            weight=ft.FontWeight.W_800,
            color=t.colors.fg,
            text_align=ft.TextAlign.START,
        )
        self._ring_timer = ft.Text(
            "",
            size=t.typography.size_sm,
            weight=ft.FontWeight.W_500,
            color=t.colors.fg_muted,
            text_align=ft.TextAlign.START,
        )
        self._ring_path = ft.Text(
            "",
            size=t.typography.size_sm,
            color=t.colors.fg_muted,
            text_align=ft.TextAlign.START,
            no_wrap=True,
            overflow=ft.TextOverflow.ELLIPSIS,
            expand=True,
        )
        self._path_strip = ft.Container(
            content=self._ring_path,
            height=48,
            width=600,
            padding=ft.Padding.symmetric(horizontal=12, vertical=10),
            border_radius=8,
            border=ft.border.all(1, ft.Colors.with_opacity(0.28, t.colors.border)),
            bgcolor=ft.Colors.with_opacity(0.14, t.colors.bg3),
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
        )
        self._status_metric_row = ft.Row(
            [
                ft.Container(
                    content=self._ring,
                    alignment=ft.Alignment(0, 0),
                    width=88,
                    height=88,
                ),
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Text(
                                "Scan elapsed",
                                size=t.typography.size_xs,
                                color=t.colors.fg_muted,
                                weight=ft.FontWeight.W_500,
                            ),
                            ft.Row(
                                [
                                    self._scan_elapsed_timer_icon,
                                    self._scan_elapsed_clock,
                                ],
                                spacing=6,
                                tight=True,
                                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            ),
                            ft.Text(
                                "Pace & ETA",
                                size=t.typography.size_xs,
                                color=t.colors.fg_muted,
                                weight=ft.FontWeight.W_500,
                            ),
                            self._ring_timer,
                        ],
                        spacing=4,
                        tight=True,
                        horizontal_alignment=ft.CrossAxisAlignment.START,
                    ),
                    expand=True,
                    padding=ft.padding.only(left=s.sm),
                ),
            ],
            width=600,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        self._view_results_btn = ft.FilledButton(
            "Open Workspace",
            icon=ft.icons.Icons.CHECK_CIRCLE,
            on_click=self._callbacks.on_view_results,
            visible=False,
            style=pill_filled_accent(t, text_size=12, weight=ft.FontWeight.W_700),
        )
        self._view_partial_btn = ft.OutlinedButton(
            "View partial results",
            icon=ft.icons.Icons.CHECKLIST,
            on_click=self._callbacks.on_view_partial_results,
            style=pill_outlined_button_style(t),
        )
        self._partial_back_home_btn = ft.OutlinedButton(
            "Back to home",
            icon=ft.icons.Icons.HOME,
            on_click=self._callbacks.on_home,
            style=pill_outlined_button_style(t),
        )
        self._partial_results_row = ft.Row(
            [
                self._view_partial_btn,
                self._partial_back_home_btn,
            ],
            alignment=ft.MainAxisAlignment.CENTER,
            spacing=s.md,
            wrap=True,
            visible=False,
        )
        self._cancel_choice_headline = ft.Text(
            "What would you like to do next?",
            size=t.typography.size_xxl,
            weight=ft.FontWeight.W_800,
            color=t.colors.fg,
            text_align=ft.TextAlign.CENTER,
            width=560,
        )
        self._cancel_choice_sub = ft.Text(
            "",
            size=t.typography.size_sm,
            color=t.colors.fg2,
            text_align=ft.TextAlign.CENTER,
            width=560,
        )
        self._cancel_choice_panel = ft.Container(
            content=ft.Column(
                [
                    self._cancel_choice_headline,
                    self._cancel_choice_sub,
                    self._partial_results_row,
                ],
                spacing=s.md,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                tight=True,
            ),
            width=620,
            padding=ft.Padding.symmetric(horizontal=s.lg, vertical=s.lg + 4),
            border_radius=16,
            border=ft.border.all(2, ft.Colors.with_opacity(0.65, t.colors.warning)),
            bgcolor=ft.Colors.with_opacity(0.14, t.colors.warning),
            visible=False,
        )
        self._cancel_btn = ft.OutlinedButton(
            "Cancel Scan",
            icon=ft.icons.Icons.STOP,
            on_click=self._callbacks.on_cancel_scan,
            style=pill_outlined_button_style(t, danger=True),
        )
        self._pause_btn = ft.OutlinedButton(
            "Pause",
            icon=ft.icons.Icons.PAUSE,
            on_click=self._callbacks.on_pause_scan,
            style=pill_outlined_button_style(t),
        )
        self._btn_row = ft.Row(
            [self._pause_btn, self._cancel_btn],
            alignment=ft.MainAxisAlignment.CENTER,
            spacing=s.md,
        )
        self._bar_canvas = cv.Canvas(shapes=[], width=_BAR_WIDTH, height=_BAR_HEIGHT)
        self._bar_overlay = ft.Container(
            content=ft.Text(
                "",
                color=ft.Colors.WHITE,
                weight=ft.FontWeight.BOLD,
                size=13,
                text_align=ft.TextAlign.CENTER,
            ),
            alignment=ft.Alignment(0, 0),
            width=_BAR_WIDTH,
            height=_BAR_HEIGHT,
            visible=False,
        )
        self._bar_stack = ft.Stack(
            [self._bar_canvas, self._bar_overlay],
            width=_BAR_WIDTH,
            height=_BAR_HEIGHT,
        )
        self._bar_row = ft.Container(
            content=self._bar_stack,
            visible=False,
        )
        self._draw_bar()

        self.content = ft.Column(
            [
                self._ring_label,
                self._ring_phase_label,
                self._scan_mode_run_label,
                self._status_metric_row,
                self._scan_phase_card,
                self._ring_counter_row,
                self._hash_algo_label,
                self._progress_detail,
                self._path_strip,
                self._bar_row,
                self._btn_row,
                self._view_results_btn,
                self._cancel_choice_panel,
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            alignment=ft.MainAxisAlignment.START,
            spacing=s.lg,
        )
        self._draw_bar()

    @property
    def progress_snapshot(self) -> dict:
        return dict(self._scan_hud_snap or {})

    @property
    def bar_is_complete(self) -> bool:
        return self._bar_is_complete

    @property
    def scan_elapsed_start(self) -> float:
        return self._scan_elapsed_start

    @property
    def last_progress_elapsed_seconds(self) -> float:
        return self._last_progress_elapsed_seconds

    def apply_theme(self, tokens: ThemeTokens) -> None:
        self._t = tokens
        self._ring_label.color = tokens.colors.fg
        self._ring_phase_label.color = tokens.colors.fg_muted
        self._scan_mode_run_label.color = tokens.colors.fg2
        self._ring_timer.color = tokens.colors.fg_muted
        self._scan_elapsed_clock.color = tokens.colors.fg
        self._scan_elapsed_timer_icon.color = tokens.colors.accent
        self._ring_counter_tip.icon_color = tokens.colors.fg_muted
        self._phase_hash_caption.color = tokens.colors.fg_muted
        self._autosave_hint.color = tokens.colors.fg_muted
        self.apply_pill_chrome()

    def apply_pill_chrome(self) -> None:
        t = self._t
        self._view_results_btn.style = pill_filled_accent(t, text_size=12, weight=ft.FontWeight.W_700)
        self._view_partial_btn.style = pill_outlined_button_style(t)
        self._partial_back_home_btn.style = pill_text_button_style(t, variant="muted")
        self._cancel_btn.style = pill_outlined_button_style(t, danger=True)
        self._pause_btn.style = pill_outlined_button_style(t)
        for ctrl in (
            self._view_results_btn,
            self._view_partial_btn,
            self._partial_back_home_btn,
            self._cancel_btn,
            self._pause_btn,
        ):
            ScanHUD._safe_update(ctrl)

    def prepare_for_scan(self, scan_mode_label: str) -> None:
        self._scan_files_catalogued = 0
        self._last_progress_elapsed_seconds = 0.0
        self._bar_slices = 0
        self._bar_active_markers.clear()
        self._bar_is_complete = False
        self._bar_last_dupes = 0
        self._bar_row.visible = False
        self._bar_overlay.visible = False
        self._draw_bar()
        self._ring.value = None
        self._ring.color = ScanHUD._heat_color_for_ratio(0.0)
        self._ring_phase_label.value = ""
        self._scan_mode_run_label.value = scan_mode_label
        self._ring_counter.value = "Files found so far: 0"
        self._ring_counter_tip.visible = False
        self._ring_timer.value = ""
        self._scan_elapsed_clock.value = "0:00"
        self._hash_algo_label.value = ""
        self._hash_algo_label.visible = False
        self._ring_path.value = ""
        self._ring_label.value = "Preparing scan…"
        self._ring_label.opacity = 1.0
        self._headline_pulse_tick = 0
        self._progress_detail.value = "Duplicate candidates tracked: 0"
        self._update_dual_phase_bars(ScanStage.DISCOVERING, 0, 0)
        self._cancel_btn.text = "Cancel Scan"
        self._cancel_btn.disabled = False
        self._cancel_btn.visible = True
        self._pause_btn.text = "Pause"
        self._pause_btn.icon = ft.icons.Icons.PAUSE
        self._pause_btn.disabled = False
        self._pause_btn.visible = True
        self._view_results_btn.visible = False
        self._view_partial_btn.visible = True
        self._view_partial_btn.disabled = False
        self._callbacks.on_set_main_panels_visible(False)
        self.visible = True
        ScanHUD._safe_update(self)
        self._callbacks.set_last_incomplete_persist_ts(time.monotonic())
        self.start_elapsed_timer()
        self._speed_points.clear()
        self._eta_smoothed_seconds = None
        self._eta_last_stage = ""
        self._eta_last_update_ts = 0.0
        self._scan_elapsed_clock.value = self._scan_elapsed_clock_value()
        self._ring_timer.value = self._build_scan_timer_line()
        ScanHUD._safe_update(self._scan_elapsed_clock)
        ScanHUD._safe_update(self._ring_timer)

    def show_cancelling(self) -> None:
        self._pause_btn.visible = False
        self._cancel_btn.text = "Cancelling…"
        self._cancel_btn.disabled = True
        self._ring_label.value = "Cancelling…"
        self._ring_phase_label.value = "Stopping the engine safely — this can take a moment on large scans."
        self._ring_timer.value = "Cancel requested — waiting for engine to stop…"
        ScanHUD._safe_update(self)

    def update_cancel_watchdog(self) -> None:
        self._ring_phase_label.value = (
            "Still stopping the engine… large candidate sets can take longer to unwind."
        )
        self._ring_timer.value = "Cancel requested — waiting for terminal callback…"
        ScanHUD._safe_update(self)

    def complete_success(self, results: list, frozen_elapsed: str) -> None:
        self._update_dual_phase_bars(ScanStage.COMPLETE, 0, 0)
        self._ring.value = 1.0
        self._ring.color = ScanHUD._heat_color_for_ratio(1.0)
        ng = len(results)
        self._ring_phase_label.value = (
            "Assembling duplicate groups from hash results." if ng else "Finished — nothing to compare."
        )
        self._ring_label.value = (
            f"Scan complete — {ng:,} duplicate group(s) found."
            if ng > 0
            else "Scan complete — no duplicates found."
        )
        self._ring_counter.value = ""
        self._scan_mode_run_label.value = ""
        self._ring_timer.value = ""
        self._scan_elapsed_clock.value = frozen_elapsed
        self._ring_path.value = ""
        self._cancel_btn.visible = False
        self._pause_btn.visible = False
        self._view_results_btn.visible = True
        self._bar_is_complete = True
        self._bar_active_markers.clear()
        self._bar_row.visible = True
        self._ring_counter_tip.visible = False
        cast = self._bar_overlay.content
        if isinstance(cast, ft.Text):
            cast.value = (
                f"✓ {len(results):,} duplicate groups found"
                if ng > 0
                else "✓ No duplicate groups detected"
            )
        self._bar_overlay.visible = True
        self._draw_bar()
        ScanHUD._safe_update(self)
        self._ring_label.value = (
            f"Scan complete — {ng:,} duplicate group(s) found."
            if ng > 0
            else "Scan complete — no duplicates found."
        )
        self._ring_phase_label.value = (
            "Assembling duplicate groups from hash results." if ng else "Finished — nothing to compare."
        )
        self._ring_path.value = ""
        self._scan_elapsed_clock.value = frozen_elapsed
        ScanHUD._safe_update(self._ring_label)
        ScanHUD._safe_update(self._ring_phase_label)
        ScanHUD._safe_update(self._ring_path)
        ScanHUD._safe_update(self._scan_elapsed_clock)

    def complete_cancelled(self, results: list, mode: str, frozen_elapsed: str) -> None:
        self._finalize_cancel_choice_with_results(list(results), mode)
        if not results:
            self._ring_phase_label.value = "No duplicate groups could be found before cancellation."
        self._ring_label.value = "Scan cancelled"
        self._ring_path.value = ""
        self._scan_elapsed_clock.value = frozen_elapsed
        ScanHUD._safe_update(self)

    def on_scan_error(self) -> None:
        self.stop_elapsed_timer()
        self._ring_timer.value = ""
        self._scan_elapsed_clock.value = ""
        self._bar_row.visible = False
        self.visible = False
        self._callbacks.on_set_main_panels_visible(True)
        ScanHUD._safe_update(self)

    def dismiss_to_home(self) -> None:
        self.stop_elapsed_timer()
        self._ring_timer.value = ""
        self._scan_elapsed_clock.value = ""
        self._cancel_choice_panel.visible = False
        self._partial_results_row.visible = False
        self.visible = False
        self._callbacks.on_set_main_panels_visible(True)
        ScanHUD._safe_update(self)

    def hide_if_idle(self, *, is_scanning: bool) -> None:
        if self.visible and (not is_scanning or self._bar_is_complete):
            self.visible = False
            self._callbacks.on_set_main_panels_visible(True)
            self._view_results_btn.visible = False
            self._partial_results_row.visible = False
            self._cancel_btn.visible = False
            self._pause_btn.visible = False
            self._ring_timer.value = ""
            self._scan_elapsed_clock.value = ""
            self._ring_path.value = ""
            ScanHUD._safe_update(self)

    def start_elapsed_timer(self) -> None:
        self._start_scan_elapsed_timer()

    def stop_elapsed_timer(self) -> None:
        self._stop_scan_elapsed_timer()

    @staticmethod
    def _heat_color_for_ratio(ratio: float) -> str:
        """Interpolate ring color red → amber → green as ratio goes 0 → 1."""
        r = max(0.0, min(1.0, float(ratio)))
        red = (0xEF, 0x44, 0x44)
        amber = (0xF5, 0x9E, 0x0B)
        green = (0x22, 0xC5, 0x55)
        if r <= 0.5:
            t = r * 2.0
            rgb = tuple(int(red[i] + (amber[i] - red[i]) * t) for i in range(3))
        else:
            t = (r - 0.5) * 2.0
            rgb = tuple(int(amber[i] + (green[i] - amber[i]) * t) for i in range(3))
        return f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"

    def _scan_ring_heat_ratio(self, stage: str, scanned: int, total: int) -> float:
        """Map backend stage + counters to 0..1 for heat coloring."""
        if stage in (ScanStage.HASHING_PARTIAL, ScanStage.HASHING_FULL) and total > 0:
            return scanned / total
        if stage == ScanStage.DISCOVERING and total > 0:
            return scanned / total
        if stage in (ScanStage.GROUPING_BY_SIZE, ScanStage.TIER_A_PREFILTER):
            if stage == ScanStage.TIER_A_PREFILTER and total > 0:
                return min(scanned / total, 0.95)
            return 0.34
        if stage == ScanStage.DISCOVERING:
            return 0.06
        if total > 0:
            return min(scanned / total, 1.0)
        return 0.05

    @staticmethod
    def _normalize_scan_stage_for_ui(raw: object) -> str:
        """Coerce progress ``stage`` to ``ScanStage`` literals.

        The scan HUD uses strict equality on ``ScanStage`` constants. Engines that omit
        ``stage`` (empty default), use legacy names (``comparing``), or vary casing would
        otherwise show the generic "Scanning…" headline, empty timer copy, and "Waiting…"
        under step 2 while ``files_scanned`` / ``files_total`` still advance.
        """
        s = str(raw or "").strip()
        if not s:
            return ""
        key = s.lower().replace("-", "_").replace(" ", "_")
        while "__" in key:
            key = key.replace("__", "_")
        if key == "network_error":
            return "network_error"
        known = frozenset(
            {
                ScanStage.DISCOVERING,
                ScanStage.GROUPING_BY_SIZE,
                ScanStage.TIER_A_PREFILTER,
                ScanStage.HASHING_PARTIAL,
                ScanStage.HASHING_FULL,
                ScanStage.COMPLETE,
                ScanStage.CANCELLED,
            }
        )
        if key in known:
            return key
        aliases = {
            "tier_a": ScanStage.TIER_A_PREFILTER,
            "tier_a_prefilter": ScanStage.TIER_A_PREFILTER,
            "comparing": ScanStage.HASHING_PARTIAL,
            "hashing": ScanStage.HASHING_PARTIAL,
            "hashingpartial": ScanStage.HASHING_PARTIAL,
            "verifying": ScanStage.HASHING_FULL,
            "verifying_duplicates": ScanStage.HASHING_FULL,
            "analyzing_images": ScanStage.HASHING_PARTIAL,
            "extracting_text": ScanStage.HASHING_FULL,
            "reading_timestamps": ScanStage.DISCOVERING,
        }
        return aliases.get(key, key)

    def _scan_hud_strings(self, stage: str, scanned: int, total: int, files_catalogued: int) -> tuple[str, str, str]:
        """Return (main headline, short subtitle, counter line without throughput)."""
        cat = max(0, int(files_catalogued))
        if stage == ScanStage.DISCOVERING:
            if total == 0:
                return (
                    "Discovering files…",
                    "Listing every file path under your selected folders. Large drives can take several minutes here.",
                    f"Files found so far: {scanned:,}",
                )
            if scanned < total:
                return (
                    "Discovering files…",
                    f"Still listing paths ({scanned:,} of {total:,} so far).",
                    f"Files found so far: {scanned:,} / {total:,}",
                )
            return (
                "Discovering files…",
                f"Finished listing {scanned:,} file paths.",
                f"Found {scanned:,} files",
            )
        if stage == ScanStage.GROUPING_BY_SIZE:
            return (
                "Grouping by size…",
                f"Sorting {scanned:,} files into size buckets to find files that might be duplicates.",
                f"Grouped {scanned:,} files — finding same-size matches…",
            )
        if stage == ScanStage.TIER_A_PREFILTER:
            return (
                "Pre-filtering same-size files…",
                "Reading a small prefix of each candidate to drop obvious non-matches before hashing.",
                f"Pre-filter: {scanned:,} / {total:,} candidates" if total > 0 else "Pre-filtering candidates…",
            )
        if stage == ScanStage.HASHING_PARTIAL:
            return (
                "Comparing file contents…",
                "",
                f"Comparing candidates: {scanned:,} / {total:,}",
            )
        if stage == ScanStage.HASHING_FULL:
            return (
                "Verifying duplicates…",
                "",
                f"Deep comparison: {scanned:,} / {total:,}",
            )
        if stage == ScanStage.COMPLETE:
            return ("Finishing up…", "Assembling duplicate groups from hash results.", "")
        return ("Scanning…", "", "Working…")

    def _update_counter_help_tooltip(self, stage: str, scanned: int, total: int, files_catalogued: int) -> None:
        cat = max(0, int(files_catalogued))
        show = stage in (
            ScanStage.HASHING_PARTIAL,
            ScanStage.HASHING_FULL,
        ) and total > 0 and total > cat * 1.12
        self._ring_counter_tip.visible = show
        if show:
            n_cand = total // 2 if total % 2 == 0 else 0
            if n_cand <= 0:
                n_cand = scanned if scanned > 0 else 0
            self._ring_counter_tip.tooltip = (
                f"{self._counter_help_tip_base}\n\n"
                f"You listed {cat:,} file paths here. Roughly twice the comparing-total (~{total:,}) matches "
                f"same-size duplicate candidates (~{n_cand:,}) when dual-pass cache prep is counted."
            )

    def _reset_cancel_choice_for_new_scan(self) -> None:
        self._callbacks.set_cancel_complete_handled(False)
        self._callbacks.set_cancel_user_dismissed_choice(False)
        self._cancel_choice_panel.visible = False
        self._cancel_choice_sub.value = ""
        self._partial_results_row.visible = False
        self._view_partial_btn.disabled = False
        self._view_partial_btn.text = "View partial results"
        try:
            self._view_partial_btn.tooltip = None
        except Exception:
            pass
        self._view_partial_btn.style = pill_outlined_button_style(self._t)

    def reset_cancel_choice_for_new_scan(self) -> None:
        self._reset_cancel_choice_for_new_scan()

    def sync_pause_button(self, *, is_paused: bool, is_scanning: bool) -> None:
        """Update the pause button to reflect current scan state.

        Called by the dashboard whenever scan paused/resumed state changes.
        """
        t = self._t
        if not is_scanning:
            self._pause_btn.visible = False
            ScanHUD._safe_update(self._pause_btn)
            return
        if is_paused:
            self._pause_btn.text = "Continue"
            self._pause_btn.icon = ft.icons.Icons.PLAY_ARROW
            self._pause_btn.style = pill_outlined_button_style(t, success=True)
        else:
            self._pause_btn.text = "Pause"
            self._pause_btn.icon = ft.icons.Icons.PAUSE
            self._pause_btn.style = pill_outlined_button_style(t)
        self._pause_btn.visible = True
        self._pause_btn.disabled = False
        ScanHUD._safe_update(self._pause_btn)

    def _present_cancel_waiting_for_results(self, *, phase_files: int) -> None:
        """Stop UI: stay on scan surface with a clear fork until the engine reports partial groups."""
        t = self._t
        frozen_elapsed = ScanHUD._fmt_elapsed_compact(
            max(0.0, time.monotonic() - self._scan_elapsed_start)
        )
        self._stop_scan_elapsed_timer()
        try:
            self._scan_elapsed_clock.value = f"Total {frozen_elapsed}"
        except Exception:
            pass
        self._ring.value = None
        self._ring.color = "#F59E0B"
        self._ring_label.value = "Scan cancelled"
        self._ring_label.opacity = 1.0
        self._ring_phase_label.value = ""
        self._ring_timer.value = ""
        self._ring_path.value = ""
        self._ring_counter_tip.visible = False
        self._cancel_btn.visible = False
        self._pause_btn.visible = False
        self._view_results_btn.visible = False
        self._cancel_choice_headline.value = "What would you like to do next?"
        self._cancel_choice_sub.value = (
            "The scanner is finishing the stop. When partial duplicate groups are ready, "
            "the primary button below will unlock. You can return home at any time — this screen stays here until you choose."
        )
        self._view_partial_btn.text = "View partial results"
        self._view_partial_btn.disabled = True
        self._view_partial_btn.tooltip = "Unlocks automatically when the engine reports what it found before the stop."
        self._view_partial_btn.style = pill_outlined_button_style(t)
        self._view_partial_btn.visible = True
        self._partial_back_home_btn.visible = True
        self._partial_results_row.visible = True
        self._cancel_choice_panel.visible = True
        self.visible = True
        self._callbacks.on_set_main_panels_visible(False)
        self._ring_counter.value = (
            f"Last reported step: {phase_files:,} files in this phase."
            if phase_files
            else "Scan interrupted by your request."
        )
        self._scan_hud_snap = dict(self._scan_hud_snap)
        self._scan_hud_snap["rate"] = None

    def _finalize_cancel_choice_with_results(self, results: list, mode: str) -> None:
        """Engine has returned — present an explicit review vs home decision (stays on scan view)."""
        self._stop_scan_elapsed_timer()
        self._ring.value = None
        self._ring.color = "#F59E0B"
        self._ring_label.value = "Scan cancelled"
        self._ring_label.opacity = 1.0
        self._ring_path.value = ""
        self._ring_counter_tip.visible = False
        self._callbacks.set_pending_partial_results(list(results))
        self._callbacks.set_pending_partial_mode(mode)
        self._callbacks.set_cancel_complete_handled(True)
        t = self._t
        ng = len(results)
        self._cancel_choice_headline.value = "What would you like to do next?"
        if ng > 0:
            self._cancel_choice_sub.value = (
                f"We found {ng:,} duplicate group(s) before the stop. "
                "Open the review page to inspect them, or go home to return to the dashboard."
            )
            self._view_partial_btn.disabled = False
            self._view_partial_btn.text = f"Open review — {ng:,} partial group(s)"
            try:
                self._view_partial_btn.tooltip = None
            except Exception:
                pass
            self._view_partial_btn.style = pill_filled_accent(
                t,
                padding=ft.Padding.symmetric(horizontal=22, vertical=12),
                text_size=t.typography.size_md,
                weight=ft.FontWeight.W_700,
                border_radius=999,
            )
        else:
            self._cancel_choice_sub.value = (
                "No duplicate groups were ready when the scan stopped — there is nothing to open in review."
            )
            self._view_partial_btn.disabled = True
            self._view_partial_btn.text = "View partial results"
            self._view_partial_btn.tooltip = "Nothing to show for this cancelled run."
            self._view_partial_btn.style = pill_outlined_button_style(t)
        self._ring_phase_label.value = ""
        self._ring_counter.value = ""
        self._ring_timer.value = ""
        self._scan_mode_run_label.value = ""
        self._cancel_btn.visible = False
        self._pause_btn.visible = False
        self._view_results_btn.visible = False
        self._partial_results_row.visible = True
        self._cancel_choice_panel.visible = True
        self.visible = True
        self._callbacks.on_set_main_panels_visible(False)
        self._scan_hud_snap = dict(self._scan_hud_snap)
        self._scan_hud_snap["rate"] = None
        try:
            self._scan_elapsed_clock.value = f"Total {ScanHUD._fmt_elapsed_compact(max(0.0, time.monotonic() - self._scan_elapsed_start))}"
        except Exception:
            pass

        if self._callbacks.get_cancel_user_dismissed_choice():
            self._callbacks.set_cancel_user_dismissed_choice(False)
            self._cancel_choice_panel.visible = False
            self._partial_results_row.visible = False
            self.visible = False
            self._callbacks.on_set_main_panels_visible(True)
            if ng > 0:
                self._callbacks.on_show_cancelled_results_banner(
                    f"Partial scan: {ng:,} duplicate group(s) are ready — open from this banner when you want."
                )
            self._callbacks.on_show_cancelled_status()
            return

    def _update_dual_phase_bars(
        self,
        stage: str,
        scanned: int,
        total: int,
    ) -> None:
        """Step 1 is text-only (no dead full bar). Step 2 keeps the live progress bar."""
        t = self._t
        sc = max(0, int(scanned))
        tot = max(0, int(total))
        catalogued = max(0, int(self._scan_files_catalogued))

        if stage == ScanStage.DISCOVERING:
            self._phase_prep_status.color = t.colors.accent
            self._phase_hash_title.value = "Step 2 — Compare contents (hash)"
            self._phase_hash_title.color = t.colors.fg_muted
            if tot > 0:
                self._phase_prep_status.value = (
                    f"Step 1 · Indexing — {sc:,} / {tot:,} paths listed "
                    "(estimate can still change while discovery runs)."
                )
            else:
                self._phase_prep_status.value = f"Step 1 · Indexing — {sc:,} paths discovered so far…"
            self._phase_hash_bar.value = None
            self._phase_hash_caption.value = (
                "Not started — hashing runs only after paths are indexed and same-size groups are built."
            )
        elif stage == ScanStage.GROUPING_BY_SIZE:
            self._phase_prep_status.color = t.colors.accent
            self._phase_hash_title.value = "Step 2 — Compare contents (hash)"
            self._phase_hash_title.color = t.colors.fg_muted
            self._phase_prep_status.value = (
                f"Step 1 · Indexing — grouping {sc:,} files by size "
                "(finding paths that could be duplicate candidates)."
            )
            self._phase_hash_bar.value = 0
            self._phase_hash_caption.value = "Not started — waits for grouping to finish."
        elif stage == ScanStage.TIER_A_PREFILTER:
            self._phase_prep_status.color = t.colors.success
            self._phase_prep_status.value = (
                f"Step 1 · Indexing — complete ({catalogued:,} paths in scope)."
            )
            self._phase_hash_title.value = "Step 2 — Pre-filter (prefix read)"
            self._phase_hash_title.color = t.colors.accent
            if tot > 0:
                ratio = min(max(sc / tot, 0.0), 1.0)
                self._phase_hash_bar.value = ratio
                self._phase_hash_caption.value = (
                    f"Pre-filter work: {sc:,} / {tot:,} ({ratio * 100:.1f}% — before content hashing)."
                )
            else:
                self._phase_hash_bar.value = 0
                self._phase_hash_caption.value = "Preparing pre-filter…"
        elif stage in (ScanStage.HASHING_PARTIAL, ScanStage.HASHING_FULL):
            self._phase_prep_status.color = t.colors.success
            self._phase_prep_status.value = (
                f"Step 1 · Indexing — complete ({catalogued:,} paths in scope). "
                "No further work in this step."
            )
            self._phase_hash_title.value = "Step 2 — Compare contents (hash)"
            self._phase_hash_title.color = t.colors.accent
            if tot > 0:
                ratio = min(max(sc / tot, 0.0), 1.0)
                self._phase_hash_bar.value = ratio
                self._phase_hash_caption.value = (
                    f"Work units: {sc:,} / {tot:,} ({ratio * 100:.1f}% of this hashing step only — "
                    f"not the whole scan until this fills)."
                )
            else:
                self._phase_hash_bar.value = None
                self._phase_hash_caption.value = "Preparing comparisons (total not reported yet)…"
        elif stage == ScanStage.COMPLETE:
            self._phase_prep_status.color = t.colors.success
            self._phase_prep_status.value = (
                f"Step 1 · Indexing — complete ({catalogued:,} paths in scope)."
            )
            self._phase_hash_title.color = t.colors.success
            self._phase_hash_bar.value = 1.0
            self._phase_hash_caption.value = "Hashing passes finished — assembling duplicate groups."
        else:
            self._phase_prep_status.color = t.colors.fg2
            self._phase_prep_status.value = "Step 1 · Indexing — preparing…"
            self._phase_hash_title.color = t.colors.fg_muted
            self._phase_hash_bar.value = None
            self._phase_hash_caption.value = "Waiting…"

    def _path_strip_caption(self) -> str:
        """Latest file path, or stage-based text so long phases still feel alive."""
        snap = self._scan_hud_snap or {}
        st = str(snap.get("stage") or "")
        raw = str(snap.get("current_file_path") or snap.get("current_file") or "").strip()
        if raw:
            if raw.lower().startswith("network path unreachable"):
                return raw
            if len(raw) > 110:
                return f"Scanning: {raw[:48]}…{raw[-56:]}"
            return f"Scanning: {raw}"
        tot = int(snap.get("total") or 0)
        scanned = int(snap.get("scanned") or 0)
        t_scope = int(snap.get("total_files_in_scope") or 0)
        proc = int(snap.get("files_processed") or scanned or 0)
        cand = int(snap.get("candidates_found") or 0)
        cat = int(snap.get("files_catalogued") or 0)
        if st == ScanStage.DISCOVERING:
            if t_scope > 0:
                return f"Discovering — {proc:,} / {t_scope:,} paths catalogued"
            return f"Discovering — {proc:,} paths indexed"
        if st == ScanStage.GROUPING_BY_SIZE and tot > 0:
            return (
                f"Grouping by size — {scanned:,} / {tot:,} files "
                f"(per-path lines resume as hashing reports each file)"
            )
        if st == ScanStage.TIER_A_PREFILTER and tot > 0:
            return f"Pre-filtering — {scanned:,} / {tot:,} same-size candidates"
        if st in (ScanStage.HASHING_PARTIAL, ScanStage.HASHING_FULL):
            algo = str(snap.get("active_hash_algorithm") or "")
            suf = f" · {algo}" if algo else ""
            if tot > 0:
                extra = f" · {cand:,} candidates" if cand else ""
                return f"Hashing — {scanned:,} / {tot:,} work units{extra}{suf}"
            return f"Hashing — {cat:,} paths in scope{suf}"
        if st == ScanStage.COMPLETE:
            return "Finishing — assembling duplicate groups…"
        return "Preparing scan…"

    @staticmethod
    def _extract_unreachable_root(message: str) -> str:
        text = str(message or "").strip()
        m = re.search(r"Network path unreachable:\s*(.+)$", text)
        if not m:
            return ""
        return str(m.group(1)).strip()

    def update_progress(self, data: dict) -> None:
        if not self._callbacks.get_scan_accept_progress():
            return
        raw_stage = data.get("stage", "")
        stage = ScanHUD._normalize_scan_stage_for_ui(raw_stage)
        if stage and stage not in frozenset(
            {
                ScanStage.DISCOVERING,
                ScanStage.GROUPING_BY_SIZE,
                ScanStage.TIER_A_PREFILTER,
                ScanStage.HASHING_PARTIAL,
                ScanStage.HASHING_FULL,
                ScanStage.COMPLETE,
                ScanStage.CANCELLED,
                "network_error",
            }
        ):
            _log.warning("Unknown scan stage %r (normalized=%r); HUD may show generic copy", raw_stage, stage)
        state = data.get("state", "")
        scanned = data.get("files_scanned", 0) or 0
        total = data.get("files_total", 0) or 0
        current_file = str(data.get("current_file", "") or "")
        current_file_path = str(data.get("current_file_path", "") or current_file)
        total_files_in_scope = int(
            data.get("totalFilesInScope", data.get("total_files_in_scope", 0))
            or data.get("files_total", 0)
            or 0
        )
        files_processed = int(
            data.get("filesProcessed", data.get("files_processed", 0))
            or data.get("files_scanned", 0)
            or 0
        )
        candidates_found = int(
            data.get("candidatesFound", data.get("candidates_found", 0))
            or data.get("duplicates_found", 0)
            or 0
        )
        rate = data.get("rate")  # None until backend has enough samples
        active_hash_algorithm = str(
            data.get("activeHashAlgorithm", data.get("active_hash_algorithm", "")) or ""
        )

        _log.debug("UI progress recv: stage=%s scanned=%d total=%d", stage, scanned, total)

        if stage == "network_error":
            if not self._callbacks.get_scan_network_warn_shown():
                self._callbacks.set_scan_network_warn_shown(True)
                try:
                    self._callbacks.on_show_snackbar(
                        "Some paths became unavailable — skipped or retried files can make this run incomplete.",
                        info=True,
                    )
                except Exception:
                    pass
            root = self._extract_unreachable_root(current_file)
            if root:
                self._callbacks.on_handle_repeated_io_failure(root)
                self._callbacks.on_sync_pause_scan_hero_button()
            if current_file_path or current_file:
                self._ring_path.value = str(current_file_path or current_file)
            return

        # Ignore a late "complete" tick from the scanner after the user cancelled —
        # otherwise the HUD briefly shows "Finishing up…" with no terminal event.
        if self._callbacks.get_was_cancelled() and stage == ScanStage.COMPLETE and state != "cancelled":
            return

        # Handle cancelled terminal event from progress stream (may arrive before on_complete).
        if state == "cancelled" or stage == ScanStage.CANCELLED:
            self._callbacks.bump_cancel_watchdog_token()
            if self._callbacks.get_cancel_complete_handled():
                self._callbacks.on_sync_pause_scan_hero_button()
                self._callbacks.on_request_page_update()
                return
            self._callbacks.set_was_cancelled(True)
            self._cancel_btn.text = "Cancel Scan"
            self._cancel_btn.disabled = False
            interrupt_snap = {
                "stage": str(stage or ""),
                "scanned": int(scanned or 0),
                "total": int(total or 0),
                "total_files_in_scope": int(total_files_in_scope),
                "files_processed": int(files_processed),
                "candidates_found": int(candidates_found),
            }
            self._present_cancel_waiting_for_results(phase_files=int(scanned or 0))
            try:
                self._callbacks.on_persist_incomplete_scan(
                    status="interrupted",
                    progress_snapshot=interrupt_snap,
                )
            except Exception:
                _log.debug("persist interrupted snapshot failed", exc_info=True)
            self._callbacks.on_sync_pause_scan_hero_button()
            self._callbacks.on_request_page_update()
            return

        if stage in (
            ScanStage.DISCOVERING,
            ScanStage.GROUPING_BY_SIZE,
            ScanStage.TIER_A_PREFILTER,
        ):
            self._scan_files_catalogued = max(
                self._scan_files_catalogued, int(scanned), int(total)
            )
        elif stage in (ScanStage.HASHING_PARTIAL, ScanStage.HASHING_FULL):
            # Discovery can finish without a HUD tick; keep Step 1 "paths in scope" honest.
            tscope = int(total_files_in_scope or 0)
            fproc = int(files_processed or 0)
            self._scan_files_catalogued = max(
                self._scan_files_catalogued,
                tscope,
                fproc,
            )

        main, sub, counter_core = self._scan_hud_strings(
            stage, int(scanned), int(total), self._scan_files_catalogued
        )
        self._ring_label.value = main
        self._ring_phase_label.value = sub
        self._update_counter_help_tooltip(stage, int(scanned), int(total), self._scan_files_catalogued)

        # Indeterminate ring only during directory discovery and size grouping.
        if stage in self._RING_INDETERMINATE_STAGES:
            self._ring.value = None
        elif total > 0 and scanned >= 0:
            self._ring.value = min(scanned / total, 0.999)  # never pre-flash 100%
        else:
            self._ring.value = None

        self._ring.color = self._heat_color_for_ratio(self._scan_ring_heat_ratio(stage, scanned, total))

        self._scan_hud_snap = {
            "stage": stage,
            "scanned": int(scanned),
            "total": int(total),
            "rate": (
                float(rate)
                if (stage in (ScanStage.HASHING_PARTIAL, ScanStage.HASHING_FULL) and rate is not None and float(rate) > 0)
                else None
            ),
            "files_catalogued": int(self._scan_files_catalogued),
            "current_file": current_file,
            "current_file_path": current_file_path,
            "total_files_in_scope": total_files_in_scope,
            "files_processed": files_processed,
            "candidates_found": candidates_found,
            "active_hash_algorithm": active_hash_algorithm,
        }

        counter = counter_core

        self._ring_counter.value = counter

        self._ring_path.value = self._path_strip_caption()

        self._update_dual_phase_bars(stage, int(scanned), int(total))
        self._progress_detail.value = f"Duplicate candidates tracked: {candidates_found:,}"
        if active_hash_algorithm and stage in (ScanStage.HASHING_PARTIAL, ScanStage.HASHING_FULL):
            self._hash_algo_label.value = f"Hash algorithm: {active_hash_algorithm}"
            self._hash_algo_label.visible = True
        else:
            self._hash_algo_label.value = ""
            self._hash_algo_label.visible = False

        try:
            self._last_progress_elapsed_seconds = float(data.get("elapsed_seconds", 0) or 0.0)
        except (TypeError, ValueError):
            self._last_progress_elapsed_seconds = 0.0
        mono_elapsed = (
            (time.monotonic() - self._scan_elapsed_start) if self._scan_timer_active else 0.0
        )
        self._scan_elapsed_clock.value = ScanHUD._fmt_elapsed_compact(
            max(0.0, mono_elapsed, self._last_progress_elapsed_seconds)
        )
        self._ring_timer.value = self._build_scan_timer_line()

        # Canvas chunk bar — visible only during hashing phases.
        is_hashing = stage in (ScanStage.HASHING_PARTIAL, ScanStage.HASHING_FULL)
        if is_hashing and total > 0:
            self._bar_row.visible = True
            new_slices = min(_BAR_SLICES, int(scanned / total * _BAR_SLICES))
            self._bar_slices = new_slices
            dupes = int(data.get("duplicates_found", 0) or 0)
            if dupes > self._bar_last_dupes:
                self._flash_bar_marker(max(0, new_slices - 1))
                self._bar_last_dupes = dupes
            else:
                self._draw_bar()
        else:
            if not is_hashing:
                self._bar_row.visible = False
                self._bar_slices = 0
                self._draw_bar()

        self._callbacks.on_sync_pause_scan_hero_button()
        self._callbacks.on_request_page_update()

    def _draw_bar(self) -> None:
        w = float(_BAR_WIDTH)
        h = float(_BAR_HEIGHT)
        if self._bar_is_complete:
            self._bar_canvas.shapes = [
                cv.Rect(0, 0, w, h, paint=ft.Paint(color=ft.Colors.GREEN)),
            ]
        else:
            n = _BAR_SLICES
            slice_w = max(2.0, w / n)
            shapes: list = []
            for i in range(n):
                color = ft.Colors.AMBER_600 if i < self._bar_slices else ft.Colors.GREY_800
                shapes.append(cv.Rect(i * slice_w, 0, slice_w - 1, h, paint=ft.Paint(color=color)))
                if i in self._bar_active_markers:
                    marker_w = max(2.0, slice_w / 2)
                    shapes.append(cv.Rect(i * slice_w, 0, marker_w, 5, paint=ft.Paint(color=ft.Colors.PURPLE_400)))
            self._bar_canvas.shapes = shapes
        try:
            self._bar_canvas.update()
        except Exception:
            pass

    def _flash_bar_marker(self, slice_idx: int) -> None:
        self._bar_active_markers.add(slice_idx)
        self._draw_bar()
        try:
            self._bridge.flet_page.run_task(self._remove_bar_marker, slice_idx)
        except Exception:
            pass

    async def _remove_bar_marker(self, slice_idx: int) -> None:
        await asyncio.sleep(_BAR_MARKER_TTL)
        self._bar_active_markers.discard(slice_idx)
        self._draw_bar()
        try:
            await self._bridge.flet_page.update_async()
        except Exception:
            pass

    def _stop_scan_elapsed_timer(self) -> None:
        self._scan_timer_active = False
        self._scan_hud_stop.set()
        t = self._scan_timer_thread
        self._scan_timer_thread = None
        if t is not None and t.is_alive():
            t.join(timeout=2.5)
        try:
            self._ring_label.opacity = 1.0
        except Exception:
            pass

    def _scan_elapsed_clock_value(self) -> str:
        """Compact H:MM:SS / M:SS for the live scan clock (UI thread)."""
        mono = (time.monotonic() - self._scan_elapsed_start) if self._scan_timer_active else 0.0
        eng = float(getattr(self, "_last_progress_elapsed_seconds", 0.0) or 0.0)
        if mono <= 0.0 and eng <= 0.0 and not self._scan_timer_active:
            return "0:00"
        return ScanHUD._fmt_elapsed_compact(max(0.0, mono, eng))

    async def _async_tick_scan_elapsed(self) -> None:
        """Flet ``run_task`` path when ``run_thread`` is unavailable."""
        self._apply_tick_scan_hud()

    def _start_scan_elapsed_timer(self) -> None:
        self._stop_scan_elapsed_timer()
        self._scan_hud_stop = threading.Event()
        self._scan_timer_active = True
        self._scan_elapsed_start = time.monotonic()
        self._scan_hud_snap = {}
        page = self._bridge.flet_page

        def worker() -> None:
            while not self._scan_hud_stop.wait(1.0):
                if not self._scan_timer_active:
                    break
                try:
                    if hasattr(page, "run_thread"):
                        page.run_thread(self._apply_tick_scan_hud)
                    elif hasattr(page, "run_task"):
                        page.run_task(self._async_tick_scan_elapsed)
                    else:
                        self._apply_tick_scan_hud()
                except Exception:
                    _log.debug("scan elapsed tick scheduling failed", exc_info=True)

        th = threading.Thread(target=worker, daemon=True, name="cerebro-scan-elapsed")
        self._scan_timer_thread = th
        th.start()

    def _apply_tick_scan_hud(self) -> None:
        if not self._scan_timer_active:
            return
        if not self.visible:
            return
        try:
            snap = self._scan_hud_snap or {}
            st = str(snap.get("stage") or "")
            if st in (ScanStage.HASHING_PARTIAL, ScanStage.HASHING_FULL):
                fp = int(snap.get("scanned") or 0)
            else:
                fp = int(snap.get("files_processed") or snap.get("scanned") or 0)
            self._speed_points.append((time.monotonic(), fp))
            self._headline_pulse_tick += 1
            self._ring_label.opacity = 0.78 if (self._headline_pulse_tick % 2 == 1) else 1.0
            self._scan_elapsed_clock.value = self._scan_elapsed_clock_value()
            self._ring_timer.value = self._build_scan_timer_line()
            self._ring_path.value = self._path_strip_caption()
            ScanHUD._safe_update(self._scan_elapsed_clock)
            ScanHUD._safe_update(self._ring_timer)
            ScanHUD._safe_update(self._ring_path)
            ScanHUD._safe_update(self._ring_label)
            now = time.monotonic()
            if now - float(getattr(self, "_last_incomplete_persist_ts", 0.0) or 0.0) >= 15.0:
                self._callbacks.set_last_incomplete_persist_ts(now)
                try:
                    self._callbacks.on_persist_incomplete_scan(status="in_progress")
                except Exception:
                    _log.debug("throttled incomplete-scan persist failed", exc_info=True)
        except Exception:
            _log.debug("scan elapsed tick update failed", exc_info=True)

    def _build_scan_timer_line(self) -> str:
        """Pace / ETA / phase hints — elapsed blends UI timer + engine wall clock."""
        mono = (time.monotonic() - self._scan_elapsed_start) if self._scan_timer_active else 0.0
        eng = float(getattr(self, "_last_progress_elapsed_seconds", 0.0) or 0.0)
        elapsed = max(0.0, mono, eng)
        snap = self._scan_hud_snap or {}
        st = str(snap.get("stage") or "")

        parts: list[str] = []
        if not st:
            return "Preparing scan…"

        is_hs = st in (ScanStage.HASHING_PARTIAL, ScanStage.HASHING_FULL)

        # Hide ETA / throughput outside hashing phases (avoids stale files/s during assembly).
        if not is_hs:
            total = int(snap.get("total") or 0)
            scanned = int(snap.get("scanned") or 0)
            if st == ScanStage.COMPLETE:
                parts.append("Assembling duplicate groups…")
            elif st == ScanStage.CANCELLED:
                parts.append("Stopping scan…")
            elif st == ScanStage.GROUPING_BY_SIZE:
                if total > 0:
                    pct = int(max(0.0, min(100.0, (float(scanned) / float(total)) * 100.0)))
                    stage_eta_s, conf = self._stable_stage_eta_seconds(
                        stage=st,
                        elapsed=elapsed,
                        scanned=scanned,
                        total=total,
                        rolling_rate=self._rolling_speed_files_per_sec(),
                        warmup_seconds=5.0,
                        min_scanned=max(1000, int(total * 0.03)),
                    )
                    if stage_eta_s is not None:
                        eta_txt = (
                            self._fmt_eta_bucket(stage_eta_s)
                            if conf == "low"
                            else self._fmt_eta(stage_eta_s)
                        )
                        if eta_txt:
                            parts.append(f"Grouping same-size candidates… {pct}%  ·  ETA ~{eta_txt}")
                        else:
                            parts.append(f"Grouping same-size candidates… {pct}%")
                    else:
                        parts.append(f"Grouping same-size candidates… {pct}%")
                else:
                    parts.append("Grouping same-size candidates…")
            elif st == ScanStage.TIER_A_PREFILTER:
                if total > 0:
                    pct = int(max(0.0, min(100.0, (float(scanned) / float(total)) * 100.0)))
                    parts.append(f"Pre-filtering same-size files… {pct}%")
                else:
                    parts.append("Pre-filtering same-size files…")
            elif st == ScanStage.DISCOVERING:
                if total > 0 and 0 < scanned < total:
                    pct = int(max(0.0, min(100.0, (float(scanned) / float(total)) * 100.0)))
                    stage_eta_s, conf = self._stable_stage_eta_seconds(
                        stage=st,
                        elapsed=elapsed,
                        scanned=scanned,
                        total=total,
                        rolling_rate=self._rolling_speed_files_per_sec(),
                        warmup_seconds=4.0,
                        min_scanned=max(500, int(total * 0.02)),
                    )
                    if stage_eta_s is not None:
                        eta_txt = (
                            self._fmt_eta_bucket(stage_eta_s)
                            if conf == "low"
                            else self._fmt_eta(stage_eta_s)
                        )
                        if eta_txt:
                            parts.append(f"Listing file paths… {pct}%  ·  ETA ~{eta_txt}")
                        else:
                            parts.append(f"Listing file paths… {pct}%")
                    else:
                        parts.append(f"Listing file paths… {pct}%")
                else:
                    parts.append("Listing file paths…")
            else:
                parts.append("Working…")
            return "  ·  ".join(parts)

        # Hashing ETA must use comparison work-unit counters, not catalogue / scope totals.
        total = int(snap.get("total") or 0)
        scanned = int(snap.get("scanned") or 0)

        rolling_rate = self._rolling_speed_files_per_sec()
        stable_eta_s, conf = self._stable_hashing_eta_seconds(
            stage=st,
            elapsed=elapsed,
            scanned=scanned,
            total=total,
            rolling_rate=rolling_rate,
        )
        if stable_eta_s is not None:
            eta = self._fmt_eta(stable_eta_s)
            if eta:
                suffix = " (estimating)" if conf == "low" else ""
                parts.append(f"ETA ~{eta}{suffix}")
            else:
                parts.append("Finishing…")
        elif rolling_rate is not None and total > 0:
            parts.append("Finishing…")
        elif st in (ScanStage.HASHING_PARTIAL, ScanStage.HASHING_FULL) and total > 0 and scanned == 0:
            cf = str(snap.get("current_file") or "")
            if elapsed <= 2.0:
                parts.append("Gathering speed data…")
            elif "Retrieving cached signatures" in cf:
                parts.append("Reading signature cache from disk…")
            elif elapsed <= 5.0:
                parts.append("Gathering speed data…")
            elif cf:
                tail = cf if len(cf) < 56 else "…" + cf[-52:]
                parts.append(f"Still preparing — {tail}")
            else:
                parts.append("Still preparing first comparisons…")
        elif st in (ScanStage.HASHING_PARTIAL, ScanStage.HASHING_FULL) and total > 0 and 0 < scanned < total:
            cf = str(snap.get("current_file") or "")
            if "Retrieving cached signatures" in cf and rolling_rate is not None and float(rolling_rate) > 0:
                eta_s = (float(total) - float(scanned)) / float(rolling_rate)
                eta = self._fmt_eta(eta_s)
                if eta:
                    parts.append(f"Retrieving cache — ETA ~{eta} (estimating)")
                else:
                    parts.append("Retrieving cache…")
            elif elapsed >= 3.0 and scanned >= 200:
                eta_s = (elapsed / float(scanned)) * (float(total) - float(scanned))
                eta = self._fmt_eta(eta_s)
                if eta:
                    parts.append(f"ETA ~{eta} (estimating)")
                else:
                    parts.append("Finishing…")
            elif elapsed >= 2.0:
                parts.append("ETA stabilizing…")
            else:
                parts.append("Gathering speed data…")
        elif total > 0 and scanned > 0:
            parts.append("Throughput: stabilizing…")
        elif st == ScanStage.DISCOVERING or total == 0:
            parts.append("Indexing paths…")
        else:
            parts.append("Working…")
        return "  ·  ".join(parts)

    def _stable_hashing_eta_seconds(
        self,
        *,
        stage: str,
        elapsed: float,
        scanned: int,
        total: int,
        rolling_rate: float | None,
    ) -> tuple[float | None, str]:
        """Return (stable_eta_seconds, confidence) for hashing phases."""
        if stage != self._eta_last_stage:
            self._eta_last_stage = stage
            self._eta_smoothed_seconds = None
            self._eta_last_update_ts = time.monotonic()
        if rolling_rate is None or total <= 0 or scanned <= 0 or scanned >= total:
            return None, "low"
        # Warm-up gate: avoid noisy early ETA.
        if elapsed < 8.0 or scanned < max(250, int(total * 0.02)):
            return None, "low"

        raw_eta = max(0.0, (float(total) - float(scanned)) / max(1e-6, float(rolling_rate)))
        prev = self._eta_smoothed_seconds
        if prev is None:
            smoothed = raw_eta
        else:
            # EMA smooths short-term throughput spikes/drops.
            smoothed = (0.25 * raw_eta) + (0.75 * prev)
            # Clamp jump size per tick so ETA cannot wildly swing.
            lo = prev * 0.85
            hi = prev * 1.15
            smoothed = max(lo, min(hi, smoothed))

        self._eta_smoothed_seconds = smoothed
        self._eta_last_update_ts = time.monotonic()

        # Confidence from recent rate variance.
        confidence = "high"
        points = list(self._speed_points)
        if len(points) >= 6:
            rates: list[float] = []
            for i in range(1, len(points)):
                dt = points[i][0] - points[i - 1][0]
                df = points[i][1] - points[i - 1][1]
                if dt > 0.2 and df > 0:
                    rates.append(df / dt)
            if len(rates) >= 4:
                mean = sum(rates) / float(len(rates))
                if mean > 0:
                    variance = sum((r - mean) ** 2 for r in rates) / float(len(rates))
                    coeff_var = (variance ** 0.5) / mean
                    if coeff_var > 0.42:
                        confidence = "low"
                    elif coeff_var > 0.24:
                        confidence = "medium"
        return smoothed, confidence

    def _stable_stage_eta_seconds(
        self,
        *,
        stage: str,
        elapsed: float,
        scanned: int,
        total: int,
        rolling_rate: float | None,
        warmup_seconds: float,
        min_scanned: int,
    ) -> tuple[float | None, str]:
        """Stage-agnostic stable ETA (for discovery/grouping/hash)."""
        if stage != self._eta_last_stage:
            self._eta_last_stage = stage
            self._eta_smoothed_seconds = None
            self._eta_last_update_ts = time.monotonic()
        if rolling_rate is None or total <= 0 or scanned <= 0 or scanned >= total:
            return None, "low"
        if elapsed < warmup_seconds or scanned < max(1, min_scanned):
            return None, "low"

        raw_eta = max(0.0, (float(total) - float(scanned)) / max(1e-6, float(rolling_rate)))
        prev = self._eta_smoothed_seconds
        if prev is None:
            smoothed = raw_eta
        else:
            smoothed = (0.22 * raw_eta) + (0.78 * prev)
            lo = prev * 0.86
            hi = prev * 1.14
            smoothed = max(lo, min(hi, smoothed))

        self._eta_smoothed_seconds = smoothed
        self._eta_last_update_ts = time.monotonic()

        confidence = "high"
        points = list(self._speed_points)
        if len(points) >= 6:
            rates: list[float] = []
            for i in range(1, len(points)):
                dt = points[i][0] - points[i - 1][0]
                df = points[i][1] - points[i - 1][1]
                if dt > 0.2 and df > 0:
                    rates.append(df / dt)
            if len(rates) >= 4:
                mean = sum(rates) / float(len(rates))
                if mean > 0:
                    variance = sum((r - mean) ** 2 for r in rates) / float(len(rates))
                    coeff_var = (variance ** 0.5) / mean
                    if coeff_var > 0.42:
                        confidence = "low"
                    elif coeff_var > 0.24:
                        confidence = "medium"
        return smoothed, confidence

    @staticmethod
    def _fmt_elapsed_compact(seconds: float) -> str:
        s = int(max(0.0, seconds))
        h, rem = divmod(s, 3600)
        m, sec = divmod(rem, 60)
        if h > 0:
            return f"{h}:{m:02d}:{sec:02d}"
        return f"{m}:{sec:02d}"

    @staticmethod
    def _fmt_eta(seconds: float) -> str:
        s = max(0, int(seconds))
        if s < 60:
            return ""
        m, s = divmod(s, 60)
        h, m = divmod(m, 60)
        if h > 0:
            return f"{h}h {m}m"
        return f"{m}m {s}s"

    @staticmethod
    def _fmt_eta_bucket(seconds: float) -> str:
        s = max(0, int(seconds))
        if s < 180:
            return "a few minutes"
        if s < 900:
            return "5–15 min"
        if s < 1800:
            return "15–30 min"
        if s < 3600:
            return "30–60 min"
        if s < 7200:
            return "1–2 hours"
        return "2+ hours"

    def _rolling_speed_files_per_sec(self) -> float | None:
        if len(self._speed_points) < 2:
            return None
        points = list(self._speed_points)
        t0, f0 = points[0]
        t1, f1 = points[-1]
        dt = t1 - t0
        if dt <= 0.0:
            return None
        df = f1 - f0
        if df <= 0:
            return None
        return df / dt
