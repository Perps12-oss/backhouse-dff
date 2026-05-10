"""Review page — visual grid + side-by-side compare for duplicate groups with glass morphism."""

from __future__ import annotations

import asyncio
import datetime
import logging
import subprocess
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional

import flet as ft

from cerebro.core.deletion import DeletionPolicy
from cerebro.engines.base_engine import DuplicateFile, DuplicateGroup
from cerebro.v2.state.actions import FileSelectionChanged
from cerebro.v2.ui.flet_app.services.delete_service import DeleteService
from cerebro.v2.ui.flet_app.services.thumbnail_cache import get_thumbnail_cache, is_image_path
from cerebro.v2.ui.flet_app.pages.review._types import RC
from cerebro.v2.ui.flet_app.pages.review.deletion_dialog import build_confirm_dialog
from cerebro.v2.ui.flet_app.pages.review.filter_bar import FilterBar, _FILTER_TABS
from cerebro.v2.ui.flet_app.pages.review.group_card import (
    build_group_card,
    group_duplicate_summary,
    group_path_hint,
)
from cerebro.v2.ui.flet_app.pages.review.smart_rules import RULE_LABELS, normalized_rule, paths_to_delete
from cerebro.v2.ui.flet_app.pages.review.stats_header import StatsHeader
from cerebro.v2.ui.flet_app.pill_button_styles import (
    pill_filled_accent,
    pill_filled_danger,
    pill_outlined_button_style,
    pill_text_button_style,
    pill_text_button_selected,
)
from cerebro.v2.ui.flet_app.theme import (
    FILTER_EXTS, EXT_ALL_KNOWN, fmt_size, theme_for_mode,
)

if TYPE_CHECKING:
    from cerebro.v2.ui.flet_app.services.state_bridge import StateBridge

_log = logging.getLogger(__name__)

_GRID_BUILD_ASYNC_THRESHOLD = 220
_GRID_FIRST_SYNC_FILES = 20   # F5: 20 tiles sync, rest async
_GRID_ASYNC_BATCH = 30
_UI_SLOW_MS = 80.0

def _file_mtime_ts(f: DuplicateFile) -> float:
    for attr in ("mtime", "modified"):
        v = getattr(f, attr, None)
        if v is None:
            continue
        try:
            return float(v)
        except (TypeError, ValueError):
            continue
    return 0.0


