"""Collapsible section wrapper for Home control-center bands."""

from __future__ import annotations

from typing import Callable

import flet as ft

from cerebro.v2.ui.flet_app.design_system.glass import glass_container
from cerebro.v2.ui.flet_app.theme import ThemeTokens


class CollapsibleSection(ft.Container):
    """Title row with expand/collapse and optional default-expanded state."""

    def __init__(
        self,
        t: ThemeTokens,
        title: str,
        body: ft.Control,
        *,
        expanded: bool = True,
        on_toggle: Callable[[bool], None] | None = None,
    ) -> None:
        self._expanded = expanded
        self._on_toggle = on_toggle
        self._body_host = ft.Container(content=body, visible=expanded)
        self._chevron = ft.Icon(
            ft.icons.Icons.EXPAND_MORE,
            size=18,
            color=t.colors.fg_muted,
            animate_rotation=ft.Animation(250, ft.AnimationCurve.EASE_IN_OUT),
            rotate=ft.Rotate(3.14159 if expanded else 0, alignment=ft.Alignment(0, 0)),
        )
        header = ft.Row(
            [
                ft.Text(title, size=t.typography.size_base, weight=ft.FontWeight.W_700, color=t.colors.fg),
                ft.Container(expand=True),
                self._chevron,
            ],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        super().__init__(
            content=glass_container(
                t=t,
                padding=ft.Padding.symmetric(horizontal=t.spacing.md, vertical=t.spacing.sm),
                content=ft.Column(
                    [
                        ft.Container(
                            content=header,
                            on_click=self._toggle,
                            ink=True,
                        ),
                        self._body_host,
                    ],
                    spacing=t.spacing.sm,
                ),
            ),
        )

    def _toggle(self, _e: ft.ControlEvent | None = None) -> None:
        self._expanded = not self._expanded
        self._body_host.visible = self._expanded
        self._chevron.rotate = ft.Rotate(
            3.14159 if self._expanded else 0,
            alignment=ft.Alignment(0, 0),
        )
        if self._on_toggle is not None:
            self._on_toggle(self._expanded)
        try:
            if self.page is not None:
                self.update()
        except RuntimeError:
            pass
