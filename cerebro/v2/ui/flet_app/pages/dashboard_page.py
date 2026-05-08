"""Dashboard page — home/landing page with quick-start scan controls, stats, and recent activity."""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, List, Optional, Set, Tuple

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

_SCAN_MODE_ICON_MAP = {
    "description": ft.icons.Icons.DESCRIPTION,
    "image": ft.icons.Icons.IMAGE,
    "image_search": ft.icons.Icons.IMAGE_SEARCH,
    "videocam": ft.icons.Icons.VIDEOCAM,
    "music_note": ft.icons.Icons.MUSIC_NOTE,
}


def _popular_scan_folder_candidates() -> List[Tuple[str, Path]]:
    """Display labels and paths under the user profile commonly used for dedup scans."""
    home = Path.home()
    return [
        ("Desktop", home / "Desktop"),
        ("Documents", home / "Documents"),
        ("Downloads", home / "Downloads"),
        ("Pictures", home / "Pictures"),
        ("Videos", home / "Videos"),
        ("Music", home / "Music"),
        ("Desktop (OneDrive)", home / "OneDrive" / "Desktop"),
        ("Documents (OneDrive)", home / "OneDrive" / "Documents"),
        ("Downloads (OneDrive)", home / "OneDrive" / "Downloads"),
    ]


def _discover_existing_popular_paths() -> List[Tuple[str, Path]]:
    """Return candidate folders that exist and are directories, de-duplicated by resolved path."""
    seen: set[str] = set()
    out: List[Tuple[str, Path]] = []
    for label, p in _popular_scan_folder_candidates():
        try:
            r = p.resolve()
        except (OSError, RuntimeError):
            continue
        if not r.is_dir():
            continue
        key = str(r).lower()
        if key in seen:
            continue
        seen.add(key)
        out.append((label, r))
    return out


