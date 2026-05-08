"""Dashboard page — home/landing page with quick-start scan controls, stats, and recent activity."""

from __future__ import annotations

import asyncio
from collections import deque
import json
import logging
import threading
import time
import re
from pathlib import Path
from typing import TYPE_CHECKING, Optional, Set

import flet as ft
import flet.canvas as cv

from cerebro.v2.ui.flet_app.theme import theme_for_mode, fmt_size, SCAN_MODES
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
        # Initial Theme Load
        self._t = theme_for_mode("dark")
        self._glass_cache: dict = {}

        # UI References (to update without rebuilding)
        self._hero: ft.Container
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
        self._stop_btn: ft.OutlinedButton
        self._progress: ft.ProgressBar
        self._progress_label: ft.Text
        self._progress_detail: ft.Text
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
        self._ring_path: ft.Text
        self._cancel_btn: ft.OutlinedButton
        self._view_results_btn: ft.FilledButton
        self._partial_results_row: ft.Row
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
        # Cancellation state: track whether we're in a cancel flow and cache
        # partial results so the user can choose to view them post-cancel.
        self._was_cancelled: bool = False
        self._pending_partial_results: list = []
        self._pending_partial_mode: str = "files"
        # Elapsed clock + ETA line (1 Hz); snapshot updated from progress callbacks.
        self._scan_timer_active: bool = False
        self._scan_elapsed_start: float = 0.0
        self._scan_hud_snap: dict = {}
        self._scan_hud_stop = threading.Event()
        self._scan_timer_thread: Optional[threading.Thread] = None
        self._last_path_paint_ts: float = 0.0
        self._speed_points: deque[tuple[float, int]] = deque(maxlen=60)
        self._status_token: int = 0
        self._cancelled_banner_token: int = 0
        self._io_failure_hits_by_root: dict[str, int] = {}
        self._io_pause_dialog_open: bool = False
        self._io_paused_root: str = ""
        # Largest file-catalogue count seen (discovery + grouping); explains hashing denominator.
        self._scan_files_catalogued: int = 0
        # Canvas chunk bar state
        self._bar_slices: int = 0
        self._bar_active_markers: Set[int] = set()
        self._bar_is_complete: bool = False
        self._bar_last_dupes: int = 0
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
            return "#22D3EE"
        if variant == "secondary":
            return "#4F46E5"
        return str(self._t.colors.primary)

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
            style=ft.ButtonStyle(color=t.colors.fg_muted),
        )
        self._hero = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.icons.Icons.AUTO_AWESOME, size=16, color="#22D3EE"),
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
            padding=ft.padding.symmetric(horizontal=t.spacing.lg, vertical=t.spacing.sm),
            width=860,
            **self._get_glass_style(opacity=0.04),
        )

        # Stat cards
        self._stats_row = ft.Row([], alignment=ft.MainAxisAlignment.CENTER, spacing=s.md)
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
        self._folder_container = ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Icon(ft.icons.Icons.FOLDER_OPEN, size=18, color="#22D3EE"),
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
            padding=s.md,
            **self._get_glass_style(0.10),
        )
        self._folder_container.on_click = self._browse_folders
        self._folder_container.on_hover = lambda e, c=self._folder_container: self._set_container_glow(
            c, e.data == "true", variant="primary"
        )
        self._folder_container.ink = True
        cast_col = self._folder_container.content

        # Action buttons — clear hierarchy: primary CTA, secondary, tertiary
        self._stop_btn = ft.OutlinedButton(
            "Stop Scan",
            icon=ft.icons.Icons.STOP,
            on_click=self._stop_scan,
            visible=False,
            style=ft.ButtonStyle(color=t.colors.danger),
        )
        self._start_btn = ft.FilledButton(
            "START SCAN",
            icon=ft.icons.Icons.ROCKET_LAUNCH,
            on_click=self._start_scan,
            style=ft.ButtonStyle(
                bgcolor="#28C7D8",
                color="#0A0E14",
                overlay_color=ft.Colors.with_opacity(0.2, "#28C7D8"),
                shape=ft.RoundedRectangleBorder(radius=14),
                text_style=ft.TextStyle(size=t.typography.size_xl, weight=ft.FontWeight.W_800),
                padding=ft.padding.symmetric(horizontal=56, vertical=28),
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
                self._stop_btn,
            ],
            horizontal_alignment=ft.CrossAxisAlignment.START,
            spacing=s.xs,
        )

        self._progress = ft.ProgressBar(width=400, bar_height=6, visible=False, color=t.colors.primary, bgcolor=t.colors.bg3)
        self._progress_label = ft.Text("", color=t.colors.fg2, size=t.typography.size_sm, visible=False)
        self._progress_detail = ft.Text("", color=t.colors.fg_muted, size=t.typography.size_xs, visible=False)

        # Circular scan progress view — swaps in over main content during active scan
        self._ring_default_color = "#00BFA5"
        self._ring = ft.ProgressRing(
            width=100, height=100,
            stroke_width=8,
            color=self._ring_default_color,
            value=None,  # indeterminate until first progress callback
        )
        self._ring_label = ft.Text(
            "Preparing scan…",
            size=t.typography.size_xl,
            weight=ft.FontWeight.BOLD,
            color=t.colors.fg,
            text_align=ft.TextAlign.CENTER,
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
        self._ring_timer = ft.Text(
            "",
            size=t.typography.size_sm,
            color=t.colors.fg_muted,
            text_align=ft.TextAlign.CENTER,
        )
        self._ring_path = ft.Text(
            "",
            size=t.typography.size_sm,
            color=t.colors.fg_muted,
            text_align=ft.TextAlign.CENTER,
            no_wrap=True,
            overflow=ft.TextOverflow.ELLIPSIS,
            width=480,
        )
        self._view_results_btn = ft.FilledButton(
            "View Results",
            icon=ft.icons.Icons.CHECK_CIRCLE,
            on_click=self._go_to_results,
            visible=False,
        )
        self._view_partial_btn = ft.OutlinedButton(
            "View Partial Results",
            icon=ft.icons.Icons.CHECKLIST,
            on_click=self._go_to_partial_results,
        )
        self._partial_results_row = ft.Row(
            [
                self._view_partial_btn,
                ft.TextButton(
                    "Back to Home",
                    icon=ft.icons.Icons.HOME,
                    on_click=self._go_to_home,
                ),
            ],
            alignment=ft.MainAxisAlignment.CENTER,
            visible=False,
        )
        self._cancel_btn = ft.OutlinedButton(
            "Cancel Scan",
            icon=ft.icons.Icons.STOP,
            on_click=self._stop_scan,
            style=ft.ButtonStyle(
                color=t.colors.danger,
                side=ft.BorderSide(1, t.colors.danger),
                shape=ft.RoundedRectangleBorder(radius=10),
                padding=ft.padding.symmetric(horizontal=24, vertical=12),
            ),
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
                    self._ring,
                    self._ring_phase_label,
                    self._scan_mode_run_label,
                    self._ring_counter_row,
                    self._hash_algo_label,
                    self._progress_label,
                    self._progress,
                    self._progress_detail,
                    self._ring_timer,
                    self._ring_path,
                    self._bar_row,
                    self._cancel_btn,
                    self._view_results_btn,
                    self._partial_results_row,
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                alignment=ft.MainAxisAlignment.CENTER,
                spacing=s.lg,
            ),
            expand=True,
            alignment=ft.Alignment(0, 0),
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
            padding=ft.padding.symmetric(horizontal=12, vertical=8),
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
            padding=ft.padding.symmetric(horizontal=s.md, vertical=s.sm),
        )
        self._scan_options_toggle_btn = ft.OutlinedButton(
            "Advanced scan settings",
            icon=ft.icons.Icons.KEYBOARD_ARROW_DOWN,
            on_click=self._toggle_scan_options_dropdown,
            style=ft.ButtonStyle(
                color=t.colors.fg2,
                shape=ft.RoundedRectangleBorder(radius=10),
            ),
        )
        self._scan_options_dropdown = ft.Container(
            content=ft.Container(
                content=self._scan_options_row,
                padding=ft.padding.all(s.xl),
                **self._get_glass_style(0.08),
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

        workflow_stack = ft.Container(
            width=840,
            padding=ft.padding.symmetric(horizontal=s.lg, vertical=s.md),
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
            **self._get_glass_style(0.035),
        )

        # Assemble — main panels tracked so scan view can swap in/out
        home_content = ft.Container(
            alignment=ft.Alignment(0, -1),
            padding=ft.padding.only(top=4),
            content=ft.Column(
                [
                    workflow_stack,
                    ft.Container(content=self._status, width=520, padding=ft.padding.only(top=s.sm)),
                    ft.Container(content=self._cancelled_results_banner, width=460, padding=ft.padding.only(top=s.sm)),
                    ft.Container(content=self._stats_row, width=360, padding=ft.padding.only(top=s.sm)),
                ],
                spacing=s.xs,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        )
        self.controls = [home_content]
        self._main_panels = list(self.controls)  # snapshot for hide/show swap
        self.controls.append(self._scan_view)     # scan view always last, starts hidden
        self._refresh_folder_chips()
        
        # Initial data fetch (async so first layout is not blocked)
        self._schedule_dashboard_data_fetch()

    # ------------------------------------------------------------------
    # Theme Helpers
    # ------------------------------------------------------------------
    def _get_glass_style(self, opacity: float = 0.08) -> dict:
        """Calculate glass style based on CURRENT theme."""
        is_dark = False
        if hasattr(self._bridge, 'app_theme'):
            is_dark = "dark" in self._bridge.app_theme.lower()
        cache_key = (opacity, is_dark)
        if cache_key in self._glass_cache:
            return self._glass_cache[cache_key]
        bg_base = ft.Colors.WHITE if is_dark else ft.Colors.BLACK
        border_base = ft.Colors.WHITE if is_dark else ft.Colors.BLACK
        bg = ft.Colors.with_opacity(opacity, bg_base)
        border_color = ft.Colors.with_opacity(0.15, border_base)
        result = dict(
            bgcolor=bg,
            border=ft.border.all(1, border_color),
            border_radius=ft.border_radius.all(16),
            shadow=ft.BoxShadow(
                blur_radius=20,
                color=ft.Colors.with_opacity(0.05, ft.Colors.BLACK),
                offset=ft.Offset(0, 4),
            ),
        )
        self._glass_cache[cache_key] = result
        return result

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
            padding=ft.padding.symmetric(horizontal=16, vertical=10),
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

    def _update_stats_ui(self):
        t = self._t
        scans_n = int(self._stats.get("scans", 0) or 0)
        dupes_n = int(self._stats.get("dupes", 0) or 0)
        bytes_n = int(self._stats.get("bytes_reclaimed", 0) or 0)
        self._stats_row.visible = (scans_n > 0) or (dupes_n > 0) or (bytes_n > 0)
        cards = [
            (ft.icons.Icons.SEARCH, "#22D3EE", "Scans Run", f"{scans_n:,}"),
            (ft.icons.Icons.CONTENT_COPY, "#A78BFA", "Duplicates Found", f"{dupes_n:,}"),
            (ft.icons.Icons.STORAGE, "#34D399", "Space Recovered", fmt_size(bytes_n)),
        ]
        controls: list[ft.Control] = []
        for icon, accent, label, value in cards:
            tile = ft.Container(
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
                                    weight=ft.FontWeight.W_500,
                                ),
                            ],
                            spacing=2,
                            tight=True,
                        )
                    ],
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=10,
                ),
                padding=ft.padding.symmetric(horizontal=14, vertical=10),
                **self._get_glass_style(0.06),
                ink=True,
            )
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
                    padding=ft.padding.symmetric(horizontal=12, vertical=14),
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
        self._start_btn.style = ft.ButtonStyle(
            bgcolor="#28C7D8",
            color="#0A0E14",
            overlay_color=ft.Colors.with_opacity(0.2, "#28C7D8"),
            shape=ft.RoundedRectangleBorder(radius=14),
            text_style=ft.TextStyle(size=self._t.typography.size_xl, weight=ft.FontWeight.W_800),
            padding=ft.padding.symmetric(horizontal=56, vertical=28),
        )
        DashboardPage._safe_update(self._start_btn)

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
        self._was_cancelled = False
        self._pending_partial_results = []
        scan_modes = self._selected_modes_for_scan()
        self._pending_partial_mode = "+".join(scan_modes)
        self._hide_cancelled_results_banner()
        self._io_failure_hits_by_root.clear()
        self._io_pause_dialog_open = False
        self._io_paused_root = ""
        self._scan_files_catalogued = 0
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
        self._hash_algo_label.value = ""
        self._hash_algo_label.visible = False
        self._ring_path.value = ""
        self._ring_label.value = "Preparing scan…"
        self._progress.value = 0.0
        self._progress.visible = True
        self._progress_label.visible = True
        self._progress_detail.visible = True
        self._progress_label.value = "0.0% complete"
        self._progress_detail.value = "Candidates: 0"
        self._cancel_btn.text = "Cancel Scan"
        self._cancel_btn.disabled = False
        self._cancel_btn.visible = True
        self._view_results_btn.visible = False
        self._partial_results_row.visible = False
        self._view_partial_btn.visible = True
        self._view_partial_btn.disabled = False
        for p in self._main_panels:
            p.visible = False
        self._scan_view.visible = True
        DashboardPage._safe_update(self)
        self._persist_incomplete_scan_session(status="in_progress")
        _log.info(
            "scan_start folders=%d modes=%s archives=%s",
            len(self._folders),
            scan_modes,
            bool(self._scan_options.get("scan_archives", False)),
        )

        self._bridge.begin_scan_session(self._folders, "+".join(scan_modes))
        self._start_scan_elapsed_timer()
        self._speed_points.clear()
        self._last_path_paint_ts = 0.0
        self._ring_timer.value = self._build_scan_timer_line()
        try:
            if self._ring_timer.page is not None:
                self._ring_timer.update()
        except Exception:
            pass

        try:
            backend = self._bridge.backend
            backend.set_on_progress(self._on_scan_progress)
            backend.set_on_complete(self._on_scan_complete)
            backend.set_on_error(self._on_scan_error)
            backend.start_scan(self._folders, mode=scan_modes, options=dict(self._scan_options))
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

    def _persist_incomplete_scan_session(self, *, status: str) -> None:
        payload = {
            "status": str(status),
            "timestamp": time.time(),
            "folders": [str(p) for p in self._folders],
            "mode": str(self._selected_mode or "files"),
            "modes": list(self._selected_modes_for_scan()),
            "options": dict(self._scan_options),
        }
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

    def prompt_resume_incomplete_scan_if_needed(self) -> None:
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
        ts = float(data.get("timestamp", time.time()) or time.time())
        stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))
        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Resume incomplete scan?"),
            content=ft.Text(f"An incomplete scan from {stamp} was found. Resume now?"),
            actions=[
                ft.TextButton("Discard", on_click=lambda _e: self._discard_incomplete_resume_prompt()),
                ft.FilledButton("Resume", on_click=lambda _e, d=data: self._resume_incomplete_scan(d)),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self._bridge.show_modal_dialog(dialog)

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
            self._bridge.show_snackbar("Saved scan folders are unavailable. Resume skipped.", info=True)
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

    def _on_scan_progress(self, data: dict) -> None:
        stage = data.get("stage", "")
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
            root = self._extract_unreachable_root(current_file)
            if root:
                self._handle_repeated_io_failure(root)
            return

        # Ignore a late "complete" tick from the scanner after the user cancelled —
        # otherwise the HUD briefly shows "Finishing up…" with no terminal event.
        if self._was_cancelled and stage == ScanStage.COMPLETE and state != "cancelled":
            return

        # Handle cancelled terminal event.
        if state == "cancelled" or stage == ScanStage.CANCELLED:
            self._was_cancelled = True
            self._stop_scan_elapsed_timer()
            self._ring.value = None
            self._ring.color = "#F59E0B"
            self._ring_label.value = "Scan cancelled"
            self._ring_phase_label.value = (
                "Processing stopped before full results were built. "
                "You can open partial results if any duplicates were found before the stop."
            )
            self._ring_counter.value = f"Stopped after processing {scanned:,} files in this phase."
            self._ring_timer.value = ""
            self._ring_path.value = ""
            self._ring_counter_tip.visible = False
            self._cancel_btn.visible = False
            self._cancel_btn.text = "Cancel Scan"
            self._cancel_btn.disabled = False
            # Return to Home automatically after cancellation terminal event.
            self._scan_view.visible = False
            for p in self._main_panels:
                p.visible = True
            self._partial_results_row.visible = False
            self._show_cancelled_status()
            self._do_page_update()
            return

        if stage in (ScanStage.DISCOVERING, ScanStage.GROUPING_BY_SIZE):
            self._scan_files_catalogued = max(
                self._scan_files_catalogued, int(scanned), int(total)
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

        is_hs = stage in (ScanStage.HASHING_PARTIAL, ScanStage.HASHING_FULL)
        rate_str = ""
        if is_hs:
            if rate is not None and float(rate) > 0:
                rate_str = f"{rate:,.0f} files/s"

        counter = counter_core
        if rate_str:
            counter += f"  ·  {rate_str}"

        self._ring_counter.value = counter

        now = time.monotonic()
        if (now - self._last_path_paint_ts) >= 0.10:
            self._last_path_paint_ts = now
            if current_file_path:
                self._ring_path.value = f"Scanning: {current_file_path}"
            elif current_file:
                self._ring_path.value = f"Scanning: {current_file}"
            else:
                self._ring_path.value = ""

        if total_files_in_scope > 0:
            progress_ratio = max(0.0, min(1.0, files_processed / total_files_in_scope))
            self._progress.value = progress_ratio
            self._progress_label.value = f"{progress_ratio * 100:.1f}% complete"
        else:
            self._progress.value = None
            self._progress_label.value = "Preparing scan…"
        self._progress_detail.value = f"Candidates: {candidates_found:,}"
        if active_hash_algorithm and stage in (ScanStage.HASHING_PARTIAL, ScanStage.HASHING_FULL):
            self._hash_algo_label.value = f"Hash algorithm: {active_hash_algorithm}"
            self._hash_algo_label.visible = True
        else:
            self._hash_algo_label.value = ""
            self._hash_algo_label.visible = False

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
                    page.run_thread(self._apply_tick_scan_hud)
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
            fp = int(snap.get("files_processed") or 0)
            self._speed_points.append((time.monotonic(), fp))
            self._ring_timer.value = self._build_scan_timer_line()
            DashboardPage._safe_update(self._ring_timer)
        except Exception:
            _log.debug("scan elapsed tick update failed", exc_info=True)

    def _build_scan_timer_line(self) -> str:
        if not self._scan_timer_active:
            return ""
        elapsed = time.monotonic() - self._scan_elapsed_start
        el = DashboardPage._fmt_elapsed_compact(elapsed)
        snap = self._scan_hud_snap or {}
        total = int(snap.get("total_files_in_scope") or snap.get("total") or 0)
        scanned = int(snap.get("files_processed") or snap.get("scanned") or 0)
        st = str(snap.get("stage") or "")

        parts = [f"Elapsed {el}"]
        if not st:
            parts.append("Preparing scan…")
            return "  ·  ".join(parts)

        is_hs = st in (ScanStage.HASHING_PARTIAL, ScanStage.HASHING_FULL)

        # Hide ETA / throughput outside hashing phases (avoids stale files/s during assembly).
        if not is_hs:
            if st == ScanStage.COMPLETE:
                parts.append("Assembling duplicate groups…")
            elif st == ScanStage.CANCELLED:
                parts.append("Stopping scan…")
            elif st == ScanStage.GROUPING_BY_SIZE:
                parts.append("Grouping same-size candidates…")
            elif st == ScanStage.DISCOVERING:
                parts.append("Listing file paths…")
            else:
                parts.append("Working…")
            return "  ·  ".join(parts)

        rolling_rate = self._rolling_speed_files_per_sec()
        if rolling_rate is not None and total > 0 and scanned < total:
            eta_s = (float(total) - float(scanned)) / float(rolling_rate)
            eta = self._fmt_eta(eta_s)
            if eta:
                parts.append(f"ETA ~{eta}")
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

    @staticmethod
    def _fmt_elapsed_compact(seconds: float) -> str:
        s = int(max(0.0, seconds))
        h, rem = divmod(s, 3600)
        m, sec = divmod(rem, 60)
        if h > 0:
            return f"{h}:{m:02d}:{sec:02d}"
        return f"{m}:{sec:02d}"

    def _on_scan_complete(self, results: list, mode: str) -> None:
        self._stop_scan_elapsed_timer()
        # If cancel was clicked, the backend still calls on_complete with partial
        # results (state=cancelled). Route those to the partial-results flow.
        if self._was_cancelled:
            self._pending_partial_results = list(results)
            self._pending_partial_mode = mode
            self._ring_timer.value = ""
            self._scan_mode_run_label.value = ""
            has_groups = len(results) > 0
            self._view_partial_btn.visible = has_groups
            if not has_groups:
                self._ring_phase_label.value = "No duplicate groups could be found before cancellation."
            if has_groups:
                self._show_cancelled_results_banner(
                    f"Cancelled scan found {len(results):,} duplicate group(s)."
                )
            self._scan_hud_snap = dict(self._scan_hud_snap)
            self._scan_hud_snap["rate"] = None
            self._scan_view.visible = False
            for p in self._main_panels:
                p.visible = True
            self._show_cancelled_status()
            DashboardPage._safe_update(self)
            return

        # Normal completion: show "View Results" button, then transition.
        self._clear_incomplete_scan_session()
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

    def _on_scan_error(self, msg: str) -> None:
        if "network path unreachable:" in str(msg or "").lower():
            root = self._extract_unreachable_root(str(msg))
            if root:
                self._handle_repeated_io_failure(root)
                return
        self._stop_scan_elapsed_timer()
        self._ring_timer.value = ""
        self._bar_row.visible = False
        self._persist_incomplete_scan_session(status="error")
        self._bridge.abort_scan_session()
        self._scan_view.visible = False
        for p in self._main_panels:
            p.visible = True
        self._status.value = f"Scan error: {msg}"
        DashboardPage._safe_update(self)
        self._bridge.play_sound("error")

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
        self._cancel_btn.text = "Cancelling…"
        self._cancel_btn.disabled = True
        self._was_cancelled = True
        self._ring_label.value = "Cancelling…"
        self._ring_phase_label.value = "Stopping the scan safely — this can take a moment on large files."
        DashboardPage._safe_update(self)
        try:
            self._bridge.flet_page.update()
        except Exception:
            pass
        try:
            self._bridge.backend.cancel_scan()
        except Exception as err:
            _log.error("Failed to stop scan: %s", err)

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

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Drive disconnected"),
            content=ft.Text(
                f"Repeated read failures were detected at:\n{key}\n\n"
                "The scan is paused. Choose Resume to keep trying, or Cancel to stop now and keep partial results."
            ),
            actions=[
                ft.TextButton("Resume Scan", on_click=self._resume_after_io_pause),
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
        try:
            self._bridge.backend.resume_scan()
        except Exception:
            _log.exception("Failed to resume scan after I/O pause")

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

    def _go_to_results(self, e: ft.ControlEvent) -> None:
        """Navigate to results after a successful scan completion."""
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
        self._stop_scan_elapsed_timer()
        self._ring_timer.value = ""
        self._bridge.abort_scan_session()
        self._scan_view.visible = False
        for p in self._main_panels:
            p.visible = True
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
        self._glass_cache = {}
        self._t = theme_for_mode(mode)
        
        # Update styles and colors on existing controls
        self._hero.bgcolor = self._get_glass_style(0.06).get('bgcolor')
        self._hero.border = self._get_glass_style(0.06).get('border')
        
        # Re-apply styles to containers
        self._folder_container.bgcolor = self._get_glass_style(0.04).get('bgcolor')
        self._folder_container.border = self._get_glass_style(0.04).get('border')

        # Refresh text colors and stats to match new theme
        self._mode_label.color = self._t.colors.fg_muted
        self._ring_label.color = self._t.colors.fg
        self._ring_phase_label.color = self._t.colors.fg_muted
        self._scan_mode_run_label.color = self._t.colors.fg2
        self._ring_timer.color = self._t.colors.fg_muted
        self._ring_counter_tip.icon_color = self._t.colors.fg_muted
        self._update_stats_ui()
        self._update_modes_ui()
        self._refresh_folder_chips() # Chips have background colors relative to theme

        if self._is_mounted():
            self.update()