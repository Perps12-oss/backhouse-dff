from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Callable, List, Optional

import flet as ft

from cerebro.engines.base_engine import DuplicateFile, DuplicateGroup
from cerebro.v2.ui.flet_app.components.common.chunked_view import (
    ChunkedViewBuilder,
    RESULTS_GRID_CHUNK_CONFIG,
    REVIEW_GROUPS_CHUNK_CONFIG,
)
from cerebro.v2.ui.flet_app.components.common.safe_controls import IMAGE_PLACEHOLDER_SRC, safe_update
from cerebro.v2.ui.flet_app.pages.review_flow.skeletons import browse_skeleton
from cerebro.v2.ui.flet_app.pages.review_flow.state import ReviewFlowState
from cerebro.v2.ui.flet_app.pages.review_flow import trust_labels
from cerebro.v2.ui.flet_app.services.thumbnail_cache import TINY_BROWSE_EDGE, get_thumbnail_cache, is_image_path
from cerebro.v2.ui.flet_app.theme import ThemeTokens, fmt_size

_GRID_THUMB_EDGE = 140
_FILE_THUMB_EDGE = 88
_LIST_THUMB_EDGE = 44
_MAX_GROUP_CHECKBOXES = 6
_THUMB_LOAD_CAP = 64


class BrowseScreenView:
    def __init__(
        self,
        t: ThemeTokens,
        state: ReviewFlowState,
        *,
        on_back,
        on_open_inspect,
        on_open_group_detail,
        on_close_group_detail,
        on_toggle_file_mark,
        on_start_delete_ceremony,
        on_proceed_execute,
        reduce_motion: bool = False,
    ) -> None:
        self._t = t
        self._state = state
        self._reduce_motion = reduce_motion
        self._on_back = on_back
        self._on_open_inspect = on_open_inspect
        self._on_open_group_detail = on_open_group_detail
        self._on_close_group_detail = on_close_group_detail
        self._on_toggle_file_mark = on_toggle_file_mark
        self._on_start_delete_ceremony = on_start_delete_ceremony
        self._on_proceed_execute = on_proceed_execute
        self._group_marked_lines: dict[int, ft.Text] = {}
        self._list = ft.ListView(expand=True, spacing=6, padding=8, auto_scroll=False)
        self._group_grid = ft.GridView(
            expand=True,
            runs_count=4,
            max_extent=240,
            child_aspect_ratio=0.72,
            spacing=10,
            run_spacing=10,
            padding=8,
        )
        # Mount only one scroller at a time. Stacking ListView + GridView (both expand=True) let the
        # top GridView paint over the list while empty / mid-refresh — blank page after "Apply rule to all".
        self._browse_slot = ft.Container(expand=True, content=self._list)
        self._thumb_view_switch = ft.Switch(
            label="Thumbnail grid",
            value=(self._state.view_mode == "grid"),
            on_change=self._on_thumb_view_mode,
        )
        self._chip = ft.Container(visible=False)
        self._chip_row = ft.Container(visible=False)
        self._bottom_bar = ft.Container(visible=False)
        self._header_list = ft.Row(visible=True, alignment=ft.MainAxisAlignment.CENTER, spacing=12)
        self._header_detail = ft.Row(visible=False, alignment=ft.MainAxisAlignment.CENTER, spacing=12)
        self._toolbar = ft.Row(
            visible=True,
            alignment=ft.MainAxisAlignment.CENTER,
            spacing=12,
            wrap=True,
        )
        self._chunked: Optional[ChunkedViewBuilder[DuplicateGroup]] = None
        self._page: Optional[ft.Page] = None
        self._browse_thumb_gen = 0
        self._detail_grid: Optional[ft.GridView] = None
        self._mark_checkboxes: dict[str, ft.Checkbox] = {}
        self._mark_checkbox_groups: dict[str, int] = {}
        # Phase 3.1 — overflow banner
        self._overflow_banner: ft.Container = ft.Container(visible=False)
        # Phase 3.2 — page navigation
        self._page_nav: ft.Row = ft.Row(visible=False, alignment=ft.MainAxisAlignment.CENTER, spacing=8)
        self._root = self._build()

    def set_reduce_motion(self, value: bool) -> None:
        self._reduce_motion = bool(value)

    def apply_theme(self, t: ThemeTokens) -> None:
        self._t = t

    @property
    def root(self) -> ft.Column:
        return self._root

    @property
    def list_host(self) -> ft.Control:
        if self._state.browse_detail_group_id is not None:
            return self._list
        c = self._browse_slot.content
        return c if c is not None else self._list

    def attach_page(self, page: ft.Page) -> None:
        self._page = page
        self._chunked = ChunkedViewBuilder(page, REVIEW_GROUPS_CHUNK_CONFIG)

    def refresh(self, *, rebuild: bool = True) -> None:
        t = self._t
        in_detail = self._state.browse_detail_group_id is not None
        self._header_list.visible = not in_detail
        self._header_detail.visible = in_detail
        self._toolbar.visible = not in_detail

        grid_mode = self._state.view_mode == "grid" and not in_detail
        if not in_detail:
            self._thumb_view_switch.value = self._state.view_mode == "grid"

        # Phase 3.2 — use paged view; all_visible for count and navigation
        all_visible = self._state.visible_groups()
        groups = self._state.paged_visible_groups()
        total_visible = len(all_visible)
        n_del = self._state.cart_delete_count
        self._chip.content = ft.Text(f"{n_del} file(s) marked for removal", size=11, color=t.colors.fg)
        self._chip.visible = n_del > 0
        self._chip_row.visible = n_del > 0
        self._bottom_bar.visible = n_del > 0

        # Phase 3.1 — informational banner when results span multiple pages
        total_pages = max(1, (total_visible + self._state.page_size - 1) // self._state.page_size)
        if total_pages > 1:
            self._overflow_banner.content = ft.Text(
                f"{total_visible:,} groups — use filters to narrow results.",
                color=ft.Colors.BLUE_300,
                size=11,
            )
            self._overflow_banner.visible = True
        else:
            self._overflow_banner.visible = False

        # Phase 3.2 — page navigation bar
        if total_pages > 1:
            page_idx = self._state.page_index

            def _go_prev(_e=None) -> None:
                if self._state.page_index > 0:
                    self._state.page_index -= 1
                    self.refresh()

            def _go_next(_e=None) -> None:
                if self._state.page_index < total_pages - 1:
                    self._state.page_index += 1
                    self.refresh()

            self._page_nav.controls = [
                ft.TextButton("← Prev", on_click=_go_prev, disabled=(page_idx == 0)),
                ft.Text(f"Page {page_idx + 1} / {total_pages}", size=11, color=t.colors.fg_muted),
                ft.TextButton("Next →", on_click=_go_next, disabled=(page_idx >= total_pages - 1)),
            ]
            self._page_nav.visible = True
        else:
            self._page_nav.visible = False

        if not rebuild:
            self.sync_checkbox_marks()
            safe_update(self._chip)
            safe_update(self._chip_row)
            safe_update(self._bottom_bar)
            safe_update(self._overflow_banner)
            safe_update(self._page_nav)
            return

        self._browse_thumb_gen += 1
        gen = self._browse_thumb_gen
        self._mark_checkboxes.clear()
        self._mark_checkbox_groups.clear()
        self._group_marked_lines.clear()
        # Never call controls.clear() before ChunkedViewBuilder.render(): render bumps
        # generation (aborting in-flight async tails) and only then assigns host.controls.
        if in_detail:
            # Do not put the detail Column inside ListView — a single expand+scroll child often
            # lays out to zero height (blank). Use a plain expanded Container instead.
            self._group_grid.controls.clear()
            self._list.controls.clear()
            self._browse_slot.content = ft.Container(
                expand=True,
                padding=8,
                alignment=ft.Alignment(0, 0),
                content=self._build_detail_panel(),
            )
        elif not groups:
            self._group_grid.controls.clear()
            sk = browse_skeleton(t, reduce_motion=self._reduce_motion)
            self._list.controls = [ft.Container(content=sk, padding=8, expand=True)]
        elif self._chunked is None:
            if grid_mode:
                self._list.controls.clear()
                self._group_grid.controls = [self._build_group_grid_tile(g) for g in groups[:1000]]
            else:
                self._group_grid.controls.clear()
                self._list.controls = [self._build_group_row(g) for g in groups[:1000]]
        else:
            chunk_preset = RESULTS_GRID_CHUNK_CONFIG if grid_mode else REVIEW_GROUPS_CHUNK_CONFIG
            host = self._group_grid if grid_mode else self._list
            if grid_mode:
                self._list.controls.clear()
            else:
                self._group_grid.controls.clear()
            self._chunked.render(
                host,
                groups,
                card_builder=lambda g, _i: (
                    self._build_group_grid_tile(g) if grid_mode else self._build_group_row(g)
                ),
                config=chunk_preset,
                on_complete=lambda: safe_update(host),
                on_abort=lambda: safe_update(host),
            )

        if not in_detail:
            if not groups or not grid_mode:
                self._browse_slot.content = self._list
            else:
                self._browse_slot.content = self._group_grid
        safe_update(self._browse_slot)
        safe_update(self._chip)
        safe_update(self._chip_row)
        safe_update(self._bottom_bar)
        safe_update(self._overflow_banner)
        safe_update(self._page_nav)
        if groups and self._page is not None and hasattr(self._page, "run_task"):
            self._page.run_task(self._load_browse_thumbs_async, gen)

    def _sort_label(self) -> str:
        key = self._state.sort_key or "size"
        direction = "↓" if self._state.sort_desc else "↑"
        return f"Sort: {key.title()} {direction}"

    def _build(self) -> ft.Column:
        t = self._t
        self._header_list.controls = [
            ft.TextButton("← Overview", on_click=self._on_back),
            ft.Text(f"Duplicates ({len(self._state.scan_results)})", weight=ft.FontWeight.W_600),
            ft.OutlinedButton(
                "Remove selected…",
                icon=ft.icons.Icons.DELETE_OUTLINE,
                tooltip="Review and confirm before any files are moved",
                on_click=self._on_start_delete_ceremony,
            ),
        ]
        self._header_detail.controls = [
            ft.TextButton("← Back to groups", on_click=self._on_close_group_detail),
        ]
        self._toolbar.controls = [
            ft.Text(self._sort_label(), size=t.typography.size_sm, color=t.colors.fg_muted),
            self._thumb_view_switch,
            ft.Text(
                "Mark files with checkboxes, then Apply cleanup",
                size=t.typography.size_xs,
                color=t.colors.fg_muted,
                italic=True,
            ),
        ]
        self._chip = ft.Container(
            content=ft.Text("", size=11, text_align=ft.TextAlign.CENTER),
            padding=ft.padding.symmetric(horizontal=12, vertical=6),
        )
        self._chip_row = ft.Container(
            content=self._chip,
            alignment=ft.Alignment(0, 0),
            padding=ft.padding.only(top=8),
            visible=False,
        )
        self._bottom_bar = ft.Container(
            content=ft.FilledButton("Apply cleanup", on_click=self._on_proceed_execute),
            padding=12,
            alignment=ft.Alignment.CENTER,
        )
        return ft.Column(
            [
                ft.Container(
                    content=self._header_list,
                    alignment=ft.Alignment(0, 0),
                ),
                ft.Container(
                    content=self._header_detail,
                    alignment=ft.Alignment(0, 0),
                ),
                ft.Container(
                    content=self._toolbar,
                    alignment=ft.Alignment(0, 0),
                ),
                # Phase 3.1 — overflow banner
                self._overflow_banner,
                # Plain Column instead of Stack(expand): nested expand+Stack can lay out to
                # zero height on some Flet builds (blank main after apply-all).
                self._chip_row,
                ft.Container(
                    content=self._browse_slot,
                    expand=True,
                    alignment=ft.Alignment(0, 0),
                ),
                # Phase 3.2 — page navigation footer
                self._page_nav,
                self._bottom_bar,
            ],
            expand=True,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        )

    def _repaint_marks_surface(self) -> None:
        """Single paint for mark UI — avoids dozens of nested updates blanking ListView/GridView."""
        safe_update(self._chip)
        safe_update(self._chip_row)
        safe_update(self._bottom_bar)
        host = self._browse_slot.content
        if host is not None:
            safe_update(host)

    def _refresh_group_marked_lines(self, *, repaint: bool = True) -> None:
        for gid, label in list(self._group_marked_lines.items()):
            group = self._state.group_by_id(gid)
            if not group or not group.files:
                continue
            n_marked = sum(
                1 for f in group.files if self._file_marked_for_delete(str(f.path), gid)
            )
            primary = group.files[0]
            size = fmt_size(int(primary.size))
            kind = trust_labels.duplicate_kind_label(getattr(group, "similarity_type", "exact"))
            if self._state.view_mode == "grid" and self._state.browse_detail_group_id is None:
                label.value = f"{kind} · ×{len(group.files)} · {size} · {n_marked} marked"
            else:
                confidence = max(
                    float(getattr(f, "similarity", 1.0) or 1.0) for f in group.files
                )
                label.value = (
                    f"{kind} · {trust_labels.confidence_line(confidence)} · "
                    f"{n_marked}/{len(group.files)} marked · {size}"
                )
            if repaint:
                safe_update(label)

    def _on_thumb_view_mode(self, e: ft.ControlEvent) -> None:
        self._state.view_mode = "grid" if bool(getattr(e.control, "value", False)) else "list"
        self.refresh()

    def _file_marked_for_delete(self, path: str, group_id: int) -> bool:
        p = str(path)
        if p in self._state.marked_paths:
            return True
        sel = self._state.set_selections.get(group_id)
        return bool(sel and p in sel.deleted_paths)

    def _group_marked_line_for_list(
        self,
        gid: int,
        group: DuplicateGroup,
        kind: str,
        confidence: float,
        n_marked: int,
        n_files: int,
        size: str,
    ) -> ft.Text:
        t = self._t
        line = ft.Text(
            f"{kind} · {trust_labels.confidence_line(confidence)} · {n_marked}/{n_files} marked · {size}",
            size=t.typography.size_xs,
            color=t.colors.fg_muted,
        )
        self._group_marked_lines[gid] = line
        return line

    def sync_checkbox_marks(self, *, repaint: bool = True) -> None:
        """Update checkbox values after smart-rule apply without rebuilding tiles."""
        for path, cb in list(self._mark_checkboxes.items()):
            gid = self._mark_checkbox_groups.get(path)
            if gid is None:
                continue
            cb.value = self._file_marked_for_delete(path, gid)
        if repaint:
            self._repaint_marks_surface()

    def update_cart_chrome(self, *, repaint: bool = True) -> None:
        """Refresh chip + cleanup bar only — never rebuilds the group list (apply-all safe path)."""
        t = self._t
        n_del = self._state.cart_delete_count
        self._chip.content = ft.Text(f"{n_del} file(s) marked for removal", size=11, color=t.colors.fg)
        self._chip.visible = n_del > 0
        self._chip_row.visible = n_del > 0
        self._bottom_bar.visible = n_del > 0
        if repaint:
            safe_update(self._chip)
            safe_update(self._chip_row)
            safe_update(self._bottom_bar)

    def _build_file_thumb_tile(
        self,
        group: DuplicateGroup,
        f: DuplicateFile,
        *,
        edge: int = _FILE_THUMB_EDGE,
        show_name: bool = True,
    ) -> ft.Container:
        t = self._t
        gid = group.group_id
        p = str(f.path)
        prot = self._state.is_path_protected(p)
        checked = self._file_marked_for_delete(p, gid)
        mark_border = ft.border.all(2, t.colors.danger) if checked else ft.border.all(1, ft.Colors.with_opacity(0.35, t.colors.border))

        def _toggle(e: ft.ControlEvent, path_s: str = p, g: int = gid) -> None:
            self._on_toggle_file_mark(path_s, g, bool(getattr(e.control, "value", False)))

        cb = ft.Checkbox(value=checked, disabled=prot, on_change=_toggle)
        self._mark_checkboxes[p] = cb
        self._mark_checkbox_groups[p] = gid

        thumb_path = p if is_image_path(Path(p)) else None
        row_data: dict = {}
        if thumb_path:
            tiny_img = ft.Image(
                src=IMAGE_PLACEHOLDER_SRC,
                visible=False,
                width=edge,
                height=edge,
                fit=ft.BoxFit.COVER,
                border_radius=6,
            )
            thumb_stack = ft.Stack(
                [
                    ft.Container(
                        width=edge,
                        height=edge,
                        border_radius=6,
                        border=mark_border,
                        clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
                        content=tiny_img,
                    ),
                    ft.Container(
                        content=cb,
                        alignment=ft.Alignment(-1, -1),
                        padding=ft.padding.only(left=2, top=2),
                    ),
                ],
                clip_behavior=ft.ClipBehavior.NONE,
            )
            row_data = {"thumb_path": thumb_path, "grid_thumb_single": True, "hero_img": tiny_img, "thumb_edge": edge}
        else:
            thumb_stack = ft.Stack(
                [
                    ft.Container(
                        width=edge,
                        height=edge,
                        border_radius=6,
                        border=mark_border,
                        alignment=ft.Alignment.CENTER,
                        content=ft.Icon(ft.icons.Icons.INSERT_DRIVE_FILE_OUTLINED, size=edge // 2, color=t.colors.fg_muted),
                    ),
                    ft.Container(
                        content=cb,
                        alignment=ft.Alignment(-1, -1),
                        padding=ft.padding.only(left=2, top=2),
                    ),
                ],
            )

        name_line: list[ft.Control] = []
        if show_name:
            name_line.append(
                ft.Text(
                    f.path.name,
                    size=t.typography.size_xs,
                    max_lines=1,
                    overflow=ft.TextOverflow.ELLIPSIS,
                    text_align=ft.TextAlign.CENTER,
                    color=t.colors.fg,
                )
            )

        return ft.Container(
            content=ft.Column(
                [thumb_stack, *name_line],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=4,
                tight=True,
            ),
            width=edge + 8,
            data=row_data if row_data else None,
        )

    def _build_detail_panel(self) -> ft.Control:
        t = self._t
        gid = self._state.browse_detail_group_id
        if gid is None:
            return ft.Container()
        group = self._state.group_by_id(gid)
        if not group or not group.files:
            return ft.Text("This group is no longer available.", color=t.colors.fg_muted)

        primary = group.files[0]
        title = ft.Text(
            f"Files in “{primary.path.name}” (×{len(group.files)})",
            weight=ft.FontWeight.W_600,
            size=t.typography.size_sm,
            text_align=ft.TextAlign.CENTER,
        )
        hint = ft.Text(
            "Check thumbnails to mark files for removal, then use Apply cleanup.",
            size=t.typography.size_xs,
            color=t.colors.fg_muted,
            text_align=ft.TextAlign.CENTER,
        )
        self._detail_grid = ft.GridView(
            expand=True,
            runs_count=4,
            max_extent=_FILE_THUMB_EDGE + 24,
            child_aspect_ratio=0.78,
            spacing=12,
            run_spacing=12,
            padding=8,
            controls=[self._build_file_thumb_tile(group, f) for f in group.files],
        )
        return ft.Column(
            [
                title,
                hint,
                ft.Container(
                    content=self._detail_grid,
                    expand=True,
                    alignment=ft.Alignment(0, 0),
                ),
            ],
            spacing=8,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            expand=True,
        )

    def _collect_thumb_data_hosts(self, roots: list[ft.Control]) -> list[ft.Control]:
        found: list[ft.Control] = []

        def walk(ctrl: ft.Control) -> None:
            if isinstance(ctrl, ft.Container):
                data = getattr(ctrl, "data", None)
                if isinstance(data, dict) and data.get("thumb_path"):
                    found.append(ctrl)
            children: list[ft.Control] = []
            if isinstance(ctrl, ft.Container) and ctrl.content is not None:
                children = [ctrl.content]
            elif hasattr(ctrl, "controls"):
                try:
                    children = list(ctrl.controls or [])
                except Exception:
                    children = []
            for child in children:
                if child is not None:
                    walk(child)

        for root in roots:
            walk(root)
        return found

    def _build_group_hero_thumb(
        self,
        group: DuplicateGroup,
        *,
        grid_mode: bool,
    ) -> tuple[ft.Control, dict]:
        t = self._t
        primary = group.files[0] if group.files else None
        thumb_path = str(primary.path) if primary and is_image_path(Path(primary.path)) else None
        edge = _GRID_THUMB_EDGE if grid_mode else _LIST_THUMB_EDGE
        if thumb_path:
            if grid_mode:
                hero = ft.Image(
                    src=IMAGE_PLACEHOLDER_SRC,
                    visible=False,
                    width=edge,
                    height=edge,
                    fit=ft.BoxFit.COVER,
                    border_radius=6,
                )
                thumb_stack = ft.Container(
                    width=edge,
                    height=edge,
                    alignment=ft.Alignment.CENTER,
                    content=ft.Stack(
                        [hero],
                        clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
                    ),
                )
                row_data = {
                    "thumb_path": thumb_path,
                    "grid_thumb_single": True,
                    "hero_img": hero,
                    "thumb_edge": _GRID_THUMB_EDGE,
                }
            else:
                tiny_img = ft.Image(
                    src=IMAGE_PLACEHOLDER_SRC,
                    visible=False,
                    width=edge,
                    height=edge,
                    fit=ft.BoxFit.COVER,
                    border_radius=4,
                )
                full_img = ft.Image(
                    src=IMAGE_PLACEHOLDER_SRC,
                    visible=False,
                    width=edge,
                    height=edge,
                    fit=ft.BoxFit.COVER,
                    border_radius=4,
                )
                full_wrap = ft.Container(content=full_img, opacity=0.0)
                thumb_stack = ft.Container(
                    width=edge + 4,
                    height=edge + 4,
                    alignment=ft.Alignment.CENTER,
                    content=ft.Stack(
                        [tiny_img, full_wrap],
                        clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
                    ),
                )
                row_data = {
                    "thumb_path": thumb_path,
                    "tiny_img": tiny_img,
                    "full_img": full_img,
                    "full_wrap": full_wrap,
                }
            return thumb_stack, row_data
        icon_size = 40 if grid_mode else 22
        placeholder = ft.Container(
            width=edge,
            height=edge,
            alignment=ft.Alignment.CENTER,
            border_radius=6,
            border=ft.border.all(1, ft.Colors.with_opacity(0.35, t.colors.border)),
            content=ft.Icon(ft.icons.Icons.INSERT_DRIVE_FILE_OUTLINED, size=icon_size, color=t.colors.fg_muted),
        )
        return placeholder, {}

    def _build_file_checkbox_row(self, group: DuplicateGroup) -> ft.Control:
        t = self._t
        gid = group.group_id
        items: list[ft.Control] = []
        overflow = 0
        for i, f in enumerate(group.files):
            if i >= _MAX_GROUP_CHECKBOXES:
                overflow = len(group.files) - _MAX_GROUP_CHECKBOXES
                break
            p = str(f.path)
            prot = self._state.is_path_protected(p)
            checked = self._file_marked_for_delete(p, gid)

            def _toggle(e: ft.ControlEvent, path_s: str = p, g: int = gid) -> None:
                self._on_toggle_file_mark(path_s, g, bool(getattr(e.control, "value", False)))

            cb = ft.Checkbox(value=checked, disabled=prot, on_change=_toggle)
            self._mark_checkboxes[p] = cb
            self._mark_checkbox_groups[p] = gid
            items.append(cb)
        if overflow > 0:
            items.append(
                ft.Text(f"+{overflow}", size=t.typography.size_xs - 1, color=t.colors.fg_muted)
            )
        return ft.Row(
            items,
            spacing=2,
            wrap=True,
            alignment=ft.MainAxisAlignment.CENTER,
            run_spacing=2,
        )

    async def _load_browse_thumbs_async(self, gen: int) -> None:
        if self._page is None:
            return
        cache = get_thumbnail_cache()
        loop = asyncio.get_running_loop()
        pending_updates: list[ft.Control] = []
        roots: list[ft.Control] = []
        if self._state.browse_detail_group_id is not None and self._detail_grid is not None:
            roots = list(self._detail_grid.controls)
        else:
            host = self._browse_slot.content
            if host is not None:
                roots = list(getattr(host, "controls", []) or [])
        hosts = self._collect_thumb_data_hosts(roots)
        if not hosts:
            return
        loaded = 0
        for ctrl in hosts:
            if loaded >= _THUMB_LOAD_CAP:
                break
            if gen != self._browse_thumb_gen:
                return
            data = ctrl.data
            path = data.get("thumb_path")
            if not path:
                continue
            if data.get("grid_thumb_single"):
                hero = data.get("hero_img")
                edge = int(data.get("thumb_edge") or _GRID_THUMB_EDGE)
                if hero is None:
                    continue
                if hero.visible and hero.src and IMAGE_PLACEHOLDER_SRC not in str(hero.src):
                    continue
                p = Path(str(path))
                b64 = await loop.run_in_executor(cache._pool, cache.get_preview_tiny_base64, p, edge)
                if gen != self._browse_thumb_gen:
                    return
                if b64:
                    hero.visible = True
                    hero.src = f"data:image/jpeg;base64,{b64}"
                    pending_updates.append(hero)
                    loaded += 1
                if len(pending_updates) >= 12:
                    self._safe_update_thumb_hosts()
                    pending_updates.clear()
                continue
            tiny_img = data.get("tiny_img")
            full_img = data.get("full_img")
            full_wrap = data.get("full_wrap")
            if tiny_img is None or full_img is None or full_wrap is None:
                continue
            if tiny_img.visible and tiny_img.src and IMAGE_PLACEHOLDER_SRC not in str(tiny_img.src):
                continue
            p = Path(str(path))
            tiny_b64 = await loop.run_in_executor(cache._pool, cache.get_preview_tiny_base64, p, TINY_BROWSE_EDGE)
            if gen != self._browse_thumb_gen:
                return
            if tiny_b64:
                tiny_img.visible = True
                tiny_img.src = f"data:image/jpeg;base64,{tiny_b64}"
                pending_updates.append(tiny_img)
                loaded += 1
            full_b64 = await loop.run_in_executor(cache._pool, cache.get_base64, p)
            if gen != self._browse_thumb_gen:
                return
            if full_b64:
                full_img.visible = True
                full_img.src = f"data:image/jpeg;base64,{full_b64}"
                if self._reduce_motion:
                    full_wrap.opacity = 1.0
                else:
                    full_wrap.opacity = 0.0
                    full_wrap.animate_opacity = ft.Animation(200, ft.AnimationCurve.EASE_OUT)
                    full_wrap.opacity = 1.0
                pending_updates.append(full_wrap)
                pending_updates.append(full_img)
                loaded += 1
            if len(pending_updates) >= 12:
                self._safe_update_thumb_hosts()
                pending_updates.clear()
        if pending_updates:
            self._safe_update_thumb_hosts()
        if loaded >= _THUMB_LOAD_CAP and gen == self._browse_thumb_gen and self._page is not None:
            self._page.run_task(self._load_browse_thumbs_async, gen)

    def _safe_update_thumb_hosts(self) -> None:
        # Update only the affected list/grid host, not the whole page.
        # Full page.update() here races with apply-all tile rebuild and causes blank canvas.
        if self._state.browse_detail_group_id is not None and self._detail_grid is not None:
            safe_update(self._detail_grid)
        else:
            host = self._browse_slot.content
            if host is not None:
                safe_update(host)

    def _build_group_grid_tile(self, group: DuplicateGroup) -> ft.Control:
        t = self._t
        gid = group.group_id
        primary = group.files[0] if group.files else None
        name = primary.path.name if primary else f"Group {gid}"
        size = fmt_size(int(primary.size)) if primary else "0 B"
        protected = any(self._state.is_path_protected(str(f.path)) for f in group.files)
        n_marked = sum(1 for f in group.files if self._file_marked_for_delete(str(f.path), gid))
        confidence = max(float(getattr(f, "similarity", 1.0) or 1.0) for f in group.files) if group.files else 1.0
        kind = trust_labels.duplicate_kind_label(getattr(group, "similarity_type", "exact"))
        hero, row_data = self._build_group_hero_thumb(group, grid_mode=True)

        title = ft.Text(
            name,
            size=t.typography.size_sm,
            max_lines=2,
            overflow=ft.TextOverflow.ELLIPSIS,
            text_align=ft.TextAlign.CENTER,
        )
        sub = ft.Text(
            f"{kind} · ×{len(group.files)} · {size} · {n_marked} marked",
            size=t.typography.size_xs,
            color=t.colors.fg_muted,
            text_align=ft.TextAlign.CENTER,
        )
        self._group_marked_lines[gid] = sub
        meta = ft.Text(
            trust_labels.confidence_line(confidence),
            size=t.typography.size_xs - 1,
            color=t.colors.fg_muted,
            text_align=ft.TextAlign.CENTER,
        )
        return ft.Container(
            content=ft.Column(
                [
                    ft.Container(content=hero, alignment=ft.Alignment.CENTER),
                    self._build_file_checkbox_row(group),
                    title,
                    sub,
                    meta,
                    ft.Row(
                        [
                            ft.Icon(ft.icons.Icons.SHIELD, size=14, color=t.colors.warning, visible=protected),
                            ft.TextButton("Open set", on_click=lambda e, g=gid: self._on_open_group_detail(g)),
                            ft.IconButton(
                                icon=ft.icons.Icons.ARROW_FORWARD,
                                tooltip="Inspect side-by-side",
                                on_click=lambda e, g=gid: self._on_open_inspect(g),
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.CENTER,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                ],
                spacing=6,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                tight=True,
            ),
            padding=ft.padding.symmetric(vertical=6, horizontal=4),
            data=row_data if row_data else None,
        )

    def _build_group_row(self, group: DuplicateGroup) -> ft.Control:
        t = self._t
        gid = group.group_id
        primary = group.files[0] if group.files else None
        name = primary.path.name if primary else f"Group {gid}"
        size = fmt_size(int(primary.size)) if primary else "0 B"
        path = str(primary.path.parent) if primary else ""
        protected = any(self._state.is_path_protected(str(f.path)) for f in group.files)
        n_marked = sum(1 for f in group.files if self._file_marked_for_delete(str(f.path), gid))
        confidence = max(float(getattr(f, "similarity", 1.0) or 1.0) for f in group.files) if group.files else 1.0
        kind = trust_labels.duplicate_kind_label(getattr(group, "similarity_type", "exact"))
        hero, row_data = self._build_group_hero_thumb(group, grid_mode=False)

        return ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            hero,
                            ft.Column(
                                [
                                    ft.Text(name, weight=ft.FontWeight.W_600),
                                    self._group_marked_line_for_list(
                                        gid, group, kind, confidence, n_marked, len(group.files), size
                                    ),
                                    ft.Text(path, size=t.typography.size_xs, color=t.colors.fg_muted),
                                ],
                                spacing=2,
                                expand=True,
                            ),
                            self._build_file_checkbox_row(group),
                            ft.Icon(ft.icons.Icons.SHIELD, size=16, color=t.colors.warning, visible=protected),
                            ft.IconButton(
                                icon=ft.icons.Icons.ARROW_FORWARD,
                                tooltip="Inspect side-by-side",
                                on_click=lambda e, g=gid: self._on_open_inspect(g),
                            ),
                        ],
                        spacing=8,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Row(
                        [
                            ft.TextButton("Open set", on_click=lambda e, g=gid: self._on_open_group_detail(g)),
                        ],
                        alignment=ft.MainAxisAlignment.CENTER,
                    ),
                ],
                spacing=4,
            ),
            padding=ft.padding.symmetric(vertical=8, horizontal=4),
            data=row_data if row_data else None,
        )
