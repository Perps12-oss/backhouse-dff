"""Dashboard page — home/landing page with quick-start scan controls, stats, and recent activity."""

from __future__ import annotations

import asyncio
from collections import deque
import json
import logging
import os
import threading
import time
import re
from pathlib import Path
from typing import TYPE_CHECKING, Optional, Set

import flet as ft
import flet.canvas as cv

from cerebro.v2.ui.flet_app.pill_button_styles import (
    pill_filled_accent,
    pill_outlined_button_style,
    pill_text_button_style,
)
from cerebro.v2.ui.flet_app.theme import theme_for_mode, fmt_size, SCAN_MODES, glass_container
from cerebro.engines.scan_stage import ScanStage

if TYPE_CHECKING:
    from cerebro.v2.ui.flet_app.services.state_bridge import StateBridge

_log = logging.getLogger(__name__)

_BAR_SLICES: int = 200
_BAR_HEIGHT: int = 28
_BAR_WIDTH: int = 520
_BAR_MARKER_TTL: float = 0.30
_INCOMPLETE_SCAN_PATH = Path.home() / ".cerebro" / "incomplete_scan.json"

_SCAN_MODE_ICON_MAP = {
    "description": ft.icons.Icons.DESCRIPTION,
    "image": ft.icons.Icons.IMAGE,
    "image_search": ft.icons.Icons.IMAGE_SEARCH,
    "videocam": ft.icons.Icons.VIDEOCAM,
    "music_note": ft.icons.Icons.MUSIC_NOTE,
}


