"""Results page — displays duplicate groups with filtering, smart selection, and delete actions."""

from __future__ import annotations

import asyncio
import datetime
import logging
import math
import re
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Set

import flet as ft

from cerebro.core.deletion import DeletionPolicy
from cerebro.engines.base_engine import DuplicateGroup
from cerebro.v2.ui.flet_app.theme import (
    FILTER_EXTS, classify_file, fmt_size, theme_for_mode,
)
from cerebro.v2.ui.flet_app.services.thumbnail_cache import get_thumbnail_cache, is_image_path

if TYPE_CHECKING:
    from cerebro.v2.ui.flet_app.services.state_bridge import StateBridge

_log = logging.getLogger(__name__)

_FILTER_TABS = [
    ("all", "All"),
    ("pictures", "Images"),
    ("music", "Music"),
    ("videos", "Videos"),
    ("documents", "Docs"),
    ("archives", "Archives"),
    ("other", "Other"),
]

_FILTER_ACCENT = {
    "all": "#C7D2FE",
    "pictures": "#C084FC",
    "music": "#34D399",
    "videos": "#F472B6",
    "documents": "#FB923C",
    "archives": "#FBBF24",
    "other": "#93C5FD",
}

# Above this many duplicate *groups*, build the ListView in chunks so the UI thread
# can still process NavigationRail taps (see debug-4176e4: multi-second sync build).
_LIST_BUILD_ASYNC_THRESHOLD = 72
_LIST_FIRST_SYNC_GROUPS = 4   # F3: show 4 cards before first frame, rest async
_LIST_ASYNC_BATCH = 16
_GRID_BUILD_ASYNC_THRESHOLD = 36
_GRID_FIRST_SYNC_GROUPS = 4   # F3: same for grid
_GRID_ASYNC_BATCH = 8

_SMART_SELECT_OPTIONS = [
    ("keep_largest", "Keep Largest"),
    ("keep_smallest", "Keep Smallest"),
    ("keep_newest", "Keep Newest"),
    ("keep_oldest", "Keep Oldest"),
]


