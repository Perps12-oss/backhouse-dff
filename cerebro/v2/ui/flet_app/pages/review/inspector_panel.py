"""Right inspector column — selection details and trust copy (expanded in later phases)."""

from __future__ import annotations

import flet as ft

from cerebro.v2.ui.flet_app.pages.review.theme_detect import app_theme_is_light
from cerebro.v2.ui.flet_app.theme import ThemeTokens


class ReviewInspectorPanel(ft.Container):
    def __init__(self, bridge, t: ThemeTokens) -> None:
        self._bridge = bridge
        self._t = t
        self._title = ft.Text(
            "Inspector",
            size=t.typography.size_base,
            weight=ft.FontWeight.W_700,
            color=t.colors.fg,
        )
        self._body = ft.Text(
            "Select a duplicate group or file to preview metadata, paths, and recommendations.",
            size=t.typography.size_sm,
            color=t.colors.fg_muted,
        )
        is_light = app_theme_is_light(bridge)
        edge = ft.Colors.with_opacity(0.12, ft.Colors.BLACK if is_light else ft.Colors.WHITE)
        super().__init__(
            width=336,
            expand=False,
            bgcolor=ft.Colors.with_opacity(0.03, ft.Colors.WHITE if not is_light else ft.Colors.BLACK),
            border=ft.border.only(left=ft.BorderSide(1, edge)),
            padding=ft.padding.all(14),
            content=ft.Column(
                [
                    self._title,
                    ft.Container(height=8),
                    self._body,
                ],
                spacing=0,
                scroll=ft.ScrollMode.AUTO,
                expand=True,
            ),
        )

    def sync_theme(self, t: ThemeTokens) -> None:
        self._t = t
        is_light = app_theme_is_light(self._bridge)
        edge = ft.Colors.with_opacity(0.12, ft.Colors.BLACK if is_light else ft.Colors.WHITE)
        self.border = ft.border.only(left=ft.BorderSide(1, edge))
        self.bgcolor = ft.Colors.with_opacity(0.03, ft.Colors.WHITE if not is_light else ft.Colors.BLACK)
        self._title.color = t.colors.fg
        self._title.size = t.typography.size_base
        self._body.color = t.colors.fg_muted
        self._body.size = t.typography.size_sm
        try:
            if self.page is not None:
                self.update()
        except RuntimeError:
            pass