class DashboardPage(ft.Column):
    """Home page with scan configuration, stats, and quick-start."""

    # Coalesce rapid Home refreshes (on_show + theme + async stats) without starving updates.
    _PRESENCE_REFRESH_MIN_S: float = 1.25

    def __init__(self, bridge: "StateBridge", folder_picker: ft.FilePicker):
        super().__init__(expand=True, scroll=ft.ScrollMode.AUTO)
        self._bridge = bridge
        self._folder_picker = folder_picker
        self._folders: list[Path] = []  # Enforce Path objects
        self._picker_active: bool = False  # guard against concurrent picker opens
        self._selected_mode = "files"
        self._selected_modes: set[str] = {"files"}
        self._scan_options: dict = {
            "scan_archives": False,
            "min_size_bytes": 0,
            "exclude_paths": [],
            "include_subfolders": True,
        }
        self._stats = {"scans": 0, "dupes": 0, "bytes_reclaimed": 0}
        self._initial_load_done = False
        self._stats_fetch_generation = 0
        self._last_on_show_ts = 0.0
        self._presence_refresh_last_mon: float = 0.0
        self._stats_row_signature: tuple[int, int, int] | None = None
        # Initial Theme Load
        self._t = theme_for_mode("dark")

        # UI References (to update without rebuilding)
        self._hero: ft.Container
        self._hero_tagline_icon: ft.Icon
        self._folder_section_icon: ft.Icon
        self._stats_row: ft.Row
        self._mode_label: ft.Text
        self._mode_row: ft.Column
        self._scan_type_summary: ft.Text
        self._scan_type_checkboxes: dict[str, ft.Checkbox]
        self._scan_safety_note: ft.Text
        self._folder_chips_row: ft.Row
        self._folder_container: ft.Container
        self._actions: ft.Row
        self._last_session_btn: ft.TextButton
        self._start_btn: ft.FilledButton
        self._pause_scan_btn: ft.OutlinedButton
        self._phase_prep_status: ft.Text
        self._phase_hash_title: ft.Text
        self._phase_hash_bar: ft.ProgressBar
        self._phase_hash_caption: ft.Text
        self._autosave_hint: ft.Text
        self._scan_phase_card: ft.Container
        self._status_metric_row: ft.Row
        self._progress_detail: ft.Text
        self._path_strip: ft.Container
        self._status: ft.Text
        self._cancelled_results_banner: ft.Container
        self._cancelled_results_text: ft.Text
        self._cancelled_results_btn: ft.TextButton
        self._ring: ft.ProgressRing
        self._ring_phase_label: ft.Text
        self._scan_mode_run_label: ft.Text
        self._ring_label: ft.Text
        self._ring_counter: ft.Text
        self._hash_algo_label: ft.Text
        self._ring_timer: ft.Text
        self._scan_elapsed_clock: ft.Text
        self._scan_elapsed_timer_icon: ft.Icon
        self._ring_path: ft.Text
        self._cancel_btn: ft.OutlinedButton
        self._view_results_btn: ft.FilledButton
        self._partial_results_row: ft.Row
        self._cancel_choice_panel: ft.Container
        self._cancel_choice_headline: ft.Text
        self._cancel_choice_sub: ft.Text
        self._scan_view: ft.Container
        self._main_panels: list
        self._bar_canvas: cv.Canvas
        self._bar_overlay: ft.Container
        self._bar_stack: ft.Stack
        self._bar_row: ft.Container
        self._scan_archives_cb: ft.Checkbox
        self._archives_warning: ft.Text
        self._advanced_options_visible: bool
        self._scan_options_dropdown_open: bool
        self._advanced_toggle_btn: ft.IconButton
        self._scan_options_toggle_btn: ft.OutlinedButton
        self._scan_options_dropdown: ft.Container
        self._advanced_panel: ft.Container
        self._min_size_slider: ft.Slider
        self._min_size_label: ft.Text
        self._exclude_paths_tf: ft.TextField
        self._exclude_paths_browse_btn: ft.OutlinedButton
        self._include_subfolders_sw: ft.Switch
        self._scan_options_row: ft.Container
        self._partial_back_home_btn: ft.OutlinedButton
        # Cancellation state: track whether we're in a cancel flow and cache
        # partial results so the user can choose to view them post-cancel.
        self._was_cancelled: bool = False
        self._pending_partial_results: list = []
        self._pending_partial_mode: str = "files"
        self._cancel_complete_handled: bool = False
        self._cancel_user_dismissed_choice: bool = False
        self._resume_interrupted_scan_once: bool = False
        self._last_incomplete_persist_ts: float = 0.0
        # Elapsed clock + ETA line (1 Hz); snapshot updated from progress callbacks.
        self._scan_timer_active: bool = False
        self._scan_elapsed_start: float = 0.0
        # Last engine-reported wall elapsed (monotonic-based in TurboFileEngine); used when the
        # 1 Hz UI timer thread does not advance the clock on some hosts.
        self._last_progress_elapsed_seconds: float = 0.0
        self._scan_hud_snap: dict = {}
        self._scan_hud_stop = threading.Event()
        self._scan_timer_thread: Optional[threading.Thread] = None
        self._speed_points: deque[tuple[float, int]] = deque(maxlen=60)
        self._eta_smoothed_seconds: Optional[float] = None
        self._eta_last_stage: str = ""
        self._eta_last_update_ts: float = 0.0
        self._status_token: int = 0
        self._cancelled_banner_token: int = 0
        self._cancel_watchdog_token: int = 0
        self._io_failure_hits_by_root: dict[str, int] = {}
        self._io_pause_dialog_open: bool = False
        self._io_paused_root: str = ""
        self._scan_network_warn_shown: bool = False
        # Largest file-catalogue count seen (discovery + grouping); explains hashing denominator.
        self._scan_files_catalogued: int = 0
        # After ``_on_scan_complete`` / ``_on_scan_error``, ignore queued progress callbacks so the
        # HUD cannot show mid-scan bars while "View Results" / completion chrome is already up.
        self._scan_accept_progress: bool = True
        # Canvas chunk bar state
        self._bar_slices: int = 0
        self._bar_active_markers: Set[int] = set()
        self._bar_is_complete: bool = False
        self._bar_last_dupes: int = 0
        self._headline_pulse_tick: int = 0
        self._build_ui()
        self._load_scan_options_for_mode(self._selected_mode)

    def _is_mounted(self) -> bool:
        """True only when this control is attached to a :class:`ft.Page` (safe before ``page.add``)."""
        try:
            return self.page is not None
        except RuntimeError:
            return False

    @staticmethod
    def _safe_update(ctrl: ft.Control | None) -> None:
        if ctrl is None:
            return
        try:
            if ctrl.page is not None:
                ctrl.update()
        except RuntimeError:
            pass

    def _is_dark_theme(self) -> bool:
        try:
            return "dark" in str(getattr(self._bridge, "app_theme", "")).lower()
        except Exception:
            return True

    def _hover_glow_color(self, variant: str = "primary") -> str:
        if self._is_dark_theme():
            if variant == "secondary":
                return "#A78BFA"
            return str(self._t.colors.accent)
        if variant == "secondary":
            return "#4F46E5"
        return str(self._t.colors.accent)

    def _hover_shadow(self, color: str, strong: bool = False) -> ft.BoxShadow:
        return ft.BoxShadow(
            blur_radius=24 if strong else 14,
            spread_radius=0,
            color=ft.Colors.with_opacity(0.42 if strong else 0.26, color),
            offset=ft.Offset(0, 3 if strong else 2),
        )

    def _set_container_glow(self, container: ft.Container, hovering: bool, *, variant: str = "primary", strong: bool = False) -> None:
        container.shadow = self._hover_shadow(self._hover_glow_color(variant), strong=strong) if hovering else None
        DashboardPage._safe_update(container)

    # ------------------------------------------------------------------
    # Construction (Runs Once)
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        t = self._t
        s = t.spacing

        # Compact greeting strip (replaces wasteful hero)
        self._last_session_btn = ft.TextButton(
            "Open Last Session",
            icon=ft.icons.Icons.HISTORY,
            on_click=self._open_last_session,
            style=pill_text_button_style(t, variant="muted"),
        )
        self._hero_tagline_icon = ft.Icon(
            ft.icons.Icons.AUTO_AWESOME, size=16, color=t.colors.accent
        )
        self._hero = glass_container(
            content=ft.Row(
                [
                    self._hero_tagline_icon,
                    ft.Text(
                        "Scan intelligently. Review safely.",
                        size=t.typography.size_base,
                        weight=ft.FontWeight.W_600,
                        color=t.colors.fg,
                        expand=True,
                    ),
                    self._last_session_btn,
                ],
                spacing=s.sm,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            t=t,
            padding=ft.Padding.symmetric(horizontal=t.spacing.lg, vertical=t.spacing.sm),
            width=860,
        )

        # Stat cards
        self._stats_row = ft.Row([], alignment=ft.MainAxisAlignment.CENTER, spacing=s.md)

        # Phase 1 — operational presence (must exist before first _update_stats_ui → _refresh_presence_ui)
        self._presence_title = ft.Text(
            "",
            size=t.typography.size_sm,
            weight=ft.FontWeight.W_700,
            color=t.colors.fg,
        )
        self._presence_body = ft.Text(
            "",
            size=t.typography.size_xs,
            color=t.colors.fg2,
        )
        self._presence_mtime = ft.Text(
            "",
            size=t.typography.size_xs,
            color=t.colors.fg_muted,
            italic=True,
        )
        self._insights_row = ft.Row(
            [],
            spacing=s.sm,
            tight=True,
            wrap=True,
            alignment=ft.MainAxisAlignment.CENTER,
        )
        self._presence_row = glass_container(
            visible=False,
            width=620,
            padding=ft.Padding.symmetric(horizontal=s.md, vertical=s.sm),
            t=t,
            content=ft.Column(
                [
                    self._presence_title,
                    self._presence_body,
                    self._presence_mtime,
                    ft.Container(height=6),
                    self._insights_row,
                ],
                spacing=2,
                tight=True,
            ),
        )

        self._update_stats_ui()

        # Scan mode selector
        self._mode_label = ft.Text(
            "Scan mode",
            size=t.typography.size_sm,
            weight=ft.FontWeight.W_600,
            color=t.colors.fg_muted,
        )
        self._mode_row = ft.Column(
            [],
            spacing=s.sm,
            horizontal_alignment=ft.CrossAxisAlignment.START,
            visible=True,
        )
        self._scan_type_summary = ft.Text(
            "1 type selected",
            size=t.typography.size_xs,
            color=t.colors.fg_muted,
            italic=True,
        )
        self._scan_type_checkboxes = {}
        self._update_modes_ui()

        # Folder list + clear drop target
        self._folder_chips_row = ft.Row([], wrap=True, spacing=s.xs)
        self._folder_section_icon = ft.Icon(
            ft.icons.Icons.FOLDER_OPEN, size=18, color=t.colors.accent
        )
        self._folder_container = glass_container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            self._folder_section_icon,
                            ft.Text("Selected folders", color=t.colors.fg_muted, size=t.typography.size_sm, weight=ft.FontWeight.W_600),
                            ft.Container(expand=True),
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    self._folder_chips_row,
                    ft.Container(
                        content=ft.FilledTonalButton(
                            "+ Quick Add: Desktop & Downloads",
                            on_click=self._quick_add_desktop_downloads,
                            style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=999)),
                        ),
                        padding=ft.padding.only(top=s.xs),
                    ),
                ],
                spacing=s.xs,
            ),
            t=t,
            padding=s.md,
        )
        self._folder_container.on_click = self._browse_folders
        self._folder_container.on_hover = lambda e, c=self._folder_container: self._set_container_glow(
            c, e.data == "true", variant="primary"
        )
        self._folder_container.ink = True
        cast_col = self._folder_container.content

        # Action buttons — clear hierarchy: primary CTA, secondary, tertiary
        self._pause_scan_btn = ft.OutlinedButton(
            "Pause scan",
            icon=ft.icons.Icons.PAUSE,
            on_click=self._on_hero_pause_toggle,
            visible=False,
            style=pill_outlined_button_style(t),
        )
        self._start_btn = ft.FilledButton(
            "START SCAN",
            icon=ft.icons.Icons.ROCKET_LAUNCH,
            on_click=self._start_scan,
            style=pill_filled_accent(
                t,
                padding=ft.Padding.symmetric(horizontal=56, vertical=28),
                text_size=t.typography.size_xl,
                weight=ft.FontWeight.W_800,
                border_radius=14,
            ),
            disabled=False,
            width=368,
            height=74,
        )
        self._scan_safety_note = ft.Text(
            "Nothing is deleted automatically • Content-aware matching enabled",
            size=t.typography.size_xs,
            color=t.colors.fg_muted,
            text_align=ft.TextAlign.CENTER,
            italic=True,
        )
        start_wrap = ft.Container(content=self._start_btn, border_radius=14)
        start_wrap.on_hover = lambda e, c=start_wrap: self._set_container_glow(c, e.data == "true", variant="primary", strong=True)
        self._actions = ft.Column(
            [
                start_wrap,
                self._scan_safety_note,
                self._pause_scan_btn,
            ],
            horizontal_alignment=ft.CrossAxisAlignment.START,
            spacing=s.xs,
        )

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
            "View Results",
            icon=ft.icons.Icons.CHECK_CIRCLE,
            on_click=self._go_to_results,
            visible=False,
            style=pill_filled_accent(t, text_size=12, weight=ft.FontWeight.W_700),
        )
        self._view_partial_btn = ft.OutlinedButton(
            "View partial results",
            icon=ft.icons.Icons.CHECKLIST,
            on_click=self._go_to_partial_results,
            style=pill_outlined_button_style(t),
        )
        self._partial_back_home_btn = ft.OutlinedButton(
            "Back to home",
            icon=ft.icons.Icons.HOME,
            on_click=self._go_to_home,
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
            on_click=self._stop_scan,
            style=pill_outlined_button_style(t, danger=True),
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

        self._scan_view = ft.Container(
            content=ft.Column(
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
                    self._cancel_btn,
                    self._view_results_btn,
                    self._cancel_choice_panel,
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                alignment=ft.MainAxisAlignment.START,
                spacing=s.lg,
            ),
            expand=True,
            alignment=ft.Alignment(0, -0.25),
            visible=False,
        )

        # Status text (hidden initially; shown only during/after scan)
        self._status = ft.Text(
            "",
            color=t.colors.fg_muted,
            size=t.typography.size_base,
            text_align=ft.TextAlign.CENTER,
        )
        self._cancelled_results_text = ft.Text(
            "",
            color=t.colors.fg2,
            size=t.typography.size_sm,
        )
        self._cancelled_results_btn = ft.TextButton(
            "View Partial Results",
            icon=ft.icons.Icons.CHECKLIST,
            on_click=self._go_to_partial_results,
            style=pill_text_button_style(t, variant="primary"),
        )
        self._cancelled_results_banner = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.icons.Icons.INFO_OUTLINE, color="#F59E0B", size=18),
                    self._cancelled_results_text,
                    ft.Container(expand=True),
                    self._cancelled_results_btn,
                ],
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.Padding.symmetric(horizontal=12, vertical=8),
            border=ft.border.all(1, ft.Colors.with_opacity(0.35, "#F59E0B")),
            border_radius=10,
            bgcolor=ft.Colors.with_opacity(0.08, "#F59E0B"),
            visible=False,
        )

        # Scan options row — opt-in toggles shown between folder list and start button
        self._scan_archives_cb = ft.Checkbox(
            label="Scan inside archives",
            value=False,
            active_color="#F59E0B",
            label_style=ft.TextStyle(color=t.colors.fg2, size=t.typography.size_sm),
            on_change=self._on_archives_cb_change,
        )
        self._archives_warning = ft.Text(
            "⚠ Very slow — archives may be gigabytes. Use only for forensic or backup dedup.",
            size=t.typography.size_xs,
            color="#F59E0B",
            italic=True,
            visible=False,
        )
        self._advanced_options_visible = False
        self._scan_options_dropdown_open = False
        self._min_size_label = ft.Text(
            "Min file size: 0 MB",
            size=t.typography.size_sm,
            color=t.colors.fg2,
        )
        self._min_size_slider = ft.Slider(
            min=0,
            max=1024,
            divisions=128,
            value=0,
            label="{value} MB",
            on_change=self._on_min_size_change,
        )
        self._exclude_paths_tf = ft.TextField(
            label="Exclude paths (one per line)",
            hint_text="D:\\Photos\\Backups",
            multiline=True,
            min_lines=3,
            max_lines=6,
            on_blur=self._on_exclude_paths_blur,
        )
        self._exclude_paths_browse_btn = ft.OutlinedButton(
            "Browse",
            icon=ft.icons.Icons.FOLDER_OPEN,
            on_click=self._browse_exclude_path,
            style=pill_outlined_button_style(t),
        )
        self._include_subfolders_sw = ft.Switch(
            label="Include subfolders",
            value=True,
            on_change=self._on_include_subfolders_change,
        )
        self._advanced_panel = ft.Container(
            visible=False,
            content=ft.Column(
                [
                    self._include_subfolders_sw,
                    self._min_size_label,
                    self._min_size_slider,
                    ft.Row(
                        [
                            ft.Text(
                                "Exclude paths",
                                size=t.typography.size_sm,
                                color=t.colors.fg_muted,
                            ),
                            ft.Container(expand=True),
                            self._exclude_paths_browse_btn,
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    self._exclude_paths_tf,
                ],
                spacing=8,
                tight=True,
            ),
            padding=ft.padding.only(top=8),
        )
        self._advanced_toggle_btn = ft.IconButton(
            icon=ft.icons.Icons.SETTINGS,
            tooltip="Advanced scan options",
            on_click=self._toggle_advanced_panel,
        )
        self._scan_options_row = ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            self._mode_label,
                            ft.Container(expand=True),
                            self._advanced_toggle_btn,
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    self._scan_type_summary,
                    self._mode_row,
                    ft.Text("Advanced scan settings", size=t.typography.size_sm, weight=ft.FontWeight.W_500, color=t.colors.fg_muted),
                    self._scan_archives_cb,
                    self._archives_warning,
                    self._advanced_panel,
                ],
                spacing=4,
                tight=True,
            ),
            padding=ft.Padding.symmetric(horizontal=s.md, vertical=s.sm),
        )
        self._scan_options_toggle_btn = ft.OutlinedButton(
            "Advanced scan settings",
            icon=ft.icons.Icons.KEYBOARD_ARROW_DOWN,
            on_click=self._toggle_scan_options_dropdown,
            style=pill_outlined_button_style(t),
        )
        self._scan_options_dropdown = ft.Container(
            content=glass_container(
                content=self._scan_options_row,
                t=t,
                padding=ft.padding.all(s.xl),
            ),
            visible=False,
            width=620,
        )

        folder_section = ft.Column(
            [
                self._folder_container,
                ft.Container(
                    content=self._actions,
                    padding=ft.padding.only(top=s.xs),
                    alignment=ft.Alignment(0.34, 0),
                ),
            ],
            spacing=s.xs,
        )
        folder_panel = ft.Container(content=folder_section, width=620)

        capability_hint = ft.Text(
            "Content-aware matching and perceptual image analysis",
            size=t.typography.size_xs,
            color=t.colors.fg_muted,
            text_align=ft.TextAlign.CENTER,
        )

        workflow_stack = glass_container(
            width=840,
            padding=ft.Padding.symmetric(horizontal=s.lg, vertical=s.md),
            t=t,
            content=ft.Column(
                [
                    self._hero,
                    folder_panel,
                    ft.Container(
                        content=self._scan_options_toggle_btn,
                        width=620,
                        padding=ft.padding.only(top=s.sm),
                        alignment=ft.Alignment(0.16, 0),
                    ),
                    self._scan_options_dropdown,
                    capability_hint,
                ],
                spacing=s.xs,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        )

        # Checkpoint restore section (checkpoint DB manifests, not in-session pause)
        self._paused_scans_col = ft.Column([], spacing=s.xs, visible=False)
        self._paused_scans_section = ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Icon(ft.icons.Icons.PAUSE_CIRCLE, size=16, color=t.colors.warning),
                            ft.Text(
                                "CHECKPOINT RESTORE",
                                size=t.typography.size_xs,
                                weight=ft.FontWeight.W_700,
                                color=t.colors.warning,
                            ),
                        ],
                        spacing=s.xs,
                    ),
                    self._paused_scans_col,
                ],
                spacing=s.xs,
            ),
            width=620,
            padding=ft.Padding.symmetric(horizontal=s.md, vertical=s.sm),
            border_radius=10,
            border=ft.border.all(1, ft.Colors.with_opacity(0.4, t.colors.warning)),
            bgcolor=ft.Colors.with_opacity(0.07, t.colors.warning),
            visible=False,
        )

        # Assemble — main panels tracked so scan view can swap in/out
        home_content = ft.Container(
            alignment=ft.Alignment(0, -1),
            padding=ft.padding.only(top=4),
            content=ft.Column(
                [
                    workflow_stack,
                    ft.Container(
                        content=self._paused_scans_section,
                        padding=ft.padding.only(top=s.sm),
                    ),
                    ft.Container(content=self._status, width=520, padding=ft.padding.only(top=s.sm)),
                    ft.Container(content=self._cancelled_results_banner, width=460, padding=ft.padding.only(top=s.sm)),
                    ft.Container(content=self._stats_row, width=360, padding=ft.padding.only(top=s.sm)),
                    ft.Container(content=self._presence_row, width=620, padding=ft.padding.only(top=s.xs)),
                ],
                spacing=s.xs,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        )
        self.controls = [home_content]
        self._main_panels = list(self.controls)  # snapshot for hide/show swap
        self.controls.append(self._scan_view)     # scan view always last, starts hidden
        self._refresh_folder_chips()
        self._apply_dashboard_pill_chrome()

        # Initial data fetch (async so first layout is not blocked)
        self._schedule_dashboard_data_fetch()

    # ------------------------------------------------------------------
    # Theme Helpers
    # ------------------------------------------------------------------


    def _get_button_style(self, base_color: str = None) -> ft.ButtonStyle:
        t = self._t
        bg = (
            ft.Colors.with_opacity(0.2, base_color or t.colors.primary)
            if base_color
            else ft.Colors.with_opacity(0.15, t.colors.primary)
        )
        return ft.ButtonStyle(
            bgcolor=bg,
            color=t.colors.fg,
            overlay_color=ft.Colors.with_opacity(0.3, t.colors.primary),
            shape=ft.RoundedRectangleBorder(radius=12),
            padding=ft.Padding.symmetric(horizontal=16, vertical=10),
        )

    # ------------------------------------------------------------------
    # Data & UI Updates (No Rebuild)
    # ------------------------------------------------------------------
    def _schedule_dashboard_data_fetch(self) -> None:
        self._stats_fetch_generation += 1
        gen = self._stats_fetch_generation
        page = self._bridge.flet_page
        if hasattr(page, "run_task"):
            page.run_task(self._fetch_dashboard_data_async, gen)
        else:
            self._fetch_dashboard_data_sync()

    def _fetch_dashboard_data_sync(self) -> None:
        try:
            stats = self._bridge.get_stats()
            if stats:
                self._stats = stats
        except Exception:
            _log.error("Failed to fetch dashboard data", exc_info=True)
        self._update_stats_ui()
        self._presence_mtime.value = ""

    async def _fetch_dashboard_data_async(self, gen: int) -> None:
        import asyncio

        loop = asyncio.get_event_loop()
        try:
            stats = await loop.run_in_executor(None, self._bridge.get_stats)
            if gen != self._stats_fetch_generation:
                return
            if stats:
                self._stats = stats
        except Exception:
            _log.error("Failed to fetch dashboard data", exc_info=True)
        self._update_stats_ui()
        try:
            from cerebro.v2.core.index_presence import (
                count_files_newer_than,
                latest_scan_entry,
            )

            entry = latest_scan_entry()
            if entry and gen == self._stats_fetch_generation:
                self._presence_mtime.value = "Checking folders for files modified since then…"
                DashboardPage._safe_update(self._presence_mtime)

                def _mtime_job():
                    return count_files_newer_than(
                        entry.folders,
                        entry.timestamp,
                        budget_seconds=2.0,
                        max_files=200_000,
                    )

                count, truncated = await loop.run_in_executor(None, _mtime_job)
                if gen != self._stats_fetch_generation:
                    return
                if truncated:
                    self._presence_mtime.value = (
                        f"≥{count:,}+ paths look newer than your last analysis "
                        "(quick check stopped early for responsiveness)."
                    )
                elif count == 0:
                    self._presence_mtime.value = (
                        "No newer files spotted under the last scanned paths — "
                        "a rescan should mostly hit the hash cache."
                    )
                else:
                    self._presence_mtime.value = (
                        f"{count:,} files have a newer modified time since that run — "
                        "start a scan to refresh duplicate groups."
                    )
                DashboardPage._safe_update(self._presence_mtime)
                DashboardPage._safe_update(self._presence_row)
        except Exception:
            _log.debug("Presence mtime check failed", exc_info=True)
            if gen == self._stats_fetch_generation:
                self._presence_mtime.value = ""
                DashboardPage._safe_update(self._presence_mtime)

    def _maybe_refresh_presence_ui(self, *, force: bool = False) -> None:
        """Rebuild presence strip unless refreshed recently (reduces chip churn)."""
        if not hasattr(self, "_presence_title"):
            return
        now = time.monotonic()
        if (
            not force
            and (now - float(getattr(self, "_presence_refresh_last_mon", 0.0) or 0.0))
            < float(DashboardPage._PRESENCE_REFRESH_MIN_S)
        ):
            return
        self._presence_refresh_last_mon = now
        self._refresh_presence_ui()

    def _update_stats_ui(self, *, refresh_presence_force: bool = False) -> None:
        t = self._t
        scans_n = int(self._stats.get("scans", 0) or 0)
        dupes_n = int(self._stats.get("dupes", 0) or 0)
        bytes_n = int(self._stats.get("bytes_reclaimed", 0) or 0)
        new_sig = (scans_n, dupes_n, bytes_n)
        sig_changed = self._stats_row_signature != new_sig
        self._stats_row_signature = new_sig
        self._stats_row.visible = (scans_n > 0) or (dupes_n > 0) or (bytes_n > 0)
        cards = [
            (ft.icons.Icons.SEARCH, "#22D3EE", "Scans Run", f"{scans_n:,}"),
            (ft.icons.Icons.CONTENT_COPY, "#A78BFA", "Duplicates Found", f"{dupes_n:,}"),
            (ft.icons.Icons.STORAGE, "#34D399", "Space Recovered", fmt_size(bytes_n)),
        ]
        controls: list[ft.Control] = []
        for icon, accent, label, value in cards:
            tile = glass_container(
                content=ft.Row(
                    [
                        ft.Container(
                            content=ft.Icon(icon, size=20, color=accent),
                            bgcolor=ft.Colors.with_opacity(0.18, accent),
                            border=ft.border.all(1, ft.Colors.with_opacity(0.24, accent)),
                            border_radius=8,
                            padding=8,
                        ),
                        ft.Column(
                            [
                                ft.Text(
                                    value,
                                    size=t.typography.size_lg,
                                    weight=ft.FontWeight.W_700,
                                    color=t.colors.fg,
                                ),
                                ft.Text(
                                    label,
                                    size=t.typography.size_sm,
                                    color=t.colors.fg_muted,
                                ),
                            ],
                            spacing=2,
                            tight=True,
                        )
                    ],
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=10,
                ),
                t=self._t,
                padding=ft.Padding.symmetric(horizontal=14, vertical=10),
            )
            tile.ink = True
            tile.on_hover = lambda e, c=tile: self._set_container_glow(c, e.data == "true", variant="secondary")
            controls.append(
                ft.GestureDetector(
                    content=tile,
                    on_tap=lambda _e: self._bridge.navigate("history"),
                    mouse_cursor=ft.MouseCursor.CLICK,
                )
            )
        self._stats_row.controls = controls
        DashboardPage._safe_update(self._stats_row)
        self._maybe_refresh_presence_ui(force=bool(refresh_presence_force or sig_changed))

    @staticmethod
    def _insight_chip(t, label: str, value: str, accent: str) -> ft.Container:
        return ft.Container(
            content=ft.Row(
                [
                    ft.Text(label, size=10, color=t.colors.fg_muted, weight=ft.FontWeight.W_500),
                    ft.Text(value, size=11, weight=ft.FontWeight.W_700, color=accent),
                ],
                tight=True,
                spacing=4,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.Padding.symmetric(horizontal=10, vertical=6),
            border_radius=999,
            bgcolor=ft.Colors.with_opacity(0.1, accent),
        )

    @staticmethod
    def _short_folder_label(path: str, max_len: int = 40) -> str:
        s = str(path).replace("\\", "/")
        if len(s) <= max_len:
            return s
        return "…" + s[-(max_len - 1) :]

    def _refresh_presence_ui(self) -> None:
        """Show last recorded scan, 7-day rollups, and last saved session rollups."""
        if not hasattr(self, "_presence_title"):
            return
        from cerebro.v2.core.index_presence import format_relative_past, latest_scan_entry
        from cerebro.v2.core.scan_history_db import get_scan_history_db
        from cerebro.v2.persistence.scan_snapshot import load_last_scan_summary

        t = self._t
        entry = latest_scan_entry()
        summary = load_last_scan_summary()

        if not entry and not summary:
            self._presence_row.visible = False
            self._insights_row.controls = []
            DashboardPage._safe_update(self._presence_row)
            return

        if entry:
            rel = format_relative_past(entry.timestamp)
            mode_lbl = str(entry.mode or "files").replace("+", " + ")
            self._presence_title.value = f"Last analysis · {rel}"
            self._presence_body.value = (
                f"{entry.groups_found:,} groups · {entry.files_found:,} duplicate paths · "
                f"{fmt_size(entry.bytes_reclaimable)} reclaimable · {mode_lbl}. "
                "Hash index on disk makes the next run faster when files are unchanged."
            )
        else:
            gc = int((summary or {}).get("groups_count", 0) or 0)
            sm = str((summary or {}).get("scan_mode", "files") or "files")
            self._presence_title.value = "Saved duplicate summary"
            self._presence_body.value = (
                f"{gc:,} groups on disk · mode {sm.replace('+', ' + ')} — "
                "run a scan to refresh history totals."
            )

        self._presence_title.color = t.colors.fg
        self._presence_body.color = t.colors.fg2
        self._presence_mtime.color = t.colors.fg_muted

        since_7d = time.time() - 7 * 24 * 3600
        n_scans, g_sum, f_sum, b_sum = get_scan_history_db().aggregate_since(since_7d)
        chips: list[ft.Control] = [
            self._insight_chip(t, "7-day scans", f"{n_scans}", "#22D3EE"),
            self._insight_chip(t, "7-day duplicate paths (total)", f"{f_sum:,}", "#A78BFA"),
            self._insight_chip(t, "7-day reclaimable (total)", fmt_size(int(b_sum)), "#34D399"),
            self._insight_chip(t, "7-day groups (total)", f"{g_sum:,}", "#F472B6"),
        ]

        if summary:
            hist_ts = float(entry.timestamp) if entry else 0.0
            sum_ts = float(summary.get("session_ts", 0.0) or 0.0)
            aligned = (not hist_ts) or abs(sum_ts - hist_ts) < 300.0
            prefix = "Last run" if aligned else "Saved session"
            b = summary.get("age_buckets") or {}
            chips.extend(
                [
                    self._insight_chip(t, f"{prefix} · <7d files", fmt_size(int(b.get("under_7d", 0))), "#F97316"),
                    self._insight_chip(t, f"{prefix} · 7–30d", fmt_size(int(b.get("d7_to_30", 0))), "#EAB308"),
                    self._insight_chip(t, f"{prefix} · 30d+", fmt_size(int(b.get("over_30d", 0))), "#94A3B8"),
                ]
            )
            for row in (summary.get("top_folders") or [])[:2]:
                pth = str(row.get("path", ""))
                br = int(row.get("reclaimable", 0) or 0)
                chips.append(
                    self._insight_chip(
                        t,
                        f"{prefix} · {DashboardPage._short_folder_label(pth, 36)}",
                        fmt_size(br),
                        "#0EA5E9",
                    )
                )

        self._insights_row.controls = chips
        self._presence_row.bgcolor = self._t.colors.glass_bg
        self._presence_row.border = ft.border.all(1, self._t.colors.glass_border)
        self._presence_row.visible = True
        DashboardPage._safe_update(self._presence_title)
        DashboardPage._safe_update(self._presence_body)
        DashboardPage._safe_update(self._presence_mtime)
        DashboardPage._safe_update(self._insights_row)
        DashboardPage._safe_update(self._presence_row)

    def _update_modes_ui(self) -> None:
        t = self._t
        controls: list[ft.Control] = []
        self._scan_type_checkboxes = {}
        has_specific = any(m != "files" for m in self._selected_modes)

        for m in SCAN_MODES:
            key = str(m.get("key", ""))
            if not key:
                continue
            label = str(m.get("label", key))
            if key == "files":
                label = "Full Scan"
            cb = ft.Checkbox(
                label=label,
                value=(key in self._selected_modes),
                active_color="#22D3EE",
                label_style=ft.TextStyle(color=t.colors.fg2, size=t.typography.size_sm),
                on_change=lambda e, k=key: self._on_scan_type_selected(k, e),
                disabled=(key == "files" and has_specific),
            )
            self._scan_type_checkboxes[key] = cb
            controls.append(cb)
        self._mode_row.controls = controls
        self._update_scan_type_summary()
        DashboardPage._safe_update(self._mode_row)
        DashboardPage._safe_update(self._scan_type_summary)

    def _on_scan_type_selected(self, key: str, e: ft.ControlEvent) -> None:
        prev_mode = self._selected_mode
        next_selected = set(self._selected_modes)
        checked = bool(e.control.value)
        if key == "files":
            if checked:
                next_selected = {"files"}
            else:
                next_selected = set(self._selected_modes) or {"files"}
        else:
            if checked:
                next_selected.discard("files")
                next_selected.add(key)
            else:
                next_selected.discard(key)
                if not next_selected:
                    next_selected = {"files"}

        self._save_scan_options_for_mode(prev_mode)
        self._selected_modes = next_selected
        self._selected_mode = self._primary_selected_mode()
        self._load_scan_options_for_mode(self._selected_mode)
        self._update_modes_ui()
        self._update_scan_type_summary()
        _log.info("scan_type_selected modes=%s", sorted(self._selected_modes))

    def _update_scan_type_summary(self) -> None:
        selected = len(self._selected_modes)
        noun = "type" if selected == 1 else "types"
        self._scan_type_summary.value = f"{selected} {noun} selected"

    def _primary_selected_mode(self) -> str:
        if "files" in self._selected_modes:
            return "files"
        if self._selected_modes:
            return sorted(self._selected_modes)[0]
        return "files"

    def _selected_modes_for_scan(self) -> list[str]:
        if "files" in self._selected_modes:
            return ["files"]
        modes = [m for m in sorted(self._selected_modes) if m]
        return modes or ["files"]

    def _scan_modes_display_label(self, modes: list[str]) -> str:
        label_by_key = {
            str(m.get("key", "")): str(m.get("label", m.get("key", "")))
            for m in SCAN_MODES
            if str(m.get("key", "")).strip()
        }
        names = [label_by_key.get(k, str(k)) for k in modes if str(k).strip()]
        if not names:
            names = ["Full Scan"]
        return "Running: " + " + ".join(names)

    def _open_last_session(self, e=None):
        try:
            self._bridge.open_last_session()
        except Exception as err:
            _log.error(f"Failed to open last session: {err}")

    # ------------------------------------------------------------------
    # User Interactions
    # ------------------------------------------------------------------
    def _on_archives_cb_change(self, e: ft.ControlEvent) -> None:
        enabled = bool(e.control.value)
        self._scan_options["scan_archives"] = enabled
        self._archives_warning.visible = enabled
        DashboardPage._safe_update(self._archives_warning)
        self._save_scan_options_for_mode(self._selected_mode)

    def _toggle_advanced_panel(self, _e: ft.ControlEvent) -> None:
        self._advanced_options_visible = not self._advanced_options_visible
        self._advanced_panel.visible = self._advanced_options_visible
        self._advanced_toggle_btn.icon = (
            ft.icons.Icons.SETTINGS_SUGGEST
            if self._advanced_options_visible
            else ft.icons.Icons.SETTINGS
        )
        DashboardPage._safe_update(self._advanced_panel)
        DashboardPage._safe_update(self._advanced_toggle_btn)

    def _toggle_scan_options_dropdown(self, _e: ft.ControlEvent) -> None:
        self._scan_options_dropdown_open = not self._scan_options_dropdown_open
        self._scan_options_dropdown.visible = self._scan_options_dropdown_open
        self._scan_options_toggle_btn.icon = (
            ft.icons.Icons.KEYBOARD_ARROW_UP
            if self._scan_options_dropdown_open
            else ft.icons.Icons.KEYBOARD_ARROW_DOWN
        )
        DashboardPage._safe_update(self._scan_options_dropdown)
        DashboardPage._safe_update(self._scan_options_toggle_btn)

    def _on_min_size_change(self, e: ft.ControlEvent) -> None:
        mb = int(e.control.value or 0)
        self._scan_options["min_size_bytes"] = mb * 1024 * 1024
        self._min_size_label.value = f"Min file size: {mb} MB"
        DashboardPage._safe_update(self._min_size_label)
        self._save_scan_options_for_mode(self._selected_mode)

    def _on_exclude_paths_blur(self, _e: ft.ControlEvent) -> None:
        raw = str(self._exclude_paths_tf.value or "")
        lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
        self._scan_options["exclude_paths"] = lines
        _log.info("exclude_paths_updated count=%d", len(lines))
        self._save_scan_options_for_mode(self._selected_mode)

    def _on_include_subfolders_change(self, e: ft.ControlEvent) -> None:
        self._scan_options["include_subfolders"] = bool(e.control.value)
        self._save_scan_options_for_mode(self._selected_mode)

    def _browse_exclude_path(self, _e: ft.ControlEvent) -> None:
        if self._picker_active:
            return
        page = getattr(self._bridge, "flet_page", None)
        if page:
            page.run_task(self._browse_exclude_path_async)

    async def _browse_exclude_path_async(self) -> None:
        if self._picker_active:
            return
        self._picker_active = True
        try:
            result = await self._folder_picker.get_directory_path(
                dialog_title="Select folder path to exclude"
            )
            if not result:
                return
            lines = list(self._scan_options.get("exclude_paths", []) or [])
            path_s = str(result).strip()
            if path_s and path_s not in lines:
                lines.append(path_s)
                self._scan_options["exclude_paths"] = lines
                self._exclude_paths_tf.value = "\n".join(lines)
                DashboardPage._safe_update(self._exclude_paths_tf)
                self._save_scan_options_for_mode(self._selected_mode)
        except Exception as exc:
            msg = str(exc).lower()
            if "session" not in msg and "closed" not in msg:
                _log.error("Exclude-path picker failed: %s", exc)
        finally:
            self._picker_active = False

    def _save_scan_options_for_mode(self, mode_key: str) -> None:
        if not mode_key:
            return
        settings = self._bridge.get_settings()
        if not isinstance(settings, dict):
            settings = {}
        scan_cfg = settings.get("scan")
        if not isinstance(scan_cfg, dict):
            scan_cfg = {}
        adv = scan_cfg.get("advanced_by_mode")
        if not isinstance(adv, dict):
            adv = {}
        adv[str(mode_key)] = {
            "min_size_bytes": int(self._scan_options.get("min_size_bytes", 0) or 0),
            "exclude_paths": list(self._scan_options.get("exclude_paths", []) or []),
            "scan_archives": bool(self._scan_options.get("scan_archives", False)),
            "include_subfolders": bool(self._scan_options.get("include_subfolders", True)),
        }
        scan_cfg["advanced_by_mode"] = adv
        settings["scan"] = scan_cfg
        self._bridge.save_settings(settings)

    def _load_scan_options_for_mode(self, mode_key: str) -> None:
        settings = self._bridge.get_settings()
        scan_cfg = settings.get("scan") if isinstance(settings, dict) else {}
        adv = scan_cfg.get("advanced_by_mode") if isinstance(scan_cfg, dict) else {}
        conf = adv.get(str(mode_key), {}) if isinstance(adv, dict) else {}
        if not isinstance(conf, dict):
            conf = {}

        self._scan_options["min_size_bytes"] = int(conf.get("min_size_bytes", 0) or 0)
        ex = conf.get("exclude_paths", [])
        self._scan_options["exclude_paths"] = [str(x) for x in ex] if isinstance(ex, list) else []
        self._scan_options["scan_archives"] = bool(conf.get("scan_archives", False))
        self._scan_options["include_subfolders"] = bool(conf.get("include_subfolders", True))

        min_mb = max(0, min(1024, int(self._scan_options["min_size_bytes"]) // (1024 * 1024)))
        self._min_size_slider.value = min_mb
        self._min_size_label.value = f"Min file size: {min_mb} MB"
        self._exclude_paths_tf.value = "\n".join(self._scan_options["exclude_paths"])
        self._scan_archives_cb.value = bool(self._scan_options["scan_archives"])
        self._archives_warning.visible = bool(self._scan_options["scan_archives"])
        self._include_subfolders_sw.value = bool(self._scan_options["include_subfolders"])
        DashboardPage._safe_update(self._min_size_slider)
        DashboardPage._safe_update(self._min_size_label)
        DashboardPage._safe_update(self._exclude_paths_tf)
        DashboardPage._safe_update(self._scan_archives_cb)
        DashboardPage._safe_update(self._archives_warning)
        DashboardPage._safe_update(self._include_subfolders_sw)

    def _effective_scan_options(self) -> dict:
        """Merge per-mode Home options with global Performance settings for the turbo file engine."""
        opts = dict(self._scan_options)
        try:
            s = self._bridge.get_settings()
            perf = s.get("performance") if isinstance(s, dict) else None
            if isinstance(perf, dict):
                opts["max_threads"] = max(0, min(256, int(perf.get("max_threads", 0) or 0)))
                opts["incremental_scan"] = bool(perf.get("hash_cache_enabled", True))
        except Exception:
            _log.debug("effective_scan_options: could not read performance settings", exc_info=True)
        opts.setdefault("max_threads", 0)
        opts.setdefault("incremental_scan", True)
        # Full-file hashing with auto pick among xxhash / blake3 / sha256 (see turbo_scanner).
        opts.setdefault("hash_algorithm", "auto")
        if getattr(self, "_resume_interrupted_scan_once", False):
            opts = dict(opts)
            opts["resume_interrupted_scan"] = True
        return opts

    def _select_mode(self, key: str) -> None:
        if self._selected_mode == key and key in self._selected_modes:
            return
        self._selected_modes = {str(key or "files")}
        self._selected_mode = key
        self._update_modes_ui()

    def _browse_folders(self, e: ft.ControlEvent) -> None:
        if self._picker_active:
            return
        page = getattr(self._bridge, "flet_page", None)
        if page:
            page.run_task(self._browse_folders_async)

    async def _browse_folders_async(self) -> None:
        if self._picker_active:
            return
        self._picker_active = True
        try:
            result = await self._folder_picker.get_directory_path(
                dialog_title="Select folder to scan"
            )
            if result:
                self._add_folder(Path(result))
        except Exception as exc:
            # "Session closed" is Flet's normal cancellation signal when the
            # user dismisses the dialog — not a real error.
            msg = str(exc).lower()
            if "session" not in msg and "closed" not in msg:
                _log.error("Folder picker failed: %s", exc)
        finally:
            self._picker_active = False

    def _add_folder(self, path: Path) -> None:
        if path in self._folders:
            return
        self._folders.append(path)
        self._refresh_folder_chips()

    def _refresh_folder_chips(self) -> None:
        t = self._t
        if not self._folders:
            self._folder_container.height = 108
            self._folder_container.border = ft.border.all(1, ft.Colors.with_opacity(0.40, "#22D3EE"))
            self._folder_container.border_radius = 12
            self._folder_chips_row.controls = [
                ft.Container(
                    border=ft.border.all(1, ft.Colors.with_opacity(0.52, t.colors.border)),
                    border_radius=10,
                    padding=ft.Padding.symmetric(horizontal=12, vertical=14),
                    bgcolor=ft.Colors.with_opacity(0.07, t.colors.primary),
                    content=ft.Column(
                        [
                            ft.Row(
                                [
                                    ft.Icon(ft.icons.Icons.FILE_UPLOAD_OUTLINED, size=24, color="#22D3EE"),
                                    ft.Text(
                                        "Drop a folder here or click to browse",
                                        color=t.colors.fg2,
                                        size=t.typography.size_base,
                                        weight=ft.FontWeight.W_600,
                                    ),
                                ],
                                spacing=8,
                            ),
                            ft.Text(
                                "Add folders to scan for duplicate files and similar images",
                                color=t.colors.fg2,
                                size=t.typography.size_sm,
                                weight=ft.FontWeight.W_500,
                            ),
                        ],
                        spacing=6,
                    ),
                )
            ]
        else:
            self._folder_container.height = None
            self._folder_container.border = ft.border.all(1, ft.Colors.with_opacity(0.35, "#22D3EE"))
            self._folder_chips_row.controls = [
                ft.Chip(
                    label=ft.Text(self._format_folder_chip_label(f), size=t.typography.size_sm),
                    on_delete=lambda e, p=f: self._remove_folder(p),
                    shape=ft.RoundedRectangleBorder(radius=8),
                    bgcolor=ft.Colors.with_opacity(0.1, t.colors.primary),
                    tooltip=str(f),
                )
                for f in self._folders
            ]
        self._sync_start_button_state()
        if self._is_mounted():
            self._folder_chips_row.update()

    def _remove_folder(self, path: Path) -> None:
        if path in self._folders:
            self._folders.remove(path)
        self._refresh_folder_chips()

    def _sync_start_button_state(self) -> None:
        self._start_btn.disabled = False
        self._start_btn.style = pill_filled_accent(
            self._t,
            padding=ft.Padding.symmetric(horizontal=56, vertical=28),
            text_size=self._t.typography.size_xl,
            weight=ft.FontWeight.W_800,
            border_radius=14,
        )
        DashboardPage._safe_update(self._start_btn)

    def _apply_dashboard_pill_chrome(self) -> None:
        """Match shell nav pill styling; call after theme changes."""
        t = self._t
        self._last_session_btn.style = pill_text_button_style(t, variant="muted")
        self._pause_scan_btn.style = pill_outlined_button_style(t)
        self._sync_start_button_state()
        self._view_results_btn.style = pill_filled_accent(t, text_size=12, weight=ft.FontWeight.W_700)
        self._view_partial_btn.style = pill_outlined_button_style(t)
        self._partial_back_home_btn.style = pill_text_button_style(t, variant="muted")
        self._cancel_btn.style = pill_outlined_button_style(t, danger=True)
        self._exclude_paths_browse_btn.style = pill_outlined_button_style(t)
        self._scan_options_toggle_btn.style = pill_outlined_button_style(t)
        self._cancelled_results_btn.style = pill_text_button_style(t, variant="primary")
        for ctrl in (
            self._last_session_btn,
            self._pause_scan_btn,
            self._view_results_btn,
            self._view_partial_btn,
            self._partial_back_home_btn,
            self._cancel_btn,
            self._exclude_paths_browse_btn,
            self._scan_options_toggle_btn,
            self._cancelled_results_btn,
        ):
            DashboardPage._safe_update(ctrl)

    def _quick_add_desktop_downloads(self, _e: ft.ControlEvent | None = None) -> None:
        home = Path.home()
        candidates = [
            home / "Desktop",
            home / "Downloads",
            home / "OneDrive" / "Desktop",
            home / "OneDrive" / "Downloads",
        ]
        added = 0
        for p in candidates:
            if p.is_dir() and p not in self._folders:
                self._folders.append(p)
                added += 1
        self._refresh_folder_chips()
        if added:
            self._bridge.show_snackbar("Desktop/Downloads added.", info=True)
        else:
            self._bridge.show_snackbar("No quick-add folders found.", info=True)

    async def _flash_folder_validation(self) -> None:
        original = self._folder_container.border
        original_bg = self._folder_container.bgcolor
        self._folder_container.border = ft.border.all(2, "#EF4444")
        self._folder_container.bgcolor = ft.Colors.with_opacity(0.12, "#EF4444")
        DashboardPage._safe_update(self._folder_container)
        await asyncio.sleep(0.35)
        self._folder_container.border = original
        self._folder_container.bgcolor = original_bg
        DashboardPage._safe_update(self._folder_container)

    def _start_scan(self, e: ft.ControlEvent) -> None:
        if not self._folders:
            self._status.value = "Please add a folder to continue."
            self._status.update()
            try:
                self._bridge.show_snackbar("Please add a folder to continue.", info=True)
                self._bridge.flet_page.run_task(self._flash_folder_validation)
            except Exception:
                pass
            return

        root_drive = self._root_drive_selection()
        if root_drive and not self._is_root_drive_warning_acknowledged(root_drive):
            _log.info("root_drive_warning drive=%s", root_drive)
            self._show_root_drive_warning(root_drive)
            return
        self._begin_scan()

    def _begin_scan(self) -> None:
        resume_interrupted = bool(getattr(self, "_resume_interrupted_scan_once", False))
        self._was_cancelled = False
        self._pending_partial_results = []
        self._reset_cancel_choice_for_new_scan()
        scan_modes = self._selected_modes_for_scan()
        self._pending_partial_mode = "+".join(scan_modes)
        self._hide_cancelled_results_banner()
        self._io_failure_hits_by_root.clear()
        self._io_pause_dialog_open = False
        self._io_paused_root = ""
        self._scan_network_warn_shown = False
        self._scan_files_catalogued = 0
        self._scan_accept_progress = True
        self._last_progress_elapsed_seconds = 0.0
        self._bar_slices = 0
        self._bar_active_markers.clear()
        self._bar_is_complete = False
        self._bar_last_dupes = 0
        self._bar_row.visible = False
        self._bar_overlay.visible = False
        self._draw_bar()
        self._ring.value = None  # indeterminate until first progress tick
        self._ring.color = self._heat_color_for_ratio(0.0)
        self._ring_phase_label.value = ""
        self._scan_mode_run_label.value = self._scan_modes_display_label(scan_modes)
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
        self._view_results_btn.visible = False
        self._view_partial_btn.visible = True
        self._view_partial_btn.disabled = False
        for p in self._main_panels:
            p.visible = False
        self._scan_view.visible = True
        DashboardPage._safe_update(self)
        self._last_incomplete_persist_ts = time.monotonic()
        self._persist_incomplete_scan_session(status="in_progress")
        _log.info(
            "scan_start folders=%d modes=%s archives=%s resume_interrupted=%s",
            len(self._folders),
            scan_modes,
            bool(self._scan_options.get("scan_archives", False)),
            resume_interrupted,
        )

        self._bridge.begin_scan_session(self._folders, "+".join(scan_modes))
        self._start_scan_elapsed_timer()
        self._speed_points.clear()
        self._eta_smoothed_seconds = None
        self._eta_last_stage = ""
        self._eta_last_update_ts = 0.0
        self._scan_elapsed_clock.value = self._scan_elapsed_clock_value()
        self._ring_timer.value = self._build_scan_timer_line()
        try:
            if self._scan_elapsed_clock.page is not None:
                self._scan_elapsed_clock.update()
            if self._ring_timer.page is not None:
                self._ring_timer.update()
        except Exception:
            pass

        try:
            backend = self._bridge.backend
            backend.set_on_progress(self._on_scan_progress)
            backend.set_on_complete(self._on_scan_complete)
            backend.set_on_error(self._on_scan_error)
            scan_opts = self._effective_scan_options()
            backend.start_scan(self._folders, mode=scan_modes, options=scan_opts)
            self._sync_pause_scan_hero_button()
            self._resume_interrupted_scan_once = False
            if resume_interrupted:
                try:
                    self._bridge.show_snackbar(
                        "Continuing interrupted scan — hash and folder caches reuse finished work when paths and filters match.",
                        info=True,
                    )
                except Exception:
                    pass
        except Exception as err:
            self._on_scan_error(f"Backend communication error: {err}")

    def _root_drive_selection(self) -> str:
        for p in self._folders:
            try:
                resolved = Path(p).resolve()
            except OSError:
                resolved = Path(p)
            anchor = str(resolved.anchor or "").upper()
            if not anchor:
                continue
            norm = str(resolved).replace("/", "\\").rstrip("\\")
            root = anchor.rstrip("\\")
            if norm == root:
                return anchor
        return ""

    def _is_root_drive_warning_acknowledged(self, drive_anchor: str) -> bool:
        settings = self._bridge.get_settings()
        scan_cfg = settings.get("scan") if isinstance(settings, dict) else {}
        warned = scan_cfg.get("warned_root_drives") if isinstance(scan_cfg, dict) else []
        if not isinstance(warned, list):
            return False
        needle = str(drive_anchor).upper()
        return needle in [str(x).upper() for x in warned]

    def _ack_root_drive_warning(self, drive_anchor: str) -> None:
        settings = self._bridge.get_settings()
        if not isinstance(settings, dict):
            settings = {}
        scan_cfg = settings.get("scan")
        if not isinstance(scan_cfg, dict):
            scan_cfg = {}
        warned = scan_cfg.get("warned_root_drives")
        if not isinstance(warned, list):
            warned = []
        anchor = str(drive_anchor).upper()
        if anchor not in [str(x).upper() for x in warned]:
            warned.append(anchor)
            scan_cfg["warned_root_drives"] = warned
            settings["scan"] = scan_cfg
            self._bridge.save_settings(settings)

    def _show_root_drive_warning(self, drive_anchor: str) -> None:
        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Root drive scan warning"),
            content=ft.Text(
                f"Scanning {drive_anchor} can take hours and include many system files. Continue?"
            ),
            actions=[
                ft.TextButton("Cancel", on_click=lambda _e: self._bridge.dismiss_top_dialog()),
                ft.FilledButton(
                    "Continue",
                    on_click=lambda _e, d=drive_anchor: self._confirm_root_drive_scan(d),
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self._bridge.show_modal_dialog(dialog)

    def _confirm_root_drive_scan(self, drive_anchor: str) -> None:
        self._bridge.dismiss_top_dialog()
        self._ack_root_drive_warning(drive_anchor)
        _log.info("root_drive_warning_acknowledged drive=%s", drive_anchor)
        self._begin_scan()

    def _persist_incomplete_scan_session(
        self,
        *,
        status: str,
        progress_snapshot: Optional[dict] = None,
    ) -> None:
        snap = progress_snapshot if progress_snapshot is not None else dict(getattr(self, "_scan_hud_snap", None) or {})
        last_progress: dict = {}
        if snap:
            last_progress = {
                "stage": str(snap.get("stage") or ""),
                "scanned": int(snap.get("scanned") or 0),
                "total": int(snap.get("total") or 0),
                "total_files_in_scope": int(snap.get("total_files_in_scope") or 0),
                "files_processed": int(snap.get("files_processed") or 0),
                "candidates_found": int(snap.get("candidates_found") or 0),
            }
        try:
            modes_list = list(self._selected_modes_for_scan())
        except (AttributeError, TypeError):
            modes_list = [str(getattr(self, "_selected_mode", "files") or "files")]
        payload = {
            "status": str(status),
            "timestamp": time.time(),
            "folders": [str(p) for p in getattr(self, "_folders", []) or []],
            "mode": str(getattr(self, "_selected_mode", None) or "files"),
            "modes": modes_list,
            "options": dict(getattr(self, "_scan_options", {}) or {}),
        }
        if last_progress:
            payload["last_progress"] = last_progress
        try:
            _INCOMPLETE_SCAN_PATH.parent.mkdir(parents=True, exist_ok=True)
            _INCOMPLETE_SCAN_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except OSError:
            _log.exception("Failed writing incomplete scan snapshot")

    def _clear_incomplete_scan_session(self) -> None:
        try:
            if _INCOMPLETE_SCAN_PATH.exists():
                _INCOMPLETE_SCAN_PATH.unlink()
        except OSError:
            _log.exception("Failed clearing incomplete scan snapshot")

    def _refresh_paused_scans(self) -> None:
        """Populate the checkpoint-restore cards from checkpoint DB (non-blocking)."""
        try:
            from cerebro.v2.core.checkpoint_db import get_checkpoint_db
            ckpt = get_checkpoint_db()
            manifests = ckpt.list_resumable_manifests()
        except Exception:
            manifests = []

        t = self._t
        s = t.spacing
        self._paused_scans_col.controls.clear()

        for m in manifests:
            total, pending = 0, 0
            try:
                from cerebro.v2.core.checkpoint_db import get_checkpoint_db
                total, pending = get_checkpoint_db().get_counts(m.scan_id)
            except Exception:
                pass
            if total == 0:
                continue
            completed = total - pending
            pct = int(completed / total * 100) if total else 0
            stamp = time.strftime("%b %d %H:%M", time.localtime(m.created_at))
            folders_preview = ", ".join(Path(p).name for p in m.root_paths[:2])
            if len(m.root_paths) > 2:
                folders_preview += f" +{len(m.root_paths) - 2}"

            def _make_resume_cb(manifest=m):
                return lambda _e: self._resume_checkpoint_manifest(manifest)

            def _make_discard_cb(manifest=m):
                return lambda _e: self._discard_checkpoint_manifest(manifest)

            card = ft.Container(
                content=ft.Row(
                    [
                        ft.Column(
                            [
                                ft.Text(
                                    folders_preview,
                                    size=t.typography.size_sm,
                                    weight=ft.FontWeight.W_600,
                                    color=t.colors.fg,
                                    no_wrap=True,
                                    overflow=ft.TextOverflow.ELLIPSIS,
                                ),
                                ft.Text(
                                    f"{completed:,} of {total:,} files hashed ({pct}%) • {stamp}",
                                    size=t.typography.size_xs,
                                    color=t.colors.fg_muted,
                                ),
                                ft.ProgressBar(
                                    value=completed / max(1, total),
                                    width=240,
                                    height=4,
                                    color=t.colors.accent,
                                    bgcolor=ft.Colors.with_opacity(0.2, t.colors.accent),
                                ),
                            ],
                            spacing=3,
                            expand=True,
                        ),
                        ft.Row(
                            [
                                ft.TextButton(
                                    "Discard",
                                    on_click=_make_discard_cb(),
                                    style=ft.ButtonStyle(color=t.colors.fg_muted),
                                ),
                                ft.FilledButton(
                                    f"Restore checkpoint ({pending:,} left)",
                                    on_click=_make_resume_cb(),
                                    style=ft.ButtonStyle(
                                        shape=ft.RoundedRectangleBorder(radius=8),
                                    ),
                                ),
                            ],
                            spacing=s.xs,
                        ),
                    ],
                    spacing=s.md,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                padding=ft.Padding.symmetric(horizontal=s.sm, vertical=s.xs),
                border_radius=8,
                bgcolor=ft.Colors.with_opacity(0.06, t.colors.fg),
            )
            self._paused_scans_col.controls.append(card)

        has_items = bool(self._paused_scans_col.controls)
        self._paused_scans_section.visible = has_items
        self._paused_scans_col.visible = has_items
        if self._is_mounted():
            try:
                self._paused_scans_section.update()
            except Exception:
                pass

    def prompt_resume_incomplete_scan_if_needed(self) -> None:
        """Show resume prompt from checkpoint DB or fall back to incomplete_scan.json."""
        try:
            self._refresh_paused_scans()
        except Exception:
            pass

        # Legacy JSON fallback for users upgrading from prior build
        if not _INCOMPLETE_SCAN_PATH.exists():
            return
        try:
            data = json.loads(_INCOMPLETE_SCAN_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            self._clear_incomplete_scan_session()
            return
        if not isinstance(data, dict):
            self._clear_incomplete_scan_session()
            return
        folders = data.get("folders")
        if not isinstance(folders, list) or not folders:
            self._clear_incomplete_scan_session()
            return

        # Migrate to checkpoint DB then clear the JSON file
        try:
            from cerebro.v2.core.checkpoint_db import get_checkpoint_db
            import json as _json
            _scope = {k: data.get("options", {}).get(k) for k in
                      ("min_size_bytes", "max_size_bytes", "skip_hidden", "recursive", "exclude_paths", "scan_archives")}
            get_checkpoint_db().create_manifest(folders, _scope, label="(migrated)")
        except Exception:
            pass
        self._clear_incomplete_scan_session()
        try:
            self._refresh_paused_scans()
        except Exception:
            pass

    def _discard_checkpoint_manifest(self, manifest) -> None:
        try:
            from cerebro.v2.core.checkpoint_db import get_checkpoint_db
            ckpt = get_checkpoint_db()
            ckpt.update_manifest_status(manifest.scan_id, "completed")
        except Exception:
            pass
        self._refresh_paused_scans()
        _log.info("checkpoint manifest discarded: scan_id=%s", manifest.scan_id)

    def _resume_checkpoint_manifest(self, manifest) -> None:
        folders = [Path(p) for p in manifest.root_paths if Path(p).exists()]
        if not folders:
            self._bridge.show_snackbar("Scan folders are no longer available.", info=True)
            return
        self._folders = folders
        try:
            scope = json.loads(manifest.scope_json)
            min_bytes = int(scope.get("min_size_bytes") or scope.get("min_size") or 0)
            merged = dict(self._scan_options)
            merged["min_size_bytes"] = min_bytes
            merged["scan_archives"] = bool(scope.get("scan_archives", False))
            merged["include_subfolders"] = bool(scope.get("recursive", True))
            ex = scope.get("exclude_paths", [])
            merged["exclude_paths"] = list(ex) if isinstance(ex, list) else []
            self._scan_options = merged
            min_mb = max(0, min(1024, min_bytes // (1024 * 1024)))
            self._min_size_slider.value = min_mb
            self._min_size_label.value = f"Min file size: {min_mb} MB"
            self._exclude_paths_tf.value = "\n".join(merged["exclude_paths"])
            self._scan_archives_cb.value = merged["scan_archives"]
            self._archives_warning.visible = merged["scan_archives"]
            self._include_subfolders_sw.value = merged["include_subfolders"]
        except Exception:
            _log.debug("Could not restore scope from manifest (non-fatal)", exc_info=True)
        self._refresh_folder_chips()
        self._update_modes_ui()
        self._resume_interrupted_scan_once = True
        _log.info("resume_checkpoint_manifest scan_id=%s folders=%d", manifest.scan_id, len(folders))
        self._begin_scan()

    def _discard_incomplete_resume_prompt(self) -> None:
        self._bridge.dismiss_top_dialog()
        self._clear_incomplete_scan_session()
        _log.info("resume_incomplete_scan discarded")

    def _resume_incomplete_scan(self, data: dict) -> None:
        self._bridge.dismiss_top_dialog()
        folders_raw = data.get("folders", [])
        mode = str(data.get("mode", "files") or "files")
        modes = data.get("modes", [])
        options = data.get("options", {})
        folders = [Path(str(p)) for p in folders_raw if Path(str(p)).exists()]
        if not folders:
            self._clear_incomplete_scan_session()
            self._bridge.show_snackbar(
                "Saved scan folders are unavailable. Restore from checkpoint was skipped.",
                info=True,
            )
            return
        self._folders = folders
        if isinstance(modes, list):
            restored_modes = {str(m).strip() for m in modes if str(m).strip()}
        else:
            restored_modes = set()
        if not restored_modes:
            restored_modes = {mode or "files"}
        self._selected_modes = {"files"} if "files" in restored_modes else restored_modes
        self._selected_mode = self._primary_selected_mode()
        merged_options = dict(self._scan_options)
        if isinstance(options, dict):
            merged_options.update(options)
        merged_options["scan_archives"] = bool(merged_options.get("scan_archives", False))
        merged_options["min_size_bytes"] = int(merged_options.get("min_size_bytes", 0) or 0)
        raw_ex = merged_options.get("exclude_paths", [])
        merged_options["exclude_paths"] = [str(x) for x in raw_ex] if isinstance(raw_ex, list) else []
        merged_options["include_subfolders"] = bool(merged_options.get("include_subfolders", True))
        self._scan_options = merged_options

        min_bytes = int(self._scan_options.get("min_size_bytes", 0) or 0)
        min_mb = max(0, min(1024, min_bytes // (1024 * 1024)))
        self._min_size_slider.value = min_mb
        self._min_size_label.value = f"Min file size: {min_mb} MB"
        self._exclude_paths_tf.value = "\n".join(self._scan_options.get("exclude_paths", []))
        self._scan_archives_cb.value = bool(self._scan_options.get("scan_archives", False))
        self._archives_warning.visible = bool(self._scan_options.get("scan_archives", False))
        self._include_subfolders_sw.value = bool(self._scan_options.get("include_subfolders", True))
        self._refresh_folder_chips()
        self._update_modes_ui()
        self._resume_interrupted_scan_once = True
        _log.info("resume_incomplete_scan folders=%d mode=%s", len(self._folders), self._selected_mode)
        self._begin_scan()

    _RING_INDETERMINATE_STAGES = frozenset({ScanStage.DISCOVERING, ScanStage.GROUPING_BY_SIZE})

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
        if stage == ScanStage.GROUPING_BY_SIZE:
            # Full file count here is not "done"; keep mid-heat until hashing ratio drives color.
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
                ScanStage.HASHING_PARTIAL,
                ScanStage.HASHING_FULL,
                ScanStage.COMPLETE,
                ScanStage.CANCELLED,
            }
        )
        if key in known:
            return key
        aliases = {
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
        self._cancel_complete_handled = False
        self._cancel_user_dismissed_choice = False
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

    def _present_cancel_waiting_for_results(self, *, phase_files: int) -> None:
        """Stop UI: stay on scan surface with a clear fork until the engine reports partial groups."""
        t = self._t
        frozen_elapsed = DashboardPage._fmt_elapsed_compact(
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
        self._scan_view.visible = True
        for p in self._main_panels:
            p.visible = False
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
        self._pending_partial_results = list(results)
        self._pending_partial_mode = mode
        self._cancel_complete_handled = True
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
        self._view_results_btn.visible = False
        self._partial_results_row.visible = True
        self._cancel_choice_panel.visible = True
        self._scan_view.visible = True
        for p in self._main_panels:
            p.visible = False
        self._scan_hud_snap = dict(self._scan_hud_snap)
        self._scan_hud_snap["rate"] = None
        try:
            self._scan_elapsed_clock.value = f"Total {DashboardPage._fmt_elapsed_compact(max(0.0, time.monotonic() - self._scan_elapsed_start))}"
        except Exception:
            pass

        if self._cancel_user_dismissed_choice:
            self._cancel_user_dismissed_choice = False
            self._cancel_choice_panel.visible = False
            self._partial_results_row.visible = False
            self._scan_view.visible = False
            for p in self._main_panels:
                p.visible = True
            if ng > 0:
                self._show_cancelled_results_banner(
                    f"Partial scan: {ng:,} duplicate group(s) are ready — open from this banner when you want."
                )
            self._show_cancelled_status()
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
            self._phase_hash_bar.value = None
            self._phase_hash_caption.value = "Not started — waits for grouping to finish."
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

    def _on_scan_progress(self, data: dict) -> None:
        if not self._scan_accept_progress:
            return
        raw_stage = data.get("stage", "")
        stage = DashboardPage._normalize_scan_stage_for_ui(raw_stage)
        if stage and stage not in frozenset(
            {
                ScanStage.DISCOVERING,
                ScanStage.GROUPING_BY_SIZE,
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
            if not self._scan_network_warn_shown:
                self._scan_network_warn_shown = True
                try:
                    self._bridge.show_snackbar(
                        "Some paths became unavailable — skipped or retried files can make this run incomplete.",
                        info=True,
                    )
                except Exception:
                    pass
            root = self._extract_unreachable_root(current_file)
            if root:
                self._handle_repeated_io_failure(root)
                self._sync_pause_scan_hero_button()
            if current_file_path or current_file:
                self._ring_path.value = str(current_file_path or current_file)
            return

        # Ignore a late "complete" tick from the scanner after the user cancelled —
        # otherwise the HUD briefly shows "Finishing up…" with no terminal event.
        if self._was_cancelled and stage == ScanStage.COMPLETE and state != "cancelled":
            return

        # Handle cancelled terminal event from progress stream (may arrive before on_complete).
        if state == "cancelled" or stage == ScanStage.CANCELLED:
            self._cancel_watchdog_token += 1
            if self._cancel_complete_handled:
                self._sync_pause_scan_hero_button()
                self._do_page_update()
                return
            self._was_cancelled = True
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
                self._persist_incomplete_scan_session(
                    status="interrupted",
                    progress_snapshot=interrupt_snap,
                )
            except Exception:
                _log.debug("persist interrupted snapshot failed", exc_info=True)
            self._sync_pause_scan_hero_button()
            self._do_page_update()
            return

        if stage in (ScanStage.DISCOVERING, ScanStage.GROUPING_BY_SIZE):
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
        self._scan_elapsed_clock.value = DashboardPage._fmt_elapsed_compact(
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

        self._sync_pause_scan_hero_button()
        self._do_page_update()

    def _do_page_update(self) -> None:
        """Call page.update() and log any failure instead of silently ignoring it."""
        try:
            self._bridge.flet_page.update()
        except Exception as exc:
            _log.debug("page.update() failed in progress callback: %s", exc)

    # ------------------------------------------------------------------
    # Canvas chunk bar
    # ------------------------------------------------------------------

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
        return DashboardPage._fmt_elapsed_compact(max(0.0, mono, eng))

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
        if not self._scan_view.visible:
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
            DashboardPage._safe_update(self._scan_elapsed_clock)
            DashboardPage._safe_update(self._ring_timer)
            DashboardPage._safe_update(self._ring_path)
            DashboardPage._safe_update(self._ring_label)
            now = time.monotonic()
            if now - float(getattr(self, "_last_incomplete_persist_ts", 0.0) or 0.0) >= 15.0:
                self._last_incomplete_persist_ts = now
                try:
                    self._persist_incomplete_scan_session(status="in_progress")
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

    def _on_scan_complete(self, results: list, mode: str) -> None:
        self._scan_accept_progress = False
        self._cancel_watchdog_token += 1
        self._pause_scan_btn.visible = False
        eng_wall = float(getattr(self, "_last_progress_elapsed_seconds", 0.0) or 0.0)
        frozen_scan_elapsed = DashboardPage._fmt_elapsed_compact(
            max(0.0, time.monotonic() - self._scan_elapsed_start, eng_wall)
        )
        self._stop_scan_elapsed_timer()
        # If cancel was clicked, the backend still calls on_complete with partial
        # results (state=cancelled). Route those to the partial-results flow.
        if self._was_cancelled:
            self._finalize_cancel_choice_with_results(list(results), mode)
            if not results:
                self._ring_phase_label.value = "No duplicate groups could be found before cancellation."
            # Do not leave the hashing headline / path up — cancel return used to skip these.
            self._ring_label.value = "Scan cancelled"
            self._ring_path.value = ""
            try:
                self._scan_elapsed_clock.value = frozen_scan_elapsed
            except Exception:
                pass
            DashboardPage._safe_update(self)
            return

        # Normal completion: show "View Results" button, then transition.
        self._clear_incomplete_scan_session()
        try:
            self._refresh_paused_scans()
        except Exception:
            pass
        self._update_dual_phase_bars(ScanStage.COMPLETE, 0, 0)
        self._ring.value = 1.0
        self._ring.color = self._heat_color_for_ratio(1.0)
        ng = len(results)
        self._ring_phase_label.value = (
            "Assembling duplicate groups from hash results." if ng else "Finished — nothing to compare."
        )
        self._ring_label.value = f"Scan complete — {ng:,} duplicate group(s) found." if ng > 0 else "Scan complete — no duplicates found."
        self._ring_counter.value = ""
        self._scan_mode_run_label.value = ""
        self._ring_timer.value = ""
        try:
            self._scan_elapsed_clock.value = frozen_scan_elapsed
        except Exception:
            pass
        self._ring_path.value = ""
        self._cancel_btn.visible = False
        self._view_results_btn.visible = True
        # Complete the canvas bar.
        self._bar_is_complete = True
        self._bar_active_markers.clear()
        self._bar_row.visible = True
        self._ring_counter_tip.visible = False

        cast = self._bar_overlay.content
        if isinstance(cast, ft.Text):
            cast.value = f"✓ {len(results):,} duplicate groups found" if ng > 0 else "✓ No duplicate groups detected"
        self._bar_overlay.visible = True
        self._draw_bar()
        DashboardPage._safe_update(self)

        self._bridge.dispatch_scan_complete(results, mode)
        try:
            reclaimed = int(sum(getattr(g, "reclaimable", 0) for g in results))
        except Exception:
            reclaimed = 0
        if reclaimed >= 1_073_741_824:
            self._bridge.show_snackbar(
                f"Great cleanup! Reclaimable space exceeds 1 GB ({fmt_size(reclaimed)}).",
                success=True,
            )
        self._bridge.play_sound("success")
        # Global listeners (store, navigation, child pages) run during dispatch; re-latch terminal
        # copy so a queued progress tick or side effect cannot leave "Comparing…" + a live path up.
        self._ring_label.value = (
            f"Scan complete — {ng:,} duplicate group(s) found." if ng > 0 else "Scan complete — no duplicates found."
        )
        self._ring_phase_label.value = (
            "Assembling duplicate groups from hash results." if ng else "Finished — nothing to compare."
        )
        self._ring_path.value = ""
        try:
            self._scan_elapsed_clock.value = frozen_scan_elapsed
        except Exception:
            pass
        DashboardPage._safe_update(self._ring_label)
        DashboardPage._safe_update(self._ring_phase_label)
        DashboardPage._safe_update(self._ring_path)
        DashboardPage._safe_update(self._scan_elapsed_clock)

    def _on_scan_error(self, msg: str) -> None:
        self._scan_accept_progress = False
        self._cancel_watchdog_token += 1
        if "network path unreachable:" in str(msg or "").lower():
            root = self._extract_unreachable_root(str(msg))
            if root:
                self._handle_repeated_io_failure(root)
                return
        self._pause_scan_btn.visible = False
        self._stop_scan_elapsed_timer()
        self._ring_timer.value = ""
        try:
            self._scan_elapsed_clock.value = ""
        except Exception:
            pass
        self._bar_row.visible = False
        try:
            self._persist_incomplete_scan_session(
                status="error",
                progress_snapshot=dict(self._scan_hud_snap or {}),
            )
        except Exception:
            self._persist_incomplete_scan_session(status="error")
        self._bridge.abort_scan_session()
        self._scan_view.visible = False
        for p in self._main_panels:
            p.visible = True
        self._status.value = f"Scan error: {msg}"
        DashboardPage._safe_update(self)
        self._bridge.play_sound("error")

    def _folders_readable_for_continue_scan(self) -> tuple[bool, str]:
        """Return (True, '') if every scan folder exists and is readable; else (False, hint path)."""
        for raw in list(getattr(self, "_folders", []) or []):
            p = Path(raw)
            try:
                resolved = p.resolve()
            except OSError:
                resolved = p
            try:
                if not resolved.exists():
                    return False, str(p)
                if not os.access(os.fspath(resolved), os.R_OK):
                    return False, str(p)
            except OSError:
                return False, str(p)
        return True, ""

    def _sync_pause_scan_hero_button(self) -> None:
        """Show Pause / Continue scan under START when a scan is active; hide when idle or cancelling."""
        btn = self._pause_scan_btn
        try:
            scanning = bool(self._bridge.backend.is_scanning)
        except Exception:
            scanning = False
        show = scanning and bool(self._scan_view.visible) and not self._was_cancelled
        if not show:
            btn.visible = False
            btn.text = "Pause scan"
            btn.icon = ft.icons.Icons.PAUSE
            btn.style = pill_outlined_button_style(self._t)
            btn.disabled = False
            DashboardPage._safe_update(btn)
            return
        paused = False
        try:
            paused = bool(self._bridge.backend.is_paused)
        except Exception:
            paused = False
        if paused:
            btn.text = "Continue scan"
            btn.icon = ft.icons.Icons.PLAY_ARROW
            btn.style = pill_outlined_button_style(self._t, success=True)
        else:
            btn.text = "Pause scan"
            btn.icon = ft.icons.Icons.PAUSE
            btn.style = pill_outlined_button_style(self._t)
        btn.visible = True
        btn.disabled = False
        DashboardPage._safe_update(btn)

    def _on_hero_pause_toggle(self, _e: ft.ControlEvent) -> None:
        if self._was_cancelled:
            return
        try:
            if not self._bridge.backend.is_scanning:
                return
        except Exception:
            return
        try:
            if self._bridge.backend.is_paused:
                ok, bad = self._folders_readable_for_continue_scan()
                if not ok:
                    try:
                        self._bridge.show_snackbar(
                            f"Cannot continue — folder not accessible ({bad}). Reconnect the drive and try again.",
                            info=True,
                        )
                    except Exception:
                        pass
                    return
                self._bridge.backend.resume_scan()
                try:
                    self._persist_incomplete_scan_session(status="in_progress")
                except Exception:
                    _log.debug("persist after continue scan failed", exc_info=True)
            else:
                self._bridge.backend.pause_scan()
                try:
                    self._persist_incomplete_scan_session(status="in_progress")
                except Exception:
                    _log.debug("persist after pause scan failed", exc_info=True)
        except Exception:
            _log.exception("Hero pause/continue")
        self._sync_pause_scan_hero_button()

    def _stop_scan(self, e: ft.ControlEvent) -> None:
        elapsed_minutes = max(0, int((time.monotonic() - self._scan_elapsed_start) / 60))
        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Cancel scanning?"),
            content=ft.Text(
                f"{elapsed_minutes} minute(s) of progress will be lost."
            ),
            actions=[
                ft.TextButton("Keep Scanning", on_click=lambda _ev: self._bridge.dismiss_top_dialog()),
                ft.FilledButton("Cancel Scan", on_click=self._confirm_stop_scan),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self._bridge.show_modal_dialog(dialog)

    def _confirm_stop_scan(self, _e: ft.ControlEvent) -> None:
        self._bridge.dismiss_top_dialog()
        self._persist_incomplete_scan_session(status="cancel_requested")
        snap = dict(self._scan_hud_snap or {})
        _log.info(
            "cancel_requested stage=%s scanned=%s total=%s candidates=%s",
            snap.get("stage", ""),
            snap.get("scanned", 0),
            snap.get("total", 0),
            snap.get("candidates_found", 0),
        )
        self._cancel_btn.text = "Cancelling…"
        self._cancel_btn.disabled = True
        self._was_cancelled = True
        self._sync_pause_scan_hero_button()
        self._ring_label.value = "Cancelling…"
        self._ring_phase_label.value = "Stopping the engine safely — this can take a moment on large scans."
        self._ring_timer.value = "Cancel requested — waiting for engine to stop…"
        self._cancel_watchdog_token += 1
        token = self._cancel_watchdog_token
        DashboardPage._safe_update(self)
        try:
            self._bridge.flet_page.update()
        except Exception:
            pass
        try:
            self._bridge.backend.cancel_scan()
            try:
                self._bridge.flet_page.run_task(self._cancel_watchdog_tick, token)
            except Exception:
                pass
        except Exception as err:
            _log.error("Failed to stop scan: %s", err)

    async def _cancel_watchdog_tick(self, token: int) -> None:
        """Keep users informed if engine cancellation takes longer than expected."""
        await asyncio.sleep(15.0)
        if token != self._cancel_watchdog_token:
            return
        if not self._scan_view.visible or not self._was_cancelled:
            return
        stage = str((self._scan_hud_snap or {}).get("stage") or "")
        scanned = int((self._scan_hud_snap or {}).get("scanned") or 0)
        total = int((self._scan_hud_snap or {}).get("total") or 0)
        backend_running = False
        try:
            backend_running = bool(getattr(self._bridge.backend, "is_scanning", False))
        except Exception:
            backend_running = False
        _log.warning(
            "cancel_waiting stage=%s scanned=%d total=%d backend_scanning=%s",
            stage,
            scanned,
            total,
            backend_running,
        )
        self._ring_phase_label.value = (
            "Still stopping the engine… large candidate sets can take longer to unwind."
        )
        self._ring_timer.value = "Cancel requested — waiting for terminal callback…"
        DashboardPage._safe_update(self)
        # Keep notifying while cancellation is still pending.
        if backend_running:
            try:
                self._bridge.flet_page.run_task(self._cancel_watchdog_tick, token)
            except Exception:
                pass

    @staticmethod
    def _extract_unreachable_root(message: str) -> str:
        text = str(message or "").strip()
        m = re.search(r"Network path unreachable:\s*(.+)$", text)
        if not m:
            return ""
        return str(m.group(1)).strip()

    def _handle_repeated_io_failure(self, root: str) -> None:
        key = str(root).strip()
        if not key:
            return
        hits = int(self._io_failure_hits_by_root.get(key, 0)) + 1
        self._io_failure_hits_by_root[key] = hits
        self._status.value = f"I/O issue on {key} (attempt {hits})"
        DashboardPage._safe_update(self._status)
        if hits < 3 or self._io_pause_dialog_open:
            return

        self._io_pause_dialog_open = True
        self._io_paused_root = key
        try:
            self._bridge.backend.pause_scan()
        except Exception:
            _log.exception("Failed to pause scan after repeated I/O failures")
        self._sync_pause_scan_hero_button()

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Drive disconnected"),
            content=ft.Text(
                f"Repeated read failures were detected at:\n{key}\n\n"
                "The scan is paused. Choose Continue scan to keep trying, or Cancel to stop now and keep partial results."
            ),
            actions=[
                ft.TextButton("Continue scan", on_click=self._resume_after_io_pause),
                ft.FilledButton("Cancel & Keep Partial Results", on_click=self._cancel_after_io_pause),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self._bridge.show_modal_dialog(dialog)

    def _resume_after_io_pause(self, _e: ft.ControlEvent) -> None:
        self._bridge.dismiss_top_dialog()
        self._io_pause_dialog_open = False
        if self._io_paused_root:
            self._io_failure_hits_by_root[self._io_paused_root] = 0
        self._io_paused_root = ""
        ok, bad = self._folders_readable_for_continue_scan()
        if not ok:
            try:
                self._bridge.show_snackbar(
                    f"Cannot continue — folder not accessible ({bad}). Reconnect the drive and try again.",
                    info=True,
                )
            except Exception:
                pass
            self._sync_pause_scan_hero_button()
            return
        try:
            self._bridge.backend.resume_scan()
            try:
                self._persist_incomplete_scan_session(status="in_progress")
            except Exception:
                _log.debug("persist after I/O continue failed", exc_info=True)
        except Exception:
            _log.exception("Failed to continue scan after I/O pause")
        self._sync_pause_scan_hero_button()

    def _cancel_after_io_pause(self, _e: ft.ControlEvent) -> None:
        self._bridge.dismiss_top_dialog()
        self._io_pause_dialog_open = False
        paused_root = self._io_paused_root
        self._io_paused_root = ""
        self._persist_incomplete_scan_session(status="cancel_requested")
        self._cancel_btn.text = "Cancelling…"
        self._cancel_btn.disabled = True
        self._was_cancelled = True
        try:
            self._bridge.backend.cancel_scan()
        except Exception:
            _log.exception("Failed to cancel scan after I/O pause")
        if paused_root:
            self._status.value = f"Drive disconnected at {paused_root}. Cancelling and preserving partial results."
            DashboardPage._safe_update(self._status)
        self._sync_pause_scan_hero_button()

    def _go_to_results(self, e: ft.ControlEvent) -> None:
        """Navigate to results after a successful scan completion."""
        self._pause_scan_btn.visible = False
        self._scan_view.visible = False
        for p in self._main_panels:
            p.visible = True
        self._status.value = "Scan complete."
        DashboardPage._safe_update(self)
        try:
            self._bridge.navigate("review")
        except Exception:
            pass

    def _go_to_partial_results(self, e: ft.ControlEvent) -> None:
        """Navigate to results page with whatever groups the scanner found before cancel."""
        results = self._pending_partial_results
        mode = self._pending_partial_mode
        if not results:
            try:
                self._bridge.show_snackbar(
                    "No duplicate groups could be built before cancellation — nothing to review.",
                    info=True,
                )
            except Exception:
                pass
            return
        self._cancel_choice_panel.visible = False
        self._partial_results_row.visible = False
        self._pause_scan_btn.visible = False
        self._scan_view.visible = False
        for p in self._main_panels:
            p.visible = True
        self._hide_cancelled_results_banner()
        self._status.value = f"Scan cancelled — {len(results):,} partial groups available."
        DashboardPage._safe_update(self)
        try:
            self._bridge.dispatch_scan_complete(results, mode)
            self._bridge.navigate("review")
        except Exception as err:
            _log.error("Navigate to partial results failed: %s", err)

    def _go_to_home(self, e: ft.ControlEvent) -> None:
        """Dismiss the scan view and return to the main panels."""
        self._cancel_user_dismissed_choice = True
        self._pause_scan_btn.visible = False
        self._stop_scan_elapsed_timer()
        self._ring_timer.value = ""
        try:
            self._scan_elapsed_clock.value = ""
        except Exception:
            pass
        pending = list(self._pending_partial_results or [])
        had_partial = len(pending) > 0 and self._was_cancelled
        self._bridge.abort_scan_session()
        self._cancel_choice_panel.visible = False
        self._partial_results_row.visible = False
        self._scan_view.visible = False
        for p in self._main_panels:
            p.visible = True
        if had_partial:
            self._show_cancelled_results_banner(
                f"Partial scan: {len(pending):,} duplicate group(s) are still available — open from this banner when you are ready."
            )
        self._show_cancelled_status()
        DashboardPage._safe_update(self)

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

    @staticmethod
    def _format_folder_chip_label(path: Path) -> str:
        return str(path)

    async def _clear_status_after(self, token: int, seconds: float) -> None:
        await asyncio.sleep(seconds)
        if token != self._status_token:
            return
        self._status.value = ""
        DashboardPage._safe_update(self._status)

    def _show_cancelled_status(self) -> None:
        ts = time.strftime("%H:%M:%S")
        self._status_token += 1
        token = self._status_token
        self._status.value = f"Scan cancelled at {ts}."
        DashboardPage._safe_update(self._status)
        try:
            self._bridge.flet_page.run_task(self._clear_status_after, token, 5.0)
        except Exception:
            pass

    async def _hide_cancelled_banner_after(self, token: int, seconds: float) -> None:
        await asyncio.sleep(seconds)
        if token != self._cancelled_banner_token:
            return
        self._cancelled_results_banner.visible = False
        DashboardPage._safe_update(self._cancelled_results_banner)

    def _cancelled_banner_timeout_settings(self) -> tuple[bool, float]:
        auto_hide = True
        timeout_seconds = 60.0
        try:
            settings = self._bridge.get_settings()
            general = settings.get("general", {}) if isinstance(settings, dict) else {}
            auto_hide = bool(general.get("partial_results_banner_auto_hide", True))
            raw_timeout = int(general.get("partial_results_banner_timeout_seconds", 60) or 60)
            timeout_seconds = 30.0 if raw_timeout == 30 else 60.0
        except Exception:
            pass
        return auto_hide, timeout_seconds

    def _show_cancelled_results_banner(self, message: str) -> None:
        self._cancelled_banner_token += 1
        token = self._cancelled_banner_token
        self._cancelled_results_text.value = str(message)
        self._cancelled_results_banner.visible = True
        DashboardPage._safe_update(self._cancelled_results_banner)
        auto_hide, timeout_seconds = self._cancelled_banner_timeout_settings()
        if not auto_hide:
            return
        try:
            self._bridge.flet_page.run_task(self._hide_cancelled_banner_after, token, timeout_seconds)
        except Exception:
            pass

    def _hide_cancelled_results_banner(self) -> None:
        self._cancelled_banner_token += 1
        self._cancelled_results_banner.visible = False
        DashboardPage._safe_update(self._cancelled_results_banner)

    @staticmethod
    def _shorten_path(path: str, max_len: int = 88) -> str:
        p = str(path)
        if len(p) <= max_len:
            return f"Current: {p}"
        head = max_len // 2 - 2
        tail = max_len - head - 3
        return f"Current: {p[:head]}...{p[-tail:]}"

    def on_show(self) -> None:
        import time

        # Home is a singleton page. If a scan already finished, returning to Home
        # from top navigation should always restore the normal dashboard shell.
        try:
            is_scanning = bool(self._bridge.backend.is_scanning)
        except Exception:
            is_scanning = False
        # ``is_scanning`` can briefly disagree with the HUD; if the chunk bar already latched
        # complete, treat the run as finished so Home does not resurrect a zombie scan surface.
        if self._scan_view.visible and (not is_scanning or self._bar_is_complete):
            self._pause_scan_btn.visible = False
            self._scan_view.visible = False
            for p in self._main_panels:
                p.visible = True
            self._view_results_btn.visible = False
            self._partial_results_row.visible = False
            self._cancel_btn.visible = False
            self._ring_timer.value = ""
            try:
                self._scan_elapsed_clock.value = ""
            except Exception:
                pass
            self._ring_path.value = ""
            # Returning to Home after completion/cancel should not keep stale
            # terminal status lines from the previous run.
            self._status.value = ""
            DashboardPage._safe_update(self)

        # F11: avoid repeated heavy refresh; first show does full async load,
        # later shows lightweight cache-backed refresh and throttled UI refreshes.
        self._schedule_dashboard_data_fetch()
        now = time.monotonic()
        should_refresh_lists = (not self._initial_load_done) or ((now - self._last_on_show_ts) > 1.5)
        if should_refresh_lists:
            self._last_on_show_ts = now
        self._initial_load_done = True
        # Do not call super().update() here unnecessarily if _fetch handled updates

    def apply_theme(self, mode: str) -> None:
        """Updates theme properties without destroying UI controls."""
        self._t = theme_for_mode(mode)
        
        # Update styles and colors on existing controls
        self._hero.bgcolor = self._t.colors.glass_bg
        self._hero.border = ft.border.all(1, self._t.colors.glass_border)
        
        # Re-apply styles to containers
        self._folder_container.bgcolor = self._t.colors.glass_bg
        self._folder_container.border = ft.border.all(1, self._t.colors.glass_border)

        # Refresh text colors and stats to match new theme
        self._mode_label.color = self._t.colors.fg_muted
        self._ring_label.color = self._t.colors.fg
        self._ring_phase_label.color = self._t.colors.fg_muted
        self._scan_mode_run_label.color = self._t.colors.fg2
        self._ring_timer.color = self._t.colors.fg_muted
        self._scan_elapsed_clock.color = self._t.colors.fg
        self._scan_elapsed_timer_icon.color = self._t.colors.accent
        self._ring_counter_tip.icon_color = self._t.colors.fg_muted
        self._phase_hash_caption.color = self._t.colors.fg_muted
        self._autosave_hint.color = self._t.colors.fg_muted
        self._update_stats_ui(refresh_presence_force=True)
        self._update_modes_ui()
        self._refresh_folder_chips() # Chips have background colors relative to theme
        self._apply_dashboard_pill_chrome()
        self._hero_tagline_icon.color = self._t.colors.accent
        self._folder_section_icon.color = self._t.colors.accent
        DashboardPage._safe_update(self._hero_tagline_icon)
        DashboardPage._safe_update(self._folder_section_icon)

        if self._is_mounted():
            self.update()