class ResultsPage(ft.Stack):
    """Duplicate group listing with type filters, smart selection, and delete."""

    def __init__(self, bridge: "StateBridge"):
        super().__init__(expand=True)
        self._scroll_col = ft.Column(expand=True, scroll=ft.ScrollMode.AUTO)
        self._bridge = bridge
        self._t = theme_for_mode("dark")
        self._groups: List[DuplicateGroup] = []
        self._filter_key = "all"
        self._scan_mode = "files"
        self._selected_paths: Set[str] = set()
        self._smart_rule = "keep_largest"
        self._list_build_generation = 0
        self._loading = False
        self._filter_counts: Dict[str, int] = {k: 0 for k, _ in _FILTER_TABS}
        self._filter_sizes: Dict[str, int] = {k: 0 for k, _ in _FILTER_TABS}
        self._filter_group_counts: Dict[str, int] = {k: 0 for k, _ in _FILTER_TABS}
        self._glass_cache: dict = {}
        self._view_mode: str = "list"
        self._view_mode_by_filter: Dict[str, str] = {"all": "list"}
        self._grouping_mode: str = "groups"
        self._folder_cross_only: bool = False
        self._min_reclaimable_bytes: int = 0
        self._thumb_slots: Dict[str, ft.Container] = {}
        self._tile_cache_grid: Dict[str, ft.Container] = {}
        self._all_group_cards: Dict[int, ft.Container] = {}
        self._inspector_file = None  # currently inspected DuplicateFile
        self._inspector_dims_generation = 0
        self._rendering_generation = 0
        self._pending_deferred_render: bool = False

        # UI References
        self._summary: ft.Text
        self._last_scan: ft.Text
        self._hero_card: ft.Container
        self._hero_primary: ft.Text
        self._hero_secondary: ft.Text
        self._type_strip: ft.Row
        self._folder_col: ft.Column
        self._group_col: ft.Column
        self._age_col: ft.Column
        self._mult_col: ft.Column
        self._smart_seg: ft.SegmentedButton
        self._smart_row: ft.Row
        self._selection_label: ft.Text
        self._delete_btn: ft.ElevatedButton
        self._permanent_btn: ft.OutlinedButton
        self._action_bar: ft.Row
        self._header: ft.Row
        self._filter_seg: ft.SegmentedButton
        self._min_group_filter: ft.Dropdown
        self._grouping_seg: ft.SegmentedButton
        self._folder_cross_toggle: ft.Switch
        self._group_list: ft.ListView
        self._empty: ft.Container
        self._loading_state: ft.Container
        self._results_grid: ft.ListView
        self._rendering_badge: ft.Container
        self._grid_btn: ft.IconButton
        self._list_btn: ft.IconButton
        self._inspector_panel: ft.Container
        self._inspector_wrapper: ft.Container
        self._inspector_thumb: ft.Container
        self._inspector_name: ft.Text
        self._inspector_size: ft.Text
        self._inspector_date: ft.Text
        self._inspector_dims: ft.Text
        self._inspector_path: ft.Text

        self._build_ui()

    # ------------------------------------------------------------------
    # Glass helper
    # ------------------------------------------------------------------
    def _get_glass_style(self, opacity: float = 0.06) -> dict:
        is_light = "light" in self._bridge.app_theme.lower() if hasattr(self._bridge, 'app_theme') else False
        cache_key = (opacity, is_light)
        if cache_key in self._glass_cache:
            return self._glass_cache[cache_key]
        bg_base = ft.Colors.BLACK if is_light else ft.Colors.WHITE
        border_base = ft.Colors.BLACK if is_light else ft.Colors.WHITE
        bg = ft.Colors.with_opacity(opacity, bg_base)
        border_color = ft.Colors.with_opacity(0.12, border_base)
        result = dict(
            bgcolor=bg,
            border=ft.border.all(1, border_color),
            border_radius=ft.border_radius.all(12),
        )
        self._glass_cache[cache_key] = result
        return result
    
    def _file_type_icon(self, extension: str) -> tuple[str, str]:
        """Return (icon_name, accent_color) for a file extension."""
        ext = (extension or "").lower().lstrip(".")
        _map = {
            # Images
            "jpg": (ft.icons.Icons.IMAGE, "#A78BFA"),
            "jpeg": (ft.icons.Icons.IMAGE, "#A78BFA"),
            "png": (ft.icons.Icons.IMAGE, "#A78BFA"),
            "gif": (ft.icons.Icons.IMAGE, "#A78BFA"),
            "heic": (ft.icons.Icons.IMAGE, "#A78BFA"),
            "webp": (ft.icons.Icons.IMAGE, "#A78BFA"),
            "raw": (ft.icons.Icons.IMAGE, "#A78BFA"),
            # Music
            "mp3": (ft.icons.Icons.MUSIC_NOTE, "#34D399"),
            "flac": (ft.icons.Icons.MUSIC_NOTE, "#34D399"),
            "wav": (ft.icons.Icons.MUSIC_NOTE, "#34D399"),
            "aac": (ft.icons.Icons.MUSIC_NOTE, "#34D399"),
            "m4a": (ft.icons.Icons.MUSIC_NOTE, "#34D399"),
            # Video
            "mp4": (ft.icons.Icons.VIDEOCAM, "#F472B6"),
            "mkv": (ft.icons.Icons.VIDEOCAM, "#F472B6"),
            "mov": (ft.icons.Icons.VIDEOCAM, "#F472B6"),
            "avi": (ft.icons.Icons.VIDEOCAM, "#F472B6"),
            # Documents
            "pdf": (ft.icons.Icons.PICTURE_AS_PDF, "#FB923C"),
            "doc": (ft.icons.Icons.DESCRIPTION, "#60A5FA"),
            "docx": (ft.icons.Icons.DESCRIPTION, "#60A5FA"),
            "xls": (ft.icons.Icons.TABLE_CHART, "#34D399"),
            "xlsx": (ft.icons.Icons.TABLE_CHART, "#34D399"),
            "ppt": (ft.icons.Icons.SLIDESHOW, "#FB923C"),
            "pptx": (ft.icons.Icons.SLIDESHOW, "#FB923C"),
            "txt": (ft.icons.Icons.ARTICLE, "#94A3B8"),
            # Archives
            "zip": (ft.icons.Icons.FOLDER_ZIP, "#FBBF24"),
            "rar": (ft.icons.Icons.FOLDER_ZIP, "#FBBF24"),
            "7z": (ft.icons.Icons.FOLDER_ZIP, "#FBBF24"),
            "tar": (ft.icons.Icons.FOLDER_ZIP, "#FBBF24"),
            "gz": (ft.icons.Icons.FOLDER_ZIP, "#FBBF24"),
        }
        return _map.get(ext, (ft.icons.Icons.INSERT_DRIVE_FILE, "#6E7681"))

    @staticmethod
    def _is_machine_generated_name(name: str) -> bool:
        stem = Path(name).stem
        if len(stem) <= 40:
            return False
        # Only digits count toward the heuristic; separators alone should not
        # make a name look machine-generated.
        digits = sum(1 for ch in stem if ch.isdigit())
        ratio = digits / max(1, len(stem))
        return ratio > 0.60 and bool(re.search(r"\d{8,}", stem))

    # ------------------------------------------------------------------
    # Build (Runs Once)
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        t = self._t

        self._summary = ft.Text("", size=t.typography.size_md, color="#BFD5FF", weight=ft.FontWeight.W_600)
        self._last_scan = ft.Text("Last scan: -", size=t.typography.size_sm, color=t.colors.fg_muted)

        # Smart select row
        self._smart_seg = ft.SegmentedButton(
            selected=["keep_largest"],
            allow_multiple_selection=False,
            on_change=self._on_smart_seg_change,
            segments=[
                ft.Segment(value=val, label=ft.Text(label, size=11))
                for val, label in _SMART_SELECT_OPTIONS
            ],
        )
        self._auto_mark_btn = ft.OutlinedButton(
            "Auto Mark",
            icon=ft.icons.Icons.AUTO_FIX_HIGH,
            on_click=self._apply_smart_select,
            style=ft.ButtonStyle(
                color="#22D3EE",
                side=ft.BorderSide(1, "#22D3EE"),
                shape=ft.RoundedRectangleBorder(radius=8),
                text_style=ft.TextStyle(size=13, weight=ft.FontWeight.W_700),
            ),
        )
        self._unmark_all_btn = ft.OutlinedButton(
            "Unmark All",
            icon=ft.icons.Icons.DESELECT,
            on_click=self._unmark_all,
            style=ft.ButtonStyle(
                color=t.colors.fg_muted,
                side=ft.BorderSide(1, t.colors.border),
                shape=ft.RoundedRectangleBorder(radius=8),
            ),
        )
        self._rule_label = ft.Text(
            "Active rule: Keep Largest",
            size=t.typography.size_sm,
            color=t.colors.fg_muted,
            weight=ft.FontWeight.W_500,
        )
        self._smart_row = ft.Row(
            [
                ft.Container(content=self._rule_label, margin=ft.margin.only(right=t.spacing.sm)),
                self._smart_seg,
                self._auto_mark_btn,
                self._unmark_all_btn,
            ],
            spacing=t.spacing.sm,
            visible=False,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        # Selection label and delete buttons
        self._selection_label = ft.Text("", size=t.typography.size_sm, color=t.colors.fg2)
        self._delete_btn = ft.OutlinedButton(
            "Move to Trash",
            icon=ft.icons.Icons.DELETE_OUTLINE,
            on_click=self._on_delete_clicked,
            style=ft.ButtonStyle(
                color=t.colors.danger,
                side=ft.BorderSide(1, t.colors.danger),
                shape=ft.RoundedRectangleBorder(radius=8),
            ),
            visible=False,
        )
        self._permanent_btn = ft.OutlinedButton(
            "Delete Permanently",
            icon=ft.icons.Icons.DELETE_FOREVER,
            on_click=self._on_permanent_delete_clicked,
            style=ft.ButtonStyle(color=t.colors.danger),
            visible=False,
        )
        self._action_bar = ft.Row(
            [self._selection_label, self._smart_row, self._delete_btn, self._permanent_btn],
            alignment=ft.MainAxisAlignment.START,
            spacing=t.spacing.md,
            visible=False,
        )

        self._grid_btn = ft.IconButton(
            icon=ft.icons.Icons.GRID_VIEW,
            tooltip="Grid view",
            icon_color="#22D3EE",
            on_click=lambda e: self._toggle_view("grid"),
        )
        self._list_btn = ft.IconButton(
            icon=ft.icons.Icons.VIEW_LIST,
            tooltip="List view",
            icon_color=t.colors.fg_muted,
            on_click=lambda e: self._toggle_view("list"),
        )
        self._header = ft.Row(
            [
                ft.Column(
                    [
                        ft.Text("Scan Results", size=t.typography.size_xl, weight=ft.FontWeight.BOLD, color=t.colors.fg),
                        self._last_scan,
                    ],
                    spacing=2,
                ),
                ft.Row([self._summary, self._grid_btn, self._list_btn], spacing=t.spacing.xs, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        )
        self._grouping_seg = ft.SegmentedButton(
            selected=["groups"],
            allow_multiple_selection=False,
            on_change=self._on_grouping_change,
            segments=[
                ft.Segment(value="groups", label=ft.Text("By Group", size=11)),
                ft.Segment(value="folders", label=ft.Text("By Folder", size=11)),
            ],
        )
        self._folder_cross_toggle = ft.Switch(
            label="Cross-folder only (0)",
            value=False,
            on_change=self._on_folder_cross_only_change,
            visible=False,
        )

        self._filter_seg = ft.SegmentedButton(
            selected=["all"],
            allow_multiple_selection=False,
            on_change=self._on_filter_seg_change,
            segments=[
                ft.Segment(
                    value=key,
                    label=ft.Column(
                        [
                            ft.Text(label, size=12, weight=ft.FontWeight.W_600, color="#DDE8FF"),
                            ft.Text("0", size=11, weight=ft.FontWeight.W_600, color=_FILTER_ACCENT.get(key, "#C7D2FE")),
                            ft.Text("0 B", size=10, color="#9FB0D0"),
                        ],
                        spacing=1,
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        tight=True,
                    ),
                )
                for key, label in _FILTER_TABS
            ],
        )
        self._min_group_filter = ft.Dropdown(
            width=220,
            value="0",
            dense=True,
            text_size=12,
            label="Minimum group reclaimable",
            options=[
                ft.dropdown.Option("0", "Show all"),
                ft.dropdown.Option(str(100 * 1024), "100 KB+"),
                ft.dropdown.Option(str(1024 * 1024), "1 MB+"),
                ft.dropdown.Option(str(10 * 1024 * 1024), "10 MB+"),
            ],
        )
        self._min_group_filter.on_change = self._on_min_group_filter_change

        self._group_list = ft.ListView(expand=True, spacing=t.spacing.sm, padding=t.spacing.lg)
        self._results_grid = ft.ListView(expand=True, spacing=t.spacing.md, padding=t.spacing.lg)
        self._hero_primary = ft.Text("0 B", size=t.typography.size_xxxl, weight=ft.FontWeight.BOLD, color="#22D3EE")
        self._hero_secondary = ft.Text("", size=t.typography.size_base, color=t.colors.fg2)
        self._hero_card = ft.Container(
            content=ft.Column(
                [
                    self._hero_primary,
                    ft.Text("can be reclaimed", size=t.typography.size_lg, weight=ft.FontWeight.W_600, color=t.colors.fg),
                    self._hero_secondary,
                    ft.FilledButton(
                        "Review duplicates →",
                        on_click=lambda e: self._bridge.navigate("review"),
                        style=ft.ButtonStyle(bgcolor="#22D3EE", color="#0B1220"),
                    ),
                ],
                spacing=t.spacing.sm,
            ),
            padding=t.spacing.xl,
            **self._get_glass_style(0.06),
        )
        self._type_strip = ft.Row(wrap=True, spacing=t.spacing.sm)
        self._folder_col = ft.Column(spacing=t.spacing.xs)
        self._group_col = ft.Column(spacing=t.spacing.xs)
        self._age_col = ft.Column(spacing=t.spacing.xs)
        self._mult_col = ft.Column(spacing=t.spacing.xs)
        self._dashboard = ft.Column(
            [
                self._hero_card,
                ft.Text("By type", size=t.typography.size_md, weight=ft.FontWeight.W_700, color=t.colors.fg),
                self._type_strip,
                ft.ResponsiveRow(
                    [
                        ft.Container(
                            col={"sm": 12, "md": 6},
                            content=ft.Column(
                                [ft.Text("Top folders", size=t.typography.size_md, weight=ft.FontWeight.W_700), self._folder_col],
                                spacing=t.spacing.xs,
                            ),
                            padding=t.spacing.md,
                            **self._get_glass_style(0.05),
                        ),
                        ft.Container(
                            col={"sm": 12, "md": 6},
                            content=ft.Column(
                                [ft.Text("Top groups", size=t.typography.size_md, weight=ft.FontWeight.W_700), self._group_col],
                                spacing=t.spacing.xs,
                            ),
                            padding=t.spacing.md,
                            **self._get_glass_style(0.05),
                        ),
                        ft.Container(
                            col={"sm": 12, "md": 6},
                            content=ft.Column(
                                [ft.Text("By age", size=t.typography.size_md, weight=ft.FontWeight.W_700), self._age_col],
                                spacing=t.spacing.xs,
                            ),
                            padding=t.spacing.md,
                            **self._get_glass_style(0.05),
                        ),
                        ft.Container(
                            col={"sm": 12, "md": 6},
                            content=ft.Column(
                                [ft.Text("Highest multiplicity", size=t.typography.size_md, weight=ft.FontWeight.W_700), self._mult_col],
                                spacing=t.spacing.xs,
                            ),
                            padding=t.spacing.md,
                            **self._get_glass_style(0.05),
                        ),
                    ],
                    run_spacing=t.spacing.sm,
                    spacing=t.spacing.sm,
                ),
                ft.Row(
                    [
                        ft.FilledButton("Browse all groups (grid)", on_click=lambda e: self._toggle_view("grid")),
                        ft.OutlinedButton("Browse all groups (list)", on_click=lambda e: self._toggle_view("list")),
                    ],
                    spacing=t.spacing.sm,
                ),
            ],
            spacing=t.spacing.md,
        )
        self._rendering_badge = ft.Container(
            alignment=ft.Alignment(-1, -1),
            margin=ft.margin.only(top=t.spacing.sm, right=t.spacing.md),
            visible=False,
            content=ft.Container(
                content=ft.Row(
                    [
                        ft.ProgressRing(width=14, height=14, stroke_width=2, color="#22D3EE"),
                        ft.Text("View ready - filling items...", size=t.typography.size_xs, color="#9FDDF7"),
                    ],
                    spacing=6,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                bgcolor=ft.Colors.with_opacity(0.82, "#09111D"),
                border=ft.border.all(1, ft.Colors.with_opacity(0.25, "#22D3EE")),
                border_radius=999,
                padding=ft.padding.symmetric(horizontal=10, vertical=6),
            ),
        )

        self._empty = ft.Container(
            content=ft.Column(
                [
                    ft.Container(
                        content=ft.Icon(ft.icons.Icons.MANAGE_SEARCH, size=48, color="#22D3EE"),
                        bgcolor=ft.Colors.with_opacity(0.08, "#22D3EE"),
                        border_radius=16,
                        padding=20,
                    ),
                    ft.Text("No duplicates found yet", size=t.typography.size_lg, weight=ft.FontWeight.W_600, color=t.colors.fg),
                    ft.Text(
                        "Head to Home and run a scan to see results here.",
                        size=t.typography.size_base,
                        color=t.colors.fg_muted,
                        text_align=ft.TextAlign.CENTER,
                    ),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=t.spacing.lg,
            ),
            expand=True,
            alignment=ft.Alignment(0, 0),
            **self._get_glass_style(0.04),
        )
        self._loading_state = ft.Container(
            content=ft.Column(
                [self._build_skeleton_card() for _ in range(5)],
                spacing=t.spacing.sm,
            ),
            expand=True,
            padding=t.spacing.lg,
        )

        self._sticky_bar = ft.Container(
            content=ft.Row(
                [
                    ft.Column(
                        [self._selection_label],
                        expand=True,
                        alignment=ft.MainAxisAlignment.CENTER,
                        spacing=0,
                    ),
                    self._delete_btn,
                    self._permanent_btn,
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=t.spacing.md,
            ),
            padding=ft.padding.symmetric(horizontal=t.spacing.xl, vertical=t.spacing.md),
            bgcolor=ft.Colors.with_opacity(0.97, "#0D0505"),
            border=ft.border.only(top=ft.BorderSide(2, "#EF4444")),
            visible=False,
            shadow=ft.BoxShadow(
                blur_radius=20,
                offset=ft.Offset(0, -4),
                color=ft.Colors.with_opacity(0.45, "#EF4444"),
            ),
        )
        self._sticky_overlay = ft.Column(
            [ft.Container(expand=True), self._sticky_bar],
            expand=True,
            spacing=0,
            visible=False,
        )

        self._scroll_col.controls = [
            ft.Container(
                content=self._header,
                padding=ft.padding.only(left=t.spacing.lg, right=t.spacing.lg, top=t.spacing.md),
                **self._get_glass_style(0.04),
            ),
            ft.Container(content=self._dashboard, padding=ft.padding.symmetric(horizontal=t.spacing.lg, vertical=t.spacing.md)),
            self._empty,
        ]
        # Inspector panel (right side overlay)
        self._inspector_thumb = ft.Container(
            width=220, height=160,
            border_radius=8,
            bgcolor=ft.Colors.with_opacity(0.08, ft.Colors.WHITE),
            alignment=ft.Alignment(0, 0),
            content=ft.Icon(ft.icons.Icons.INSERT_DRIVE_FILE, size=48, color=ft.Colors.with_opacity(0.3, ft.Colors.WHITE)),
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
        )
        self._inspector_name = ft.Text("", size=t.typography.size_md, weight=ft.FontWeight.W_600, color=t.colors.fg, text_align=ft.TextAlign.CENTER, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS)
        self._inspector_size = ft.Text("", size=t.typography.size_sm, color="#4ADE80", weight=ft.FontWeight.W_600)
        self._inspector_date = ft.Text("", size=t.typography.size_xs, color="#BFD5FF")
        self._inspector_dims = ft.Text("", size=t.typography.size_xs, color="#C084FC")
        self._inspector_path = ft.Text("", size=t.typography.size_xs, color=t.colors.fg_muted, max_lines=3, overflow=ft.TextOverflow.ELLIPSIS)

        def _meta_row_insp(icon_name: str, text_ctrl: ft.Text) -> ft.Row:
            return ft.Row(
                [ft.Icon(icon_name, size=12, color=ft.Colors.with_opacity(0.5, ft.Colors.WHITE)), text_ctrl],
                spacing=6, vertical_alignment=ft.CrossAxisAlignment.START,
            )

        self._inspector_panel = ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Text("Inspector", size=t.typography.size_sm, weight=ft.FontWeight.W_700, color=t.colors.fg, expand=True),
                            ft.IconButton(
                                icon=ft.icons.Icons.CLOSE,
                                icon_size=16,
                                icon_color=t.colors.fg_muted,
                                on_click=lambda e: self._close_inspector(),
                                tooltip="Close",
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Divider(height=1, color=ft.Colors.with_opacity(0.12, ft.Colors.WHITE)),
                    self._inspector_thumb,
                    self._inspector_name,
                    _meta_row_insp(ft.icons.Icons.STORAGE, self._inspector_size),
                    _meta_row_insp(ft.icons.Icons.SCHEDULE, self._inspector_date),
                    _meta_row_insp(ft.icons.Icons.ASPECT_RATIO, self._inspector_dims),
                    _meta_row_insp(ft.icons.Icons.FOLDER_OPEN, self._inspector_path),
                ],
                spacing=t.spacing.sm,
                scroll=ft.ScrollMode.AUTO,
            ),
            width=280,
            padding=t.spacing.lg,
            bgcolor=ft.Colors.with_opacity(0.92, "#0B1220"),
            border=ft.border.only(left=ft.BorderSide(1, ft.Colors.with_opacity(0.18, ft.Colors.WHITE))),
            shadow=ft.BoxShadow(blur_radius=24, offset=ft.Offset(-4, 0), color=ft.Colors.with_opacity(0.35, ft.Colors.BLACK)),
            visible=False,
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
        )
        self._inspector_wrapper = ft.Container(
            content=self._inspector_panel,
            alignment=ft.Alignment(1, 0),
            expand=True,
            visible=False,
        )

        self.controls = [self._scroll_col, self._sticky_overlay, self._inspector_wrapper, self._rendering_badge]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def load_results(self, groups: List[DuplicateGroup], mode: str = "files", *, defer_render: bool = False) -> None:
        self._groups = sorted(list(groups), key=lambda g: int(getattr(g, "reclaimable", 0) or 0), reverse=True)
        self._scan_mode = mode or "files"
        self._selected_paths.clear()
        self._all_group_cards = {}
        self._recompute_filter_counts()
        if defer_render:
            # Data is fresh; grid will build when on_show() fires (user navigates to Results tab)
            self._pending_deferred_render = True
            return
        self._pending_deferred_render = False
        self._loading = True
        self._refresh()
        page = self._bridge.flet_page
        if hasattr(page, "run_task"):
            page.run_task(self._finish_loading_async)
        else:
            self._loading = False
            self._refresh()

    def get_groups(self) -> List[DuplicateGroup]:
        return list(self._groups)

    def on_show(self) -> None:
        if self._pending_deferred_render:
            self._pending_deferred_render = False
            self._loading = True
            self._refresh()
            page = self._bridge.flet_page
            if hasattr(page, "run_task"):
                page.run_task(self._finish_loading_async)
            else:
                self._loading = False
        self._refresh()

    def _is_mounted(self) -> bool:
        try:
            return self.page is not None
        except RuntimeError:
            return False

    @staticmethod
    def _safe_update(ctrl: ft.Control | None) -> None:
        """Call ``update()`` only when *ctrl* is on the page (avoids errors on freshly appended children)."""
        if ctrl is None:
            return
        try:
            if ctrl.page is not None:
                ctrl.update()
        except RuntimeError:
            pass

    def _set_rendering(self, value: bool) -> None:
        self._rendering_generation += 1
        gen = self._rendering_generation
        self._rendering_badge.visible = value
        self._safe_update(self._rendering_badge)
        if value:
            page = self._bridge.flet_page
            if hasattr(page, "run_task"):
                page.run_task(self._rendering_failsafe_async, gen)

    async def _rendering_failsafe_async(self, gen: int) -> None:
        await asyncio.sleep(1.6)
        if gen != self._rendering_generation:
            return
        if self._rendering_badge.visible:
            self._set_rendering(False)
            self._safe_update(self._rendering_badge)

    # ------------------------------------------------------------------
    # Selection and smart select
    # ------------------------------------------------------------------
    def _toggle_file(self, path: str) -> None:
        if path in self._selected_paths:
            self._selected_paths.discard(path)
        else:
            self._selected_paths.add(path)
        self._update_selection_ui()

    def _on_file_checkbox(self, e: ft.ControlEvent, path: str) -> None:
        checked = bool(getattr(e.control, "value", False))
        if checked:
            self._selected_paths.add(path)
        else:
            self._selected_paths.discard(path)
        self._update_selection_ui()

    def _on_smart_seg_change(self, e: ft.ControlEvent) -> None:
        sel = getattr(e.control, "selected", None) or {"keep_largest"}
        self._smart_rule = next(iter(sel), "keep_largest")
        label = dict(_SMART_SELECT_OPTIONS).get(self._smart_rule, "Keep Largest")
        self._rule_label.value = f"Active rule: {label}"
        ResultsPage._safe_update(self._rule_label)

    def _pick_keeper(self, group: DuplicateGroup):
        if not group.files:
            return None
        if self._smart_rule == "keep_largest":
            return max(group.files, key=lambda f: f.size)
        if self._smart_rule == "keep_smallest":
            return min(group.files, key=lambda f: f.size)
        if self._smart_rule == "keep_newest":
            return max(group.files, key=lambda f: getattr(f, "mtime", 0) or 0)
        if self._smart_rule == "keep_oldest":
            return min(group.files, key=lambda f: getattr(f, "mtime", 0) or 0)
        return max(group.files, key=lambda f: f.size)

    def _unmark_all(self, e=None) -> None:
        self._selected_paths.clear()
        self._refresh()

    def _apply_smart_select(self, e=None) -> None:
        self._selected_paths.clear()
        for g in self._filtered_groups():
            if len(g.files) < 2:
                continue
            # Determine the file to keep based on rule
            if self._smart_rule == "keep_largest":
                keep = max(g.files, key=lambda f: f.size)
            elif self._smart_rule == "keep_smallest":
                keep = min(g.files, key=lambda f: f.size)
            elif self._smart_rule == "keep_newest":
                keep = max(g.files, key=lambda f: getattr(f, "mtime", 0) or 0)
            elif self._smart_rule == "keep_oldest":
                keep = min(g.files, key=lambda f: getattr(f, "mtime", 0) or 0)
            else:
                keep = max(g.files, key=lambda f: f.size)  # fallback
            for f in g.files:
                if f is not keep:
                    self._selected_paths.add(str(f.path))
        self._refresh()

    def _apply_group_selection_to_set(self, group: DuplicateGroup, selected: bool) -> None:
        keeper = self._pick_keeper(group) if selected else None
        for f in group.files:
            fp = str(f.path)
            if selected:
                if keeper is not None and f is keeper:
                    self._selected_paths.discard(fp)
                else:
                    self._selected_paths.add(fp)
            else:
                self._selected_paths.discard(fp)

    def _set_group_selection(self, group: DuplicateGroup, selected: bool) -> None:
        self._apply_group_selection_to_set(group, selected)
        self._refresh()

    def _set_folder_selection(self, groups: List[DuplicateGroup], selected: bool) -> None:
        for g in groups:
            self._apply_group_selection_to_set(g, selected)
        self._refresh()

    def _update_selection_ui(self) -> None:
        # Results is read-only intelligence surface; decisions happen on Review.
        self._smart_row.visible = False
        self._delete_btn.visible = False
        self._permanent_btn.visible = False
        self._selection_label.value = ""
        self._sticky_bar.visible = False
        self._sticky_overlay.visible = False
        ResultsPage._safe_update(self._smart_row)
        ResultsPage._safe_update(self._sticky_bar)
        ResultsPage._safe_update(self._sticky_overlay)
        self._update_summary_line()

    def _current_marked_bytes(self) -> int:
        total_bytes = 0
        selected_set = self._selected_paths
        for g in self._groups:
            for f in g.files:
                if str(f.path) in selected_set:
                    total_bytes += f.size
        return total_bytes

    def _update_summary_line(self) -> None:
        filtered = self._filtered_groups()
        recoverable = sum(g.reclaimable for g in filtered)
        total_files = sum(len(g.files) for g in filtered)
        eta_minutes = max(1, int(math.ceil((len(filtered) * 1.3) / 60.0)))
        self._summary.value = f"{len(filtered):,} groups · {total_files:,} files · ~{eta_minutes} min to review"
        self._safe_update(self._summary)

    def _refresh_dashboard(self, filtered: List[DuplicateGroup]) -> None:
        total_bytes = sum(int(getattr(g, "reclaimable", 0) or 0) for g in filtered)
        total_files = sum(len(g.files) for g in filtered)
        eta_minutes = max(1, int(math.ceil((len(filtered) * 1.3) / 60.0)))
        self._hero_primary.value = fmt_size(total_bytes)
        self._hero_secondary.value = f"{len(filtered):,} duplicate groups · {total_files:,} files · ~{eta_minutes} min to review"
        recent = self._bridge.get_scan_history_table_rows(limit=1)
        self._last_scan.value = f"Last scan: {recent[0]['date']}" if recent else "Last scan: -"
        self._type_strip.controls = self._build_type_tiles(filtered, total_bytes)
        self._folder_col.controls = self._build_top_folders(filtered)
        self._group_col.controls = self._build_top_groups(filtered)
        self._age_col.controls = self._build_age_buckets(filtered)
        self._mult_col.controls = self._build_multiplicity(filtered)

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------
    def _on_delete_clicked(self, e) -> None:
        self._show_delete_dialog(DeletionPolicy.TRASH)

    def _on_permanent_delete_clicked(self, e) -> None:
        self._show_delete_dialog(DeletionPolicy.PERMANENT)

    def _show_delete_dialog(self, policy: DeletionPolicy) -> None:
        count = len(self._selected_paths)
        if count == 0:
            return
        policy_label = "permanently delete" if policy == DeletionPolicy.PERMANENT else "move to trash"
        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Confirm Deletion"),
            content=ft.Text(f"Are you sure you want to {policy_label} {count:,} files?\nThis will keep one copy of each duplicate."),
            actions=[
                ft.TextButton("Cancel", on_click=lambda e: self._bridge.dismiss_top_dialog()),
                ft.ElevatedButton(
                    policy_label.title(),
                    on_click=lambda e: self._execute_delete_and_close(dialog, policy),
                    style=ft.ButtonStyle(bgcolor=self._t.colors.danger, color=self._t.colors.bg),
                ),
            ],
        )
        self._bridge.show_modal_dialog(dialog)

    def _execute_delete_and_close(self, dialog, policy):
        self._bridge.dismiss_top_dialog()
        self._execute_delete(policy)

    def _execute_delete(self, policy: DeletionPolicy) -> None:
        from cerebro.v2.ui.flet_app.services.delete_service import DeleteService
        paths = list(self._selected_paths)
        if not paths:
            return
        service = DeleteService()
        progress_text = ft.Text("Preparing deletion...", size=self._t.typography.size_sm)
        progress_bar = ft.ProgressBar(value=0)
        progress_dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Deleting files"),
            content=ft.Column([progress_text, progress_bar], tight=True, spacing=10),
        )
        self._bridge.show_modal_dialog(progress_dialog)

        page = self._bridge.flet_page

        def _ui_progress(done: int, total: int, name: str) -> None:
            t = max(1, int(total or 1))
            progress_bar.value = min(1.0, done / t)
            progress_text.value = f"{done:,}/{t:,} processed · {name}"
            ResultsPage._safe_update(progress_bar)
            ResultsPage._safe_update(progress_text)

        def _ui_done(new_groups, deleted: int, failed: int, bytes_reclaimed: int, err: Exception | None) -> None:
            self._bridge.dismiss_top_dialog()
            if err is not None:
                self._bridge.show_snackbar(f"Deletion failed: {err}", error=True)
                return
            self._selected_paths.clear()
            self._groups = list(new_groups)
            self._bridge.coordinator.results_files_removed(paths)
            self._refresh()
            if deleted > 0:
                self._show_success_modal(deleted, bytes_reclaimed, policy)
            if failed > 0:
                self._bridge.show_snackbar(
                    f"{failed:,} files could not be deleted.",
                    error=True,
                )

        def _progress(done: int, total: int, name: str) -> None:
            if hasattr(page, "run_thread"):
                page.run_thread(_ui_progress, done, total, name)
            else:
                _ui_progress(done, total, name)

        def _done(new_groups, deleted: int, failed: int, bytes_reclaimed: int, err: Exception | None) -> None:
            if hasattr(page, "run_thread"):
                page.run_thread(_ui_done, new_groups, deleted, failed, bytes_reclaimed, err)
            else:
                _ui_done(new_groups, deleted, failed, bytes_reclaimed, err)

        service.delete_and_prune_async(
            paths=paths,
            groups=self._groups,
            policy=policy,
            progress_callback=_progress,
            done_callback=_done,
        )

    def _show_success_modal(self, deleted: int, bytes_reclaimed: int, policy: DeletionPolicy) -> None:
        t = self._t
        has_remaining = len(self._groups) > 0
        policy_label = "moved to Trash" if policy == DeletionPolicy.TRASH else "permanently deleted"

        def _done(e):
            self._bridge.dismiss_top_dialog()

        def _new_scan(e):
            self._bridge.dismiss_top_dialog()
            self._bridge.navigate("dashboard")

        def _undo(e):
            self._bridge.dismiss_top_dialog()
            self._undo_last_trash_delete()

        actions: list = [ft.TextButton("Done", on_click=_done)]
        if policy == DeletionPolicy.TRASH:
            actions.insert(0, ft.TextButton("Undo", on_click=_undo))
        if not has_remaining:
            actions.append(
                ft.FilledButton(
                    "Start New Scan",
                    on_click=_new_scan,
                    style=ft.ButtonStyle(
                        bgcolor="#00BFA5",
                        color="#0A0E14",
                        shape=ft.RoundedRectangleBorder(radius=8),
                    ),
                )
            )

        modal = ft.AlertDialog(
            modal=True,
            content=ft.Container(
                content=ft.Column(
                    [
                        ft.Container(
                            content=ft.Icon(ft.icons.Icons.CHECK_CIRCLE, size=64, color="#34D399"),
                            bgcolor=ft.Colors.with_opacity(0.12, "#34D399"),
                            border_radius=40,
                            padding=16,
                        ),
                        ft.Text(
                            "Space Recovered!",
                            size=t.typography.size_xl,
                            weight=ft.FontWeight.BOLD,
                            color=t.colors.fg,
                            text_align=ft.TextAlign.CENTER,
                        ),
                        ft.Text(
                            fmt_size(bytes_reclaimed),
                            size=t.typography.size_xxxl,
                            weight=ft.FontWeight.BOLD,
                            color="#34D399",
                            text_align=ft.TextAlign.CENTER,
                        ),
                        ft.Text(
                            f"{deleted:,} files {policy_label}",
                            size=t.typography.size_base,
                            color=t.colors.fg_muted,
                            text_align=ft.TextAlign.CENTER,
                        ),
                    ],
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=t.spacing.md,
                ),
                padding=t.spacing.xl,
                width=320,
            ),
            actions=actions,
            actions_alignment=ft.MainAxisAlignment.CENTER,
        )
        self._bridge.show_modal_dialog(modal)

    def _undo_last_trash_delete(self) -> None:
        from cerebro.v2.ui.flet_app.services.delete_service import DeleteService

        ok, restored = DeleteService.undo_last_trash_delete()
        if ok and restored > 0:
            self._bridge.show_snackbar(f"Restored {restored:,} file(s) from Trash.", success=True)
        elif restored > 0:
            self._bridge.show_snackbar(
                f"Partially restored {restored:,} file(s). Check missing paths.",
                info=True,
            )
        else:
            self._bridge.show_snackbar("Nothing to undo.", info=True)

    # ------------------------------------------------------------------
    # Filtering
    # ------------------------------------------------------------------
    def _on_filter_seg_change(self, e: ft.ControlEvent) -> None:
        sel = getattr(e.control, "selected", None) or {"all"}
        self._filter_key = next(iter(sel), "all")
        if self._filter_key not in self._view_mode_by_filter:
            self._view_mode_by_filter[self._filter_key] = "grid" if self._filter_key == "pictures" else "list"
        self._view_mode = self._view_mode_by_filter[self._filter_key]
        self._grid_btn.icon_color = "#22D3EE" if self._view_mode == "grid" else self._t.colors.fg_muted
        self._list_btn.icon_color = "#22D3EE" if self._view_mode == "list" else self._t.colors.fg_muted
        ResultsPage._safe_update(self._grid_btn)
        ResultsPage._safe_update(self._list_btn)
        self._refresh()

    def _on_min_group_filter_change(self, e: ft.ControlEvent) -> None:
        try:
            self._min_reclaimable_bytes = max(0, int(getattr(e.control, "value", "0") or 0))
        except (TypeError, ValueError):
            self._min_reclaimable_bytes = 0
        self._refresh()

    def _on_grouping_change(self, e: ft.ControlEvent) -> None:
        sel = getattr(e.control, "selected", None) or {"groups"}
        self._grouping_mode = next(iter(sel), "groups")
        self._folder_cross_toggle.visible = self._grouping_mode == "folders"
        ResultsPage._safe_update(self._folder_cross_toggle)
        if self._grouping_mode == "folders":
            self._view_mode = "list"
            self._view_mode_by_filter[self._filter_key] = "list"
            self._grid_btn.icon_color = self._t.colors.fg_muted
            self._list_btn.icon_color = "#22D3EE"
            ResultsPage._safe_update(self._grid_btn)
            ResultsPage._safe_update(self._list_btn)
        self._refresh()

    def _on_folder_cross_only_change(self, e: ft.ControlEvent) -> None:
        self._folder_cross_only = bool(getattr(e.control, "value", False))
        if self._grouping_mode == "folders":
            self._refresh()

    def _filtered_groups(self) -> List[DuplicateGroup]:
        groups = [
            g for g in self._groups
            if int(getattr(g, "reclaimable", 0) or 0) >= self._min_reclaimable_bytes
        ]
        if self._filter_key == "all":
            return groups
        exts = FILTER_EXTS.get(self._filter_key)
        if exts is None:
            return [g for g in groups if all(classify_file(getattr(f, "extension", "")) == "other" for f in g.files)]
        return [g for g in groups if any(getattr(f, "extension", "").lower() in exts for f in g.files)]

    def _count_cross_folder_groups(self, groups: List[DuplicateGroup]) -> int:
        count = 0
        for g in groups:
            folders = {str(Path(str(f.path)).parent) for f in g.files}
            if len(folders) > 1:
                count += 1
        return count

    def _build_type_tiles(self, groups: List[DuplicateGroup], total_bytes: int) -> List[ft.Control]:
        buckets: Dict[str, Dict[str, int]] = {k: {"bytes": 0, "files": 0} for k, _ in _FILTER_TABS}
        for g in groups:
            for f in g.files:
                kind = classify_file(getattr(f, "extension", ""))
                if kind not in buckets:
                    kind = "other"
                buckets[kind]["bytes"] += int(getattr(f, "size", 0) or 0)
                buckets[kind]["files"] += 1
        ranked = sorted(
            [k for k, _ in _FILTER_TABS if k != "all"],
            key=lambda k: buckets[k]["bytes"],
            reverse=True,
        )
        out: List[ft.Control] = []
        for key in ranked:
            label = next((v for k, v in _FILTER_TABS if k == key), key.title())
            b = buckets[key]["bytes"]
            pct = 0.0 if total_bytes <= 0 else min(1.0, b / total_bytes)
            out.append(
                ft.Container(
                    width=140,
                    padding=ft.padding.all(10),
                    border_radius=10,
                    bgcolor=ft.Colors.with_opacity(0.05, ft.Colors.WHITE),
                    border=ft.border.all(1, ft.Colors.with_opacity(0.14, ft.Colors.WHITE)),
                    content=ft.Column(
                        [
                            ft.Text(label, size=self._t.typography.size_sm, weight=ft.FontWeight.W_700, color=self._t.colors.fg),
                            ft.Text(fmt_size(b), size=self._t.typography.size_sm, color="#BFD5FF"),
                            ft.Text(f"{buckets[key]['files']:,} files", size=self._t.typography.size_xs, color=self._t.colors.fg_muted),
                            ft.ProgressBar(value=pct, color=_FILTER_ACCENT.get(key, "#93C5FD"), bgcolor=ft.Colors.with_opacity(0.12, ft.Colors.WHITE)),
                        ],
                        spacing=4,
                    ),
                )
            )
        return out

    def _build_top_folders(self, groups: List[DuplicateGroup]) -> List[ft.Control]:
        buckets: Dict[str, Dict[str, int]] = {}
        for g in groups:
            folder = str(Path(str(g.files[0].path)).parent) if g.files else "(unknown)"
            if folder not in buckets:
                buckets[folder] = {"bytes": 0, "groups": 0}
            buckets[folder]["bytes"] += int(getattr(g, "reclaimable", 0) or 0)
            buckets[folder]["groups"] += 1
        ranked = sorted(buckets.items(), key=lambda kv: kv[1]["bytes"], reverse=True)[:5]
        return [
            ft.Row(
                [
                    ft.Text(Path(folder).name or folder, expand=True, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                    ft.Text(f"{fmt_size(meta['bytes'])} · {meta['groups']} groups", color="#BFD5FF", size=self._t.typography.size_sm),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            )
            for folder, meta in ranked
        ] or [ft.Text("No data yet", color=self._t.colors.fg_muted)]

    def _build_top_groups(self, groups: List[DuplicateGroup]) -> List[ft.Control]:
        ranked = sorted(groups, key=lambda g: int(getattr(g, "reclaimable", 0) or 0), reverse=True)[:5]
        out: List[ft.Control] = []
        for g in ranked:
            sample = Path(str(g.files[0].path)).name if g.files else "Group"
            out.append(
                ft.Text(
                    f"{fmt_size(g.reclaimable)} · {len(g.files)} copies · {sample}",
                    size=self._t.typography.size_sm,
                    color="#BFD5FF",
                    max_lines=1,
                    overflow=ft.TextOverflow.ELLIPSIS,
                )
            )
        return out or [ft.Text("No data yet", color=self._t.colors.fg_muted)]

    def _build_age_buckets(self, groups: List[DuplicateGroup]) -> List[ft.Control]:
        now = datetime.datetime.now().timestamp()
        buckets = [
            ("< 1 week", 0, 7 * 86400),
            ("< 1 month", 7 * 86400, 30 * 86400),
            ("< 1 year", 30 * 86400, 365 * 86400),
            ("> 1 year", 365 * 86400, 10_000 * 86400),
        ]
        totals = {name: 0 for name, _, _ in buckets}
        for g in groups:
            for f in g.files:
                ts = float(getattr(f, "mtime", 0) or 0)
                if ts <= 0:
                    continue
                age = max(0, now - ts)
                for name, lo, hi in buckets:
                    if lo <= age < hi:
                        totals[name] += int(getattr(f, "size", 0) or 0)
                        break
        max_v = max(totals.values()) if totals else 0
        return [
            ft.Row(
                [
                    ft.Text(name, width=86, size=self._t.typography.size_sm),
                    ft.Text(fmt_size(v), width=80, size=self._t.typography.size_sm, color="#BFD5FF"),
                    ft.ProgressBar(value=(0 if max_v <= 0 else v / max_v), expand=True, color="#22D3EE"),
                ],
                spacing=8,
            )
            for name, v in totals.items()
        ]

    def _build_multiplicity(self, groups: List[DuplicateGroup]) -> List[ft.Control]:
        ranked = sorted(groups, key=lambda g: len(g.files), reverse=True)[:5]
        return [
            ft.Text(
                f"{len(g.files)} copies · {Path(str(g.files[0].path)).name if g.files else 'Group'}",
                size=self._t.typography.size_sm,
                color="#BFD5FF",
                max_lines=1,
                overflow=ft.TextOverflow.ELLIPSIS,
            )
            for g in ranked
        ] or [ft.Text("No data yet", color=self._t.colors.fg_muted)]

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------
    def _refresh(self) -> None:
        filtered = self._filtered_groups()
        t = self._t
        total_files = sum(len(g.files) for g in filtered)
        cross_count = self._count_cross_folder_groups(filtered)
        self._folder_cross_toggle.label = f"Cross-folder only ({cross_count:,})"
        ResultsPage._safe_update(self._folder_cross_toggle)
        self._update_summary_line()
        self._refresh_dashboard(filtered)
        self._update_selection_ui()
        self._refresh_filter_labels()
        sc = self._scroll_col.controls
        if self._loading:
            if self._empty in sc:
                sc.remove(self._empty)
            if self._group_list in sc:
                sc.remove(self._group_list)
            if self._loading_state not in sc:
                sc.append(self._loading_state)
            self._safe_update(self._scroll_col)
            return
        if self._loading_state in sc:
            sc.remove(self._loading_state)

        if not filtered:
            self._rendering_badge.visible = False
            if self._empty not in sc:
                sc.append(self._empty)
            if self._group_list in sc:
                sc.remove(self._group_list)
            if self._results_grid in sc:
                sc.remove(self._results_grid)
            self._safe_update(self._scroll_col)
            return

        if self._empty in sc:
            sc.remove(self._empty)

        if self._view_mode == "grid":
            if self._group_list in sc:
                sc.remove(self._group_list)
            if self._results_grid not in sc:
                sc.append(self._results_grid)
            self._thumb_slots.clear()
            self._tile_cache_grid.clear()
            n = len(filtered)
            if n <= _GRID_BUILD_ASYNC_THRESHOLD:
                self._results_grid.controls = [
                    self._build_group_grid_section(g, i) for i, g in enumerate(filtered)
                ]
                self._loading = False
                self._set_rendering(False)
                self._safe_update(self._scroll_col)
                page = self._bridge.flet_page
                if self._thumb_slots and hasattr(page, "run_task"):
                    page.run_task(self._load_grid_thumbnails_async, dict(self._thumb_slots))
                return

            self._list_build_generation += 1
            gen = self._list_build_generation
            self._set_rendering(True)
            head_n = min(_GRID_FIRST_SYNC_GROUPS, n)
            head = filtered[:head_n]
            tail = filtered[head_n:]
            self._results_grid.controls = [self._build_group_grid_section(g, i) for i, g in enumerate(head)]
            self._loading = False
            self._safe_update(self._scroll_col)
            try:
                self._results_grid.update()
            except Exception:
                pass
            page = self._bridge.flet_page
            if tail and hasattr(page, "run_task"):
                page.run_task(self._append_grid_sections_async, tail, head_n, gen)
            elif tail:
                self._results_grid.controls.extend(
                    [self._build_group_grid_section(g, head_n + i) for i, g in enumerate(tail)]
                )
                self._safe_update(self._scroll_col)
                self._set_rendering(False)
            if self._thumb_slots and hasattr(page, "run_task"):
                page.run_task(self._load_grid_thumbnails_async, dict(self._thumb_slots))
            return

        if self._results_grid in sc:
            sc.remove(self._results_grid)
        if self._group_list not in sc:
            sc.append(self._group_list)

        if self._grouping_mode == "folders":
            self._group_list.controls = self._build_folder_sections(filtered)
            self._loading = False
            self._set_rendering(False)
            self._safe_update(self._scroll_col)
            return

        n = len(filtered)
        if n <= _LIST_BUILD_ASYNC_THRESHOLD:
            filtered_ids = {g.group_id for g in filtered}
            self._group_list.controls = [self._build_or_get_group_card(g) for g in self._groups]
            self._apply_group_visibility(filtered_ids)
            self._loading = False
            self._set_rendering(False)
            self._safe_update(self._scroll_col)
            if n > 80:
                try:
                    self._group_list.update()
                except Exception:
                    pass
            return

        self._list_build_generation += 1
        gen = self._list_build_generation
        self._set_rendering(True)
        all_n = len(self._groups)
        filtered_ids = {g.group_id for g in filtered}
        head_n = min(_LIST_FIRST_SYNC_GROUPS, all_n)
        head = self._groups[:head_n]
        tail = self._groups[head_n:]
        self._group_list.controls = [self._build_or_get_group_card(g) for g in head]
        self._apply_group_visibility(filtered_ids)
        self._safe_update(self._scroll_col)
        try:
            self._group_list.update()
        except Exception:
            pass
        if tail:
            page = self._bridge.flet_page
            if hasattr(page, "run_task"):
                page.run_task(self._append_group_cards_async, tail, gen, filtered_ids)
            else:
                self._group_list.controls.extend([self._build_or_get_group_card(g) for g in tail])
                self._apply_group_visibility(filtered_ids)
                self._safe_update(self._scroll_col)
                try:
                    self._group_list.update()
                except Exception:
                    pass

    async def _append_group_cards_async(self, tail: List[DuplicateGroup], gen: int, filtered_ids: Set[int]) -> None:
        for i in range(0, len(tail), _LIST_ASYNC_BATCH):
            if gen != self._list_build_generation:
                self._set_rendering(False)
                return
            chunk = tail[i : i + _LIST_ASYNC_BATCH]
            self._group_list.controls.extend([self._build_or_get_group_card(g) for g in chunk])
            self._apply_group_visibility(filtered_ids)
            # F4: update only the list, not the full page, to avoid O(n²) layout cost
            try:
                self._group_list.update()
            except Exception:
                pass
            await asyncio.sleep(0)
        if gen == self._list_build_generation:
            self._set_rendering(False)
            self._loading = False
            self._safe_update(self._scroll_col)

    async def _append_grid_sections_async(self, tail: List[DuplicateGroup], start_idx: int, gen: int) -> None:
        for i in range(0, len(tail), _GRID_ASYNC_BATCH):
            if gen != self._list_build_generation:
                self._set_rendering(False)
                return
            chunk = tail[i : i + _GRID_ASYNC_BATCH]
            offset = start_idx + i
            self._results_grid.controls.extend(
                [self._build_group_grid_section(g, offset + j) for j, g in enumerate(chunk)]
            )
            # F4: update only the grid, not the full page
            try:
                self._results_grid.update()
            except Exception:
                pass
            await asyncio.sleep(0)
        if gen == self._list_build_generation:
            self._set_rendering(False)

    async def _finish_loading_async(self) -> None:
        await asyncio.sleep(0)
        self._loading = False
        self._refresh()

    def _build_skeleton_card(self) -> ft.Container:
        t = self._t
        bar = lambda w: ft.Container(
            width=w,
            height=10,
            bgcolor=ft.Colors.with_opacity(0.10, ft.Colors.WHITE),
            border_radius=4,
        )
        return ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Container(
                                width=30,
                                height=30,
                                bgcolor=ft.Colors.with_opacity(0.10, ft.Colors.WHITE),
                                border_radius=8,
                            ),
                            ft.Column([bar(220), bar(160)], spacing=8, expand=True),
                            bar(80),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    )
                ],
                spacing=t.spacing.xs,
            ),
            padding=t.spacing.md,
            **self._get_glass_style(0.04),
        )

    def _build_group_card(self, group: DuplicateGroup, extra_badge: str | None = None) -> ft.Container:
        t = self._t
        sample = group.files[0].path if group.files else ""
        sample_path = Path(str(sample))
        name = sample_path.name if sample else "Group"
        parent = str(sample_path.parent) if sample else ""
        parent_leaf = sample_path.parent.name if sample else ""
        machine_name = self._is_machine_generated_name(name)
        ext = sample_path.suffix if sample else ""
        icon_name, accent = self._file_type_icon(ext)

        # Build heavy duplicate rows lazily on first expand to avoid long filter/render stalls.
        file_checks = ft.Column([], spacing=2, visible=False)
        details_built = {"value": False}

        def _toggle_expand(e=None):
            if not details_built["value"]:
                file_checks.controls = [
                    ft.Container(
                        content=ft.Row(
                            [
                                ft.Text(
                                    str(Path(str(f.path)).name),
                                    size=t.typography.size_base,
                                    color=t.colors.fg,
                                    weight=ft.FontWeight.W_500,
                                    expand=True,
                                    max_lines=1,
                                    overflow=ft.TextOverflow.ELLIPSIS,
                                ),
                                ft.Text(
                                    fmt_size(f.size),
                                    size=t.typography.size_sm,
                                    color=t.colors.fg2,
                                    weight=ft.FontWeight.W_500,
                                ),
                            ],
                            spacing=t.spacing.sm,
                        ),
                        padding=ft.padding.only(left=t.spacing.xl, top=2, bottom=2),
                        border=ft.border.only(left=ft.BorderSide(2, ft.Colors.with_opacity(0.3, accent))),
                    )
                    for f in group.files
                ]
                details_built["value"] = True
            file_checks.visible = not file_checks.visible
            ResultsPage._safe_update(file_checks)
            expand_btn.text = "Collapse" if file_checks.visible else "Expand"
            ResultsPage._safe_update(expand_btn)
            self._safe_update(self._scroll_col)

        expand_btn = ft.TextButton(
            "Expand",
            on_click=_toggle_expand,
            style=ft.ButtonStyle(
                color=t.colors.fg2,
                text_style=ft.TextStyle(size=t.typography.size_sm, weight=ft.FontWeight.W_600),
            ),
        )

        card = ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Container(
                                content=ft.Icon(icon_name, size=18, color=accent),
                                bgcolor=ft.Colors.with_opacity(0.12, accent),
                                border_radius=8,
                                padding=8,
                            ),
                            ft.Column(
                                [
                                    ft.Text(
                                        f"Folder: {parent_leaf}" if machine_name and parent_leaf else name,
                                        weight=ft.FontWeight.W_700 if machine_name else ft.FontWeight.W_600,
                                        color="#E2F3FF" if machine_name else t.colors.fg,
                                        size=t.typography.size_md,
                                        no_wrap=True,
                                        overflow=ft.TextOverflow.ELLIPSIS,
                                    ),
                                    ft.Text(
                                        name if machine_name else parent,
                                        size=t.typography.size_sm,
                                        color=t.colors.fg_muted,
                                        no_wrap=True,
                                        overflow=ft.TextOverflow.ELLIPSIS,
                                        visible=bool(machine_name or parent),
                                    ),
                                    ft.Row(
                                        [
                                            ft.Text(
                                                f"{len(group.files)} files",
                                                size=t.typography.size_sm,
                                                color="#7DD3FC",
                                                weight=ft.FontWeight.W_500,
                                            ),
                                            ft.Text("·", size=t.typography.size_sm, color=t.colors.fg_muted),
                                            ft.Text(
                                                fmt_size(group.total_size),
                                                size=t.typography.size_sm,
                                                color="#A78BFA",
                                                weight=ft.FontWeight.W_500,
                                            ),
                                            ft.Text("·", size=t.typography.size_sm, color=t.colors.fg_muted),
                                            ft.Text(
                                                parent,
                                                size=t.typography.size_sm,
                                                color="#93C5FD",
                                                no_wrap=True,
                                                overflow=ft.TextOverflow.ELLIPSIS,
                                                expand=True,
                                            ),
                                            ft.Text(
                                                extra_badge or "",
                                                size=t.typography.size_sm,
                                                color="#FBBF24",
                                                visible=bool(extra_badge),
                                            ),
                                        ],
                                        spacing=4,
                                    ),
                                ],
                                spacing=3,
                                expand=True,
                            ),
                            ft.Text(fmt_size(group.reclaimable), weight=ft.FontWeight.BOLD, color="#22D3EE", size=t.typography.size_md),
                            expand_btn,
                            ft.IconButton(
                                icon=ft.icons.Icons.VISIBILITY,
                                tooltip="Open group in Review",
                                icon_color=t.colors.fg2,
                                on_click=lambda e, g=group: self._open_group(g),
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    file_checks,
                ],
                spacing=t.spacing.xs,
            ),
            padding=t.spacing.md,
            **self._get_glass_style(0.06),
            on_click=lambda e: _toggle_expand(),
            ink=True,
        )
        return card

    def _build_or_get_group_card(self, group: DuplicateGroup) -> ft.Container:
        gid = int(getattr(group, "group_id", 0))
        cached = self._all_group_cards.get(gid)
        if cached is not None:
            return cached
        card = self._build_group_card(group)
        self._all_group_cards[gid] = card
        return card

    def _apply_group_visibility(self, filtered_ids: Set[int]) -> None:
        for g in self._groups:
            gid = int(getattr(g, "group_id", 0))
            card = self._all_group_cards.get(gid)
            if card is not None:
                card.visible = gid in filtered_ids

    def _build_folder_sections(self, groups: List[DuplicateGroup]) -> List[ft.Control]:
        buckets: Dict[str, Dict[str, object]] = {}
        for g in groups:
            keeper = self._pick_keeper(g)
            if keeper is None:
                continue
            owner_folder = str(Path(str(keeper.path)).parent)
            unique_folders = {str(Path(str(f.path)).parent) for f in g.files}
            cross_count = max(0, len(unique_folders) - 1)
            if self._folder_cross_only and cross_count <= 0:
                continue
            if owner_folder not in buckets:
                buckets[owner_folder] = {"groups": [], "reclaimable": 0, "files": 0}
            bucket = buckets[owner_folder]
            cast_groups = bucket["groups"]
            if isinstance(cast_groups, list):
                cast_groups.append((g, cross_count))
            bucket["reclaimable"] = int(bucket["reclaimable"]) + int(getattr(g, "reclaimable", 0) or 0)
            bucket["files"] = int(bucket["files"]) + len(getattr(g, "files", []) or [])

        ordered = sorted(
            buckets.items(),
            key=lambda kv: int(kv[1]["reclaimable"]),  # type: ignore[index]
            reverse=True,
        )
        out: List[ft.Control] = []
        for folder, meta in ordered:
            folder_name = Path(folder).name or folder
            folder_groups = [x[0] for x in meta["groups"]]  # type: ignore[index]
            body = ft.Column(
                [
                    self._build_group_card(
                        g,
                        f"Also in {n} folder(s)" if n > 0 else None,
                    )
                    for g, n in meta["groups"]  # type: ignore[index]
                ],
                spacing=self._t.spacing.sm,
                visible=True,
            )
            expanded = {"value": True}
            icon_btn = ft.IconButton(
                icon=ft.icons.Icons.EXPAND_LESS,
                tooltip="Collapse/expand folder section",
            )

            def _toggle(_e=None, c=body, st=expanded, icon=icon_btn):
                st["value"] = not st["value"]
                c.visible = st["value"]
                icon.icon = ft.icons.Icons.EXPAND_LESS if st["value"] else ft.icons.Icons.EXPAND_MORE
                ResultsPage._safe_update(c)
                ResultsPage._safe_update(icon)

            icon_btn.on_click = _toggle
            header = ft.Row(
                [
                    ft.Text(f"📁 {folder_name}", size=self._t.typography.size_md, weight=ft.FontWeight.W_700, color="#E2F3FF"),
                    ft.Text(
                        f"{len(folder_groups):,} groups · {int(meta['files']):,} files · {fmt_size(int(meta['reclaimable']))} reclaimable",
                        size=self._t.typography.size_sm,
                        color=self._t.colors.fg_muted,
                    ),
                    ft.Container(expand=True),
                    ft.TextButton(
                        "Mark folder by rule",
                        on_click=lambda _e, gs=folder_groups: self._set_folder_selection(gs, True),
                        style=ft.ButtonStyle(color="#22D3EE"),
                    ),
                    ft.TextButton(
                        "Clear folder marks",
                        on_click=lambda _e, gs=folder_groups: self._set_folder_selection(gs, False),
                        style=ft.ButtonStyle(color=self._t.colors.fg_muted),
                    ),
                    icon_btn,
                ],
                spacing=self._t.spacing.sm,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            )
            out.append(
                ft.Container(
                    content=ft.Column([header, body], spacing=self._t.spacing.sm),
                    padding=self._t.spacing.md,
                    **self._get_glass_style(0.05),
                )
            )
        return out

    # ------------------------------------------------------------------
    # View toggle
    # ------------------------------------------------------------------
    def _open_inspector(self, f) -> None:
        from cerebro.v2.ui.flet_app.services.thumbnail_cache import get_thumbnail_cache, is_image_path
        self._inspector_file = f
        p = Path(str(getattr(f, "path", "")))
        self._inspector_name.value = p.name
        self._inspector_size.value = fmt_size(f.size)
        try:
            import datetime
            ts = float(getattr(f, "mtime", 0) or 0)
            self._inspector_date.value = datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d  %H:%M") if ts > 0 else ""
        except Exception:
            self._inspector_date.value = ""
        self._inspector_dims_generation += 1
        dims_gen = self._inspector_dims_generation
        self._inspector_dims.value = "Loading..."
        if is_image_path(p):
            page = self._bridge.flet_page
            if hasattr(page, "run_task"):
                page.run_task(self._load_inspector_dims_async, p, dims_gen)
            else:
                self._inspector_dims.value = ""
        else:
            self._inspector_dims.value = ""
        self._inspector_path.value = str(p.parent)
        self._inspector_thumb.content = ft.Icon(ft.icons.Icons.INSERT_DRIVE_FILE, size=48, color=ft.Colors.with_opacity(0.3, ft.Colors.WHITE))
        if is_image_path(p):
            try:
                b64 = get_thumbnail_cache().get_base64(p)
                if b64:
                    self._inspector_thumb.content = ft.Image(
                        src=f"data:image/jpeg;base64,{b64}",
                        width=220, height=160,
                        fit=ft.BoxFit.CONTAIN,
                        border_radius=8,
                    )
            except Exception:
                pass
        self._inspector_panel.visible = True
        self._inspector_wrapper.visible = True
        ResultsPage._safe_update(self._inspector_panel)
        ResultsPage._safe_update(self._inspector_wrapper)

    async def _load_inspector_dims_async(self, p: Path, gen: int) -> None:
        import asyncio as _aio
        loop = _aio.get_event_loop()

        def _read_dims() -> str:
            try:
                from PIL import Image as _Img
                with _Img.open(p) as img:
                    return f"{img.width} × {img.height}"
            except Exception:
                return ""

        dims = await loop.run_in_executor(None, _read_dims)
        if gen != self._inspector_dims_generation:
            return
        self._inspector_dims.value = dims
        ResultsPage._safe_update(self._inspector_dims)

    def _close_inspector(self) -> None:
        self._inspector_file = None
        self._inspector_panel.visible = False
        self._inspector_wrapper.visible = False
        ResultsPage._safe_update(self._inspector_panel)
        ResultsPage._safe_update(self._inspector_wrapper)

    def _toggle_view(self, mode: str) -> None:
        if self._grouping_mode == "folders" and mode == "grid":
            return
        if self._view_mode == mode:
            return
        self._view_mode = mode
        self._view_mode_by_filter[self._filter_key] = mode
        self._grid_btn.icon_color = "#22D3EE" if mode == "grid" else self._t.colors.fg_muted
        self._list_btn.icon_color = "#22D3EE" if mode == "list" else self._t.colors.fg_muted
        ResultsPage._safe_update(self._grid_btn)
        ResultsPage._safe_update(self._list_btn)
        self._refresh()

    def _build_file_tile(self, f) -> ft.Container:
        """Build a 120x120 thumbnail tile with checkbox and size overlay."""
        t = self._t
        key = str(getattr(f, "path", ""))
        p = Path(key)
        icon_name, accent = self._file_type_icon(p.suffix)
        modified = ""
        try:
            ts = float(getattr(f, "mtime", 0) or 0)
            if ts > 0:
                modified = datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
        except Exception:
            modified = ""

        size_bar = ft.Container(
            content=ft.Text(
                fmt_size(f.size),
                size=9,
                color="#FFFFFF",
                text_align=ft.TextAlign.CENTER,
            ),
            bgcolor=ft.Colors.with_opacity(0.72, "#0A0E14"),
            padding=ft.padding.symmetric(horizontal=4, vertical=3),
            alignment=ft.Alignment(0, 0),
        )

        placeholder = ft.Container(
            content=ft.Icon(
                icon_name,
                size=36,
                color=ft.Colors.with_opacity(0.9, accent),
            ),
            expand=True,
            alignment=ft.Alignment(0, 0),
            bgcolor=ft.Colors.with_opacity(0.06, ft.Colors.WHITE),
        )
        thumb_slot = ft.Container(
            content=placeholder,
            expand=True,
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
        )
        self._thumb_slots[key] = thumb_slot

        metadata_bar = ft.Container(
            content=ft.Column(
                [
                    ft.Text(p.name, size=9, color="#FFFFFF", max_lines=1, overflow=ft.TextOverflow.ELLIPSIS, text_align=ft.TextAlign.CENTER),
                    ft.Text(str(p.parent), size=8, color="#B9CAE6", max_lines=1, overflow=ft.TextOverflow.ELLIPSIS, text_align=ft.TextAlign.CENTER),
                    ft.Text(modified, size=8, color="#9FB0D0", max_lines=1, overflow=ft.TextOverflow.ELLIPSIS, text_align=ft.TextAlign.CENTER),
                ],
                spacing=1,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            bgcolor=ft.Colors.with_opacity(0.82, "#0A0E14"),
            padding=ft.padding.symmetric(horizontal=4, vertical=4),
        )
        stack = ft.Stack(
            [
                ft.Column([thumb_slot, metadata_bar], expand=True, spacing=0),
                ft.Container(content=size_bar, alignment=ft.Alignment(1, -1), padding=ft.padding.only(top=2, right=2)),
            ],
            expand=True,
        )
        tile = ft.Container(
            content=stack,
            width=170,
            height=160,
            border_radius=8,
            border=ft.border.all(1, ft.Colors.with_opacity(0.15, ft.Colors.WHITE)),
            bgcolor=ft.Colors.with_opacity(0.06, ft.Colors.WHITE),
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
            tooltip=str(p),
            ink=True,
            on_click=lambda e, _f=f: self._open_inspector(_f),
        )
        self._tile_cache_grid[key] = tile
        return tile

    def _build_group_grid_section(self, group, idx: int) -> ft.Container:
        """Build a group card with thumbnail tiles for grid view."""
        t = self._t
        tiles = [self._build_file_tile(f) for f in group.files]
        header = ft.Row(
            [
                ft.Container(
                    content=ft.Text(
                        f"Group {idx + 1}",
                        size=t.typography.size_sm,
                        weight=ft.FontWeight.W_700,
                        color=t.colors.fg,
                    ),
                    bgcolor=ft.Colors.with_opacity(0.08, ft.Colors.WHITE),
                    border_radius=4,
                    padding=ft.padding.symmetric(horizontal=8, vertical=2),
                ),
                ft.Text(
                    f"{len(group.files)} files · {fmt_size(group.reclaimable)} reclaimable",
                    size=t.typography.size_sm,
                    color=t.colors.fg_muted,
                ),
                ft.TextButton(
                    "Select Group",
                    on_click=lambda _e, g=group: self._set_group_selection(g, True),
                    style=ft.ButtonStyle(color="#22D3EE"),
                ),
            ],
            spacing=t.spacing.sm,
        )
        return ft.Container(
            content=ft.Column(
                [header, ft.Row(tiles, spacing=t.spacing.sm, wrap=True)],
                spacing=t.spacing.sm,
            ),
            padding=t.spacing.md,
            **self._get_glass_style(0.05),
        )

    async def _load_grid_thumbnails_async(self, slots: Dict[str, ft.Container]) -> None:
        import asyncio as _aio

        pending: list[tuple[ft.Container, str]] = []

        async def _on_ready(path: Path, b64: str | None) -> None:
            if not b64:
                return
            slot = slots.get(str(path))
            if slot is None:
                return
            pending.append((slot, b64))
            if len(pending) >= 20:
                for thumb_slot, thumb_b64 in pending:
                    thumb_slot.content = ft.Image(
                        src=f"data:image/jpeg;base64,{thumb_b64}",
                        width=120,
                        height=120,
                        fit=ft.BoxFit.COVER,
                        border_radius=6,
                    )
                pending.clear()
                ResultsPage._safe_update(self._results_grid)
                await _aio.sleep(0)

        paths = [Path(k) for k in slots.keys()]
        await get_thumbnail_cache().load_batch_async(paths, _on_ready)
        if pending:
            for thumb_slot, thumb_b64 in pending:
                thumb_slot.content = ft.Image(
                    src=f"data:image/jpeg;base64,{thumb_b64}",
                    width=120,
                    height=120,
                    fit=ft.BoxFit.COVER,
                    border_radius=6,
                )
            ResultsPage._safe_update(self._results_grid)

    def _recompute_filter_counts(self) -> None:
        counts: Dict[str, int] = {k: 0 for k, _ in _FILTER_TABS}
        group_counts: Dict[str, int] = {k: 0 for k, _ in _FILTER_TABS}
        sizes: Dict[str, int] = {k: 0 for k, _ in _FILTER_TABS}
        # F9: count only what _filtered_groups() actually displays (respects min reclaimable)
        for g in self._filtered_groups():
            files = list(g.files)
            counts["all"] += len(files)
            group_counts["all"] += 1
            seen_group_kinds: set[str] = set()
            for f in files:
                key = classify_file(getattr(f, "extension", ""))
                bucket = key if key in counts else "other"
                counts[bucket] += 1
                sizes["all"] += f.size
                sizes[bucket] += f.size
                seen_group_kinds.add(key if key in group_counts else "other")
            for kind in seen_group_kinds:
                group_counts[kind] += 1
        self._filter_counts = counts
        self._filter_sizes = sizes
        self._filter_group_counts = group_counts

    def _refresh_filter_labels(self) -> None:
        selected = set(self._filter_seg.selected or [])
        for seg in self._filter_seg.segments:
            key = seg.value
            base = next((label for k, label in _FILTER_TABS if k == key), key.title())
            files_n = self._filter_counts.get(key, 0)
            size_n = self._filter_sizes.get(key, 0)
            col = seg.label
            if isinstance(col, ft.Column) and len(col.controls) >= 3:
                is_active = key in selected
                accent = _FILTER_ACCENT.get(key, "#C7D2FE")
                col.controls[0].value = base
                col.controls[0].color = "#FFFFFF" if is_active else "#DDE8FF"
                col.controls[0].weight = ft.FontWeight.W_700 if is_active else ft.FontWeight.W_600
                col.controls[1].value = f"{files_n:,} files"
                if files_n == 0:
                    col.controls[1].color = "#6C7C98"
                else:
                    col.controls[1].color = accent if is_active else ft.Colors.with_opacity(0.72, accent)
                col.controls[1].weight = ft.FontWeight.W_700 if is_active else ft.FontWeight.W_600
                col.controls[2].value = fmt_size(size_n)
                col.controls[2].color = "#7D8EAB" if files_n == 0 else ("#B7C6E6" if is_active else "#9FB0D0")

    def _open_group(self, group: DuplicateGroup) -> None:
        self._bridge.coordinator.review_open_group(group.group_id, self._groups)
        self._bridge.navigate("review")

    def apply_theme(self, mode: str) -> None:
        """Updates theme properties without destroying UI controls."""
        self._glass_cache = {}
        self._t = theme_for_mode(mode)

        # Update colors on static elements
        self._summary.color = self._t.colors.fg2

        # Update container glass styles (parent exists only when this page is mounted)
        hdr_parent = getattr(self._header, "parent", None)
        if hdr_parent is not None:
            hdr_parent.bgcolor = self._get_glass_style(0.04).get("bgcolor")
            hdr_parent.border = self._get_glass_style(0.04).get("border")
        filt_parent = getattr(self._filter_seg, "parent", None)
        if filt_parent is not None:
            filt_parent.bgcolor = self._get_glass_style(0.03).get("bgcolor")
            filt_parent.border = self._get_glass_style(0.03).get("border")

        self._empty.bgcolor = self._get_glass_style(0.04).get("bgcolor")
        self._empty.border = self._get_glass_style(0.04).get("border")

        self._safe_update(self)