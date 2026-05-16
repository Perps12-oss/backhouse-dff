from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Callable, List, Optional

import flet as ft

from cerebro.engines.base_engine import DuplicateGroup
from cerebro.v2.ui.flet_app.components.common.chunked_view import (
    ChunkedViewBuilder,
    RESULTS_GRID_CHUNK_CONFIG,
    REVIEW_GROUPS_CHUNK_CONFIG,
)
from cerebro.v2.ui.flet_app.components.common.safe_controls import IMAGE_PLACEHOLDER_SRC, safe_update
from cerebro.v2.ui.flet_app.pages.review.smart_rules import RULE_LABELS
from cerebro.v2.ui.flet_app.pages.review_flow.skeletons import browse_skeleton
from cerebro.v2.ui.flet_app.pages.review_flow.state import ReviewFlowState
from cerebro.v2.ui.flet_app.pages.review_flow import trust_labels
from cerebro.v2.ui.flet_app.services.thumbnail_cache import TINY_BROWSE_EDGE, get_thumbnail_cache, is_image_path
from cerebro.v2.ui.flet_app.theme import ThemeTokens, fmt_size

_GRID_THUMB_EDGE = 200


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
        on_apply_smart_rule_all,
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
        self._on_apply_smart_rule_all = on_apply_smart_rule_all
        self._on_start_delete_ceremony = on_start_delete_ceremony
        self._on_proceed_execute = on_proceed_execute
        self._smart_rule: str = RULE_LABELS[0][0]
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
        self._bottom_bar = ft.Container(visible=False)
        self._header_list = ft.Row(visible=True)
        self._header_detail = ft.Row(visible=False)
        self._toolbar = ft.Row(visible=True)
        self._chunked: Optional[ChunkedViewBuilder[DuplicateGroup]] = None
        self._page: Optional[ft.Page] = None
        self._browse_thumb_gen = 0
        self._root = self._build()

    def set_reduce_motion(self, value: bool) -> None:
        self._reduce_motion = bool(value)

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

    def refresh(self) -> None:
        t = self._t
        in_detail = self._state.browse_detail_group_id is not None
        self._header_list.visible = not in_detail
        self._header_detail.visible = in_detail
        self._toolbar.visible = not in_detail
        safe_update(self._header_list)
        safe_update(self._header_detail)
        safe_update(self._toolbar)

        grid_mode = self._state.view_mode == "grid" and not in_detail
        if not in_detail:
            self._thumb_view_switch.value = self._state.view_mode == "grid"
            safe_update(self._thumb_view_switch)

        groups = self._state.visible_groups()
        self._browse_thumb_gen += 1
        gen = self._browse_thumb_gen
        # Never call controls.clear() before ChunkedViewBuilder.render(): render bumps
        # generation (aborting in-flight async tails) and only then assigns host.controls.
        # A clear-then-gap left the list empty on screen and caused "blank after Smart select"
        # when refresh ran twice close together (apply rule + parent safe_update).
        if in_detail:
            # Do not put the detail Column inside ListView — a single expand+scroll child often
            # lays out to zero height (blank). Use a plain expanded Container instead.
            self._group_grid.controls.clear()
            self._list.controls.clear()
            self._browse_slot.content = ft.Container(
                expand=True,
                padding=8,
                alignment=ft.Alignment.TOP_LEFT,
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

        n_del = len(self._state.cart_buckets()["delete"])
        self._chip.content = ft.Text(f"{n_del} file(s) marked for removal", size=11, color=t.colors.fg)
        self._chip.visible = n_del > 0
        self._bottom_bar.visible = n_del > 0
        safe_update(self._chip)
        safe_update(self._bottom_bar)
        safe_update(self._list)
        safe_update(self._group_grid)
        if not in_detail and groups and self._page is not None and hasattr(self._page, "run_task"):
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
            ft.Container(expand=True),
            ft.OutlinedButton(
                "Remove selected…",
                icon=ft.icons.Icons.DELETE_OUTLINE,
                tooltip="Review and confirm before any files are moved",
                on_click=self._on_start_delete_ceremony,
            ),
        ]
        self._header_detail.controls = [
            ft.TextButton("← Back to groups", on_click=self._on_close_group_detail),
            ft.Container(expand=True),
        ]
        self._toolbar.controls = [
            ft.Text(self._sort_label(), size=t.typography.size_sm, color=t.colors.fg_muted),
            self._thumb_view_switch,
            ft.Dropdown(
                label="Smart select",
                width=260,
                dense=True,
                options=[ft.dropdown.Option(key, label) for key, label in RULE_LABELS],
                value=self._smart_rule,
                on_select=self._on_smart_rule_change,
            ),
            ft.OutlinedButton(
                "Apply rule to all",
                on_click=lambda _e: self._on_apply_smart_rule_all(self._smart_rule),
            ),
        ]
        self._chip = ft.Container(
            content=ft.Text("", size=11),
            padding=ft.padding.symmetric(horizontal=12, vertical=6),
            border_radius=20,
            bgcolor=ft.Colors.with_opacity(0.12, t.colors.primary),
        )
        self._bottom_bar = ft.Container(
            content=ft.FilledButton("Apply cleanup", on_click=self._on_proceed_execute),
            padding=12,
            alignment=ft.Alignment.CENTER,
        )
        return ft.Column(
            [
                self._header_list,
                self._header_detail,
                self._toolbar,
                ft.Stack(
                    [
                        self._browse_slot,
                        ft.Container(content=self._chip, top=8, right=8),
                    ],
                    expand=True,
                ),
                self._bottom_bar,
            ],
            expand=True,
        )

    def _on_smart_rule_change(self, e: ft.ControlEvent) -> None:
        v = getattr(e.control, "value", None)
        if v:
            self._smart_rule = str(v)

    def _on_thumb_view_mode(self, e: ft.ControlEvent) -> None:
        self._state.view_mode = "grid" if bool(getattr(e.control, "value", False)) else "list"
        self.refresh()

    def _file_marked_for_delete(self, path: str, group_id: int) -> bool:
        p = str(path)
        if p in self._state.marked_paths:
            return True
        sel = self._state.set_selections.get(group_id)
        return bool(sel and p in sel.deleted_paths)

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
        )
        hint = ft.Text(
            "Check = mark for removal. Use Smart select → Apply on the group list to set candidates by rule, then adjust here.",
            size=t.typography.size_xs,
            color=t.colors.fg_muted,
        )
        rows: List[ft.Control] = []
        for f in group.files:
            p = str(f.path)
            prot = self._state.is_path_protected(p)
            checked = self._file_marked_for_delete(p, group.group_id)
            reason = trust_labels.protected_skip_label() if prot else trust_labels.selection_reason_for_file(
                group, f, smart_rule_key=self._smart_rule
            )

            def _toggle(e: ft.ControlEvent, path_s: str = p, g: int = group.group_id) -> None:
                self._on_toggle_file_mark(path_s, g, bool(getattr(e.control, "value", False)))

            rows.append(
                ft.Container(
                    padding=ft.padding.symmetric(vertical=4, horizontal=8),
                    border_radius=6,
                    border=ft.border.all(1, t.colors.border),
                    bgcolor=t.colors.bg2,
                    content=ft.Row(
                        [
                            ft.Checkbox(value=checked, disabled=prot, on_change=_toggle),
                            ft.Column(
                                [
                                    ft.Text(f.path.name, size=t.typography.size_sm),
                                    ft.Text(str(f.path.parent), size=t.typography.size_xs, color=t.colors.fg_muted),
                                    ft.Text(reason, size=t.typography.size_xs, color=t.colors.fg_muted),
                                ],
                                expand=True,
                                spacing=0,
                            ),
                            ft.Text(fmt_size(int(f.size)), size=t.typography.size_xs, color=t.colors.fg_muted),
                            ft.Icon(ft.icons.Icons.SHIELD, size=14, color=t.colors.warning, visible=prot),
                        ],
                        spacing=8,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                )
            )
        return ft.Column([title, hint, *rows], spacing=8, scroll=ft.ScrollMode.AUTO, expand=True)

    async def _load_browse_thumbs_async(self, gen: int) -> None:
        if self._page is None:
            return
        cache = get_thumbnail_cache()
        loop = asyncio.get_running_loop()
        pending_updates: list[ft.Control] = []
        host = self._browse_slot.content
        if host is None or self._state.browse_detail_group_id is not None:
            return
        for ctrl in list(host.controls):
            if gen != self._browse_thumb_gen:
                return
            data = getattr(ctrl, "data", None)
            if not isinstance(data, dict):
                continue
            path = data.get("thumb_path")
            if not path:
                continue
            if data.get("grid_thumb_single"):
                hero = data.get("hero_img")
                edge = int(data.get("thumb_edge") or _GRID_THUMB_EDGE)
                if hero is None:
                    continue
                p = Path(str(path))
                b64 = await loop.run_in_executor(cache._pool, cache.get_preview_tiny_base64, p, edge)
                if gen != self._browse_thumb_gen:
                    return
                if b64:
                    hero.visible = True
                    hero.src = f"data:image/jpeg;base64,{b64}"
                    pending_updates.append(hero)
                if len(pending_updates) >= 12:
                    safe_update(host)
                    pending_updates.clear()
                continue
            tiny_img = data.get("tiny_img")
            full_img = data.get("full_img")
            full_wrap = data.get("full_wrap")
            if tiny_img is None or full_img is None or full_wrap is None:
                continue
            p = Path(str(path))
            tiny_b64 = await loop.run_in_executor(cache._pool, cache.get_preview_tiny_base64, p, TINY_BROWSE_EDGE)
            if gen != self._browse_thumb_gen:
                return
            if tiny_b64:
                tiny_img.visible = True
                tiny_img.src = f"data:image/jpeg;base64,{tiny_b64}"
                pending_updates.append(tiny_img)
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
            if len(pending_updates) >= 12:
                safe_update(host)
                pending_updates.clear()
        if pending_updates:
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

        thumb_path = str(primary.path) if primary and is_image_path(Path(primary.path)) else None
        row_data: dict = {}
        thumb_h = 140.0
        if thumb_path:
            hero = ft.Image(
                src=IMAGE_PLACEHOLDER_SRC,
                visible=False,
                width=thumb_h,
                height=thumb_h,
                fit=ft.BoxFit.COVER,
                border_radius=6,
            )
            row_data = {
                "thumb_path": thumb_path,
                "grid_thumb_single": True,
                "hero_img": hero,
                "thumb_edge": _GRID_THUMB_EDGE,
            }
            thumb_stack = ft.Container(
                width=thumb_h,
                height=thumb_h,
                alignment=ft.Alignment.CENTER,
                content=ft.Stack(
                    [
                        ft.Container(
                            width=thumb_h,
                            height=thumb_h,
                            border_radius=6,
                            bgcolor=t.colors.bg,
                        ),
                        hero,
                    ],
                    clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
                ),
            )
        else:
            thumb_stack = ft.Container(
                width=thumb_h,
                height=thumb_h,
                alignment=ft.Alignment.CENTER,
                border_radius=6,
                bgcolor=t.colors.bg,
                content=ft.Icon(ft.icons.Icons.INSERT_DRIVE_FILE_OUTLINED, size=48, color=t.colors.fg_muted),
            )

        mark_border = ft.border.all(3, t.colors.danger) if n_marked > 0 else ft.border.all(1, t.colors.border)

        title = ft.Text(
            name,
            size=t.typography.size_sm,
            max_lines=2,
            overflow=ft.TextOverflow.ELLIPSIS,
        )
        sub = ft.Text(
            f"{kind} · ×{len(group.files)} · {size}",
            size=t.typography.size_xs,
            color=t.colors.fg_muted,
        )
        meta = ft.Text(
            trust_labels.confidence_line(confidence),
            size=t.typography.size_xs - 1,
            color=t.colors.fg_muted,
        )
        inspect_btn = ft.IconButton(
            icon=ft.icons.Icons.ARROW_FORWARD,
            tooltip="Inspect side-by-side",
            on_click=lambda e, g=gid: self._on_open_inspect(g),
        )
        return ft.Container(
            content=ft.Column(
                [
                    ft.Container(content=thumb_stack, alignment=ft.Alignment.CENTER),
                    title,
                    sub,
                    meta,
                    ft.Row(
                        [
                            ft.Icon(ft.icons.Icons.SHIELD, size=14, color=t.colors.warning, visible=protected),
                            ft.Container(expand=True),
                            inspect_btn,
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                ],
                spacing=4,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                tight=True,
            ),
            padding=8,
            border_radius=8,
            border=mark_border,
            bgcolor=t.colors.bg2,
            ink=True,
            on_click=lambda e, g=gid: self._on_open_group_detail(g),
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

        thumb_path = str(primary.path) if primary and is_image_path(Path(primary.path)) else None
        thumb_cell: Optional[ft.Control] = None
        row_data: dict = {}
        if thumb_path:
            tiny_img = ft.Image(
                src=IMAGE_PLACEHOLDER_SRC,
                visible=False,
                width=44,
                height=44,
                fit=ft.BoxFit.COVER,
                border_radius=4,
            )
            full_img = ft.Image(
                src=IMAGE_PLACEHOLDER_SRC,
                visible=False,
                width=44,
                height=44,
                fit=ft.BoxFit.COVER,
                border_radius=4,
            )
            full_wrap = ft.Container(content=full_img, opacity=0.0)
            thumb_cell = ft.Container(
                width=48,
                height=48,
                alignment=ft.Alignment.CENTER,
                content=ft.Stack(
                    [
                        ft.Container(
                            width=44,
                            height=44,
                            border_radius=4,
                            bgcolor=t.colors.bg,
                        ),
                        tiny_img,
                        full_wrap,
                    ],
                    clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
                ),
            )
            row_data = {"thumb_path": thumb_path, "tiny_img": tiny_img, "full_img": full_img, "full_wrap": full_wrap}

        mark_border = ft.border.only(left=ft.BorderSide(4, t.colors.danger)) if n_marked > 0 else None

        row_inner = ft.Row(
            [
                ft.Container(width=8),
                thumb_cell if thumb_cell else ft.Container(width=0),
                ft.Icon(ft.icons.Icons.INSERT_DRIVE_FILE_OUTLINED, size=18, color=t.colors.primary),
                ft.Icon(ft.icons.Icons.SHIELD, size=16, color=t.colors.warning, visible=protected),
                ft.Column(
                    [
                        ft.Text(name),
                        ft.Text(
                            f"{kind} · {trust_labels.confidence_line(confidence)} · {n_marked}/{len(group.files)} marked",
                            size=t.typography.size_xs,
                            color=t.colors.fg_muted,
                        ),
                    ],
                    spacing=2,
                    expand=True,
                ),
                ft.Text(f"×{len(group.files)}", color=t.colors.primary),
                ft.Text(size, color=t.colors.fg_muted),
                ft.IconButton(
                    icon=ft.icons.Icons.ARROW_FORWARD,
                    tooltip="Inspect side-by-side",
                    on_click=lambda e, g=gid: self._on_open_inspect(g),
                ),
            ],
            spacing=8,
        )
        row = ft.Container(
            content=ft.Column(
                [
                    row_inner,
                    ft.Text(path, size=t.typography.size_xs, color=t.colors.fg_muted),
                ],
                spacing=4,
            ),
            padding=10,
            border_radius=8,
            border=mark_border or ft.border.all(1, t.colors.border),
            bgcolor=t.colors.bg2,
            ink=True,
            on_click=lambda e, g=gid: self._on_open_group_detail(g),
            data=row_data if row_data else None,
        )
        return row
