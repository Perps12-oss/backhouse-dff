"""Capped vertical group navigator for the review workstation rail."""

from __future__ import annotations

from typing import Callable, Iterable, List, Optional

import flet as ft

from cerebro.engines.base_engine import DuplicateGroup
from cerebro.v2.ui.flet_app.theme import ThemeTokens, fmt_size

RAIL_GROUP_CAP = 50


class GroupNavigatorRail(ft.Column):
    """Top reclaimable groups with quick-jump search and show-all affordance."""

    def __init__(
        self,
        t: ThemeTokens,
        *,
        on_group_select: Callable[[int], None],
        on_search: Callable[[], None],
        on_show_all: Callable[[], None],
    ) -> None:
        self._t = t
        self._on_group_select = on_group_select
        self._on_search = on_search
        self._on_show_all = on_show_all
        self._list = ft.ListView(height=220, spacing=4, padding=0, auto_scroll=False)
        self._footer = ft.Text("", size=10, color=t.colors.fg_muted)
        header = ft.Row(
            [
                ft.Text("GROUPS", size=10, weight=ft.FontWeight.W_700, color=t.colors.fg_muted),
                ft.Container(expand=True),
                ft.IconButton(
                    ft.icons.Icons.SEARCH,
                    icon_size=18,
                    tooltip="Quick jump to a group",
                    on_click=lambda _e: self._on_search(),
                ),
            ],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        self._show_all_btn = ft.TextButton(
            "Show all in browser…",
            on_click=lambda _e: self._on_show_all(),
            style=ft.ButtonStyle(padding=ft.Padding.symmetric(horizontal=6, vertical=2)),
        )
        super().__init__(
            [header, self._list, self._footer, self._show_all_btn],
            spacing=6,
        )

    def refresh(self, groups: Iterable[DuplicateGroup], *, active_group_id: Optional[int] = None) -> None:
        all_groups = list(groups)
        capped = all_groups[:RAIL_GROUP_CAP]
        self._list.controls.clear()
        for group in capped:
            gid = int(group.group_id)
            label = f"Group {gid} · {len(group.files)} files"
            reclaim = fmt_size(int(getattr(group, "reclaimable", 0) or 0))
            is_active = active_group_id is not None and gid == active_group_id
            self._list.controls.append(
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Text(label, size=11, weight=ft.FontWeight.W_600, color=self._t.colors.fg),
                            ft.Text(reclaim, size=10, color=self._t.colors.fg_muted),
                        ],
                        spacing=0,
                        tight=True,
                    ),
                    padding=ft.Padding.symmetric(horizontal=8, vertical=6),
                    border_radius=8,
                    bgcolor=ft.Colors.with_opacity(0.12 if is_active else 0.04, self._t.colors.accent),
                    on_click=lambda _e, group_id=gid: self._on_group_select(group_id),
                    ink=True,
                )
            )
        hidden = max(0, len(all_groups) - len(capped))
        self._footer.value = (
            f"Showing top {len(capped)} by reclaimable"
            if hidden == 0
            else f"Showing top {len(capped)} of {len(all_groups)} groups"
        )
        self._show_all_btn.visible = hidden > 0
        try:
            if self.page is not None:
                self.update()
        except RuntimeError:
            pass
