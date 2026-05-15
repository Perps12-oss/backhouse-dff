from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Callable, List, Optional

import flet as ft

from cerebro.engines.base_engine import DuplicateGroup
from cerebro.v2.ui.flet_app.components.common.chunked_view import ChunkedViewBuilder, REVIEW_GROUPS_CHUNK_CONFIG
from cerebro.v2.ui.flet_app.components.common.safe_controls import IMAGE_PLACEHOLDER_SRC, safe_update
from cerebro.v2.ui.flet_app.pages.review_flow.skeletons import browse_skeleton
from cerebro.v2.ui.flet_app.pages.review_flow.state import ReviewFlowState
from cerebro.v2.ui.flet_app.services.thumbnail_cache import TINY_BROWSE_EDGE, get_thumbnail_cache, is_image_path
from cerebro.v2.ui.flet_app.theme import ThemeTokens, fmt_size


class BrowseScreenView:
    def __init__(
        self,
        t: ThemeTokens,
        state: ReviewFlowState,
        *,
        on_back,
        on_toggle_set,
        on_toggle_expand,
        on_open_inspect,
        on_open_cart,
        reduce_motion: bool = False,
    ) -> None:
        self._t = t
        self._state = state
        self._reduce_motion = reduce_motion
        self._on_back = on_back
        self._on_toggle_set = on_toggle_set
        self._on_toggle_expand = on_toggle_expand
        self._on_open_inspect = on_open_inspect
        self._on_open_cart = on_open_cart
        self._list = ft.ListView(expand=True, spacing=6, padding=8, auto_scroll=False)
        self._chip = ft.Container(visible=False)
        self._bottom_bar = ft.Container(visible=False)
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
    def list_host(self) -> ft.ListView:
        return self._list

    def attach_page(self, page: ft.Page) -> None:
        self._page = page
        self._chunked = ChunkedViewBuilder(page, REVIEW_GROUPS_CHUNK_CONFIG)

    def refresh(self) -> None:
        groups = self._state.visible_groups()
        self._browse_thumb_gen += 1
        gen = self._browse_thumb_gen
        self._list.controls.clear()
        if not groups:
            sk = browse_skeleton(self._t, reduce_motion=self._reduce_motion)
            self._list.controls.append(
                ft.Container(content=sk, padding=8, expand=True),
            )
        elif self._chunked is None:
            for g in groups[:1000]:
                self._list.controls.append(self._build_row(g))
        else:
            self._chunked.render(
                self._list,
                groups,
                card_builder=lambda g, _i: self._build_row(g),
                on_complete=lambda: safe_update(self._list),
            )
        selected = self._state.selected_set_count()
        marked = len(self._state.marked_paths)
        self._chip.content = ft.Text(f"{selected} sets selected • {marked} files marked", size=11, color=self._t.colors.fg)
        self._chip.visible = selected > 0 or marked > 0
        self._bottom_bar.visible = marked > 0
        if marked > 0:
            self._bottom_bar.content = ft.FilledButton(
                f"Review {marked}",
                icon=ft.icons.Icons.SHOPPING_CART_OUTLINED,
                on_click=self._on_open_cart,
            )
        safe_update(self._chip)
        safe_update(self._bottom_bar)
        safe_update(self._list)
        if groups and self._page is not None and hasattr(self._page, "run_task"):
            self._page.run_task(self._load_browse_thumbs_async, gen)

    def _build(self) -> ft.Column:
        t = self._t
        header = ft.Row(
            [
                ft.TextButton("← Overview", on_click=self._on_back),
                ft.Text(f"Duplicates ({len(self._state.scan_results)})", weight=ft.FontWeight.W_600),
                ft.Container(expand=True),
            ],
        )
        toolbar = ft.Row(
            [
                ft.Text("List", size=t.typography.size_sm, color=t.colors.fg_muted),
                ft.Text("Sort: Size", size=t.typography.size_sm, color=t.colors.fg_muted),
                ft.TextButton("Select All", on_click=lambda e: self._select_all_visible()),
            ],
        )
        self._chip = ft.Container(
            content=ft.Text("", size=11),
            padding=ft.padding.symmetric(horizontal=12, vertical=6),
            border_radius=20,
            bgcolor=ft.Colors.with_opacity(0.12, t.colors.primary),
        )
        self._bottom_bar = ft.Container(
            content=ft.FilledButton("Review", on_click=self._on_open_cart),
            padding=12,
            alignment=ft.Alignment.CENTER,
        )
        return ft.Column(
            [
                header,
                toolbar,
                ft.Stack(
                    [self._list, ft.Container(content=self._chip, top=8, right=8)],
                    expand=True,
                ),
                self._bottom_bar,
            ],
            expand=True,
        )

    def _select_all_visible(self) -> None:
        for g in self._state.visible_groups():
            self._state.selected_set_ids.add(g.group_id)
        self.refresh()

    def _checkbox_change(self, e: ft.ControlEvent, gid: int) -> None:
        self._on_toggle_set(gid)
        if self._reduce_motion:
            return
        wrap = e.control.parent
        if not isinstance(wrap, ft.Container):
            return
        try:
            wrap.animate_scale = ft.Animation(150, ft.AnimationCurve.EASE_OUT)
            wrap.scale = 1.12
            wrap.update()
            wrap.scale = 1.0
            wrap.update()
        except Exception:
            try:
                wrap.bgcolor = ft.Colors.with_opacity(0.2, self._t.colors.primary)
                wrap.update()
                wrap.bgcolor = None
                wrap.update()
            except Exception:
                pass

    async def _load_browse_thumbs_async(self, gen: int) -> None:
        if self._page is None:
            return
        cache = get_thumbnail_cache()
        loop = asyncio.get_running_loop()
        pending_updates: list[ft.Control] = []
        for ctrl in list(self._list.controls):
            if gen != self._browse_thumb_gen:
                return
            data = getattr(ctrl, "data", None)
            if not isinstance(data, dict):
                continue
            path = data.get("thumb_path")
            if not path:
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
                safe_update(self._list)
                pending_updates.clear()
        if pending_updates:
            safe_update(self._list)

    def _build_row(self, group: DuplicateGroup) -> ft.Control:
        t = self._t
        gid = group.group_id
        primary = group.files[0] if group.files else None
        name = primary.path.name if primary else f"Group {gid}"
        size = fmt_size(int(primary.size)) if primary else "0 B"
        path = str(primary.path.parent) if primary else ""
        checked = gid in self._state.selected_set_ids
        expanded = gid in self._state.expanded_set_ids
        protected = any(self._state.is_path_protected(str(f.path)) for f in group.files)
        marked = any(str(f.path) in self._state.marked_paths for f in group.files)
        confidence = max(float(getattr(f, "similarity", 1.0) or 1.0) for f in group.files) if group.files else 1.0
        badge_color = t.colors.success if confidence >= 0.99 else t.colors.warning
        name_style = ft.TextStyle(decoration=ft.TextDecoration.LINE_THROUGH if marked and self._state.dry_run else None)
        members: List[ft.Control] = []
        if expanded:
            for f in group.files:
                members.append(
                    ft.Text(f"  • {f.path.name} ({fmt_size(int(f.size))})", size=t.typography.size_xs, color=t.colors.fg_muted)
                )

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

        mark_border = ft.border.only(left=ft.BorderSide(4, t.colors.danger)) if marked else None

        cb = ft.Checkbox(value=checked, on_change=lambda e, g=gid: self._checkbox_change(e, g))
        cb_wrap = ft.Container(content=cb, scale=1.0)

        row_inner = ft.Row(
            [
                cb_wrap,
                thumb_cell if thumb_cell else ft.Container(width=0),
                ft.Icon(ft.icons.Icons.INSERT_DRIVE_FILE_OUTLINED, size=18, color=t.colors.primary),
                ft.Icon(ft.icons.Icons.SHIELD, size=16, color=t.colors.warning, visible=protected),
                ft.Text(name, expand=True, style=name_style),
                ft.Text(f"×{len(group.files)}", color=t.colors.primary),
                ft.Text(f"{confidence:.0%}", color=badge_color, size=t.typography.size_xs),
                ft.Text(size, color=t.colors.fg_muted),
                ft.IconButton(
                    icon=ft.icons.Icons.ARROW_FORWARD,
                    tooltip="Inspect",
                    on_click=lambda e, g=gid: self._on_open_inspect(g),
                ),
                ft.IconButton(
                    icon=ft.icons.Icons.EXPAND_MORE if not expanded else ft.icons.Icons.EXPAND_LESS,
                    on_click=lambda e, g=gid: self._on_toggle_expand(g),
                ),
            ],
            spacing=8,
        )
        row = ft.Container(
            content=ft.Column(
                [
                    row_inner,
                    ft.Text(path, size=t.typography.size_xs, color=t.colors.fg_muted),
                    *members,
                ],
                spacing=4,
            ),
            padding=10,
            border_radius=8,
            border=mark_border or ft.border.all(1, t.colors.border),
            bgcolor=t.colors.bg2,
            on_click=lambda e, g=gid: self._on_open_inspect(g),
            data=row_data if row_data else None,
        )
        return row
