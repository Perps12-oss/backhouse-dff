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

_SMART_RULES = [
    ("keep_largest", "Keep Largest"),
    ("keep_smallest", "Keep Smallest"),
    ("keep_newest", "Keep Newest"),
    ("keep_oldest", "Keep Oldest"),
]


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
        self._smart_rule = "keep_largest"
        self._grid_extent = 200  # tile max_extent: S=140 M=200 L=260
        self._loading = False
        self._tile_cache: Dict[str, ft.Container] = {}
        self._files_by_filter: Dict[str, List[DuplicateFile]] = {k: [] for k, _ in _FILTER_TABS}
        self._filter_counts: Dict[str, int] = {k: 0 for k, _ in _FILTER_TABS}
        self._filter_group_counts: Dict[str, int] = {k: 0 for k, _ in _FILTER_TABS}

        # UI References
        self._title_lbl: ft.Text
        self._summary_lbl: ft.Text
        self._top_bar: ft.Container
        self._smart_dropdown: ft.Dropdown
        self._smart_apply: ft.ElevatedButton
        self._smart_row: ft.Row
        self._zoom_row: ft.Row
        self._cmp_title: ft.Text
        self._cmp_smart_dropdown: ft.Dropdown
        self._cmp_smart_apply: ft.ElevatedButton
        self._delete_btn: ft.ElevatedButton
        self._keep_btn: ft.OutlinedButton
        self._cmp_bar: ft.Container
        self._filter_bar: ft.Row
        self._content: ft.Column
        self._empty_state: ft.Container
        self._loading_state: ft.Container
        self._grid: ft.GridView
        self._compare_panel_a: ft.Container
        self._compare_panel_b: ft.Container
        self._compare_view: ft.Row

        self._build_ui()

    # ------------------------------------------------------------------
    # Glass & Style Helpers
    # ------------------------------------------------------------------
    def _get_glass_style(self, opacity: float = 0.06) -> dict:
        is_light = "light" in self._bridge.app_theme.lower() if hasattr(self._bridge, 'app_theme') else False
        bg = ft.Colors.with_opacity(opacity, ft.Colors.WHITE if not is_light else ft.Colors.BLACK)
        border_color = ft.Colors.with_opacity(0.12, ft.Colors.WHITE if not is_light else ft.Colors.BLACK)
        return dict(
            bgcolor=bg,
            border=ft.border.all(1, border_color),
            border_radius=ft.border_radius.all(12),
            blur=ft.Blur(8, 8),
        )

    def _get_filter_btn_style(self, is_active: bool) -> ft.ButtonStyle:
        return ft.ButtonStyle(
            bgcolor="#22D3EE" if is_active else ft.Colors.with_opacity(0.06, ft.Colors.WHITE),
            color="#0A0E14" if is_active else self._t.colors.fg2,
            overlay_color=ft.Colors.with_opacity(0.15, "#22D3EE"),
            shape=ft.RoundedRectangleBorder(radius=8),
            padding=ft.padding.symmetric(horizontal=14, vertical=8),
        )

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
        self._title_lbl = ft.Text("Review", size=t.typography.size_lg, weight=ft.FontWeight.BOLD, color=t.colors.fg)
        self._summary_lbl = ft.Text("", size=t.typography.size_sm, color=t.colors.fg2)
        self._top_bar = ft.Container(
            content=ft.Row(
                [
                    ft.TextButton("← Back to Results", on_click=self._go_back,
                                  style=ft.ButtonStyle(color=t.colors.primary)),
                    self._title_lbl,
                    self._summary_lbl,
                ],
                alignment=ft.MainAxisAlignment.START,
            ),
            padding=t.spacing.lg,
            **self._get_glass_style(0.04),
        )

        # Smart select for grid mode
        self._smart_dropdown = ft.Dropdown(
            options=[ft.dropdown.Option(key=val, text=label) for val, label in _SMART_RULES],
            value=self._smart_rule,
            width=160,
            label="Smart Select",
            border_radius=8,
        )
        self._smart_apply = ft.ElevatedButton(
            "Apply",
            on_click=self._apply_smart_select_review,
            style=ft.ButtonStyle(
                bgcolor=ft.Colors.with_opacity(0.15, t.colors.primary),
                color=t.colors.fg,
                shape=ft.RoundedRectangleBorder(radius=8),
            ),
        )
        self._zoom_row = self._build_zoom_row()
        self._smart_row = ft.Row(
            [self._smart_dropdown, self._smart_apply, self._zoom_row],
            spacing=t.spacing.sm,
            visible=False,
        )

        # Compare navigation bar
        self._cmp_title = ft.Text("", size=t.typography.size_sm, color=t.colors.fg, weight=ft.FontWeight.W_600)
        self._cmp_smart_dropdown = ft.Dropdown(
            options=[ft.dropdown.Option(key=val, text=label) for val, label in _SMART_RULES],
            value=self._smart_rule,
            width=150,
            label="Smart Select",
            border_radius=8,
        )
        self._cmp_smart_apply = ft.ElevatedButton(
            "Apply",
            on_click=self._apply_smart_select_compare_current,
            style=ft.ButtonStyle(
                bgcolor=ft.Colors.with_opacity(0.15, t.colors.primary),
                color=t.colors.fg,
                shape=ft.RoundedRectangleBorder(radius=8),
            ),
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
            content=ft.Row(
                [
                    ft.TextButton("← Grid", on_click=self._to_grid),
                    ft.TextButton("← Prev", on_click=self._prev_group),
                    ft.TextButton("Next →", on_click=self._next_group),
                    self._cmp_smart_dropdown,
                    self._cmp_smart_apply,
                    self._cmp_title,
                    self._keep_btn,
                    self._delete_btn,
                    ft.TextButton("Open A", on_click=lambda e: self._open_side("a")),
                    ft.TextButton("Open B", on_click=lambda e: self._open_side("b")),
                ],
            ),
            visible=False,
            padding=t.spacing.sm,
            **self._get_glass_style(0.04),
        )

        # Filter bar
        self._filter_bar = ft.Row(
            [
                ft.ElevatedButton(
                    label,
                    on_click=lambda e, k=key: self._set_filter(k),
                    data=key,
                    style=self._get_filter_btn_style(key == "all"),
                )
                for key, label in _FILTER_TABS
            ],
            spacing=t.spacing.xs,
            wrap=True,
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
            alignment=ft.Alignment(0.5, 0.5),
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
            alignment=ft.Alignment(0.5, 0.5),
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

        # Compare view
        self._compare_panel_a = ft.Container(expand=True, padding=t.spacing.md, **self._get_glass_style(0.04))
        self._compare_panel_b = ft.Container(expand=True, padding=t.spacing.md, **self._get_glass_style(0.04))
        self._compare_view = ft.Row(
            [
                self._compare_panel_a,
                ft.VerticalDivider(width=1, color="#30363D", thickness=1),
                self._compare_panel_b,
            ],
            expand=True,
            visible=False,
        )

        self.controls = [
            self._top_bar,
            ft.Container(content=self._smart_row, padding=ft.padding.only(left=t.spacing.lg)),
            ft.Container(content=self._cmp_bar, padding=ft.padding.only(left=t.spacing.lg, right=t.spacing.lg)),
            ft.Container(content=self._filter_bar, padding=ft.padding.only(left=t.spacing.lg, bottom=t.spacing.sm)),
            self._content,
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
            if not self._groups:
                self._mode = "empty"
            return
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
        if not self._groups:
            self._enter_mode("empty")

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
        if mode == "empty":
            self._filter_bar.visible = False
            self._cmp_bar.visible = False
            self._smart_row.visible = False
            self._content.controls.append(self._empty_state)
        elif mode == "loading":
            self._filter_bar.visible = False
            self._cmp_bar.visible = False
            self._smart_row.visible = False
            self._content.controls.append(self._loading_state)
        elif mode == "grid":
            self._filter_bar.visible = True
            self._cmp_bar.visible = False
            self._smart_row.visible = True
            self._refresh_grid()
            self._content.controls.append(self._grid)
        elif mode == "compare":
            self._filter_bar.visible = False
            self._cmp_bar.visible = True
            self._smart_row.visible = False
            self._content.controls.append(self._compare_view)
            self._bind_keys()
            
        self._safe_update(self._content)
        self._safe_update(self._filter_bar)
        self._safe_update(self._cmp_bar)
        self._safe_update(self._smart_row)

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
        self._grid.controls = [self._tile_for_file(f) for f in files]
        self._refresh_filter_labels()
        self._safe_update(self._grid)

    def _tile_for_file(self, f: DuplicateFile) -> ft.Container:
        key = str(getattr(f, "path", ""))
        cached = self._tile_cache.get(key)
        if cached is not None:
            return cached
        tile = self._build_tile(f)
        self._tile_cache[key] = tile
        return tile

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
    def _apply_smart_select_review(self, e=None):
        """Apply keep rule to all visible groups and delete the rest."""
        rule = self._smart_dropdown.value or "keep_largest"
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
        self._show_smart_delete_dialog(to_delete)

    def _apply_smart_select_compare_current(self, e=None) -> None:
        """Apply keep rule to files in the current group that match the active type filter."""
        gid = self._compare_gid
        if gid is None:
            return
        rule = self._cmp_smart_dropdown.value or self._smart_rule or "keep_largest"
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
        service = DeleteService()
        new_groups, deleted, failed, bytes_reclaimed = service.delete_and_prune(paths, self._groups, policy)
        self._groups = new_groups
        self._group_files = {g.group_id: list(g.files) for g in self._groups}
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
            self._refresh_grid()

    # ------------------------------------------------------------------
    # Compare
    # ------------------------------------------------------------------
    def _enter_compare(self, gid: int) -> None:
        files = self._group_files.get(gid) or []
        if not files:
            self._to_grid()
            return
        self._cmp_smart_dropdown.value = self._smart_dropdown.value or self._smart_rule
        self._compare_gid = gid
        self._compare_a = files[0]
        self._compare_b = files[1] if len(files) > 1 else None
        self._enter_mode("compare")
        self._update_compare_panels()
        self._update_compare_chrome()

    def _update_compare_panels(self) -> None:
        self._compare_panel_a.content = self._build_compare_side(self._compare_a, "A")
        self._compare_panel_b.content = self._build_compare_side(self._compare_b, "B")
        self._safe_update(self._compare_panel_a)
        self._safe_update(self._compare_panel_b)

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
        return ft.Column(
            [
                label_badge,
                thumb,
                ft.Text(name, size=t.typography.size_md, weight=ft.FontWeight.W_600, color=t.colors.fg),
                size_badge,
                ft.Text(str(p.parent), size=t.typography.size_xs, color=t.colors.fg_muted, overflow=ft.TextOverflow.ELLIPSIS),
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
    def _set_filter(self, key: str) -> None:
        self._filter_key = key
        for btn in self._filter_bar.controls:
            is_active = btn.data == key
            btn.style = self._get_filter_btn_style(is_active)
            self._safe_update(btn)
        if self._mode == "grid":
            self._refresh_grid()

    def _rebuild_filter_index(self) -> None:
        self._tile_cache = {}
        by_filter: Dict[str, List[DuplicateFile]] = {k: [] for k, _ in _FILTER_TABS}
        group_counts: Dict[str, int] = {k: 0 for k, _ in _FILTER_TABS}
        for g in self._groups:
            group_counts["all"] += 1
            seen_group_kinds: set[str] = set()
            for f in g.files:
                ext = getattr(f, "extension", Path(str(f.path)).suffix.lower())
                if ext.lower() in EXT_ALL_KNOWN:
                    kind = next((k for k, exts in FILTER_EXTS.items() if exts and ext.lower() in exts), "other")
                else:
                    kind = "other"
                by_filter["all"].append(f)
                by_filter[kind if kind in by_filter else "other"].append(f)
                seen_group_kinds.add(kind if kind in group_counts else "other")
            for kind in seen_group_kinds:
                group_counts[kind] += 1
        self._files_by_filter = by_filter
        self._filter_counts = {k: len(v) for k, v in by_filter.items()}
        self._filter_group_counts = group_counts

    def _refresh_filter_labels(self) -> None:
        for btn in self._filter_bar.controls:
            key = str(getattr(btn, "data", "") or "")
            base = next((label for k, label in _FILTER_TABS if k == key), key.title())
            files_n = self._filter_counts.get(key, 0)
            groups_n = self._filter_group_counts.get(key, 0)
            btn.text = f"{base} · {files_n:,}"
            btn.tooltip = f"{groups_n:,} groups · {files_n:,} files"

    # ------------------------------------------------------------------
    # Keyboard
    # ------------------------------------------------------------------
    def _bind_keys(self) -> None:
        self._bridge.flet_page.on_keyboard_event = self._on_key

    def _on_key(self, e: ft.KeyboardEvent) -> None:
        if self._mode != "compare":
            return
        k = e.key.lower().replace(" ", "")
        if k in ("arrowleft", "left"):
            self._prev_group()
        elif k in ("arrowright", "right"):
            self._next_group()
        elif k == "d":
            self._delete_compare_side("b")
        elif k == "k":
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

        # Update Filter Buttons
        for btn in self._filter_bar.controls:
            is_active = btn.data == self._filter_key
            btn.style = self._get_filter_btn_style(is_active)

        # Force refresh of dynamic content (Grid/Compare) to apply new text/icon colors
        self._tile_cache = {}
        if self._mode == "grid":
            self._refresh_grid()
        elif self._mode == "compare":
            self._update_compare_panels()

        if self._is_mounted():
            self.update()