"""Left navigation column for the review workstation (categories + future review-state filters)."""

from __future__ import annotations

from typing import Callable, Dict, List

import flet as ft

from cerebro.v2.ui.flet_app.components.workspace.group_navigator_rail import GroupNavigatorRail
from cerebro.v2.ui.flet_app.pages.review._types import FILTER_TAB_ACCENTS, RC
from cerebro.v2.ui.flet_app.pages.review.filter_bar import FILTER_TABS
from cerebro.v2.ui.flet_app.pages.review.review_scope import REVIEW_SCOPE_LABELS
from cerebro.v2.ui.flet_app.pages.review.theme_detect import app_theme_is_light
from cerebro.v2.ui.flet_app.theme import ThemeTokens, fmt_size


class ReviewWorkstationSidebar(ft.Container):
    def __init__(
        self,
        bridge,
        t: ThemeTokens,
        on_category_change: Callable[[str], None],
        *,
        on_group_select: Callable[[int], None] | None = None,
        on_group_search: Callable[[], None] | None = None,
        on_show_all_groups: Callable[[], None] | None = None,
        on_review_scope_change: Callable[[str], None] | None = None,
        footer: ft.Control | None = None,
    ) -> None:
        self._bridge = bridge
        self._t = t
        self._on_category = on_category_change
        self._on_review_scope = on_review_scope_change or (lambda _scope: None)
        self._compare_mode = False
        self._active_key = "all"
        self._review_scope = "all"
        self._category_rows: Dict[str, tuple[ft.Text, ft.Text, ft.Control]] = {}
        self._category_btns: list[ft.TextButton] = []
        self._review_scope_btns: Dict[str, ft.TextButton] = {}

        is_light = app_theme_is_light(bridge)
        edge = ft.Colors.with_opacity(0.12, ft.Colors.BLACK if is_light else ft.Colors.WHITE)
        header_style = ft.TextStyle(
            size=10,
            weight=ft.FontWeight.W_700,
            color=t.colors.fg_muted,
            letter_spacing=0.6,
        )

        workspace_block = ft.Column(
            [
                ft.Text("WORKSPACE", style=header_style),
                ft.Text(
                    "Current scan",
                    size=t.typography.size_sm,
                    color=t.colors.fg2,
                ),
            ],
            spacing=4,
        )

        review_items: List[ft.Control] = [
            ft.Text("REVIEW STATE", style=header_style),
        ]
        for scope_key, lbl, tip in REVIEW_SCOPE_LABELS:
            btn = ft.TextButton(
                lbl,
                tooltip=tip,
                style=ft.ButtonStyle(
                    color=t.colors.fg,
                    text_style=ft.TextStyle(size=12),
                    padding=ft.Padding.symmetric(horizontal=8, vertical=4),
                ),
                on_click=lambda e, key=scope_key: self._on_review_scope_pick(key),
            )
            self._review_scope_btns[scope_key] = btn
            review_items.append(btn)

        cat_header = ft.Text("CATEGORIES", style=header_style)
        cat_list = ft.Column(spacing=2)
        for key, label in FILTER_TABS:
            name = ft.Text(label, size=12, weight=ft.FontWeight.W_600, color=t.colors.fg2)
            count = ft.Text("0", size=11, weight=ft.FontWeight.W_700, color=FILTER_TAB_ACCENTS.get(key, RC.filter_all))
            size_lbl = ft.Text("0 B", size=10, color=t.colors.fg_muted)
            self._category_rows[key] = (name, count, size_lbl)
            btn = ft.TextButton(
                content=ft.Row(
                    [
                        ft.Column([name, size_lbl], spacing=0, tight=True, expand=True),
                        count,
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                style=ft.ButtonStyle(
                    padding=ft.Padding.symmetric(horizontal=8, vertical=6),
                    shape=ft.RoundedRectangleBorder(radius=8),
                ),
                on_click=lambda e, k=key: self._on_category_pick(k),
            )
            self._category_btns.append(btn)
            cat_list.controls.append(ft.Container(content=btn, border_radius=8))

        self._group_rail = GroupNavigatorRail(
            t,
            on_group_select=on_group_select or (lambda _gid: None),
            on_search=on_group_search or (lambda: None),
            on_show_all=on_show_all_groups or (lambda: None),
        )

        body_controls: List[ft.Control] = [
            workspace_block,
            ft.Container(height=16),
            *review_items,
            ft.Container(height=16),
            cat_header,
            cat_list,
            ft.Container(height=12),
            self._group_rail,
        ]
        if footer is not None:
            body_controls.append(footer)

        body = ft.Column(
            body_controls,
            spacing=0,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

        super().__init__(
            width=268,
            expand=False,
            bgcolor=ft.Colors.with_opacity(0.03, ft.Colors.WHITE if not is_light else ft.Colors.BLACK),
            border=ft.border.only(right=ft.BorderSide(1, edge)),
            padding=ft.padding.all(12),
            content=body,
        )

    def _on_category_pick(self, key: str) -> None:
        if self._compare_mode:
            return
        self._on_category(key)

    def _on_review_scope_pick(self, scope: str) -> None:
        if self._compare_mode:
            return
        self._review_scope = scope
        self._on_review_scope(scope)
        self.set_review_scope(scope)

    @staticmethod
    def _safe_update(ctrl: ft.Control | None) -> None:
        if ctrl is None:
            return
        try:
            if ctrl.page is not None:
                ctrl.update()
        except RuntimeError:
            pass

    def set_compare_mode(self, on: bool) -> None:
        self._compare_mode = on
        for b in self._category_btns:
            b.disabled = on
        for b in self._review_scope_btns.values():
            b.disabled = on
        ReviewWorkstationSidebar._safe_update(self)

    def set_review_scope(self, scope: str) -> None:
        self._review_scope = scope
        for key, btn in self._review_scope_btns.items():
            active = key == scope
            btn.style = ft.ButtonStyle(
                color=self._t.colors.fg if active else self._t.colors.fg2,
                text_style=ft.TextStyle(size=12, weight=ft.FontWeight.W_700 if active else ft.FontWeight.W_400),
                padding=ft.Padding.symmetric(horizontal=8, vertical=4),
            )
        ReviewWorkstationSidebar._safe_update(self)

    def refresh_group_rail(self, groups: List, *, active_group_id: int | None = None) -> None:
        self._group_rail.refresh(groups, active_group_id=active_group_id)

    def sync_theme(self, t: ThemeTokens) -> None:
        self._t = t
        is_light = app_theme_is_light(self._bridge)
        edge = ft.Colors.with_opacity(0.12, ft.Colors.BLACK if is_light else ft.Colors.WHITE)
        self.border = ft.border.only(right=ft.BorderSide(1, edge))
        self.bgcolor = ft.Colors.with_opacity(0.03, ft.Colors.WHITE if not is_light else ft.Colors.BLACK)
        ReviewWorkstationSidebar._safe_update(self)

    def update_counts(self, counts: Dict[str, int], sizes: Dict[str, int], active_key: str) -> None:
        """Same contract as ``FilterBar.update_counts``."""
        t = self._t
        self._active_key = active_key
        for key, (name, count, size_lbl) in self._category_rows.items():
            files_n = counts.get(key, 0)
            size_n = sizes.get(key, 0)
            is_active = key == active_key
            accent = FILTER_TAB_ACCENTS.get(key, RC.filter_all)
            name.color = t.colors.fg if is_active else t.colors.fg2
            name.weight = ft.FontWeight.W_700 if is_active else ft.FontWeight.W_600
            count.value = f"{files_n:,}"
            count.color = accent if is_active else ft.Colors.with_opacity(0.85, accent)
            count.weight = ft.FontWeight.W_800 if is_active else ft.FontWeight.W_700
            size_lbl.value = fmt_size(size_n)
            size_lbl.color = t.colors.fg2 if is_active else t.colors.fg_muted
        ReviewWorkstationSidebar._safe_update(self)