class DashboardPage(ft.Column):
    """Home page with scan configuration, stats, and quick-start."""

    def __init__(self, bridge: "StateBridge", folder_picker: ft.FilePicker):
        super().__init__(expand=True, scroll=ft.ScrollMode.AUTO)
        self._bridge = bridge
        self._folder_picker = folder_picker
        self._folders: list[Path] = []  # Enforce Path objects
        self._picker_active: bool = False  # guard against concurrent picker opens
        self._selected_mode = "files"
        self._scan_options: dict = {"scan_archives": False}
        self._stats = {"scans": 0, "dupes": 0, "bytes_reclaimed": 0}
        self._initial_load_done = False
        self._stats_fetch_generation = 0
        self._last_on_show_ts = 0.0
        self._session_hidden_quick_add: set[str] = set()
        self._session_recent_scan_paths: list[Path] = []
        self._quick_add_expanded: bool = False
        # Initial Theme Load
        self._t = theme_for_mode("dark")
        self._glass_cache: dict = {}

        # UI References (to update without rebuilding)
        self._hero: ft.Container
        self._stats_row: ft.Row
        self._mode_label: ft.Text
        self._mode_row: ft.Row
        self._folder_chips_row: ft.Row
        self._folder_container: ft.Container
        self._recent_paths_row: ft.Row
        self._recent_wrap: ft.Column
        self._quick_add_title: ft.Text
        self._quick_paths_row: ft.Row
        self._quick_add_wrap: ft.Column
        self._quick_add_body: ft.Container
        self._quick_toggle_btn: ft.TextButton
        self._quick_reset_btn: ft.TextButton
        self._clear_folders_btn: ft.TextButton
        self._actions: ft.Row
        self._browse_btn: ft.OutlinedButton
        self._last_session_btn: ft.TextButton
        self._start_btn: ft.FilledButton
        self._stop_btn: ft.OutlinedButton
        self._progress: ft.ProgressBar
        self._progress_label: ft.Text
        self._progress_detail: ft.Text
        self._status: ft.Text
        self._ring: ft.ProgressRing
        self._ring_phase_label: ft.Text
        self._ring_label: ft.Text
        self._ring_counter: ft.Text
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
        # Largest file-catalogue count seen (discovery + grouping); explains hashing denominator.
        self._scan_files_catalogued: int = 0
        # Canvas chunk bar state
        self._bar_slices: int = 0
        self._bar_active_markers: Set[int] = set()
        self._bar_is_complete: bool = False
        self._bar_last_dupes: int = 0
        self._build_ui()

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
        self._hero = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.icons.Icons.AUTO_AWESOME, size=20, color="#22D3EE"),
                    ft.Text(
                        "Welcome back. Ready to free up some space?",
                        size=t.typography.size_md,
                        color=t.colors.fg2,
                        expand=True,
                    ),
                ],
                spacing=s.md,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.padding.symmetric(horizontal=t.spacing.xl, vertical=t.spacing.md),
            **self._get_glass_style(opacity=0.04),
        )

        # Stat cards
        self._stats_row = ft.Row([], alignment=ft.MainAxisAlignment.CENTER, spacing=s.lg)
        self._update_stats_ui()

        # Scan mode selector
        self._mode_label = ft.Text(
            "Choose scan type",
            size=t.typography.size_sm,
            weight=ft.FontWeight.W_500,
            color=t.colors.fg_muted,
        )
        self._mode_row = ft.Row(
            [],
            wrap=True,
            spacing=s.md,
            run_spacing=s.md,
            alignment=ft.MainAxisAlignment.START,
            vertical_alignment=ft.CrossAxisAlignment.START,
        )
        self._update_modes_ui()

        # Folder list
        self._folder_chips_row = ft.Row([], wrap=True, spacing=s.xs)
        self._folder_container = ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Text("Selected folders", color=t.colors.fg_muted, size=t.typography.size_sm),
                            ft.Container(expand=True),
                        ],
                    ),
                    self._folder_chips_row,
                ],
                spacing=s.xs,
            ),
            padding=s.md,
            **self._get_glass_style(0.10),
        )
        self._folder_container.on_click = self._browse_folders
        self._folder_container.ink = True
        self._clear_folders_btn = ft.TextButton(
            "Clear selected",
            icon=ft.icons.Icons.CLEAR_ALL,
            on_click=self._clear_selected_folders,
            style=ft.ButtonStyle(color=t.colors.fg_muted),
            visible=False,
        )
        cast_col = self._folder_container.content
        if isinstance(cast_col, ft.Column) and cast_col.controls and isinstance(cast_col.controls[0], ft.Row):
            cast_col.controls[0].controls.append(self._clear_folders_btn)

        self._quick_paths_row = ft.Row([], wrap=True, spacing=s.sm, alignment=ft.MainAxisAlignment.START)
        self._recent_paths_row = ft.Row([], wrap=True, spacing=s.sm, alignment=ft.MainAxisAlignment.START)
        self._recent_paths_generation = 0
        self._recent_wrap = ft.Column(
            [
                ft.Text(
                    "Recent scan folders",
                    size=t.typography.size_sm,
                    weight=ft.FontWeight.W_500,
                    color=t.colors.fg_muted,
                ),
                self._recent_paths_row,
            ],
            spacing=s.xs,
            visible=False,
        )
        self._quick_add_title = ft.Text(
            "Quick add — smart suggestions (recent + frequent)",
            size=t.typography.size_sm,
            weight=ft.FontWeight.W_500,
            color=t.colors.fg_muted,
        )
        self._quick_reset_btn = ft.TextButton(
            "Reset hidden suggestions",
            on_click=self._reset_hidden_quick_suggestions,
            style=ft.ButtonStyle(color=t.colors.fg_muted),
            visible=False,
        )
        self._quick_toggle_btn = ft.TextButton(
            "Show suggestions",
            icon=ft.icons.Icons.EXPAND_MORE,
            on_click=self._toggle_quick_add,
            style=ft.ButtonStyle(color=t.colors.fg_muted),
        )
        self._quick_add_body = ft.Container(content=self._quick_paths_row, visible=False)
        self._quick_add_wrap = ft.Column(
            [
                ft.Row(
                    [self._quick_add_title, self._quick_toggle_btn, ft.Container(expand=True), self._quick_reset_btn],
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                self._quick_add_body,
            ],
            spacing=s.xs,
        )
        self._quick_scan_btn = ft.FilledTonalButton(
            "Quick Scan: Desktop + Downloads",
            icon=ft.icons.Icons.BOLT,
            on_click=self._quick_scan_common_folders,
            style=ft.ButtonStyle(
                shape=ft.RoundedRectangleBorder(radius=10),
                color=t.colors.fg,
            ),
            visible=False,
        )
        self._load_quick_add_ui_preferences()
        self._refresh_recent_paths_bar()
        self._refresh_quick_add_bar()

        # Action buttons — clear hierarchy: primary CTA, secondary, tertiary
        self._stop_btn = ft.OutlinedButton(
            "Stop Scan",
            icon=ft.icons.Icons.STOP,
            on_click=self._stop_scan,
            visible=False,
            style=ft.ButtonStyle(color=t.colors.danger),
        )
        self._start_btn = ft.FilledButton(
            "Start Scan",
            icon=ft.icons.Icons.PLAY_ARROW,
            on_click=self._start_scan,
            style=ft.ButtonStyle(
                bgcolor="#22D3EE",
                color="#0A0E14",
                overlay_color=ft.Colors.with_opacity(0.2, "#22D3EE"),
                shape=ft.RoundedRectangleBorder(radius=10),
                padding=ft.padding.symmetric(horizontal=24, vertical=12),
            ),
            disabled=True,
        )
        self._browse_btn = ft.OutlinedButton(
            "Browse Folders",
            icon=ft.icons.Icons.FOLDER_OPEN,
            on_click=self._browse_folders,
            style=ft.ButtonStyle(
                color=t.colors.fg2,
                side=ft.BorderSide(1, t.colors.border),
                shape=ft.RoundedRectangleBorder(radius=10),
                padding=ft.padding.symmetric(horizontal=16, vertical=12),
            ),
        )
        self._last_session_btn = ft.TextButton(
            "Open Last Session",
            icon=ft.icons.Icons.HISTORY,
            on_click=self._open_last_session,
            style=ft.ButtonStyle(color=t.colors.fg_muted),
        )
        browse_wrap = ft.Container(content=self._browse_btn, border_radius=10)
        start_wrap = ft.Container(content=self._start_btn, border_radius=10)
        last_wrap = ft.Container(content=self._last_session_btn, border_radius=10)
        browse_wrap.on_hover = lambda e, c=browse_wrap: self._set_container_glow(c, e.data == "true", variant="secondary")
        start_wrap.on_hover = lambda e, c=start_wrap: self._set_container_glow(c, e.data == "true", variant="primary", strong=True)
        last_wrap.on_hover = lambda e, c=last_wrap: self._set_container_glow(c, e.data == "true", variant="secondary")
        secondary_actions = ft.Row(
            [browse_wrap, last_wrap],
            alignment=ft.MainAxisAlignment.CENTER,
            spacing=s.md,
            wrap=True,
        )
        self._actions = ft.Column(
            [
                start_wrap,
                secondary_actions,
                self._stop_btn,
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=s.sm,
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
                    self._ring_counter_row,
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
        self._scan_options_row = ft.Container(
            content=ft.Column(
                [
                    ft.Text("Scan options", size=t.typography.size_sm, weight=ft.FontWeight.W_500, color=t.colors.fg_muted),
                    self._scan_archives_cb,
                    self._archives_warning,
                ],
                spacing=4,
                tight=True,
            ),
            padding=ft.padding.symmetric(horizontal=s.md, vertical=s.sm),
        )

        # Assemble — main panels tracked so scan view can swap in/out
        self.controls = [
            self._hero,
            ft.Container(content=self._stats_row, padding=ft.padding.symmetric(vertical=s.lg)),
            ft.Container(content=self._mode_label, padding=ft.padding.only(left=s.md, top=s.sm)),
            ft.Container(
                content=self._mode_row,
                padding=ft.padding.symmetric(horizontal=s.md, vertical=s.sm),
                **self._get_glass_style(0.08),
            ),
            self._folder_container,
            ft.Container(
                content=ft.Column([self._quick_scan_btn, self._recent_wrap, self._quick_add_wrap], spacing=s.sm),
                padding=ft.padding.only(left=s.md, right=s.md, bottom=s.sm),
            ),
            self._scan_options_row,
            ft.Container(content=self._actions, padding=ft.padding.only(top=s.md, bottom=s.md)),
            ft.Container(content=self._status, padding=ft.padding.only(top=s.md)),
        ]
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
        cards = [
            (ft.icons.Icons.SEARCH, "#22D3EE", "Scans Run", f"{self._stats.get('scans', 0):,}"),
            (ft.icons.Icons.CONTENT_COPY, "#A78BFA", "Duplicates Found", f"{self._stats.get('dupes', 0):,}"),
            (ft.icons.Icons.STORAGE, "#34D399", "Space Recovered", fmt_size(self._stats.get('bytes_reclaimed', 0))),
        ]
        controls: list[ft.Control] = []
        for icon, accent, label, value in cards:
            tile = ft.Container(
                content=ft.Row(
                    [
                        ft.Container(
                            content=ft.Icon(icon, size=20, color=accent),
                            bgcolor=ft.Colors.with_opacity(0.18, accent),
                            border=ft.border.all(1, ft.Colors.with_opacity(0.35, accent)),
                            border_radius=8,
                            padding=8,
                        ),
                        ft.Column(
                            [
                                ft.Text(
                                    value,
                                    size=t.typography.size_lg,
                                    weight=ft.FontWeight.W_700,
                                    color=accent,
                                ),
                                ft.Text(
                                    label,
                                    size=t.typography.size_sm,
                                    color=t.colors.fg2,
                                    weight=ft.FontWeight.W_600,
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
        s = t.spacing
        TEAL = "#00BFA5"

        cards = []
        for m in SCAN_MODES:
            is_active = m["key"] == self._selected_mode
            raw_icon = str(m.get("icon", "") or "").lower()
            icon_name = _SCAN_MODE_ICON_MAP.get(raw_icon, ft.icons.Icons.CATEGORY)

            icon_bg = ft.Colors.with_opacity(0.20 if is_active else 0.08, TEAL if is_active else ft.Colors.WHITE)
            icon_color = TEAL if is_active else t.colors.fg_muted
            label_color = "#F8FEFF" if is_active else t.colors.fg2
            border_color = "#22D3EE" if is_active else ft.Colors.with_opacity(0.12, ft.Colors.WHITE)
            bg_color = ft.Colors.with_opacity(0.24 if is_active else 0.04, TEAL if is_active else ft.Colors.WHITE)

            card_content = ft.Column(
                [
                    ft.Row(
                        [
                            ft.Container(
                                content=ft.Icon(icon_name, size=20, color=icon_color),
                                bgcolor=icon_bg,
                                border_radius=8,
                                padding=8,
                            ),
                            ft.Container(expand=True),
                            ft.Icon(
                                ft.icons.Icons.RADIO_BUTTON_CHECKED if is_active
                                else ft.icons.Icons.RADIO_BUTTON_UNCHECKED,
                                size=14,
                                color=TEAL if is_active else ft.Colors.with_opacity(0.25, ft.Colors.WHITE),
                            ),
                            ft.Container(
                                content=ft.Text(
                                    "SELECTED",
                                    size=8,
                                    weight=ft.FontWeight.W_700,
                                    color="#081018",
                                ),
                                bgcolor="#22D3EE",
                                border_radius=999,
                                padding=ft.padding.symmetric(horizontal=7, vertical=2),
                                visible=is_active,
                            ),
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.START,
                    ),
                    ft.Text(
                        m["label"],
                        size=t.typography.size_lg,
                        weight=ft.FontWeight.W_700,
                        color=label_color,
                    ),
                    ft.Text(
                        m.get("desc", ""),
                        size=t.typography.size_sm,
                        color=t.colors.fg_muted,
                    ),
                ],
                spacing=s.sm,
                tight=True,
            )

            card_kwargs: dict = dict(
                content=card_content,
                width=160,
                height=142,
                padding=ft.padding.all(s.md),
                border=ft.border.all(3 if is_active else 1, border_color),
                border_radius=12,
                bgcolor=bg_color,
                alignment=ft.Alignment(-1, -1),
                ink=True,
                on_click=lambda e, k=m["key"]: self._select_mode(k),
            )
            if is_active:
                card_kwargs["shadow"] = ft.BoxShadow(
                    blur_radius=28,
                    spread_radius=0,
                    color=ft.Colors.with_opacity(0.48, TEAL),
                    offset=ft.Offset(0, 4),
                )
            card = ft.Container(**card_kwargs)
            card.on_hover = lambda e, c=card, active=is_active: self._on_mode_card_hover(c, e.data == "true", active)
            cards.append(card)

        self._mode_row.controls = cards
        DashboardPage._safe_update(self._mode_row)

    def _on_mode_card_hover(self, card: ft.Container, hovering: bool, is_active: bool) -> None:
        if hovering:
            card.shadow = self._hover_shadow(self._hover_glow_color("primary"), strong=True)
        else:
            if is_active:
                card.shadow = ft.BoxShadow(
                    blur_radius=28,
                    spread_radius=0,
                    color=ft.Colors.with_opacity(0.48, "#00BFA5"),
                    offset=ft.Offset(0, 4),
                )
            else:
                card.shadow = None
        DashboardPage._safe_update(card)

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

    def _select_mode(self, key: str) -> None:
        if self._selected_mode == key:
            return
        self._selected_mode = key
        self._update_modes_ui()

    def _refresh_quick_add_bar(self) -> None:
        """Populate one-tap smart suggestions based on scan history + recency."""
        t = self._t
        paths = self._discover_smart_quick_paths(limit=8)
        self._quick_add_title.color = t.colors.fg_muted
        hidden_count = len(self._get_hidden_quick_suggestions() | set(self._session_hidden_quick_add))
        self._quick_reset_btn.visible = hidden_count > 0
        if not paths:
            self._quick_add_wrap.visible = False
            if self._is_mounted():
                self._quick_add_wrap.update()
            return
        self._quick_add_wrap.visible = True
        self._quick_add_body.visible = self._quick_add_expanded
        self._quick_toggle_btn.text = "Hide suggestions" if self._quick_add_expanded else "Show suggestions"
        self._quick_toggle_btn.icon = ft.icons.Icons.EXPAND_LESS if self._quick_add_expanded else ft.icons.Icons.EXPAND_MORE
        self._quick_paths_row.controls = []
        for label, p in paths:
            remove_btn = ft.TextButton(
                "X",
                tooltip="Remove suggestion",
                on_click=lambda _e, pp=p: self._dismiss_quick_suggestion(pp),
                style=ft.ButtonStyle(
                    color=t.colors.fg_muted,
                    text_style=ft.TextStyle(size=t.typography.size_xs, weight=ft.FontWeight.W_700),
                    padding=ft.padding.symmetric(horizontal=6, vertical=4),
                    shape=ft.RoundedRectangleBorder(radius=6),
                ),
            )
            quick_item = ft.Container(
                content=ft.Row(
                    [
                        ft.TextButton(
                            label,
                            icon=ft.icons.Icons.FOLDER_SPECIAL,
                            on_click=lambda _e, pp=p: self._add_folder(pp),
                            style=ft.ButtonStyle(
                                color=t.colors.fg2,
                                padding=ft.padding.symmetric(horizontal=8, vertical=6),
                                shape=ft.RoundedRectangleBorder(radius=8),
                            ),
                        ),
                        remove_btn,
                    ],
                    spacing=2,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                bgcolor=ft.Colors.with_opacity(0.10, t.colors.primary),
                border=ft.border.all(1, ft.Colors.with_opacity(0.16, t.colors.primary)),
                border_radius=10,
                padding=ft.padding.only(left=2, right=2),
            )
            quick_item.on_hover = lambda e, c=quick_item: self._set_container_glow(c, e.data == "true", variant="secondary")
            self._quick_paths_row.controls.append(quick_item)
        if self._is_mounted():
            self._quick_paths_row.update()
            self._quick_add_body.update()
            self._quick_toggle_btn.update()
            self._quick_reset_btn.update()
            self._quick_add_wrap.update()

    def _refresh_recent_paths_bar(self) -> None:
        self._recent_paths_generation += 1
        gen = self._recent_paths_generation
        page = self._bridge.flet_page
        if hasattr(page, "run_task"):
            page.run_task(self._refresh_recent_paths_bar_async, gen)
            return
        recents = self._discover_recent_scan_paths(limit=6)
        self._apply_recent_paths(recents)

    async def _refresh_recent_paths_bar_async(self, gen: int) -> None:
        import asyncio

        loop = asyncio.get_event_loop()
        recents = await loop.run_in_executor(None, lambda: self._discover_recent_scan_paths(limit=6))
        if gen != self._recent_paths_generation:
            return
        self._apply_recent_paths(recents)

    def _apply_recent_paths(self, recents: list[tuple[str, Path]]) -> None:
        t = self._t
        if not recents:
            self._recent_wrap.visible = False
            self._quick_scan_btn.visible = False
            if self._is_mounted():
                self._recent_wrap.update()
                self._quick_scan_btn.update()
            return
        self._quick_scan_btn.visible = True
        self._recent_wrap.visible = True
        self._recent_paths_row.controls = []
        for label, p in recents:
            recent_chip = ft.Chip(
                label=ft.Text(label, size=t.typography.size_sm),
                leading=ft.Icon(ft.icons.Icons.HISTORY, size=14, color=t.colors.fg2),
                shape=ft.RoundedRectangleBorder(radius=10),
                on_click=lambda _e, pp=p: self._add_folder(pp),
            )
            recent_chip.bgcolor = ft.Colors.with_opacity(0.03, t.colors.primary)
            recent_chip.side = ft.BorderSide(1, ft.Colors.with_opacity(0.30, t.colors.primary))
            recent_chip.tooltip = str(p)
            self._recent_paths_row.controls.append(recent_chip)
        if self._is_mounted():
            self._recent_paths_row.update()
            self._recent_wrap.update()
            self._quick_scan_btn.update()

    def _discover_recent_scan_paths(self, limit: int = 6) -> list[tuple[str, Path]]:
        try:
            from cerebro.v2.core.scan_history_db import get_scan_history_db

            seen: set[str] = set()
            out: list[tuple[str, Path]] = []

            for p in self._session_recent_scan_paths:
                try:
                    rp = Path(str(p)).resolve()
                except (OSError, RuntimeError, ValueError):
                    continue
                if not rp.is_dir():
                    continue
                key = str(rp).lower()
                if key in seen:
                    continue
                seen.add(key)
                out.append((rp.name or str(rp), rp))
                if len(out) >= max(1, limit):
                    return out

            for entry in get_scan_history_db().get_recent(250):
                for raw in (entry.folders or []):
                    try:
                        p = Path(str(raw)).resolve()
                    except (OSError, RuntimeError, ValueError):
                        continue
                    if not p.is_dir():
                        continue
                    key = str(p).lower()
                    if key in seen:
                        continue
                    seen.add(key)
                    out.append((p.name or str(p), p))
                    if len(out) >= max(1, limit):
                        return out
            return out
        except Exception:
            _log.exception("Failed loading recent scan paths")
            return []

    def _load_quick_add_ui_preferences(self) -> None:
        settings = self._bridge.get_settings()
        if not isinstance(settings, dict):
            self._quick_add_expanded = False
            return
        dashboard = settings.get("dashboard")
        if not isinstance(dashboard, dict):
            self._quick_add_expanded = False
            return
        self._quick_add_expanded = bool(dashboard.get("quick_add_expanded", False))

    def _persist_quick_add_ui_preferences(self) -> None:
        settings = self._bridge.get_settings()
        if not isinstance(settings, dict):
            settings = {}
        dashboard = settings.get("dashboard")
        if not isinstance(dashboard, dict):
            dashboard = {}
        dashboard["quick_add_expanded"] = bool(self._quick_add_expanded)
        settings["dashboard"] = dashboard
        self._bridge.save_settings(settings)

    def _toggle_quick_add(self, _e: ft.ControlEvent | None = None) -> None:
        self._quick_add_expanded = not self._quick_add_expanded
        self._persist_quick_add_ui_preferences()
        self._refresh_quick_add_bar()

    def _discover_smart_quick_paths(self, limit: int = 8) -> list[tuple[str, Path]]:
        hidden = self._get_hidden_quick_suggestions() | set(self._session_hidden_quick_add)
        try:
            from cerebro.v2.core.scan_history_db import get_scan_history_db
            import time

            now = time.time()
            scores: dict[str, float] = {}
            pretty: dict[str, Path] = {}

            # Prioritize folders scanned in this session so suggestions feel live.
            for rank, p in enumerate(self._session_recent_scan_paths):
                try:
                    rp = Path(str(p)).resolve()
                except (OSError, RuntimeError, ValueError):
                    continue
                if not rp.is_dir():
                    continue
                key = str(rp).lower()
                if key in hidden:
                    continue
                scores[key] = scores.get(key, 0.0) + 20.0 - float(rank)
                pretty[key] = rp

            entries = get_scan_history_db().get_recent(300)
            for i, entry in enumerate(entries):
                # Recency + frequency weighted score.
                age_days = max(0.0, (now - float(entry.timestamp or now)) / 86400.0)
                recency_boost = 1.0 / (1.0 + age_days)
                order_boost = 1.0 / (1.0 + i)
                for raw in (entry.folders or []):
                    try:
                        p = Path(str(raw)).resolve()
                    except (OSError, RuntimeError, ValueError):
                        continue
                    if not p.is_dir():
                        continue
                    key = str(p).lower()
                    if key in hidden:
                        continue
                    scores[key] = scores.get(key, 0.0) + 1.0 + (2.0 * recency_boost) + order_boost
                    pretty[key] = p
            ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[: max(1, limit)]
            out: list[tuple[str, Path]] = []
            for key, _score in ranked:
                p = pretty[key]
                label = p.name or str(p)
                out.append((label, p))
            if out:
                return out
        except Exception:
            _log.exception("Failed building smart quick-add suggestions")
        # Fallback for brand-new users, still honoring hidden dismissals.
        fallback: list[tuple[str, Path]] = []
        for label, p in _discover_existing_popular_paths():
            try:
                key = str(p.resolve()).lower()
            except (OSError, RuntimeError, ValueError):
                key = str(p).lower()
            if key in hidden:
                continue
            fallback.append((label, p))
            if len(fallback) >= max(1, limit):
                break
        return fallback

    def _get_hidden_quick_suggestions(self) -> set[str]:
        settings = self._bridge.get_settings()
        if not isinstance(settings, dict):
            return set()
        dashboard = settings.get("dashboard")
        if not isinstance(dashboard, dict):
            return set()
        hidden = dashboard.get("quick_add_hidden")
        if not isinstance(hidden, list):
            return set()
        return {str(x).lower() for x in hidden}

    def _dismiss_quick_suggestion(self, path: Path) -> None:
        try:
            key = str(Path(str(path)).resolve()).lower()
        except (OSError, RuntimeError, ValueError):
            key = str(path).lower()
        self._session_hidden_quick_add.add(key)
        settings = self._bridge.get_settings()
        if not isinstance(settings, dict):
            settings = {}
        dashboard = settings.get("dashboard")
        if not isinstance(dashboard, dict):
            dashboard = {}
        hidden = dashboard.get("quick_add_hidden")
        if not isinstance(hidden, list):
            hidden = []
        if key not in [str(x).lower() for x in hidden]:
            hidden.append(str(path))
        dashboard["quick_add_hidden"] = hidden
        settings["dashboard"] = dashboard
        self._bridge.save_settings(settings)
        self._refresh_quick_add_bar()
        self._bridge.show_snackbar("Suggestion removed.", info=True)

    def _reset_hidden_quick_suggestions(self, _e: ft.ControlEvent | None = None) -> None:
        settings = self._bridge.get_settings()
        if not isinstance(settings, dict):
            settings = {}
        dashboard = settings.get("dashboard")
        if not isinstance(dashboard, dict):
            dashboard = {}
        dashboard["quick_add_hidden"] = []
        settings["dashboard"] = dashboard
        self._session_hidden_quick_add.clear()
        self._bridge.save_settings(settings)
        self._refresh_quick_add_bar()

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
            self._folder_container.height = 130
            self._folder_chips_row.controls = [
                ft.Container(
                    border=ft.border.all(1, ft.Colors.with_opacity(0.35, t.colors.border)),
                    border_radius=10,
                    padding=ft.padding.symmetric(horizontal=12, vertical=14),
                    bgcolor=ft.Colors.with_opacity(0.04, t.colors.primary),
                    content=ft.Column(
                        [
                            ft.Row(
                                [
                                    ft.Icon(ft.icons.Icons.UPLOAD_FILE, size=16, color=t.colors.fg_muted),
                                    ft.Text(
                                        "Drag and drop folders here, or click to browse",
                                        color=t.colors.fg2,
                                        size=t.typography.size_base,
                                        weight=ft.FontWeight.W_500,
                                    ),
                                ],
                                spacing=8,
                            ),
                            ft.Text(
                                "No folders selected yet",
                                color=t.colors.fg_muted,
                                size=t.typography.size_sm,
                                italic=True,
                            ),
                        ],
                        spacing=6,
                    ),
                )
            ]
        else:
            self._folder_container.height = None
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
        self._clear_folders_btn.visible = bool(self._folders)
        self._sync_start_button_state()
        if self._is_mounted():
            self._folder_chips_row.update()
            self._clear_folders_btn.update()

    def _remove_folder(self, path: Path) -> None:
        if path in self._folders:
            self._folders.remove(path)
        self._refresh_folder_chips()

    def _clear_selected_folders(self, _e: ft.ControlEvent | None = None) -> None:
        self._folders.clear()
        self._refresh_folder_chips()

    def _sync_start_button_state(self) -> None:
        has_folders = bool(self._folders)
        self._start_btn.disabled = not has_folders
        if has_folders:
            self._start_btn.style = ft.ButtonStyle(
                bgcolor="#22D3EE",
                color="#0A0E14",
                overlay_color=ft.Colors.with_opacity(0.2, "#22D3EE"),
                shape=ft.RoundedRectangleBorder(radius=10),
                padding=ft.padding.symmetric(horizontal=24, vertical=12),
            )
        else:
            self._start_btn.style = ft.ButtonStyle(
                bgcolor=ft.Colors.with_opacity(0.16, "#94A3B8"),
                color="#64748B",
                shape=ft.RoundedRectangleBorder(radius=10),
                padding=ft.padding.symmetric(horizontal=24, vertical=12),
            )
        DashboardPage._safe_update(self._start_btn)

    def _quick_scan_common_folders(self, _e: ft.ControlEvent | None = None) -> None:
        candidates = _discover_existing_popular_paths()
        preferred_labels = {"desktop", "downloads", "desktop (onedrive)", "downloads (onedrive)"}
        picked: list[Path] = []
        for label, p in candidates:
            if label.lower() in preferred_labels:
                picked.append(p)
        if not picked:
            self._bridge.show_snackbar("Quick folders not found on this machine. Use Browse Folders.", info=True)
            return
        for p in picked:
            if p not in self._folders:
                self._folders.append(p)
        self._refresh_folder_chips()
        self._bridge.show_snackbar("Quick folders added. You can start scanning now.", info=True)

    def _start_scan(self, e: ft.ControlEvent) -> None:
        if not self._folders:
            self._status.value = "Please select at least one folder first."
            self._status.update()
            return
        
        self._was_cancelled = False
        self._pending_partial_results = []
        self._pending_partial_mode = self._selected_mode
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
        self._ring_counter.value = "Files found so far: 0"
        self._ring_counter_tip.visible = False
        self._ring_timer.value = ""
        self._ring_path.value = ""
        self._ring_label.value = "Preparing scan…"
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

        self._bridge.begin_scan_session(self._folders, self._selected_mode)
        self._start_scan_elapsed_timer()
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
            backend.start_scan(self._folders, mode=self._selected_mode, options=dict(self._scan_options))
        except Exception as err:
            self._on_scan_error(f"Backend communication error: {err}")

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
                "Only matching-size copies are hashed as candidates.",
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
        rate = data.get("rate")  # None until backend has enough samples

        _log.debug("UI progress recv: stage=%s scanned=%d total=%d", stage, scanned, total)

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
            self._partial_results_row.visible = True
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

        if current_file and stage in (ScanStage.HASHING_PARTIAL, ScanStage.HASHING_FULL):
            p = self._shorten_path(current_file)
            body = p.replace("Current: ", "", 1) if p.startswith("Current: ") else p
            self._ring_path.value = f"Now: {body}"
        elif current_file:
            self._ring_path.value = self._shorten_path(current_file)
        else:
            self._ring_path.value = ""

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
        rate = snap.get("rate")
        total = int(snap.get("total") or 0)
        scanned = int(snap.get("scanned") or 0)
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

        if rate is not None and float(rate) > 0 and total > 0 and scanned < total:
            eta_s = (float(total) - float(scanned)) / float(rate)
            qual = " (estimating)" if elapsed < 5.0 else ""
            parts.append(f"ETA ~{self._fmt_eta(eta_s)}{qual}")
        elif rate is not None and float(rate) > 0 and total > 0:
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
            if "Retrieving cached signatures" in cf and rate is not None and float(rate) > 0:
                eta_s = (float(total) - float(scanned)) / float(rate)
                parts.append(f"Retrieving cache — ETA ~{self._fmt_eta(eta_s)} (estimating)")
            elif elapsed >= 3.0 and scanned >= 200:
                eta_s = (elapsed / float(scanned)) * (float(total) - float(scanned))
                parts.append(f"ETA ~{self._fmt_eta(eta_s)} (estimating)")
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
            has_groups = len(results) > 0
            self._view_partial_btn.visible = has_groups
            if not has_groups:
                self._ring_phase_label.value = "No duplicate groups could be found before cancellation."
            self._scan_hud_snap = dict(self._scan_hud_snap)
            self._scan_hud_snap["rate"] = None
            DashboardPage._safe_update(self)
            return

        # Normal completion: show "View Results" button, then transition.
        self._ring.value = 1.0
        self._ring.color = self._heat_color_for_ratio(1.0)
        ng = len(results)
        self._ring_phase_label.value = (
            "Assembling duplicate groups from hash results." if ng else "Finished — nothing to compare."
        )
        self._ring_label.value = f"Scan complete — {ng:,} duplicate group(s) found." if ng > 0 else "Scan complete — no duplicates found."
        self._ring_counter.value = ""
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

        # Refresh quick suggestions immediately with latest scanned folders.
        seen_recent: set[str] = set()
        recents: list[Path] = []
        for p in self._folders:
            key = str(p).lower()
            if key in seen_recent:
                continue
            seen_recent.add(key)
            recents.append(p)
        self._session_recent_scan_paths = recents
        self._refresh_recent_paths_bar()
        self._refresh_quick_add_bar()

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
        self._stop_scan_elapsed_timer()
        self._ring_timer.value = ""
        self._bar_row.visible = False
        self._bridge.abort_scan_session()
        self._scan_view.visible = False
        for p in self._main_panels:
            p.visible = True
        self._status.value = f"Scan error: {msg}"
        DashboardPage._safe_update(self)
        self._bridge.play_sound("error")

    def _stop_scan(self, e: ft.ControlEvent) -> None:
        # Immediately show "Cancelling..." and disable the button; keep the
        # scan view visible so the user sees progress until the terminal event.
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

    def _go_to_results(self, e: ft.ControlEvent) -> None:
        """Navigate to results after a successful scan completion."""
        self._scan_view.visible = False
        for p in self._main_panels:
            p.visible = True
        self._status.value = "Scan complete."
        DashboardPage._safe_update(self)
        try:
            self._bridge.navigate("duplicates")
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
        self._status.value = f"Scan cancelled — {len(results):,} partial groups available."
        DashboardPage._safe_update(self)
        try:
            self._bridge.dispatch_scan_complete(results, mode)
            self._bridge.navigate("duplicates")
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
        self._status.value = "Scan cancelled."
        DashboardPage._safe_update(self)

    @staticmethod
    def _fmt_eta(seconds: float) -> str:
        s = max(0, int(seconds))
        m, s = divmod(s, 60)
        h, m = divmod(m, 60)
        if h > 0:
            return f"{h}h {m}m"
        if m > 0:
            return f"{m}m {s}s"
        return f"{s}s"

    @staticmethod
    def _format_folder_chip_label(path: Path) -> str:
        parts = list(path.parts)
        if len(parts) >= 3:
            return f"{parts[0]}\\...\\{parts[-1]}"
        return str(path)

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
            self._refresh_recent_paths_bar()
            self._refresh_quick_add_bar()
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
        self._ring_timer.color = self._t.colors.fg_muted
        self._ring_counter_tip.icon_color = self._t.colors.fg_muted
        self._update_stats_ui()
        self._update_modes_ui()
        self._refresh_folder_chips() # Chips have background colors relative to theme
        self._refresh_quick_add_bar()

        if self._is_mounted():
            self.update()