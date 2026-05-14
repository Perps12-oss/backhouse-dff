from __future__ import annotations

from typing import Callable, Iterable, List, Optional

import flet as ft

from cerebro.engines.base_engine import DuplicateGroup
from cerebro.v2.ui.flet_app.components.common.chunked_view import ChunkedViewBuilder, REVIEW_GROUPS_CHUNK_CONFIG
from cerebro.v2.ui.flet_app.components.common.safe_controls import safe_update
from cerebro.v2.ui.flet_app.pages.review_flow.state import ReviewFlowState
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
    ) -> None:
        self._t = t
        self._state = state
        self._on_back = on_back
        self._on_toggle_set = on_toggle_set
        self._on_toggle_expand = on_toggle_expand
        self._on_open_inspect = on_open_inspect
        self._on_open_cart = on_open_cart
        self._list = ft.ListView(expand=True, spacing=6, padding=8, auto_scroll=False)
        self._chip = ft.Container(visible=False)
        self._bottom_bar = ft.Container(visible=False)
        self._chunked: Optional[ChunkedViewBuilder[DuplicateGroup]] = None
        self._root = self._build()

    @property
    def root(self) -> ft.Column:
        return self._root

    @property
    def list_host(self) -> ft.ListView:
        return self._list

    def attach_page(self, page: ft.Page) -> None:
        self._chunked = ChunkedViewBuilder(page, REVIEW_GROUPS_CHUNK_CONFIG)

    def refresh(self) -> None:
        groups = self._state.visible_groups()
        self._list.controls.clear()
        if self._chunked is None:
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
            alignment=ft.alignment.center,
        )
        return ft.Column(
            [
                header,
                toolbar,
                ft.Stack([self._list, ft.Container(content=self._chip, top=8, right=8)]),
                self._bottom_bar,
            ],
            expand=True,
        )

    def _select_all_visible(self) -> None:
        for g in self._state.visible_groups():
            self._state.selected_set_ids.add(g.group_id)
        self.refresh()

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
        name_style = ft.TextStyle(decoration=ft.TextDecoration.LINE_THROUGH if marked and self._state.dry_run else None)
        members: List[ft.Control] = []
        if expanded:
            for f in group.files:
                members.append(
                    ft.Text(f"  • {f.path.name} ({fmt_size(int(f.size))})", size=t.typography.size_xs, color=t.colors.fg_muted)
                )
        row = ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Checkbox(value=checked, on_change=lambda e, g=gid: self._on_toggle_set(g)),
                            ft.Icon(ft.icons.Icons.INSERT_DRIVE_FILE_OUTLINED, size=18, color=t.colors.primary),
                            ft.Icon(ft.icons.Icons.SHIELD, size=16, color=t.colors.warning, visible=protected),
                            ft.Text(name, expand=True, style=name_style),
                            ft.Text(f"×{len(group.files)}", color=t.colors.primary),
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
                    ),
                    ft.Text(path, size=t.typography.size_xs, color=t.colors.fg_muted),
                    *members,
                ],
                spacing=4,
            ),
            padding=10,
            border_radius=8,
            border=ft.border.all(1, t.colors.border),
            bgcolor=t.colors.surface,
            on_click=lambda e, g=gid: self._on_open_inspect(g),
        )
        return row
