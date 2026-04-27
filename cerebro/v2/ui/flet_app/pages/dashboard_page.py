"""Dashboard page — home/landing page with quick-start scan controls, stats, and recent activity."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, List, Tuple

import flet as ft

from cerebro.v2.ui.flet_app.theme import theme_for_mode, fmt_size, SCAN_MODES

if TYPE_CHECKING:
    from cerebro.v2.ui.flet_app.services.state_bridge import StateBridge

_log = logging.getLogger(__name__)

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
        self._selected_mode = "files"
        self._stats = {"scans": 0, "dupes": 0, "bytes_reclaimed": 0}
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
        self._ring_label: ft.Text
        self._ring_counter: ft.Text
        self._ring_path: ft.Text
        self._cancel_btn: ft.OutlinedButton
        self._scan_view: ft.Container
        self._main_panels: list
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
                        "Welcome back — find and reclaim wasted disk space.",
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
        self._folder_chips_row = ft.Row(
            [ft.Text("No folders selected", color=t.colors.fg_muted, size=t.typography.size_base)],
            wrap=True,
            spacing=s.xs,
        )
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
            **self._get_glass_style(0.04),
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
        self._actions = ft.Row(
            [
                browse_wrap,
                start_wrap,
                last_wrap,
                self._stop_btn,
            ],
            alignment=ft.MainAxisAlignment.CENTER,
            spacing=s.lg,
        )

        self._progress = ft.ProgressBar(width=400, bar_height=6, visible=False, color=t.colors.primary, bgcolor=t.colors.bg3)
        self._progress_label = ft.Text("", color=t.colors.fg2, size=t.typography.size_sm, visible=False)
        self._progress_detail = ft.Text("", color=t.colors.fg_muted, size=t.typography.size_xs, visible=False)

        # Circular scan progress view — swaps in over main content during active scan
        self._ring = ft.ProgressRing(
            width=100, height=100,
            stroke_width=8,
            color="#00BFA5",
            value=None,  # indeterminate until first progress callback
        )
        self._ring_label = ft.Text(
            "Scanning your drive...",
            size=t.typography.size_xl,
            weight=ft.FontWeight.BOLD,
            color=t.colors.fg,
            text_align=ft.TextAlign.CENTER,
        )
        self._ring_counter = ft.Text(
            "Processed: 0 / 0",
            size=t.typography.size_md,
            color=t.colors.fg2,
            font_family="Courier New",
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
        self._scan_view = ft.Container(
            content=ft.Column(
                [
                    self._ring,
                    self._ring_label,
                    self._ring_counter,
                    self._ring_path,
                    self._cancel_btn,
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

        # Assemble — main panels tracked so scan view can swap in/out
        self.controls = [
            self._hero,
            ft.Container(content=self._stats_row, padding=ft.padding.symmetric(vertical=s.lg)),
            ft.Container(content=self._mode_label, padding=ft.padding.only(left=s.md, top=s.sm)),
            ft.Container(content=self._mode_row, padding=ft.padding.symmetric(horizontal=s.md, vertical=s.sm)),
            self._folder_container,
            ft.Container(
                content=ft.Column([self._recent_wrap, self._quick_add_wrap], spacing=s.sm),
                padding=ft.padding.only(left=s.md, right=s.md, bottom=s.sm),
            ),
            ft.Container(content=self._actions, padding=ft.padding.only(top=s.md, bottom=s.md)),
            ft.Container(content=self._status, padding=ft.padding.only(top=s.md)),
        ]
        self._main_panels = list(self.controls)  # snapshot for hide/show swap
        self.controls.append(self._scan_view)     # scan view always last, starts hidden
        
        # Initial data fetch
        self._fetch_dashboard_data()

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
    def _fetch_dashboard_data(self):
        try:
            stats = self._bridge.get_stats()
            if stats:
                self._stats = stats
            
        except Exception as e:
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
                content=ft.Column(
                    [
                        ft.Container(
                            content=ft.Icon(icon, size=20, color=accent),
                            bgcolor=ft.Colors.with_opacity(0.18, accent),
                            border=ft.border.all(1, ft.Colors.with_opacity(0.35, accent)),
                            border_radius=8,
                            padding=8,
                        ),
                        ft.Text(
                            value,
                            size=t.typography.size_xxl,
                            weight=ft.FontWeight.W_700,
                            color=accent,
                            text_align=ft.TextAlign.CENTER,
                        ),
                        ft.Text(
                            label,
                            size=t.typography.size_base,
                            color=t.colors.fg2,
                            weight=ft.FontWeight.W_600,
                            text_align=ft.TextAlign.CENTER,
                        ),
                    ],
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=8,
                ),
                padding=ft.padding.symmetric(horizontal=28, vertical=18),
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
                    ft.Text(
                        "Click to select",
                        size=t.typography.size_xs,
                        color="#A5F3FC" if is_active else t.colors.fg_muted,
                        italic=True,
                    ),
                ],
                spacing=s.sm,
                tight=True,
            )

            card_kwargs: dict = dict(
                content=card_content,
                width=160,
                height=154,
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
        t = self._t
        recents = self._discover_recent_scan_paths(limit=6)
        if not recents:
            self._recent_wrap.visible = False
            if self._is_mounted():
                self._recent_wrap.update()
            return
        self._recent_wrap.visible = True
        self._recent_paths_row.controls = [
            ft.Chip(
                label=ft.Text(label, size=t.typography.size_sm),
                leading=ft.Icon(ft.icons.Icons.HISTORY, size=14, color=t.colors.fg2),
                bgcolor=ft.Colors.with_opacity(0.10, t.colors.primary),
                shape=ft.RoundedRectangleBorder(radius=10),
                on_click=lambda _e, pp=p: self._add_folder(pp),
            )
            for label, p in recents
        ]
        if self._is_mounted():
            self._recent_paths_row.update()
            self._recent_wrap.update()

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
        # Use the bridge's page reference to run async task safely
        if hasattr(self._bridge, 'flet_page') and self._bridge.flet_page:
            self._bridge.flet_page.run_task(self._browse_folders_async)
        else:
            _log.warning("Bridge page not available for folder picker")

    async def _browse_folders_async(self) -> None:
        try:
            result = await self._folder_picker.get_directory_path(
                dialog_title="Select folder to scan"
            )
            # Flet 0.25+ returns the folder path as str | None (not an object with .path).
            if result:
                self._add_folder(Path(result))
        except Exception as e:
            _log.error(f"Folder picker failed: {e}")

    def _add_folder(self, path: Path) -> None:
        if path in self._folders:
            return
        self._folders.append(path)
        self._refresh_folder_chips()

    def _refresh_folder_chips(self) -> None:
        t = self._t
        if not self._folders:
            self._folder_chips_row.controls = [
                ft.Row(
                    [
                        ft.Icon(ft.icons.Icons.FOLDER_OPEN, size=16, color=t.colors.fg_muted),
                        ft.Text(
                            "No folders selected — browse or quick-add below",
                            color=t.colors.fg_muted,
                            size=t.typography.size_base,
                            italic=True,
                        ),
                    ],
                    spacing=6,
                )
            ]
        else:
            self._folder_chips_row.controls = [
                ft.Chip(
                    label=ft.Text(str(f), size=t.typography.size_sm),
                    on_delete=lambda e, p=f: self._remove_folder(p),
                    shape=ft.RoundedRectangleBorder(radius=8),
                    bgcolor=ft.Colors.with_opacity(0.1, t.colors.primary),
                )
                for f in self._folders
            ]
        self._clear_folders_btn.visible = bool(self._folders)
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

    def _start_scan(self, e: ft.ControlEvent) -> None:
        if not self._folders:
            self._status.value = "Please select at least one folder first."
            self._status.update()
            return
        
        self._ring.value = None  # indeterminate until first progress tick
        self._ring_counter.value = "Processed: 0 / 0"
        self._ring_path.value = ""
        self._ring_label.value = "Scanning your drive..."
        for p in self._main_panels:
            p.visible = False
        self._scan_view.visible = True
        DashboardPage._safe_update(self)

        self._bridge.begin_scan_session(self._folders, self._selected_mode)

        try:
            backend = self._bridge.backend
            backend.set_on_progress(self._on_scan_progress)
            backend.set_on_complete(self._on_scan_complete)
            backend.set_on_error(self._on_scan_error)
            backend.start_scan(self._folders, mode=self._selected_mode)
        except Exception as err:
            self._on_scan_error(f"Backend communication error: {err}")

    def _on_scan_progress(self, data: dict) -> None:
        stage = data.get("stage", "")
        scanned = data.get("files_scanned", 0)
        total = data.get("files_total", 0)
        elapsed = data.get("elapsed_seconds", 0.0)
        current_file = str(data.get("current_file", "") or "")
        
        rate = (float(scanned) / float(elapsed)) if elapsed > 0 else 0.0
        eta_s = ((float(total) - float(scanned)) / rate) if (total and rate > 0) else 0.0
        self._ring_counter.value = (
            f"Processed: {scanned:,} / {total:,}  ·  {rate:,.0f} files/s  ·  ETA {self._fmt_eta(eta_s)}"
            if total
            else f"Processed: {scanned:,}  ·  {rate:,.0f} files/s"
        )
        self._ring_path.value = self._shorten_path(current_file) if current_file else ""
        if total > 0:
            self._ring.value = scanned / total

        try:
            self._bridge.flet_page.update()
        except Exception:
            pass

    def _on_scan_complete(self, results: list, mode: str) -> None:
        self._scan_view.visible = False
        for p in self._main_panels:
            p.visible = True
        self._status.value = f"Scan complete — {len(results):,} duplicate groups found."
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
        self._bridge.abort_scan_session()
        self._scan_view.visible = False
        for p in self._main_panels:
            p.visible = True
        self._status.value = f"Scan error: {msg}"
        DashboardPage._safe_update(self)
        self._bridge.play_sound("error")

    def _stop_scan(self, e: ft.ControlEvent) -> None:
        try:
            self._bridge.backend.cancel_scan()
        except Exception as err:
            _log.error(f"Failed to stop scan: {err}")

        self._bridge.abort_scan_session()
        self._scan_view.visible = False
        for p in self._main_panels:
            p.visible = True
        self._status.value = "Cancelling scan..."
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
    def _shorten_path(path: str, max_len: int = 88) -> str:
        p = str(path)
        if len(p) <= max_len:
            return f"Current: {p}"
        head = max_len // 2 - 2
        tail = max_len - head - 3
        return f"Current: {p[:head]}...{p[-tail:]}"

    def on_show(self) -> None:
        self._fetch_dashboard_data()
        self._refresh_recent_paths_bar()
        self._refresh_quick_add_bar()
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
        self._update_stats_ui()
        self._update_modes_ui()
        self._refresh_folder_chips() # Chips have background colors relative to theme
        self._refresh_quick_add_bar()

        if self._is_mounted():
            self.update()