class ReviewPage(ft.Column):
    """Grid and compare view for visual triage of duplicate groups."""

    def __init__(self, bridge: "StateBridge"):
        super().__init__(expand=True, scroll=ft.ScrollMode.AUTO)
        self._bridge = bridge
        self._t = theme_for_mode("dark")
        self._groups: List[DuplicateGroup] = []
        self._group_index: Dict[int, int] = {}
        self._group_files: Dict[int, List[DuplicateFile]] = {}
        self._filter_key = "all"
        self._mode = "empty"  # "empty" | "loading" | "groups" | "grid" | "compare"
        self._compare_gid: Optional[int] = None
        self._compare_a: Optional[DuplicateFile] = None
        self._compare_b: Optional[DuplicateFile] = None
        self._marked_paths: set[str] = set()
        self._marked_bytes: int = 0
        self._reduce_motion: bool = self._bridge.is_reduce_motion_enabled()
        self._delete_service = DeleteService()
        self._reviewed_group_ids: set[int] = set()
        self._smart_rule = "keep_largest"
        self._grid_extent = 160  # tile max_extent: S=120 M=160 L=210
        self._loading = False
        self._tile_cache: Dict[str, ft.Container] = {}
        self._thumb_slots: Dict[str, ft.Container] = {}
        self._files_by_filter: Dict[str, List[DuplicateFile]] = {k: [] for k, _ in _FILTER_TABS}
        self._glass_cache: dict = {}
        self._filter_counts: Dict[str, int] = {k: 0 for k, _ in _FILTER_TABS}
        self._filter_sizes: Dict[str, int] = {k: 0 for k, _ in _FILTER_TABS}
        self._filter_group_counts: Dict[str, int] = {k: 0 for k, _ in _FILTER_TABS}
        self._grid_build_generation = 0
        self._pending_deferred_render: bool = False
        self._cmp_smart_rule: str = "keep_largest"
        self._compare_render_generation = 0
        self._compare_thumb_slots: Dict[str, ft.Container] = {}
        self._compare_dims_labels: Dict[str, ft.Text] = {}
        self._group_list_items: Dict[int, ft.Container] = {}
        self._group_list_order: List[int] = []
        self._active_group_row_id: Optional[int] = None
        self._compare_nav_in_flight = False
        self._thumb_load_generation = 0

        # UI References
        self._stats_header: StatsHeader
        self._smart_apply_all_btn: ft.FilledButton
        self._smart_seg: ft.SegmentedButton
        self._smart_row: ft.Row
        self._zoom_row: ft.Row
        self._cmp_title: ft.Text
        self._cmp_smart_seg: ft.SegmentedButton
        self._delete_btn: ft.ElevatedButton
        self._keep_btn: ft.OutlinedButton
        self._cmp_bar: ft.Container
        self._filter_bar: FilterBar
        self._content: ft.Column
        self._empty_state: ft.Container
        self._loading_state: ft.Container
        self._grid: ft.GridView
        self._rendering_badge: ft.Container
        self._compare_panel_a: ft.Container
        self._compare_panel_b: ft.Container
        self._group_list_panel: ft.ListView
        self._group_list_scroll_host: ft.Container
        self._compare_columns: ft.Row
        self._compare_main_row: ft.Row
        self._progress_lbl: ft.Text
        self._progress_bar: ft.ProgressBar
        self._marked_bar: ft.Container
        self._marked_lbl: ft.Text
        self._compare_view: ft.Column
        self._groups_overview: ft.ListView
        self._view_toggle_row: ft.Row
        self._group_sort_dd: ft.Dropdown
        self._group_sort_key: str
        self._group_sort_row: ft.Row
        self._btn_back: ft.TextButton
        self._btn_view_groups: ft.TextButton
        self._btn_view_tiles: ft.TextButton
        self._btn_cmp_grid: ft.TextButton
        self._btn_cmp_prev: ft.TextButton
        self._btn_cmp_next: ft.TextButton
        self._zoom_btn_s: ft.TextButton
        self._zoom_btn_m: ft.TextButton
        self._zoom_btn_l: ft.TextButton
        self._empty_go_home_btn: ft.FilledButton
        self._marked_delete_b_btn: ft.FilledButton
        self._marked_delete_marked_btn: ft.FilledButton
        self._marked_safety_lbl: ft.Text
        self._cmp_apply_rule_btn: ft.FilledButton

        self._build_ui()

    # ------------------------------------------------------------------
    # Glass & Style Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _hwrap_strip(strip: ft.Control) -> ft.Row:
        """Center a control horizontally within the full page width."""
        return ft.Row(
            [
                ft.Container(expand=True),
                strip,
                ft.Container(expand=True),
            ],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

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

    def _on_zoom_size_click(self, extent: int, _e: ft.ControlEvent | None = None) -> None:
        self._grid_extent = extent
        self._grid.max_extent = extent
        self._sync_zoom_pill_styles()
        ReviewPage._safe_update(self._grid)

    def _sync_zoom_pill_styles(self) -> None:
        t = self._t
        for extent, btn in ((120, self._zoom_btn_s), (160, self._zoom_btn_m), (210, self._zoom_btn_l)):
            btn.style = pill_text_button_selected(t) if self._grid_extent == extent else pill_text_button_style(t, variant="muted")
            ReviewPage._safe_update(btn)

    def _build_zoom_row(self) -> ft.Row:
        """Three-level zoom control for the grid density (nav-matched pill toggles)."""
        t = self._t
        self._zoom_btn_s = ft.TextButton(
            "S",
            on_click=lambda e: self._on_zoom_size_click(120, e),
            style=pill_text_button_selected(t) if self._grid_extent == 120 else pill_text_button_style(t, variant="muted"),
        )
        self._zoom_btn_m = ft.TextButton(
            "M",
            on_click=lambda e: self._on_zoom_size_click(160, e),
            style=pill_text_button_selected(t) if self._grid_extent == 160 else pill_text_button_style(t, variant="muted"),
        )
        self._zoom_btn_l = ft.TextButton(
            "L",
            on_click=lambda e: self._on_zoom_size_click(210, e),
            style=pill_text_button_selected(t) if self._grid_extent == 210 else pill_text_button_style(t, variant="muted"),
        )
        return ft.Row(
            [
                ft.Text("Size:", size=9, color=self._t.colors.fg_muted),
                self._zoom_btn_s,
                self._zoom_btn_m,
                self._zoom_btn_l,
            ],
            spacing=4,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    def _sync_view_toggle_pills(self) -> None:
        t = self._t
        if self._mode == "groups":
            self._btn_view_groups.style = pill_text_button_selected(t)
            self._btn_view_tiles.style = pill_text_button_style(t, variant="muted")
        elif self._mode == "grid":
            self._btn_view_groups.style = pill_text_button_style(t, variant="muted")
            self._btn_view_tiles.style = pill_text_button_selected(t)
        else:
            self._btn_view_groups.style = pill_text_button_style(t, variant="primary")
            self._btn_view_tiles.style = pill_text_button_style(t, variant="muted")
        for b in (self._btn_view_groups, self._btn_view_tiles):
            ReviewPage._safe_update(b)

    def _apply_pill_chrome(self) -> None:
        """Reapply nav-matched pill styles (call after theme change or mode switch)."""
        t = self._t
        self._btn_back.style = pill_text_button_style(t, variant="primary")
        self._smart_apply_all_btn.style = pill_filled_accent(
            t,
            padding=ft.padding.symmetric(horizontal=16, vertical=10),
            text_size=12,
            weight=ft.FontWeight.W_700,
        )
        self._delete_btn.style = pill_outlined_button_style(t, danger=True)
        self._keep_btn.style = pill_outlined_button_style(t, success=True)
        self._btn_cmp_grid.style = pill_text_button_style(t)
        self._btn_cmp_prev.style = pill_text_button_style(t)
        self._btn_cmp_next.style = pill_text_button_style(t, variant="primary")
        self._empty_go_home_btn.style = pill_filled_accent(t, text_size=12, weight=ft.FontWeight.W_700)
        self._cmp_apply_rule_btn.style = pill_filled_accent(
            t,
            padding=ft.padding.symmetric(horizontal=12, vertical=8),
            text_size=11,
            weight=ft.FontWeight.W_600,
        )
        self._marked_delete_b_btn.style = pill_filled_danger(t)
        self._marked_delete_marked_btn.style = pill_outlined_button_style(t, danger=True)
        self._sync_view_toggle_pills()
        self._sync_zoom_pill_styles()
        for b in (
            self._btn_back,
            self._smart_apply_all_btn,
            self._delete_btn,
            self._keep_btn,
            self._cmp_apply_rule_btn,
            self._btn_cmp_grid,
            self._btn_cmp_prev,
            self._btn_cmp_next,
            self._empty_go_home_btn,
            self._marked_delete_b_btn,
            self._marked_delete_marked_btn,
        ):
            ReviewPage._safe_update(b)

    # ------------------------------------------------------------------
    # Build (Runs Once)
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        t = self._t
        self._btn_back = ft.TextButton(
            "← Back",
            on_click=self._go_back,
            style=pill_text_button_style(t, variant="primary"),
            tooltip="Group list when reviewing groups; returns here from Compare or Grid.",
        )
        # Stats header
        self._stats_header = StatsHeader(self._bridge, t, back_btn=self._btn_back)

        # Smart select for grid mode
        self._smart_seg = ft.SegmentedButton(
            selected=["keep_largest"],
            allow_multiple_selection=False,
            on_change=self._on_smart_seg_change,
            segments=[
                ft.Segment(value=val, label=ft.Text(label, size=12, weight=ft.FontWeight.W_600))
                for val, label in RULE_LABELS
            ],
        )
        self._zoom_row = self._build_zoom_row()
        self._smart_apply_all_btn = ft.FilledButton(
            "Apply Rule to Visible",
            icon=ft.icons.Icons.AUTO_FIX_HIGH,
            on_click=self._apply_smart_select_review,
            style=pill_filled_accent(
                t,
                padding=ft.padding.symmetric(horizontal=16, vertical=10),
                text_size=12,
                weight=ft.FontWeight.W_700,
            ),
        )
        self._smart_row = ft.Row(
            [self._smart_seg, self._zoom_row, self._smart_apply_all_btn],
            spacing=t.spacing.sm,
            visible=False,
            wrap=True,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        # Compare navigation bar
        self._cmp_title = ft.Text("", size=t.typography.size_sm, color=t.colors.fg, weight=ft.FontWeight.W_600)
        self._cmp_smart_seg = ft.SegmentedButton(
            selected=["keep_largest"],
            allow_multiple_selection=False,
            on_change=self._on_cmp_smart_seg_change,
            segments=[
                ft.Segment(value=val, label=ft.Text(label, size=12, weight=ft.FontWeight.W_600))
                for val, label in RULE_LABELS
            ],
        )
        self._delete_btn = ft.OutlinedButton(
            "Delete side B",
            icon=ft.icons.Icons.DELETE_OUTLINE,
            on_click=lambda e: self._delete_compare_side("b"),
            style=pill_outlined_button_style(t, danger=True),
            tooltip="After confirmation, removes the right-hand file (side B).",
        )
        self._keep_btn = ft.OutlinedButton(
            "Keep side A",
            icon=ft.icons.Icons.CHECK,
            on_click=lambda e: self._delete_compare_side("a"),
            style=pill_outlined_button_style(t, success=True),
            tooltip="After confirmation, removes the left-hand file (side A).",
        )
        self._cmp_apply_rule_btn = ft.FilledButton(
            "Mark by rule",
            icon=ft.icons.Icons.FLAG,
            on_click=self._on_cmp_apply_rule_click,
            style=pill_filled_accent(
                t,
                padding=ft.padding.symmetric(horizontal=12, vertical=8),
                text_size=11,
                weight=ft.FontWeight.W_600,
            ),
            tooltip="Uses the selected smart rule to mark extras in this group for deletion (checkboxes).",
        )
        self._btn_cmp_grid = ft.TextButton("← Grid", on_click=self._to_grid, style=pill_text_button_style(t))
        self._btn_cmp_prev = ft.TextButton("← Prev", on_click=self._prev_group, style=pill_text_button_style(t))
        self._btn_cmp_next = ft.TextButton(
            "Next →",
            on_click=self._next_group,
            style=pill_text_button_style(t, variant="primary"),
        )
        self._cmp_bar = ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            self._btn_cmp_grid,
                            self._btn_cmp_prev,
                            self._btn_cmp_next,
                            self._cmp_title,
                        ],
                        wrap=True,
                        spacing=t.spacing.xs,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Row(
                        [
                            self._cmp_smart_seg,
                            self._cmp_apply_rule_btn,
                            self._keep_btn,
                            self._delete_btn,
                        ],
                        wrap=True,
                        spacing=t.spacing.sm,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Text(
                        "Smart rule only chooses marks in this group. Keep side A / Delete side B remove one pane at a time (confirmed).",
                        size=t.typography.size_xs,
                        color=t.colors.fg_muted,
                        italic=True,
                    ),
                ],
                spacing=t.spacing.xs,
            ),
            visible=False,
            padding=t.spacing.sm,
            **self._get_glass_style(0.04),
        )

        self._filter_bar = FilterBar(t, on_change=self._on_filter_changed)

        # Content area
        self._content = ft.Column(expand=True)

        self._empty_go_home_btn = ft.FilledButton(
            "Go Home",
            icon=ft.icons.Icons.LIST_ALT,
            on_click=lambda e: self._bridge.navigate("dashboard"),
            style=pill_filled_accent(t, text_size=12, weight=ft.FontWeight.W_700),
        )
        # Empty state
        self._empty_state = ft.Container(
            content=ft.Column(
                [
                    ft.Container(
                        content=ft.Icon(ft.icons.Icons.GRID_VIEW, size=44, color=RC.side_a),
                        bgcolor=ft.Colors.with_opacity(0.08, RC.side_a),
                        border_radius=16,
                        padding=20,
                    ),
                    ft.Text("Nothing to review yet", size=t.typography.size_lg, weight=ft.FontWeight.W_600, color=t.colors.fg),
                    ft.Text(
                        "Run a scan first, then come here to visually triage duplicates.",
                        size=t.typography.size_base,
                        color=t.colors.fg_muted,
                        text_align=ft.TextAlign.CENTER,
                    ),
                    self._empty_go_home_btn,
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
                [
                    ft.ProgressRing(width=28, height=28, stroke_width=3, color=RC.side_a),
                    ft.Text("Loading review content...", color=t.colors.fg_muted, size=t.typography.size_sm),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=t.spacing.md,
            ),
            expand=True,
            alignment=ft.Alignment(0, 0),
            **self._get_glass_style(0.04),
        )

        # Grid view
        self._grid = ft.GridView(
            expand=True,
            runs_count=5,
            max_extent=self._grid_extent,
            child_aspect_ratio=1.0,
            spacing=t.spacing.sm,
            run_spacing=t.spacing.sm,
            padding=t.spacing.lg,
        )
        self._rendering_badge = ft.Container(
            alignment=ft.Alignment(-1, -1),
            margin=ft.margin.only(top=t.spacing.sm, right=t.spacing.md),
            visible=False,
            content=ft.Container(
                content=ft.Row(
                    [
                        ft.ProgressRing(width=14, height=14, stroke_width=2, color=RC.side_a),
                        ft.Text("View ready - filling items...", size=t.typography.size_xs, color="#9FDDF7"),
                    ],
                    spacing=6,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                bgcolor=ft.Colors.with_opacity(0.82, "#09111D"),
                border=ft.border.all(1, ft.Colors.with_opacity(0.25, RC.side_a)),
                border_radius=999,
                padding=ft.padding.symmetric(horizontal=10, vertical=6),
            ),
        )

        # Compare view (left list + right multi-copy viewer)
        # The group list must live in a height-bounded area so it scrolls internally; otherwise the
        # Row grows to thousands of px and default cross-axis CENTER places A/B mid-scroll (~"group 237").
        self._group_list_panel = ft.ListView(
            expand=True,
            spacing=6,
            padding=ft.padding.all(8),
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
        )
        self._group_list_scroll_host = ft.Container(
            content=self._group_list_panel,
            expand=True,
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
        )
        left_panel = ft.Container(
            width=320,
            padding=t.spacing.sm,
            content=ft.Column(
                [
                    ft.Text("Jump to group", size=t.typography.size_md, weight=ft.FontWeight.W_700),
                    self._group_list_scroll_host,
                ],
                spacing=t.spacing.xs,
                expand=True,
            ),
            **self._get_glass_style(0.04),
        )
        self._compare_panel_a = ft.Container(expand=True, padding=t.spacing.md, **self._get_glass_style(0.04))
        self._compare_panel_b = ft.Container(expand=True, padding=t.spacing.md, **self._get_glass_style(0.04))
        self._compare_columns = ft.Row(scroll=ft.ScrollMode.AUTO, spacing=t.spacing.sm)
        right_view = ft.Container(
            content=ft.Row(
                [
                    self._compare_panel_a,
                    ft.Container(
                        content=ft.VerticalDivider(width=1, color=t.colors.border3, thickness=2),
                        padding=ft.padding.symmetric(horizontal=t.spacing.sm),
                    ),
                    self._compare_panel_b,
                ],
                expand=True,
                spacing=0,
            ),
            expand=True,
        )
        self._progress_bar = ft.ProgressBar(
            value=0,
            color=t.colors.accent,
            bgcolor=ft.Colors.with_opacity(0.14, t.colors.border),
        )
        self._progress_lbl = ft.Text("", size=t.typography.size_sm, color=t.colors.fg2)
        self._marked_lbl = ft.Text("", size=t.typography.size_sm, color="#FCA5A5")
        self._marked_delete_b_btn = ft.FilledButton(
            "Delete side B",
            on_click=lambda _e: self._delete_compare_side("b"),
            style=pill_filled_danger(t),
        )
        self._marked_delete_marked_btn = ft.OutlinedButton(
            "Delete marked files",
            on_click=self._delete_marked_files,
            style=pill_outlined_button_style(t, danger=True),
            tooltip="Deletes every file you marked for removal (separate from side B).",
        )
        self._marked_safety_lbl = ft.Text(
            "Deletion always asks for confirmation. Prefer Move to Trash / Recycle Bin when offered.",
            size=t.typography.size_xs,
            color=t.colors.fg_muted,
        )
        self._marked_bar = ft.Container(
            visible=False,
            padding=ft.padding.symmetric(horizontal=t.spacing.md, vertical=t.spacing.sm),
            bgcolor=ft.Colors.with_opacity(0.95, "#1A0C0C"),
            border=ft.border.only(top=ft.BorderSide(1, RC.danger)),
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Container(content=self._marked_lbl, expand=True),
                            ft.Row(
                                [self._marked_delete_b_btn, self._marked_delete_marked_btn],
                                spacing=t.spacing.md,
                                tight=True,
                            ),
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.START,
                        spacing=t.spacing.sm,
                    ),
                    self._marked_safety_lbl,
                ],
                spacing=t.spacing.xs,
                tight=True,
            ),
        )
        self._compare_main_row = ft.Row(
            [left_panel, right_view],
            expand=True,
            vertical_alignment=ft.CrossAxisAlignment.START,
            spacing=t.spacing.sm,
        )
        self._compare_view = ft.Column(
            [
                ft.Container(content=self._compare_main_row, expand=True),
                ft.Container(content=ft.Column([self._progress_bar, self._progress_lbl], spacing=6), padding=ft.padding.symmetric(horizontal=t.spacing.sm)),
                self._marked_bar,
            ],
            expand=True,
            visible=False,
        )

        self._groups_overview = ft.ListView(
            spacing=8,
            padding=ft.padding.all(16),
        )

        self._btn_view_groups = ft.TextButton(
            "Groups",
            on_click=lambda e: self._enter_mode("groups"),
            style=pill_text_button_style(t, variant="primary"),
        )
        self._btn_view_tiles = ft.TextButton(
            "Tiles",
            on_click=lambda e: self._enter_mode("grid"),
            style=pill_text_button_style(t, variant="muted"),
        )
        self._view_toggle_row = ft.Row(
            [self._btn_view_groups, self._btn_view_tiles],
            spacing=t.spacing.sm,
            visible=False,
        )
        self._group_sort_key = "reclaimable_desc"
        self._group_sort_dd = ft.Dropdown(
            width=240,
            value=self._group_sort_key,
            options=[
                ft.dropdown.Option("reclaimable_desc", "Highest reclaimable"),
                ft.dropdown.Option("files_desc", "Most copies"),
                ft.dropdown.Option("path_asc", "Folder A-Z"),
            ],
            on_select=self._on_group_sort_changed,
            text_size=12,
            dense=True,
            content_padding=ft.padding.symmetric(horizontal=10, vertical=8),
        )
        self._group_sort_row = ft.Row(
            [
                ft.Text("Sort groups:", size=t.typography.size_sm, color=t.colors.fg_muted, weight=ft.FontWeight.W_600),
                self._group_sort_dd,
            ],
            spacing=t.spacing.sm,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            visible=False,
        )

        _strip_pad = ft.padding.symmetric(horizontal=t.spacing.lg)
        self.controls = [
            self._stats_header,
            ft.Container(
                content=ReviewPage._hwrap_strip(self._view_toggle_row),
                padding=_strip_pad,
            ),
            ft.Container(
                content=ReviewPage._hwrap_strip(self._group_sort_row),
                padding=ft.padding.only(left=t.spacing.lg, right=t.spacing.lg, bottom=t.spacing.xs),
            ),
            ft.Container(
                content=ReviewPage._hwrap_strip(self._smart_row),
                padding=_strip_pad,
            ),
            ft.Container(
                content=ReviewPage._hwrap_strip(self._cmp_bar),
                padding=ft.padding.symmetric(horizontal=t.spacing.lg),
            ),
            self._filter_bar,
            self._content,
            self._rendering_badge,
        ]
        self._apply_pill_chrome()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def load_group(self, groups: List[DuplicateGroup], group_id: int, mode: Optional[str] = None) -> None:
        self._groups = list(groups)
        self._group_files = {g.group_id: list(g.files) for g in self._groups}
        self._group_list_items.clear()
        self._group_list_order = []
        self._active_group_row_id = None
        self._rebuild_group_index()
        self._rebuild_filter_index()
        if not self._groups:
            self._enter_mode("empty")
            return
        self._loading = True
        self._enter_mode("loading")
        page = self._bridge.flet_page
        if hasattr(page, "run_task"):
            page.run_task(self._finish_load_to_compare_async, group_id)
        else:
            self._loading = False
            self._enter_compare(group_id)

    def _schedule_load_to_groups(self) -> None:
        self._loading = True
        self._enter_mode("loading")
        page = self._bridge.flet_page
        if hasattr(page, "run_task"):
            page.run_task(self._finish_load_to_groups_async)
        else:
            self._loading = False
            self._enter_mode("groups")

    def load_results(
        self,
        groups: List[DuplicateGroup],
        mode: str = "files",
        defer_render: bool = False,
    ) -> None:
        self._groups = list(groups)
        self._group_files = {g.group_id: list(g.files) for g in self._groups}
        self._group_list_items.clear()
        self._group_list_order = []
        self._active_group_row_id = None
        self._rebuild_group_index()
        self._rebuild_filter_index()
        if defer_render:
            # Keep data fresh, but do not build the heavy grid until this page is shown.
            self._pending_deferred_render = True
            if not self._groups:
                self._mode = "empty"
            return
        self._pending_deferred_render = False
        if not self._groups:
            self._enter_mode("empty")
            return
        self._schedule_load_to_groups()

    def apply_pruned_groups(self, groups: List[DuplicateGroup], mode: str = "files") -> None:
        old_ids = {g.group_id for g in self._groups}
        self._groups = list(groups)
        self._group_files = {g.group_id: list(g.files) for g in self._groups}
        new_ids = {g.group_id for g in self._groups}
        if old_ids != new_ids:
            self._group_list_items.clear()
            self._group_list_order = []
            self._active_group_row_id = None
        else:
            self._group_list_order = []
        self._rebuild_group_index()
        self._rebuild_filter_index()
        if not self._groups:
            self._enter_mode("empty")
            return
        if self._mode == "compare":
            if self._compare_gid is None or self._compare_gid not in self._group_files:
                self._enter_compare(self._groups[0].group_id)
                return
            files = self._group_files[self._compare_gid]
            if not files:
                self._enter_compare(self._groups[0].group_id)
                return
            self._compare_a = files[0]
            self._compare_b = files[1] if len(files) > 1 else None
            self._update_compare_panels()
            self._update_compare_chrome()
            self._refresh_group_list_panel()
        elif self._mode == "groups":
            self._refresh_groups_overview()
            self._safe_update(self._content)
        elif self._mode == "grid":
            self._refresh_grid()
        else:
            self._schedule_load_to_groups()

    def on_show(self) -> None:
        self._reduce_motion = self._bridge.is_reduce_motion_enabled()
        self._marked_paths = set(self._bridge.state.selected_files)
        self._recompute_marked_bytes()
        if self._pending_deferred_render:
            self._pending_deferred_render = False
            if self._groups:
                self._schedule_load_to_groups()
            self._refresh_stats_header()
            return
        if not self._groups:
            self._enter_mode("empty")
            return
        if self._mode in ("empty", "loading"):
            self._schedule_load_to_groups()
            self._refresh_stats_header()
            return
        # If already in a rendered mode, refresh counts/chrome.
        if self._mode == "grid":
            self._refresh_grid()
            self._safe_update(self._content)
        self._refresh_stats_header()

    def get_groups(self) -> List[DuplicateGroup]:
        return list(self._groups)

    def _is_mounted(self) -> bool:
        try:
            return self.page is not None
        except RuntimeError:
            return False

    def _push_marked_paths_to_store(self) -> None:
        """Sync ``AppState.selected_files`` to the current mark set (paths still marked for deletion)."""
        self._bridge.store.dispatch(FileSelectionChanged(file_ids=tuple(self._marked_paths)))

    @staticmethod
    def _safe_update(ctrl: ft.Control | None) -> None:
        """Call ``update()`` only if *ctrl* is attached to a page (avoids freeze on orphan controls)."""
        if ctrl is None:
            return
        try:
            if ctrl.page is not None:
                ctrl.update()
        except RuntimeError:
            pass

    @staticmethod
    def _log_if_slow(label: str, started_at: float) -> None:
        elapsed_ms = (time.perf_counter() - started_at) * 1000.0
        if elapsed_ms > _UI_SLOW_MS:
            _log.debug("[UI_SLOW] %s took %.1f ms", label, elapsed_ms)

    def _set_rendering(self, value: bool) -> None:
        self._grid_build_generation += 1
        gen = self._grid_build_generation
        self._rendering_badge.visible = value
        self._safe_update(self._rendering_badge)
        if value:
            page = self._bridge.flet_page
            if hasattr(page, "run_task"):
                page.run_task(self._rendering_failsafe_async, gen)

    async def _rendering_failsafe_async(self, gen: int) -> None:
        await asyncio.sleep(1.6)
        if gen != self._grid_build_generation:
            return
        if self._rendering_badge.visible:
            self._rendering_badge.visible = False
            self._safe_update(self._rendering_badge)

    # ------------------------------------------------------------------
    # Mode management
    # ------------------------------------------------------------------
    _MODE_VISIBILITY: Dict[str, Dict[str, bool]] = {
        "empty":   {"filter": False, "cmp_bar": False, "smart": False, "toggle": False, "sort": False},
        "loading": {"filter": False, "cmp_bar": False, "smart": False, "toggle": False, "sort": False},
        "groups":  {"filter": True,  "cmp_bar": False, "smart": False, "toggle": True,  "sort": True},
        "grid":    {"filter": True,  "cmp_bar": False, "smart": True,  "toggle": True,  "sort": False},
        "compare": {"filter": False, "cmp_bar": True,  "smart": False, "toggle": False, "sort": False},
    }

    def _enter_mode(self, mode: str) -> None:
        # Safety invariant: if groups exist, never render the empty-state shell.
        # This prevents stale/contradictory UI when event ordering briefly races.
        if mode == "empty" and bool(self._groups):
            mode = "groups"
        self._mode = mode
        # Compare layout needs a bounded viewport: page-level scroll + unbounded ListView made the
        # compare Row as tall as all groups and vertically centered A/B (~mid-list).
        self.scroll = None if mode == "compare" else ft.ScrollMode.AUTO
        if mode != "grid":
            # Cancel any stale grid thumbnail jobs when leaving grid mode.
            self._thumb_load_generation += 1
        if mode != "compare":
            # Unbind keys if not in compare mode to save resources/events
            if hasattr(self._bridge, 'flet_page') and self._bridge.flet_page:
                self._bridge.flet_page.on_keyboard_event = None

        self._content.controls.clear()
        if mode != "grid":
            self._set_rendering(False)
        self._compare_view.visible = mode == "compare"

        vis = self._MODE_VISIBILITY[mode]
        self._filter_bar.visible = vis["filter"]
        self._cmp_bar.visible = vis["cmp_bar"]
        self._smart_row.visible = vis["smart"]
        self._view_toggle_row.visible = vis["toggle"]
        self._group_sort_row.visible = vis["sort"]

        if mode == "empty":
            self._content.controls.append(self._empty_state)
        elif mode == "loading":
            self._content.controls.append(self._loading_state)
        elif mode == "groups":
            self._refresh_filter_labels()
            self._refresh_groups_overview()
            self._content.controls.append(self._groups_overview)
        elif mode == "grid":
            self._refresh_grid()
            self._content.controls.append(self._grid)
        elif mode == "compare":
            self._content.controls.append(self._compare_view)
            self._bind_keys()

        self._safe_update(self._content)
        self._safe_update(self._filter_bar)
        self._safe_update(self._cmp_bar)
        self._safe_update(self._smart_row)
        self._safe_update(self._view_toggle_row)
        self._safe_update(self._group_sort_row)
        self._refresh_stats_header()
        self._apply_pill_chrome()

    async def _finish_load_to_grid_async(self) -> None:
        await asyncio.sleep(0)
        self._loading = False
        if not self._groups:
            self._enter_mode("empty")
            return
        self._enter_mode("grid")

    async def _finish_load_to_groups_async(self) -> None:
        await asyncio.sleep(0)
        self._loading = False
        if not self._groups:
            self._enter_mode("empty")
            return
        self._enter_mode("groups")

    async def _finish_load_to_compare_async(self, group_id: int) -> None:
        await asyncio.sleep(0)
        self._loading = False
        if not self._groups:
            self._enter_mode("empty")
            return
        self._enter_compare(group_id)

    def _to_grid(self, e=None) -> None:
        self._enter_mode("grid")

    # ------------------------------------------------------------------
    # Groups Overview
    # ------------------------------------------------------------------
    def _build_group_card(self, g: DuplicateGroup, idx: int, total_reclaim_scan: int) -> ft.Container:
        return build_group_card(
            self._t,
            self._bridge,
            g,
            idx,
            total_reclaim_scan,
            self._reviewed_group_ids,
            on_open_group=self._enter_compare,
            get_glass_style=self._get_glass_style,
        )

    def _sorted_groups_for_current_filter(self) -> List[DuplicateGroup]:
        filtered = [
            g for g in self._groups
            if self._filter_key == "all" or any(self._passes_filter(f) for f in g.files)
        ]
        key = str(self._group_sort_key or "reclaimable_desc")
        if key == "files_desc":
            return sorted(filtered, key=lambda g: len(g.files), reverse=True)
        if key == "path_asc":
            return sorted(
                filtered,
                key=lambda g: str(Path(str(g.files[0].path)).parent).lower() if g.files else "",
            )
        return sorted(filtered, key=lambda g: int(getattr(g, "reclaimable", 0) or 0), reverse=True)

    def _refresh_groups_overview(self) -> None:
        filtered_groups = self._sorted_groups_for_current_filter()
        total_r = sum(int(getattr(x, "reclaimable", 0) or 0) for x in self._groups) or 1
        self._groups_overview.controls = [
            self._build_group_card(g, i, total_r) for i, g in enumerate(filtered_groups)
        ]
        self._safe_update(self._groups_overview)

    def _on_group_sort_changed(self, e: ft.ControlEvent) -> None:
        self._group_sort_key = str(e.control.value or "reclaimable_desc")
        if self._mode == "groups":
            self._refresh_groups_overview()
            self._refresh_stats_header()

    # ------------------------------------------------------------------
    # Grid
    # ------------------------------------------------------------------
    def _refresh_grid(self) -> None:
        _t0 = time.perf_counter()
        self._thumb_load_generation += 1
        load_gen = self._thumb_load_generation
        files = self._files_by_filter.get(self._filter_key, [])
        self._refresh_filter_labels()
        n = len(files)
        if n <= _GRID_BUILD_ASYNC_THRESHOLD:
            # Build placeholder tiles immediately — no thumbnail I/O
            self._grid.controls = [self._tile_for_file_placeholder(f) for f in files]
            self._set_rendering(False)
            self._safe_update(self._grid)
            page = self._bridge.flet_page
            if files and hasattr(page, "run_task"):
                page.run_task(self._load_thumbnails_async, list(files), load_gen)
            self._log_if_slow("review:grid_refresh", _t0)
            return

        self._set_rendering(True)
        gen = self._grid_build_generation
        head_n = min(_GRID_FIRST_SYNC_FILES, n)
        head = files[:head_n]
        tail = files[head_n:]
        self._grid.controls = [self._tile_for_file_placeholder(f) for f in head]
        self._safe_update(self._grid)
        try:
            self._grid.update()
        except Exception:
            pass
        page = self._bridge.flet_page
        if tail and hasattr(page, "run_task"):
            page.run_task(self._append_grid_tiles_async, tail, gen, list(files))
        elif tail:
            self._grid.controls.extend([self._tile_for_file_placeholder(f) for f in tail])
            self._safe_update(self._grid)
            self._set_rendering(False)
            if files and hasattr(page, "run_task"):
                page.run_task(self._load_thumbnails_async, list(files), load_gen)
        self._log_if_slow("review:grid_refresh", _t0)

    async def _append_grid_tiles_async(self, tail: List[DuplicateFile], gen: int, all_files: List[DuplicateFile]) -> None:
        for i in range(0, len(tail), _GRID_ASYNC_BATCH):
            if gen != self._grid_build_generation:
                self._set_rendering(False)
                return
            chunk = tail[i : i + _GRID_ASYNC_BATCH]
            self._grid.controls.extend([self._tile_for_file_placeholder(f) for f in chunk])
            # F4: update only the grid, not the full page
            try:
                self._grid.update()
            except Exception:
                pass
            await asyncio.sleep(0)
        if gen == self._grid_build_generation:
            self._set_rendering(False)
            page = self._bridge.flet_page
            if all_files and hasattr(page, "run_task"):
                page.run_task(self._load_thumbnails_async, list(all_files), self._thumb_load_generation)

    def _tile_for_file(self, f: DuplicateFile) -> ft.Container:
        key = str(getattr(f, "path", ""))
        cached = self._tile_cache.get(key)
        if cached is not None:
            return cached
        return self._tile_for_file_placeholder(f)

    def _tile_for_file_placeholder(self, f: DuplicateFile) -> ft.Container:
        """Build a tile with a placeholder icon — no thumbnail loading."""
        t = self._t
        p = Path(str(f.path))
        key = str(getattr(f, "path", ""))

        info_bar = ft.Container(
            content=ft.Column(
                [
                    ft.Text(p.name, size=t.typography.size_xs, color="#FFFFFF",
                            overflow=ft.TextOverflow.ELLIPSIS, max_lines=1,
                            text_align=ft.TextAlign.CENTER),
                    ft.Text(fmt_size(f.size), size=t.typography.size_xs,
                            color=ft.Colors.with_opacity(0.75, "#FFFFFF")),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=2,
            ),
            bgcolor=ft.Colors.with_opacity(0.72, RC.tile_bg),
            padding=ft.padding.symmetric(horizontal=6, vertical=4),
            animate_opacity=(
                None if self._reduce_motion
                else ft.Animation(150, ft.AnimationCurve.EASE_IN_OUT)
            ),
            opacity=0,
        )

        placeholder = ft.Container(
            content=ft.Icon(ft.icons.Icons.INSERT_DRIVE_FILE,
                            size=48, color=ft.Colors.with_opacity(0.3, ft.Colors.WHITE)),
            expand=True,
            alignment=ft.Alignment(0, 0),
            bgcolor=ft.Colors.with_opacity(0.06, ft.Colors.WHITE),
        )
        thumb_slot = ft.Container(content=placeholder, expand=True,
                                   clip_behavior=ft.ClipBehavior.HARD_EDGE)

        stack = ft.Stack(
            [
                thumb_slot,
                ft.Column([ft.Container(expand=True), info_bar], expand=True, spacing=0),
                ft.Container(
                    alignment=ft.Alignment(-1, -1),
                    padding=ft.padding.only(left=6, top=6),
                    content=ft.Checkbox(
                        value=key in self._marked_paths,
                        on_change=lambda e, file=f: self._toggle_mark_file(file),
                        active_color=RC.danger,
                    ),
                ),
            ],
            expand=True,
        )

        def _hover(e: ft.ControlEvent) -> None:
            enter = e.data == "true"
            info_bar.opacity = 1 if enter else 0
            tile.border = (ft.border.all(2, RC.side_a) if enter
                           else ft.border.all(1, ft.Colors.with_opacity(0.12, ft.Colors.WHITE)))
            ReviewPage._safe_update(info_bar)
            ReviewPage._safe_update(tile)

        tile = ft.Container(
            content=stack,
            border_radius=ft.border_radius.all(10),
            border=ft.border.all(1, ft.Colors.with_opacity(0.12, ft.Colors.WHITE)),
            bgcolor=ft.Colors.with_opacity(0.06, ft.Colors.WHITE),
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
            ink=True,
            on_click=lambda e, file=f: self._on_tile_clicked(file),
            on_hover=_hover,
        )
        self._thumb_slots[key] = thumb_slot
        self._tile_cache[key] = tile
        return tile

    async def _load_thumbnails_async(self, files: List[DuplicateFile], load_gen: int) -> None:
        pending: list[tuple[ft.Container, str]] = []

        async def _on_ready(path: Path, b64: str | None) -> None:
            if load_gen != self._thumb_load_generation or self._mode != "grid":
                return
            if not b64:
                return
            key = str(path)
            if key not in self._tile_cache:
                return
            thumb_slot = self._thumb_slots.get(key)
            if thumb_slot is None:
                return
            pending.append((thumb_slot, b64))
            if len(pending) >= 8:
                _apply_t0 = time.perf_counter()
                for slot, thumb_b64 in pending:
                    slot.content = ft.Image(
                        src=f"data:image/jpeg;base64,{thumb_b64}",
                        width=96,
                        height=96,
                        fit=ft.BoxFit.CONTAIN,
                        border_radius=8,
                    )
                pending.clear()
                if load_gen == self._thumb_load_generation and self._mode == "grid":
                    self._safe_update(self._grid)
                self._log_if_slow("review:thumbnail_batch_apply", _apply_t0)
                await asyncio.sleep(0)

        paths = [Path(str(f.path)) for f in files]
        await get_thumbnail_cache().load_batch_async(paths, _on_ready)
        if load_gen != self._thumb_load_generation or self._mode != "grid":
            return
        if pending:
            _apply_t0 = time.perf_counter()
            for slot, thumb_b64 in pending:
                slot.content = ft.Image(
                    src=f"data:image/jpeg;base64,{thumb_b64}",
                    width=96,
                    height=96,
                    fit=ft.BoxFit.CONTAIN,
                    border_radius=8,
                )
            if load_gen == self._thumb_load_generation and self._mode == "grid":
                self._safe_update(self._grid)
            self._log_if_slow("review:thumbnail_batch_apply", _apply_t0)

    def _passes_filter(self, f: DuplicateFile) -> bool:
        if self._filter_key == "all":
            return True
        ext = getattr(f, "extension", Path(str(f.path)).suffix.lower())
        if self._filter_key == "other":
            return ext.lower() not in EXT_ALL_KNOWN
        exts = FILTER_EXTS.get(self._filter_key)
        return ext.lower() in exts if exts else True

    def _thumb_widget(self, path: Path, edge: int) -> ft.Control:
        t = self._t
        if is_image_path(path):
            b64 = get_thumbnail_cache().get_base64(path)
            if b64:
                return ft.Image(
                    src=f"data:image/jpeg;base64,{b64}",
                    width=edge,
                    height=edge,
                    fit=ft.BoxFit.CONTAIN,
                    border_radius=8,
                )
        return ft.Icon(ft.icons.Icons.INSERT_DRIVE_FILE, size=max(28, edge // 2), color=t.colors.primary)

    def _on_tile_clicked(self, f: DuplicateFile) -> None:
        gid = next((g.group_id for g in self._groups if f in g.files), None)
        if gid is not None:
            self._enter_compare(gid)

    # ------------------------------------------------------------------
    # Smart select (grid mode)
    # ------------------------------------------------------------------
    def _on_smart_seg_change(self, e: ft.ControlEvent) -> None:
        sel = getattr(e.control, "selected", None) or {"keep_largest"}
        self._smart_rule = next(iter(sel), "keep_largest")

    def _on_cmp_smart_seg_change(self, e: ft.ControlEvent) -> None:
        sel = getattr(e.control, "selected", None) or {"keep_largest"}
        self._cmp_smart_rule = next(iter(sel), "keep_largest")

    def _on_cmp_apply_rule_click(self, e=None) -> None:
        self._apply_smart_select_compare_current_with_rule(self._cmp_smart_rule)

    def _apply_smart_select_compare_current_with_rule(self, rule: str) -> None:
        """Apply keep rule to files in the current compare group."""
        gid = self._compare_gid
        if gid is None:
            return
        files = [f for f in self._group_files.get(gid, []) if self._passes_filter(f)]
        if len(files) < 2:
            return
        to_delete = paths_to_delete(normalized_rule(rule), files)
        if not to_delete:
            return
        for p in to_delete:
            self._marked_paths.add(str(p))
        self._recompute_marked_bytes()
        self._push_marked_paths_to_store()
        self._update_compare_panels()
        self._refresh_grid()
        self._bridge.show_snackbar(f"Rule applied: {len(to_delete):,} files marked in this group.", info=True)

    def _apply_smart_select_review(self, e=None):
        """Ask whether to apply the active rule in bulk or as per-group suggestion."""
        rule = self._smart_rule or "keep_largest"
        rule_lbl = dict(RULE_LABELS).get(rule, "Keep Largest")
        def _apply_all(_e):
            self._bridge.dismiss_top_dialog()
            self._apply_rule_to_all_groups()
        def _suggest_only(_e):
            self._bridge.dismiss_top_dialog()
            self._bridge.show_snackbar(f"Suggestion mode enabled: {rule_lbl}.", info=True)
        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("Apply rule"),
            content=ft.Text(f'Use "{rule_lbl}" for all groups, or only as a suggestion while reviewing?'),
            actions=[
                ft.TextButton("Cancel", on_click=lambda _e: self._bridge.dismiss_top_dialog()),
                ft.OutlinedButton("Suggest per-group", on_click=_suggest_only),
                ft.ElevatedButton("Apply to all groups", on_click=_apply_all),
            ],
        )
        self._bridge.show_modal_dialog(dlg)

    def _apply_rule_to_all_groups(self) -> None:
        rule = normalized_rule(self._smart_rule or "keep_largest")
        to_delete: List[str] = []
        for g in self._groups:
            files = [f for f in g.files if self._passes_filter(f)]
            to_delete.extend(paths_to_delete(rule, files))
        if not to_delete:
            return
        self._marked_paths = set(to_delete)
        self._recompute_marked_bytes()
        self._push_marked_paths_to_store()
        if self._mode == "grid":
            self._refresh_grid()
        else:
            self._update_compare_panels()
        self._update_progress_and_marked_bar()

    def _apply_smart_select_compare_current(self, e=None) -> None:
        """Apply keep rule to files in the current group that match the active type filter."""
        gid = self._compare_gid
        if gid is None:
            return
        rule = normalized_rule(self._cmp_smart_rule)
        files = [f for f in self._group_files.get(gid, []) if self._passes_filter(f)]
        to_delete = paths_to_delete(rule, files)
        if not to_delete:
            return
        self._show_smart_delete_dialog(to_delete)

    def _show_smart_delete_dialog(self, paths: List[str]) -> None:
        def _confirmed(policy: DeletionPolicy) -> None:
            self._bridge.dismiss_top_dialog()
            self._execute_smart_delete(paths, policy)

        self._bridge.show_modal_dialog(
            build_confirm_dialog(
                f"{len(paths):,} file(s) according to the selected rule",
                _confirmed,
                self._bridge.dismiss_top_dialog,
                self._t,
            )
        )

    def _execute_smart_delete(self, paths: List[str], policy: DeletionPolicy) -> None:
        if not paths:
            return
        service = self._delete_service
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
            ReviewPage._safe_update(progress_bar)
            ReviewPage._safe_update(progress_text)

        def _ui_done(new_groups, deleted: int, failed: int, bytes_reclaimed: int, err: Exception | None) -> None:
            self._bridge.dismiss_top_dialog()
            if err is not None:
                self._bridge.show_snackbar(f"Deletion failed: {err}", error=True)
                return
            self._groups = list(new_groups)
            self._group_files = {g.group_id: list(g.files) for g in self._groups}
            self._rebuild_group_index()
            self._rebuild_filter_index()
            for p in paths:
                self._marked_paths.discard(str(p))
            self._recompute_marked_bytes()
            self._bridge.coordinator.results_groups_pruned(self._groups)
            # GroupsPruned clears ``selected_files`` in the reducer; push surviving marks back.
            self._push_marked_paths_to_store()
            if deleted > 0:
                if policy == DeletionPolicy.TRASH:
                    self._bridge.show_snackbar(
                        f"Moved {deleted:,} files to Trash ({fmt_size(bytes_reclaimed)} reclaimed).",
                        success=True,
                        action_label="Undo",
                        on_action=lambda _e: self._undo_last_trash_delete(),
                    )
                else:
                    self._bridge.show_snackbar(
                        f"Permanently deleted {deleted:,} files ({fmt_size(bytes_reclaimed)} reclaimed).",
                        success=True,
                    )
            if failed > 0:
                self._bridge.show_snackbar(
                    f"{failed:,} file(s) were unavailable (for example disconnected drive) and were skipped.",
                    error=True,
                )
            if not self._groups:
                self._enter_mode("empty")
            else:
                if self._mode == "compare":
                    gid = self._compare_gid
                    if gid is None or gid not in self._group_files:
                        gid = self._groups[0].group_id
                    self._enter_compare(gid)
                else:
                    self._refresh_grid()

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

    # ------------------------------------------------------------------
    # Compare
    # ------------------------------------------------------------------
    def _enter_compare(self, gid: int) -> None:
        _t0 = time.perf_counter()
        if self._compare_nav_in_flight:
            return
        self._compare_nav_in_flight = True
        files = self._group_files.get(gid) or []
        try:
            if not files:
                self._to_grid()
                self._log_if_slow("review:on_click_group_nav", _t0)
                return
            if self._compare_gid is not None:
                self._reviewed_group_ids.add(self._compare_gid)
            self._compare_gid = gid
            self._compare_a = files[0]
            self._compare_b = files[1] if len(files) > 1 else None
            self._enter_mode("compare")
            self._cmp_smart_rule = next(
                iter(getattr(self._cmp_smart_seg, "selected", None) or {"keep_largest"}),
                "keep_largest",
            )
            self._refresh_group_list_panel()
            self._update_compare_panels()
            self._update_compare_chrome()
            self._log_if_slow("review:on_click_group_nav", _t0)
        finally:
            self._compare_nav_in_flight = False

    def _update_compare_panels(self) -> None:
        _t0 = time.perf_counter()
        self._compare_render_generation += 1
        gen = self._compare_render_generation
        self._compare_thumb_slots.clear()
        self._compare_dims_labels.clear()
        self._compare_panel_a.content = self._build_compare_side(self._compare_a, "A", gen)
        self._compare_panel_b.content = self._build_compare_side(self._compare_b, "B", gen)
        self._apply_compare_panel_tints()
        self._safe_update(self._compare_panel_a)
        self._safe_update(self._compare_panel_b)
        self._update_progress_and_marked_bar()
        self._log_if_slow("review:compare_panel_update", _t0)

    def _apply_compare_panel_tints(self) -> None:
        """Visually separate side A and side B (compare mode only)."""
        self._compare_panel_a.bgcolor = ft.Colors.with_opacity(0.10, RC.side_a)
        self._compare_panel_a.border = ft.border.all(1, ft.Colors.with_opacity(0.38, RC.side_a))
        self._compare_panel_b.bgcolor = ft.Colors.with_opacity(0.10, RC.side_b)
        self._compare_panel_b.border = ft.border.all(1, ft.Colors.with_opacity(0.38, RC.side_b))

    def _reset_compare_panels_idle_chrome(self) -> None:
        g = self._get_glass_style(0.04)
        self._compare_panel_a.bgcolor = g.get("bgcolor")
        self._compare_panel_a.border = g.get("border")
        self._compare_panel_b.bgcolor = g.get("bgcolor")
        self._compare_panel_b.border = g.get("border")

    def _keep_only_file(self, keep_file: DuplicateFile) -> None:
        gid = self._compare_gid
        if gid is None:
            return
        files = self._group_files.get(gid, [])
        for f in files:
            fp = str(f.path)
            if f is keep_file:
                self._marked_paths.discard(fp)
            else:
                self._marked_paths.add(fp)
        self._recompute_marked_bytes()
        self._push_marked_paths_to_store()
        self._update_compare_panels()

    def _toggle_mark_file(self, file: DuplicateFile) -> None:
        fp = str(file.path)
        size = int(getattr(file, "size", 0) or 0)
        if fp in self._marked_paths:
            self._marked_paths.discard(fp)
            self._marked_bytes -= size
        else:
            self._marked_paths.add(fp)
            self._marked_bytes += size
        self._push_marked_paths_to_store()
        self._update_compare_panels()

    def _refresh_group_list_panel(self) -> None:
        def _set_row_style(row: ft.Container, active: bool) -> None:
            row.bgcolor = ft.Colors.with_opacity(0.10 if active else 0.04, RC.side_a if active else ft.Colors.WHITE)
            row.border = ft.border.all(
                1,
                ft.Colors.with_opacity(0.28 if active else 0.10, RC.side_a if active else ft.Colors.WHITE),
            )

        current_order = [g.group_id for g in self._groups]
        needs_full_build = (
            not self._group_list_items
            or current_order != self._group_list_order
        )

        if needs_full_build:
            self._group_list_items.clear()
            controls: list[ft.Control] = []
            for i, g in enumerate(self._groups):
                active = g.group_id == self._compare_gid
                row = ft.Container(
                    padding=ft.padding.symmetric(horizontal=10, vertical=8),
                    border_radius=8,
                    ink=True,
                    on_click=lambda _e, gid=g.group_id: self._enter_compare(gid),
                    content=ft.Column(
                        [
                            ft.Text(f"Group {i + 1} · {fmt_size(g.reclaimable)}", size=self._t.typography.size_sm, weight=ft.FontWeight.W_700),
                            ft.Text(
                                group_duplicate_summary(g),
                                size=self._t.typography.size_xs,
                                color=self._t.colors.fg_muted,
                                max_lines=2,
                            ),
                            ft.Text(
                                group_path_hint(list(g.files)),
                                size=self._t.typography.size_xs,
                                color=self._t.colors.fg2,
                                max_lines=2,
                                overflow=ft.TextOverflow.ELLIPSIS,
                            ),
                        ],
                        spacing=2,
                    ),
                )
                _set_row_style(row, active)
                self._group_list_items[g.group_id] = row
                controls.append(row)
            self._group_list_order = current_order
            self._group_list_panel.controls = controls
            self._active_group_row_id = self._compare_gid
            self._safe_update(self._group_list_panel)
            return

        prev_gid = self._active_group_row_id
        curr_gid = self._compare_gid
        if prev_gid == curr_gid:
            return
        if prev_gid is not None:
            prev = self._group_list_items.get(prev_gid)
            if prev is not None:
                _set_row_style(prev, False)
                self._safe_update(prev)
        if curr_gid is not None:
            curr = self._group_list_items.get(curr_gid)
            if curr is not None:
                _set_row_style(curr, True)
                self._safe_update(curr)
        self._active_group_row_id = curr_gid

    def _recompute_marked_bytes(self) -> None:
        total = 0
        for g in self._groups:
            for f in g.files:
                if str(f.path) in self._marked_paths:
                    total += int(getattr(f, "size", 0) or 0)
        self._marked_bytes = total

    def _update_progress_and_marked_bar(self) -> None:
        reviewed = len(self._reviewed_group_ids)
        total = max(1, len(self._groups))
        self._progress_bar.value = min(1.0, reviewed / total)
        marked_bytes = self._marked_bytes
        remaining = max(0, sum(g.reclaimable for g in self._groups) - marked_bytes)
        self._progress_lbl.value = f"{reviewed} of {len(self._groups)} reviewed · {fmt_size(marked_bytes)} marked · {fmt_size(remaining)} remaining"
        if self._mode == "compare":
            self._marked_lbl.value = (
                f"{fmt_size(marked_bytes)} marked for removal across {len(self._marked_paths)} file(s). "
                "Use Keep side A / Delete side B for one-off deletes, or clear marks with each file's checkbox."
            )
        else:
            self._marked_lbl.value = f"{fmt_size(marked_bytes)} marked for removal across {len(self._marked_paths)} file(s)"
        self._marked_bar.visible = bool(self._marked_paths) or self._mode == "compare"
        self._safe_update(self._progress_bar)
        self._safe_update(self._progress_lbl)
        self._safe_update(self._marked_lbl)
        self._safe_update(self._marked_bar)

    def _delete_marked_files(self, e=None) -> None:
        if not self._marked_paths:
            return
        self._show_smart_delete_dialog(sorted(self._marked_paths))

    @staticmethod
    def _get_image_dimensions(path: Path) -> str:
        """Return 'WxH' string for image files, empty string otherwise."""
        try:
            from PIL import Image
            with Image.open(path) as img:
                return f"{img.width} × {img.height}"
        except Exception:
            return ""

    @staticmethod
    def _fmt_mtime(mtime) -> str:
        """Format a unix timestamp to a human-readable date string."""
        try:
            ts = float(mtime or 0)
            if ts <= 0:
                return ""
            return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d  %H:%M")
        except Exception:
            return ""

    def _build_compare_side(self, f: Optional[DuplicateFile], label: str, gen: int) -> ft.Column:
        t = self._t
        label_color = RC.side_a if label == "A" else RC.side_b
        if not f:
            return ft.Column(
                [ft.Text(f"Side {label}: No peer file", color=t.colors.fg_muted)],
                alignment=ft.MainAxisAlignment.CENTER,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                expand=True,
            )
        p = Path(str(f.path))
        marked = str(f.path) in self._marked_paths
        name = p.name
        thumb_slot = ft.Container(
            content=ft.Icon(ft.icons.Icons.INSERT_DRIVE_FILE, size=56, color=ft.Colors.with_opacity(0.35, ft.Colors.WHITE)),
            expand=True,
            alignment=ft.Alignment.CENTER,
            bgcolor=ft.Colors.with_opacity(0.06, ft.Colors.WHITE),
            border_radius=8,
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
        )
        label_badge = ft.Container(
            content=ft.Text(
                f"Side {label}",
                size=t.typography.size_sm,
                weight=ft.FontWeight.BOLD,
                color=label_color,
            ),
            bgcolor=ft.Colors.with_opacity(0.12, label_color),
            border=ft.border.all(1, ft.Colors.with_opacity(0.35, label_color)),
            border_radius=6,
            padding=ft.padding.symmetric(horizontal=10, vertical=4),
        )
        size_badge = ft.Container(
            content=ft.Text(
                fmt_size(f.size),
                size=t.typography.size_xs,
                weight=ft.FontWeight.W_600,
                color=RC.success,
            ),
            bgcolor=ft.Colors.with_opacity(0.10, RC.success),
            border=ft.border.all(1, ft.Colors.with_opacity(0.30, RC.success)),
            border_radius=6,
            padding=ft.padding.symmetric(horizontal=8, vertical=3),
        )

        def _meta_row(icon_name: str, value: str, color: str = RC.muted_text) -> ft.Row:
            return ft.Row(
                [
                    ft.Icon(icon_name, size=12, color=ft.Colors.with_opacity(0.55, color)),
                    ft.Text(value, size=t.typography.size_xs, color=color, overflow=ft.TextOverflow.ELLIPSIS, expand=True),
                ],
                spacing=4,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            )

        meta_rows: list = []
        date_str = self._fmt_mtime(_file_mtime_ts(f))
        if date_str:
            meta_rows.append(_meta_row(ft.icons.Icons.SCHEDULE, date_str, "#BFD5FF"))
        dims_txt = ft.Text("", size=t.typography.size_xs, color="#C084FC")
        meta_rows.append(
            ft.Row(
                [
                    ft.Icon(ft.icons.Icons.ASPECT_RATIO, size=12, color=ft.Colors.with_opacity(0.55, "#C084FC")),
                    dims_txt,
                ],
                spacing=4,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            )
        )
        meta_rows.append(_meta_row(ft.icons.Icons.FOLDER_OPEN, str(p.parent), RC.info))

        meta_box = ft.Container(
            content=ft.Column(meta_rows, spacing=4, tight=True),
            padding=ft.padding.symmetric(horizontal=10, vertical=6),
            bgcolor=ft.Colors.with_opacity(0.06, ft.Colors.WHITE),
            border_radius=6,
            width=400,
        )

        key = f"{label}:{gen}"
        self._compare_thumb_slots[key] = thumb_slot
        self._compare_dims_labels[key] = dims_txt
        page = self._bridge.flet_page
        if hasattr(page, "run_task"):
            page.run_task(self._populate_compare_media_async, f, p, key, gen)

        head: list[ft.Control] = [label_badge]
        if (
            label == "A"
            and self._compare_a
            and self._compare_b
            and self._compare_a.size == self._compare_b.size
            and Path(str(self._compare_a.path)).name == Path(str(self._compare_b.path)).name
        ):
            grp = next((g for g in self._groups if g.group_id == self._compare_gid), None)
            if grp is not None and (getattr(grp, "similarity_type", None) or "exact").lower() == "exact":
                head.append(
                    ft.Container(
                        content=ft.Text(
                            "Same name and size — engine matched these as exact duplicates. Compare folders below.",
                            size=t.typography.size_xs,
                            color=t.colors.fg_muted,
                            text_align=ft.TextAlign.CENTER,
                        ),
                        padding=ft.padding.symmetric(horizontal=8, vertical=4),
                    )
                )

        return ft.Column(
            head
            + [
                thumb_slot,
                ft.Text(name, size=t.typography.size_md, weight=ft.FontWeight.W_600, color=t.colors.fg),
                size_badge,
                meta_box,
                ft.Checkbox(
                    label="Mark for deletion",
                    value=marked,
                    active_color=RC.danger,
                    on_change=lambda e, file=f: self._toggle_mark_file(file),
                ),
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=t.spacing.sm,
            alignment=ft.MainAxisAlignment.START,
            expand=True,
        )

    async def _populate_compare_media_async(self, f: DuplicateFile, p: Path, key: str, gen: int) -> None:
        loop = asyncio.get_event_loop()

        def _read_dims() -> str:
            if not is_image_path(p):
                return ""
            try:
                from PIL import Image
                with Image.open(p) as img:
                    return f"{img.width} × {img.height}"
            except Exception:
                return ""

        b64 = None
        if is_image_path(p):
            try:
                b64 = await loop.run_in_executor(
                    None, lambda: get_thumbnail_cache().get_compare_preview_base64(p)
                )
            except Exception:
                b64 = None
        dims = await loop.run_in_executor(None, _read_dims)

        if gen != self._compare_render_generation:
            return
        slot = self._compare_thumb_slots.get(key)
        dims_lbl = self._compare_dims_labels.get(key)
        if slot is not None and b64:
            slot.content = ft.Image(
                src=f"data:image/jpeg;base64,{b64}",
                expand=True,
                fit=ft.BoxFit.COVER,
                filter_quality=ft.FilterQuality.HIGH,
                border_radius=8,
                cache_width=1600,
                cache_height=1200,
            )
            self._safe_update(slot)
        if dims_lbl is not None:
            dims_lbl.value = dims
            self._safe_update(dims_lbl)

    def _update_compare_chrome(self) -> None:
        gid = self._compare_gid
        if gid is None:
            return
        idx = next((i for i, g in enumerate(self._groups) if g.group_id == gid), 0)
        total = len(self._groups)
        count = len(self._group_files.get(gid, []))
        name_a = Path(str(getattr(self._compare_a, "path", ""))).name if self._compare_a else "(A)"
        name_b = Path(str(getattr(self._compare_b, "path", ""))).name if self._compare_b else "(no peer)"
        g = self._groups[idx] if 0 <= idx < len(self._groups) else None
        sim_note = ""
        if g is not None:
            sim = (getattr(g, "similarity_type", None) or "exact").lower()
            sim_note = " · exact match" if sim == "exact" else f" · {sim}"
        self._cmp_title.value = (
            f"Group {idx + 1}/{total} · {count} files{sim_note} · {name_a}"
            + (f" vs {name_b}" if name_b != name_a else "")
        )
        self._safe_update(self._cmp_title)

    def _prev_group(self, e=None) -> None:
        if self._compare_gid is None:
            return
        idx = self._group_index.get(self._compare_gid, 0)
        if idx > 0:
            self._enter_compare(self._groups[idx - 1].group_id)

    def _next_group(self, e=None) -> None:
        if self._compare_gid is None:
            return
        idx = self._group_index.get(self._compare_gid, 0)
        if idx < len(self._groups) - 1:
            self._enter_compare(self._groups[idx + 1].group_id)

    def _open_side(self, side: str) -> None:
        f = self._compare_a if side == "a" else self._compare_b
        if not f:
            return
        path = Path(str(f.path))
        folder = path.parent if path.is_file() else path
        try:
            if sys.platform == "win32":
                subprocess.Popen(["explorer", "/select,", str(path)])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(folder)])
            else:
                subprocess.Popen(["xdg-open", str(folder)])
        except Exception as e:
            _log.error("Failed to open file: %s", e)

    # ------------------------------------------------------------------
    # Filter
    # ------------------------------------------------------------------
    def _on_filter_changed(self, key: str) -> None:
        self._filter_key = key
        if self._mode == "grid":
            self._refresh_grid()
        elif self._mode == "groups":
            self._refresh_filter_labels()
            self._refresh_groups_overview()
        elif self._mode == "compare":
            self._refresh_filter_labels()
            self._update_compare_panels()

    def _rebuild_group_index(self) -> None:
        self._group_index = {g.group_id: i for i, g in enumerate(self._groups)}

    def _rebuild_filter_index(self) -> None:
        self._tile_cache = {}
        self._thumb_slots = {}
        by_filter: Dict[str, List[DuplicateFile]] = {k: [] for k, _ in _FILTER_TABS}
        group_counts: Dict[str, int] = {k: 0 for k, _ in _FILTER_TABS}
        file_sizes: Dict[str, int] = {k: 0 for k, _ in _FILTER_TABS}
        for g in self._groups:
            group_counts["all"] += 1
            seen_group_kinds: set[str] = set()
            for f in g.files:
                ext = getattr(f, "extension", Path(str(f.path)).suffix.lower())
                if ext.lower() in EXT_ALL_KNOWN:
                    kind = next((k for k, exts in FILTER_EXTS.items() if exts and ext.lower() in exts), "other")
                else:
                    kind = "other"
                bucket = kind if kind in by_filter else "other"
                by_filter["all"].append(f)
                by_filter[bucket].append(f)
                file_sizes["all"] += f.size
                file_sizes[bucket] += f.size
                seen_group_kinds.add(kind if kind in group_counts else "other")
            for kind in seen_group_kinds:
                group_counts[kind] += 1
        self._files_by_filter = by_filter
        self._filter_counts = {k: len(v) for k, v in by_filter.items()}
        self._filter_sizes = file_sizes
        self._filter_group_counts = group_counts
        self._refresh_filter_labels()

    def _refresh_filter_labels(self) -> None:
        self._filter_bar.update_counts(self._filter_counts, self._filter_sizes, self._filter_key)
        self._refresh_stats_header()

    def _refresh_stats_header(self) -> None:
        fl = next((lab for k, lab in _FILTER_TABS if k == self._filter_key), self._filter_key.title())
        self._stats_header.refresh(
            self._mode, fl, self._filter_key,
            self._filter_counts, self._filter_sizes, self._filter_group_counts,
            self._reviewed_group_ids, self._sorted_groups_for_current_filter(),
            self._t,
        )

    # ------------------------------------------------------------------
    # Keyboard
    # ------------------------------------------------------------------
    def _bind_keys(self) -> None:
        self._bridge.flet_page.on_keyboard_event = self._on_key

    def _on_key(self, e: ft.KeyboardEvent) -> None:
        if self._mode != "compare":
            return
        k = e.key.lower().replace(" ", "")
        if k in ("arrowleft", "left", "arrowup", "up"):
            self._prev_group()
        elif k in ("arrowright", "right", "arrowdown", "down"):
            self._next_group()
        elif k == "d":
            self._delete_compare_side("b")
        elif k == "k":
            self._delete_compare_side("a")
        elif k in ("delete", "backspace"):
            self._delete_compare_side("b")
        elif k == "enter":
            self._next_group()
        elif k == "space":
            self._apply_smart_select_compare_current()
            self._next_group()
        elif k == "1":
            # Keep first visible side
            self._delete_compare_side("b")
        elif k == "2":
            # Keep second visible side
            self._delete_compare_side("a")

    # ------------------------------------------------------------------
    # Delete from compare
    # ------------------------------------------------------------------
    def _delete_compare_side(self, side: str) -> None:
        f = self._compare_a if side == "a" else self._compare_b
        if not f:
            return
        name = Path(str(f.path)).name
        path = str(f.path)

        def _confirmed(policy: DeletionPolicy) -> None:
            self._bridge.dismiss_top_dialog()
            self._execute_smart_delete([path], policy)

        self._bridge.show_modal_dialog(
            build_confirm_dialog(f'"{name}"', _confirmed, self._bridge.dismiss_top_dialog, self._t)
        )

    def _undo_last_trash_delete(self) -> None:
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
    # Navigation
    # ------------------------------------------------------------------
    def _go_back(self, e=None) -> None:
        if self._mode in ("compare", "grid"):
            self._enter_mode("groups")
        else:
            self._bridge.navigate("dashboard")

    def apply_theme(self, mode: str) -> None:
        """Updates theme properties without destroying UI controls or keyboard bindings."""
        self._glass_cache = {}
        self._t = theme_for_mode(mode)

        # Update Glass Styles
        self._stats_header.bgcolor = self._get_glass_style(0.04).get('bgcolor')
        self._stats_header.border = self._get_glass_style(0.04).get('border')
        self._filter_bar.sync_theme(self._t)
        self._refresh_filter_labels()

        self._cmp_bar.bgcolor = self._get_glass_style(0.04).get('bgcolor')
        self._cmp_bar.border = self._get_glass_style(0.04).get('border')

        self._empty_state.bgcolor = self._get_glass_style(0.04).get('bgcolor')
        self._empty_state.border = self._get_glass_style(0.04).get('border')

        if self._mode == "compare":
            self._apply_compare_panel_tints()
        else:
            self._reset_compare_panels_idle_chrome()

        self._marked_safety_lbl.color = self._t.colors.fg_muted

        self._apply_pill_chrome()

        if self._is_mounted():
            self.update()