"""Review page — visual grid + side-by-side compare for duplicate groups with glass morphism."""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional

import flet as ft

from cerebro.core.deletion import DeletionPolicy
from cerebro.engines.base_engine import DuplicateFile, DuplicateGroup
from cerebro.v2.ui.flet_app.services.thumbnail_cache import get_thumbnail_cache, is_image_path
from cerebro.v2.ui.flet_app.theme import (
    FILTER_EXTS, EXT_ALL_KNOWN, fmt_size, theme_for_mode,
)

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

_SMART_RULES = [
    ("keep_largest", "Keep Largest"),
    ("keep_smallest", "Keep Smallest"),
    ("keep_newest", "Keep Newest"),
    ("keep_oldest", "Keep Oldest"),
]

_GRID_BUILD_ASYNC_THRESHOLD = 220
_GRID_FIRST_SYNC_FILES = 20   # F5: 20 tiles sync, rest async
_GRID_ASYNC_BATCH = 30


class ReviewPage(ft.Column):
    """Grid and compare view for visual triage of duplicate groups."""

    def __init__(self, bridge: "StateBridge"):
        super().__init__(expand=True, scroll=ft.ScrollMode.AUTO)
        self._bridge = bridge
        self._t = theme_for_mode("dark")
        self._groups: List[DuplicateGroup] = []
        self._group_files: Dict[int, List[DuplicateFile]] = {}
        self._filter_key = "all"
        self._mode = "empty"  # "empty" | "grid" | "compare"
        self._compare_gid: Optional[int] = None
        self._compare_a: Optional[DuplicateFile] = None
        self._compare_b: Optional[DuplicateFile] = None
        self._marked_paths: set[str] = set()
        self._reviewed_group_ids: set[int] = set()
        self._smart_rule = "keep_largest"
        self._grid_extent = 200  # tile max_extent: S=140 M=200 L=260
        self._loading = False
        self._tile_cache: Dict[str, ft.Container] = {}
        self._thumb_slots: Dict[str, ft.Container] = {}
        self._files_by_filter: Dict[str, List[DuplicateFile]] = {k: [] for k, _ in _FILTER_TABS}
        self._glass_cache: dict = {}
        self._filter_counts: Dict[str, int] = {k: 0 for k, _ in _FILTER_TABS}
        self._filter_sizes: Dict[str, int] = {k: 0 for k, _ in _FILTER_TABS}
        self._filter_group_counts: Dict[str, int] = {k: 0 for k, _ in _FILTER_TABS}
        self._grid_build_generation = 0
        self._rendering_generation = 0
        self._pending_deferred_render: bool = False

        # UI References
        self._title_lbl: ft.Text
        self._summary_lbl: ft.Text
        self._stats_row: ft.Row
        self._smart_apply_all_btn: ft.FilledButton
        self._top_bar: ft.Container
        self._smart_seg: ft.SegmentedButton
        self._smart_row: ft.Row
        self._zoom_row: ft.Row
        self._cmp_title: ft.Text
        self._cmp_smart_seg: ft.SegmentedButton
        self._delete_btn: ft.ElevatedButton
        self._keep_btn: ft.OutlinedButton
        self._cmp_bar: ft.Container
        self._filter_seg: ft.SegmentedButton
        self._content: ft.Column
        self._empty_state: ft.Container
        self._loading_state: ft.Container
        self._grid: ft.GridView
        self._rendering_badge: ft.Container
        self._compare_panel_a: ft.Container
        self._compare_panel_b: ft.Container
        self._group_list_panel: ft.ListView
        self._compare_columns: ft.Row
        self._progress_lbl: ft.Text
        self._progress_bar: ft.ProgressBar
        self._marked_bar: ft.Container
        self._marked_lbl: ft.Text
        self._compare_view: ft.Row

        self._build_ui()

    # ------------------------------------------------------------------
    # Glass & Style Helpers
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

    def _build_zoom_row(self) -> ft.Row:
        """Three-level zoom control for the grid density."""
        def _set_size(extent: int) -> None:
            self._grid_extent = extent
            self._grid.max_extent = extent
            ReviewPage._safe_update(self._grid)

        return ft.Row(
            [
                ft.Text("Size:", size=9, color=self._t.colors.fg_muted),
                ft.TextButton("S", on_click=lambda e: _set_size(140),
                    style=ft.ButtonStyle(color=self._t.colors.fg_muted, padding=ft.padding.symmetric(horizontal=6, vertical=2))),
                ft.TextButton("M", on_click=lambda e: _set_size(200),
                    style=ft.ButtonStyle(color="#22D3EE", padding=ft.padding.symmetric(horizontal=6, vertical=2))),
                ft.TextButton("L", on_click=lambda e: _set_size(260),
                    style=ft.ButtonStyle(color=self._t.colors.fg_muted, padding=ft.padding.symmetric(horizontal=6, vertical=2))),
            ],
            spacing=0,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    # ------------------------------------------------------------------
    # Build (Runs Once)
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        t = self._t
        # Top bar
        self._title_lbl = ft.Text("Review Workspace", size=t.typography.size_lg, weight=ft.FontWeight.BOLD, color=t.colors.fg)
        self._summary_lbl = ft.Text("", size=t.typography.size_sm, color=t.colors.fg2)
        self._stats_row = ft.Row(spacing=t.spacing.sm, wrap=True)
        self._top_bar = ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.TextButton("← Back to Results", on_click=self._go_back,
                                          style=ft.ButtonStyle(color=t.colors.primary)),
                            self._title_lbl,
                            self._summary_lbl,
                        ],
                        alignment=ft.MainAxisAlignment.START,
                        wrap=True,
                    ),
                    self._stats_row,
                ],
                spacing=t.spacing.xs,
            ),
            padding=t.spacing.lg,
            **self._get_glass_style(0.04),
        )

        # Smart select for grid mode
        self._smart_seg = ft.SegmentedButton(
            selected=["keep_largest"],
            allow_multiple_selection=False,
            on_change=self._on_smart_seg_change,
            segments=[
                ft.Segment(value=val, label=ft.Text(label, size=12, weight=ft.FontWeight.W_600))
                for val, label in _SMART_RULES
            ],
        )
        self._zoom_row = self._build_zoom_row()
        self._smart_apply_all_btn = ft.FilledButton(
            "Apply Rule to Visible",
            icon=ft.icons.Icons.AUTO_FIX_HIGH,
            on_click=self._apply_smart_select_review,
            style=ft.ButtonStyle(
                bgcolor="#22D3EE",
                color="#081019",
                shape=ft.RoundedRectangleBorder(radius=8),
                text_style=ft.TextStyle(size=12, weight=ft.FontWeight.W_700),
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
                for val, label in _SMART_RULES
            ],
        )
        self._delete_btn = ft.OutlinedButton(
            "Delete B", icon=ft.icons.Icons.DELETE_OUTLINE,
            on_click=lambda e: self._delete_compare_side("b"),
            style=ft.ButtonStyle(
                color=t.colors.danger,
                side=ft.BorderSide(width=1, color=t.colors.danger),
                shape=ft.RoundedRectangleBorder(radius=8),
            ),
        )
        self._keep_btn = ft.OutlinedButton(
            "Keep A", icon=ft.icons.Icons.CHECK,
            on_click=lambda e: self._delete_compare_side("a"),
            style=ft.ButtonStyle(color=t.colors.success),
        )
        self._cmp_bar = ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.TextButton("← Grid", on_click=self._to_grid),
                            ft.TextButton("← Prev", on_click=self._prev_group),
                            ft.TextButton("Next →", on_click=self._next_group),
                            self._cmp_title,
                        ],
                        wrap=True,
                        spacing=t.spacing.xs,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Row(
                        [
                            self._cmp_smart_seg,
                            self._keep_btn,
                            self._delete_btn,
                            ft.OutlinedButton("Open A", on_click=lambda e: self._open_side("a")),
                            ft.OutlinedButton("Open B", on_click=lambda e: self._open_side("b")),
                        ],
                        wrap=True,
                        spacing=t.spacing.xs,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                ],
                spacing=t.spacing.xs,
            ),
            visible=False,
            padding=t.spacing.sm,
            **self._get_glass_style(0.04),
        )

        # Filter bar
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

        # Content area
        self._content = ft.Column(expand=True)

        # Empty state
        self._empty_state = ft.Container(
            content=ft.Column(
                [
                    ft.Container(
                        content=ft.Icon(ft.icons.Icons.GRID_VIEW, size=44, color="#22D3EE"),
                        bgcolor=ft.Colors.with_opacity(0.08, "#22D3EE"),
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
                    ft.FilledButton(
                        "Go to Results",
                        icon=ft.icons.Icons.LIST_ALT,
                        on_click=lambda e: self._bridge.navigate("duplicates"),
                        style=ft.ButtonStyle(
                            bgcolor="#22D3EE",
                            color="#0A0E14",
                            shape=ft.RoundedRectangleBorder(radius=8),
                        ),
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
                [
                    ft.ProgressRing(width=28, height=28, stroke_width=3, color="#22D3EE"),
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

        # Compare view (left list + right multi-copy viewer)
        self._group_list_panel = ft.ListView(expand=True, spacing=6, padding=ft.padding.all(8))
        left_panel = ft.Container(
            width=320,
            padding=t.spacing.sm,
            content=ft.Column(
                [
                    ft.Text("Groups", size=t.typography.size_md, weight=ft.FontWeight.W_700),
                    self._group_list_panel,
                ],
                spacing=t.spacing.xs,
                expand=True,
            ),
            **self._get_glass_style(0.04),
        )
        self._compare_panel_a = ft.Container(expand=True, padding=t.spacing.md, **self._get_glass_style(0.04))
        self._compare_panel_b = ft.Container(expand=True, padding=t.spacing.md, **self._get_glass_style(0.04))
        self._compare_columns = ft.Row(scroll=ft.ScrollMode.AUTO, spacing=t.spacing.sm)
        right_view = ft.Column(
            [
                ft.Container(content=self._compare_columns, expand=True),
            ],
            expand=True,
            spacing=t.spacing.sm,
        )
        self._progress_bar = ft.ProgressBar(value=0, color="#22D3EE", bgcolor=ft.Colors.with_opacity(0.14, ft.Colors.WHITE))
        self._progress_lbl = ft.Text("", size=t.typography.size_sm, color=t.colors.fg2)
        self._marked_lbl = ft.Text("", size=t.typography.size_sm, color="#FCA5A5")
        self._marked_bar = ft.Container(
            visible=False,
            padding=ft.padding.symmetric(horizontal=t.spacing.md, vertical=t.spacing.sm),
            bgcolor=ft.Colors.with_opacity(0.95, "#1A0C0C"),
            border=ft.border.only(top=ft.BorderSide(1, "#EF4444")),
            content=ft.Row(
                [
                    self._marked_lbl,
                    ft.FilledButton("Delete marked files", on_click=self._delete_marked_files, style=ft.ButtonStyle(bgcolor="#EF4444", color="#FFFFFF")),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            ),
        )
        self._compare_view = ft.Column(
            [
                ft.Row([left_panel, right_view], expand=True),
                ft.Container(content=ft.Column([self._progress_bar, self._progress_lbl], spacing=6), padding=ft.padding.symmetric(horizontal=t.spacing.sm)),
                self._marked_bar,
            ],
            expand=True,
            visible=False,
        )

        self.controls = [
            self._top_bar,
            ft.Container(content=self._smart_row, padding=ft.padding.only(left=t.spacing.lg)),
            ft.Container(content=self._cmp_bar, padding=ft.padding.only(left=t.spacing.lg, right=t.spacing.lg)),
            ft.Container(content=self._filter_seg, padding=ft.padding.only(left=t.spacing.lg, bottom=t.spacing.sm)),
            self._content,
            self._rendering_badge,
        ]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def load_group(self, groups: List[DuplicateGroup], group_id: int, mode: Optional[str] = None) -> None:
        self._groups = list(groups)
        self._group_files = {g.group_id: list(g.files) for g in self._groups}
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

    def load_results(
        self,
        groups: List[DuplicateGroup],
        mode: str = "files",
        defer_render: bool = False,
    ) -> None:
        self._groups = list(groups)
        self._group_files = {g.group_id: list(g.files) for g in self._groups}
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
        self._loading = True
        self._enter_mode("loading")
        page = self._bridge.flet_page
        if hasattr(page, "run_task"):
            page.run_task(self._finish_load_to_grid_async)
        else:
            self._loading = False
            self._enter_mode("grid")

    def apply_pruned_groups(self, groups: List[DuplicateGroup], mode: str = "files") -> None:
        self._groups = list(groups)
        self._group_files = {g.group_id: list(g.files) for g in self._groups}
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
        else:
            self._refresh_grid()

    def on_show(self) -> None:
        if self._pending_deferred_render:
            self._pending_deferred_render = False
            if self._groups:
                self._loading = True
                self._enter_mode("loading")
                page = self._bridge.flet_page
                if hasattr(page, "run_task"):
                    page.run_task(self._finish_load_to_grid_async)
                else:
                    self._loading = False
                    self._enter_mode("grid")
                return
        if not self._groups:
            self._enter_mode("empty")
            return
        # If groups were synced while Review was hidden (defer_render=True),
        # ensure we materialize the grid when the page becomes visible.
        if self._mode in ("empty", "loading"):
            self._loading = True
            self._enter_mode("loading")
            page = self._bridge.flet_page
            if hasattr(page, "run_task"):
                page.run_task(self._finish_load_to_grid_async)
            else:
                self._loading = False
                self._enter_mode("grid")
            return
        # If already in a rendered mode, refresh counts/chrome.
        if self._mode == "grid":
            self._refresh_grid()
            self._safe_update(self._content)

    def get_groups(self) -> List[DuplicateGroup]:
        return list(self._groups)

    def _is_mounted(self) -> bool:
        try:
            return self.page is not None
        except RuntimeError:
            return False

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
        import asyncio

        await asyncio.sleep(1.6)
        if gen != self._rendering_generation:
            return
        if self._rendering_badge.visible:
            self._rendering_badge.visible = False
            self._safe_update(self._rendering_badge)

    # ------------------------------------------------------------------
    # Mode management
    # ------------------------------------------------------------------
    def _enter_mode(self, mode: str) -> None:
        self._mode = mode
        if mode != "compare":
            # Unbind keys if not in compare mode to save resources/events
            if hasattr(self._bridge, 'flet_page') and self._bridge.flet_page:
                self._bridge.flet_page.on_keyboard_event = None
        
        self._content.controls.clear()
        if mode != "grid":
            self._set_rendering(False)
        if mode == "empty":
            self._filter_seg.visible = False
            self._cmp_bar.visible = False
            self._smart_row.visible = False
            self._content.controls.append(self._empty_state)
        elif mode == "loading":
            self._filter_seg.visible = False
            self._cmp_bar.visible = False
            self._smart_row.visible = False
            self._content.controls.append(self._loading_state)
        elif mode == "grid":
            self._filter_seg.visible = True
            self._cmp_bar.visible = False
            self._smart_row.visible = True
            self._refresh_grid()
            self._content.controls.append(self._grid)
        elif mode == "compare":
            self._filter_seg.visible = False
            self._cmp_bar.visible = True
            self._smart_row.visible = False
            self._content.controls.append(self._compare_view)
            self._bind_keys()
            
        self._safe_update(self._content)
        self._safe_update(self._filter_seg)
        self._safe_update(self._cmp_bar)
        self._safe_update(self._smart_row)
        self._update_top_stats()

    async def _finish_load_to_grid_async(self) -> None:
        import asyncio

        await asyncio.sleep(0)
        self._loading = False
        if not self._groups:
            self._enter_mode("empty")
            return
        self._enter_mode("grid")

    async def _finish_load_to_compare_async(self, group_id: int) -> None:
        import asyncio

        await asyncio.sleep(0)
        self._loading = False
        if not self._groups:
            self._enter_mode("empty")
            return
        self._enter_compare(group_id)

    def _to_grid(self, e=None) -> None:
        self._enter_mode("grid")

    # ------------------------------------------------------------------
    # Grid
    # ------------------------------------------------------------------
    def _refresh_grid(self) -> None:
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
                page.run_task(self._load_thumbnails_async, list(files))
            return

        self._grid_build_generation += 1
        gen = self._grid_build_generation
        self._set_rendering(True)
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
                page.run_task(self._load_thumbnails_async, list(files))

    async def _append_grid_tiles_async(self, tail: List[DuplicateFile], gen: int, all_files: List[DuplicateFile]) -> None:
        import asyncio

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
                page.run_task(self._load_thumbnails_async, list(all_files))

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
            bgcolor=ft.Colors.with_opacity(0.72, "#0A0E14"),
            padding=ft.padding.symmetric(horizontal=6, vertical=4),
            animate_opacity=(
                None if self._bridge.is_reduce_motion_enabled()
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
            ],
            expand=True,
        )

        def _hover(e: ft.ControlEvent) -> None:
            enter = e.data == "true"
            info_bar.opacity = 1 if enter else 0
            tile.border = (ft.border.all(2, "#22D3EE") if enter
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

    async def _load_thumbnails_async(self, files: List[DuplicateFile]) -> None:
        import asyncio

        pending: list[tuple[ft.Container, str]] = []

        async def _on_ready(path: Path, b64: str | None) -> None:
            if not b64:
                return
            key = str(path)
            if key not in self._tile_cache:
                return
            thumb_slot = self._thumb_slots.get(key)
            if thumb_slot is None:
                return
            pending.append((thumb_slot, b64))
            if len(pending) >= 20:
                for slot, thumb_b64 in pending:
                    slot.content = ft.Image(
                        src=f"data:image/jpeg;base64,{thumb_b64}",
                        width=120,
                        height=120,
                        fit=ft.BoxFit.CONTAIN,
                        border_radius=8,
                    )
                pending.clear()
                self._safe_update(self._grid)
                await asyncio.sleep(0)

        paths = [Path(str(f.path)) for f in files]
        await get_thumbnail_cache().load_batch_async(paths, _on_ready)
        if pending:
            for slot, thumb_b64 in pending:
                slot.content = ft.Image(
                    src=f"data:image/jpeg;base64,{thumb_b64}",
                    width=120,
                    height=120,
                    fit=ft.BoxFit.CONTAIN,
                    border_radius=8,
                )
            self._safe_update(self._grid)

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

    def _build_tile(self, f: DuplicateFile) -> ft.Container:
        t = self._t
        p = Path(str(f.path))
        name = p.name
        thumb = self._thumb_widget(p, 120)

        info_bar = ft.Container(
            content=ft.Column(
                [
                    ft.Text(name, size=t.typography.size_xs, color="#FFFFFF", overflow=ft.TextOverflow.ELLIPSIS, max_lines=1, text_align=ft.TextAlign.CENTER),
                    ft.Text(fmt_size(f.size), size=t.typography.size_xs, color=ft.Colors.with_opacity(0.75, "#FFFFFF")),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=2,
            ),
            bgcolor=ft.Colors.with_opacity(0.72, "#0A0E14"),
            padding=ft.padding.symmetric(horizontal=6, vertical=4),
            animate_opacity=(
                None
                if self._bridge.is_reduce_motion_enabled()
                else ft.Animation(150, ft.AnimationCurve.EASE_IN_OUT)
            ),
            opacity=0,
        )

        stack = ft.Stack(
            [
                ft.Container(content=thumb, expand=True, clip_behavior=ft.ClipBehavior.HARD_EDGE),
                ft.Column(
                    [ft.Container(expand=True), info_bar],
                    expand=True,
                    spacing=0,
                ),
            ],
            expand=True,
        )

        def _hover(e: ft.ControlEvent) -> None:
            enter = e.data == "true"
            info_bar.opacity = 1 if enter else 0
            tile.border = ft.border.all(2, "#22D3EE") if enter else ft.border.all(1, ft.Colors.with_opacity(0.12, ft.Colors.WHITE))
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
        return tile

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
        self._apply_smart_select_compare_current_with_rule(next(iter(sel), "keep_largest"))

    def _apply_smart_select_compare_current_with_rule(self, rule: str) -> None:
        """Apply keep rule to files in the current compare group."""
        gid = self._compare_gid
        if gid is None:
            return
        files = [f for f in self._group_files.get(gid, []) if self._passes_filter(f)]
        if len(files) < 2:
            return
        if rule == "keep_largest":
            keep = max(files, key=lambda f: f.size)
        elif rule == "keep_smallest":
            keep = min(files, key=lambda f: f.size)
        elif rule == "keep_newest":
            keep = max(files, key=lambda f: getattr(f, "mtime", 0) or 0)
        elif rule == "keep_oldest":
            keep = min(files, key=lambda f: getattr(f, "mtime", 0) or 0)
        else:
            keep = max(files, key=lambda f: f.size)
        to_delete = [str(f.path) for f in files if f is not keep]
        if not to_delete:
            return
        self._show_smart_delete_dialog(to_delete)

    def _apply_smart_select_review(self, e=None):
        """Ask whether to apply the active rule in bulk or as per-group suggestion."""
        rule = self._smart_rule or "keep_largest"
        rule_lbl = dict(_SMART_RULES).get(rule, "Keep Largest")
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
        rule = self._smart_rule or "keep_largest"
        to_delete = []
        for g in self._groups:
            files = [f for f in g.files if self._passes_filter(f)]
            if len(files) < 2:
                continue
            if rule == "keep_largest":
                keep = max(files, key=lambda f: f.size)
            elif rule == "keep_smallest":
                keep = min(files, key=lambda f: f.size)
            elif rule == "keep_newest":
                keep = max(files, key=lambda f: getattr(f, "mtime", 0) or 0)
            elif rule == "keep_oldest":
                keep = min(files, key=lambda f: getattr(f, "mtime", 0) or 0)
            else:
                keep = max(files, key=lambda f: f.size)
            for f in files:
                if f is not keep:
                    to_delete.append(str(f.path))
        if not to_delete:
            return
        self._marked_paths = set(to_delete)
        self._update_progress_and_marked_bar()

    def _apply_smart_select_compare_current(self, e=None) -> None:
        """Apply keep rule to files in the current group that match the active type filter."""
        gid = self._compare_gid
        if gid is None:
            return
        rule = next(iter(getattr(self._cmp_smart_seg, "selected", None) or {"keep_largest"}), "keep_largest")
        files = [f for f in self._group_files.get(gid, []) if self._passes_filter(f)]
        if len(files) < 2:
            return
        if rule == "keep_largest":
            keep = max(files, key=lambda f: f.size)
        elif rule == "keep_smallest":
            keep = min(files, key=lambda f: f.size)
        elif rule == "keep_newest":
            keep = max(files, key=lambda f: getattr(f, "mtime", 0) or 0)
        elif rule == "keep_oldest":
            keep = min(files, key=lambda f: getattr(f, "mtime", 0) or 0)
        else:
            keep = max(files, key=lambda f: f.size)
        to_delete = [str(f.path) for f in files if f is not keep]
        if not to_delete:
            return
        self._show_smart_delete_dialog(to_delete)

    def _show_smart_delete_dialog(self, paths: List[str]) -> None:
        t = self._t
        def _do_permanent(e):
            self._bridge.dismiss_top_dialog()
            self._execute_smart_delete(paths, DeletionPolicy.PERMANENT)
        def _do_trash(e):
            self._bridge.dismiss_top_dialog()
            self._execute_smart_delete(paths, DeletionPolicy.TRASH)
        def _cancel(e):
            self._bridge.dismiss_top_dialog()
        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Smart Delete"),
            content=ft.Text(f"This will delete {len(paths):,} files according to the selected rule."),
            actions=[
                ft.TextButton("Cancel", on_click=_cancel),
                ft.OutlinedButton("Delete Permanently", on_click=_do_permanent, style=ft.ButtonStyle(color=t.colors.danger)),
                ft.ElevatedButton("Move to Trash", on_click=_do_trash, style=ft.ButtonStyle(bgcolor=t.colors.danger, color=t.colors.bg)),
            ],
        )
        self._bridge.show_modal_dialog(dialog)

    def _execute_smart_delete(self, paths: List[str], policy: DeletionPolicy) -> None:
        from cerebro.v2.ui.flet_app.services.delete_service import DeleteService
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
            ReviewPage._safe_update(progress_bar)
            ReviewPage._safe_update(progress_text)

        def _ui_done(new_groups, deleted: int, failed: int, bytes_reclaimed: int, err: Exception | None) -> None:
            self._bridge.dismiss_top_dialog()
            if err is not None:
                self._bridge.show_snackbar(f"Deletion failed: {err}", error=True)
                return
            self._groups = list(new_groups)
            self._group_files = {g.group_id: list(g.files) for g in self._groups}
            for p in paths:
                self._marked_paths.discard(str(p))
            self._bridge.coordinator.results_files_removed(paths)
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
                self._bridge.show_snackbar(f"{failed:,} files could not be deleted.", error=True)
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
        files = self._group_files.get(gid) or []
        if not files:
            self._to_grid()
            return
        if self._compare_gid is not None:
            self._reviewed_group_ids.add(self._compare_gid)
        self._compare_gid = gid
        self._compare_a = files[0]
        self._compare_b = files[1] if len(files) > 1 else None
        self._enter_mode("compare")
        self._update_compare_panels()
        self._update_compare_chrome()

    def _update_compare_panels(self) -> None:
        gid = self._compare_gid
        files = self._group_files.get(gid, []) if gid is not None else []
        cols: list[ft.Control] = []
        for i, f in enumerate(files):
            cols.append(self._build_compare_file_column(f, i))
        self._compare_columns.controls = cols
        self._safe_update(self._compare_columns)
        self._refresh_group_list_panel()
        self._update_progress_and_marked_bar()

    def _build_compare_file_column(self, f: DuplicateFile, idx: int) -> ft.Container:
        p = Path(str(f.path))
        marked = str(f.path) in self._marked_paths
        return ft.Container(
            width=290,
            padding=ft.padding.all(10),
            border_radius=10,
            border=ft.border.all(2 if marked else 1, "#EF4444" if marked else ft.Colors.with_opacity(0.14, ft.Colors.WHITE)),
            bgcolor=ft.Colors.with_opacity(0.05, ft.Colors.WHITE),
            content=ft.Column(
                [
                    ft.Text(f"COPY {idx + 1}", weight=ft.FontWeight.W_700, color="#BFD5FF"),
                    self._thumb_widget(p, 180),
                    ft.Text(p.name, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                    ft.Text(f"Path: {p.parent}", size=self._t.typography.size_xs, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS, color="#93C5FD"),
                    ft.Text(f"Modified: {self._fmt_mtime(getattr(f, 'mtime', None))}", size=self._t.typography.size_xs, color="#BFD5FF"),
                    ft.Text(f"Size: {fmt_size(f.size)}", size=self._t.typography.size_xs, color="#4ADE80"),
                    ft.Row(
                        [
                            ft.OutlinedButton("KEEP", on_click=lambda _e, file=f: self._keep_only_file(file)),
                            ft.OutlinedButton("Mark" if not marked else "Unmark", on_click=lambda _e, file=f: self._toggle_mark_file(file)),
                        ],
                        spacing=6,
                    ),
                ],
                spacing=6,
            ),
        )

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
        self._update_compare_panels()

    def _toggle_mark_file(self, file: DuplicateFile) -> None:
        fp = str(file.path)
        if fp in self._marked_paths:
            self._marked_paths.discard(fp)
        else:
            self._marked_paths.add(fp)
        self._update_compare_panels()

    def _refresh_group_list_panel(self) -> None:
        controls: list[ft.Control] = []
        for i, g in enumerate(self._groups):
            active = g.group_id == self._compare_gid
            controls.append(
                ft.Container(
                    padding=ft.padding.symmetric(horizontal=10, vertical=8),
                    border_radius=8,
                    bgcolor=ft.Colors.with_opacity(0.10 if active else 0.04, "#22D3EE" if active else ft.Colors.WHITE),
                    border=ft.border.all(1, ft.Colors.with_opacity(0.28 if active else 0.10, "#22D3EE" if active else ft.Colors.WHITE)),
                    ink=True,
                    on_click=lambda _e, gid=g.group_id: self._enter_compare(gid),
                    content=ft.Column(
                        [
                            ft.Text(f"Group {i + 1} · {fmt_size(g.reclaimable)}", size=self._t.typography.size_sm, weight=ft.FontWeight.W_700),
                            ft.Text(f"{len(g.files)} copies", size=self._t.typography.size_xs, color=self._t.colors.fg_muted),
                        ],
                        spacing=2,
                    ),
                )
            )
        self._group_list_panel.controls = controls
        self._safe_update(self._group_list_panel)

    def _update_progress_and_marked_bar(self) -> None:
        reviewed = len(self._reviewed_group_ids)
        total = max(1, len(self._groups))
        self._progress_bar.value = min(1.0, reviewed / total)
        marked_bytes = 0
        for g in self._groups:
            for f in g.files:
                if str(f.path) in self._marked_paths:
                    marked_bytes += int(getattr(f, "size", 0) or 0)
        remaining = max(0, sum(g.reclaimable for g in self._groups) - marked_bytes)
        self._progress_lbl.value = f"{reviewed} of {len(self._groups)} reviewed · {fmt_size(marked_bytes)} marked · {fmt_size(remaining)} remaining"
        self._marked_lbl.value = f"{fmt_size(marked_bytes)} marked across {len(self._marked_paths)} files"
        self._marked_bar.visible = bool(self._marked_paths)
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
            import datetime
            ts = float(mtime or 0)
            if ts <= 0:
                return ""
            return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d  %H:%M")
        except Exception:
            return ""

    def _build_compare_side(self, f: Optional[DuplicateFile], label: str) -> ft.Column:
        t = self._t
        label_color = "#22D3EE" if label == "A" else "#A78BFA"
        if not f:
            return ft.Column(
                [ft.Text(f"Side {label}: No peer file", color=t.colors.fg_muted)],
                alignment=ft.MainAxisAlignment.CENTER,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                expand=True,
            )
        p = Path(str(f.path))
        name = p.name
        thumb = self._thumb_widget(p, 200)
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
                color="#4ADE80",
            ),
            bgcolor=ft.Colors.with_opacity(0.10, "#4ADE80"),
            border=ft.border.all(1, ft.Colors.with_opacity(0.30, "#4ADE80")),
            border_radius=6,
            padding=ft.padding.symmetric(horizontal=8, vertical=3),
        )

        def _meta_row(icon_name: str, value: str, color: str = "#9FB0D0") -> ft.Row:
            return ft.Row(
                [
                    ft.Icon(icon_name, size=12, color=ft.Colors.with_opacity(0.55, color)),
                    ft.Text(value, size=t.typography.size_xs, color=color, overflow=ft.TextOverflow.ELLIPSIS, expand=True),
                ],
                spacing=4,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            )

        meta_rows: list = []
        date_str = self._fmt_mtime(getattr(f, "mtime", None))
        if date_str:
            meta_rows.append(_meta_row(ft.icons.Icons.SCHEDULE, date_str, "#BFD5FF"))
        dims = self._get_image_dimensions(p) if is_image_path(p) else ""
        if dims:
            meta_rows.append(_meta_row(ft.icons.Icons.ASPECT_RATIO, dims, "#C084FC"))
        meta_rows.append(_meta_row(ft.icons.Icons.FOLDER_OPEN, str(p.parent), "#93C5FD"))

        meta_box = ft.Container(
            content=ft.Column(meta_rows, spacing=4, tight=True),
            padding=ft.padding.symmetric(horizontal=10, vertical=6),
            bgcolor=ft.Colors.with_opacity(0.06, ft.Colors.WHITE),
            border_radius=6,
            width=260,
        )

        return ft.Column(
            [
                label_badge,
                thumb,
                ft.Text(name, size=t.typography.size_md, weight=ft.FontWeight.W_600, color=t.colors.fg),
                size_badge,
                meta_box,
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=t.spacing.sm,
            alignment=ft.MainAxisAlignment.CENTER,
        )

    def _update_compare_chrome(self) -> None:
        gid = self._compare_gid
        if gid is None:
            return
        idx = next((i for i, g in enumerate(self._groups) if g.group_id == gid), 0)
        total = len(self._groups)
        count = len(self._group_files.get(gid, []))
        name_a = Path(str(getattr(self._compare_a, "path", ""))).name if self._compare_a else "(A)"
        name_b = Path(str(getattr(self._compare_b, "path", ""))).name if self._compare_b else "(no peer)"
        self._cmp_title.value = f"Group {idx + 1}/{total} · {count} copies · {name_a} ↔ {name_b}"
        self._safe_update(self._cmp_title)

    def _prev_group(self, e=None) -> None:
        if self._compare_gid is None:
            return
        idx = next((i for i, g in enumerate(self._groups) if g.group_id == self._compare_gid), 0)
        if idx > 0:
            self._enter_compare(self._groups[idx - 1].group_id)

    def _next_group(self, e=None) -> None:
        if self._compare_gid is None:
            return
        idx = next((i for i, g in enumerate(self._groups) if g.group_id == self._compare_gid), 0)
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
            _log.error(f"Failed to open file: {e}")

    # ------------------------------------------------------------------
    # Filter
    # ------------------------------------------------------------------
    def _on_filter_seg_change(self, e: ft.ControlEvent) -> None:
        sel = getattr(e.control, "selected", None) or {"all"}
        self._filter_key = next(iter(sel), "all")
        if self._mode == "grid":
            self._refresh_grid()

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
        self._update_top_stats()

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
                col.controls[1].value = f"{files_n:,}"
                col.controls[1].color = accent if is_active else ft.Colors.with_opacity(0.85, accent)
                col.controls[1].weight = ft.FontWeight.W_700 if is_active else ft.FontWeight.W_600
                col.controls[2].value = fmt_size(size_n)
                col.controls[2].color = "#B7C6E6" if is_active else "#9FB0D0"
        self._update_top_stats()

    def _metric_chip(self, label: str, value: str, accent: str) -> ft.Container:
        return ft.Container(
            content=ft.Row(
                [
                    ft.Text(label, size=self._t.typography.size_xs, color="#9FB0D0"),
                    ft.Text(value, size=self._t.typography.size_sm, weight=ft.FontWeight.W_700, color=accent),
                ],
                spacing=6,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.padding.symmetric(horizontal=10, vertical=6),
            bgcolor=ft.Colors.with_opacity(0.08, ft.Colors.WHITE),
            border=ft.border.all(1, ft.Colors.with_opacity(0.18, ft.Colors.WHITE)),
            border_radius=999,
        )

    def _update_top_stats(self) -> None:
        selected_files = len(self._files_by_filter.get(self._filter_key, []))
        selected_groups = self._filter_group_counts.get(self._filter_key, 0)
        reclaimable = fmt_size(self._filter_sizes.get(self._filter_key, 0))
        mode_label = "Compare" if self._mode == "compare" else "Grid"
        self._summary_lbl.value = f"Filter: {self._filter_key.title()} · Mode: {mode_label}"
        self._stats_row.controls = [
            self._metric_chip("Groups", f"{selected_groups:,}", "#A78BFA"),
            self._metric_chip("Files", f"{selected_files:,}", "#7DD3FC"),
            self._metric_chip("Total Size", reclaimable, "#4ADE80"),
        ]
        self._safe_update(self._summary_lbl)
        self._safe_update(self._stats_row)

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
        t = self._t
        name = Path(str(f.path)).name
        path = str(f.path)

        def _do_delete(policy: DeletionPolicy) -> None:
            from cerebro.v2.ui.flet_app.services.delete_service import DeleteService
            service = DeleteService()
            new_groups, deleted, failed, bytes_reclaimed = service.delete_and_prune([path], self._groups, policy)
            self._groups = new_groups
            self._group_files = {g.group_id: list(g.files) for g in self._groups}
            self._bridge.coordinator.results_files_removed([path])
            if deleted > 0:
                if policy == DeletionPolicy.TRASH:
                    self._bridge.show_snackbar(
                        f'Moved "{name}" to Trash.',
                        success=True,
                        action_label="Undo",
                        on_action=lambda _e: self._undo_last_trash_delete(),
                    )
                else:
                    self._bridge.show_snackbar(
                        f'Permanently deleted "{name}".',
                        success=True,
                    )
            if failed > 0:
                self._bridge.show_snackbar(f"Failed to delete {failed:,} file(s).", error=True)
            if not self._groups:
                self._enter_mode("empty")
                return
            gid = self._compare_gid
            if gid not in self._group_files:
                gid = self._groups[0].group_id
            self._enter_compare(gid)

        def _cancel_cmp(e):
            self._bridge.dismiss_top_dialog()

        def _do_perm_cmp(e):
            self._bridge.dismiss_top_dialog()
            _do_delete(DeletionPolicy.PERMANENT)

        def _do_trash_cmp(e):
            self._bridge.dismiss_top_dialog()
            _do_delete(DeletionPolicy.TRASH)

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Confirm Deletion"),
            content=ft.Text(f'Delete "{name}"?'),
            actions=[
                ft.TextButton("Cancel", on_click=_cancel_cmp),
                ft.OutlinedButton(
                    "Delete Permanently",
                    on_click=_do_perm_cmp,
                    style=ft.ButtonStyle(color=t.colors.danger),
                ),
                ft.ElevatedButton(
                    "Move to Trash",
                    on_click=_do_trash_cmp,
                    style=ft.ButtonStyle(bgcolor=t.colors.danger, color=t.colors.bg),
                ),
            ],
        )
        self._bridge.show_modal_dialog(dialog)

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
    # Navigation
    # ------------------------------------------------------------------
    def _go_back(self, e=None) -> None:
        if self._mode == "compare":
            self._to_grid()
            return
        self._bridge.navigate("duplicates")

    def apply_theme(self, mode: str) -> None:
        """Updates theme properties without destroying UI controls or keyboard bindings."""
        self._glass_cache = {}
        self._t = theme_for_mode(mode)

        # Update Glass Styles
        self._top_bar.bgcolor = self._get_glass_style(0.04).get('bgcolor')
        self._top_bar.border = self._get_glass_style(0.04).get('border')

        self._cmp_bar.bgcolor = self._get_glass_style(0.04).get('bgcolor')
        self._cmp_bar.border = self._get_glass_style(0.04).get('border')

        self._empty_state.bgcolor = self._get_glass_style(0.04).get('bgcolor')
        self._empty_state.border = self._get_glass_style(0.04).get('border')

        self._compare_panel_a.bgcolor = self._get_glass_style(0.04).get('bgcolor')
        self._compare_panel_a.border = self._get_glass_style(0.04).get('border')

        self._compare_panel_b.bgcolor = self._get_glass_style(0.04).get('bgcolor')
        self._compare_panel_b.border = self._get_glass_style(0.04).get('border')

        if self._is_mounted():
            self.update()