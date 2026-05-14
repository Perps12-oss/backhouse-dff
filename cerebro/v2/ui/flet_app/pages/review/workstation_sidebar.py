"""Left navigation column for the review workstation (review-state filters)."""

from __future__ import annotations

from typing import Callable, Dict

import flet as ft

from cerebro.v2.ui.flet_app.pages.review.review_scope import REVIEW_SCOPE_LABELS
from cerebro.v2.ui.flet_app.pages.review.theme_detect import app_theme_is_light
from cerebro.v2.ui.flet_app.theme import ThemeTokens


class ReviewWorkstationSidebar(ft.Container):
    def __init__(
        self,
        bridge,
        t: ThemeTokens,
        *,
        on_review_scope_change: Callable[[str], None] | None = None,
    ) -> None:
        self._bridge = bridge
        self._t = t
        self._on_review_scope = on_review_scope_change or (lambda _scope: None)
        self._review_scope = "all"
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

        review_items: list[ft.Control] = [
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

        body = ft.Column(
            [
                workspace_block,
                ft.Container(height=16),
                *review_items,
            ],
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

    def _on_review_scope_pick(self, scope: str) -> None:
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

    def sync_theme(self, t: ThemeTokens) -> None:
        self._t = t
        is_light = app_theme_is_light(self._bridge)
        edge = ft.Colors.with_opacity(0.12, ft.Colors.BLACK if is_light else ft.Colors.WHITE)
        self.border = ft.border.only(right=ft.BorderSide(1, edge))
        self.bgcolor = ft.Colors.with_opacity(0.03, ft.Colors.WHITE if not is_light else ft.Colors.BLACK)
        ReviewWorkstationSidebar._safe_update(self)
