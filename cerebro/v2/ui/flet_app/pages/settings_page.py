"""Settings page — theme and application preferences."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import flet as ft

from cerebro.v2.ui.flet_app.theme import theme_for_mode

if TYPE_CHECKING:
    from cerebro.v2.ui.flet_app.services.state_bridge import StateBridge

_log = logging.getLogger(__name__)


class SettingsPage(ft.Column):
    """Application settings with theme toggle."""

    def __init__(self, bridge: "StateBridge"):
        super().__init__(expand=True, scroll=ft.ScrollMode.AUTO)
        self._bridge = bridge
        self._t = theme_for_mode("light")
        self._build()

    def _build(self) -> None:
        t = self._t

        self._title = ft.Text(
            "Settings",
            size=t.typography.size_xl,
            weight=ft.FontWeight.BOLD,
            color=t.colors.fg,
        )

        self._theme_label = ft.Text("Theme", size=t.typography.size_md, color=t.colors.fg, weight=ft.FontWeight.W_600)
        self._theme_buttons = ft.Row(
            [
                ft.ElevatedButton(
                    "Light",
                    on_click=lambda e: self._set_theme("light"),
                    style=ft.ButtonStyle(bgcolor=t.colors.primary, color=t.colors.bg),
                ),
                ft.ElevatedButton(
                    "Dark",
                    on_click=lambda e: self._set_theme("dark"),
                    style=ft.ButtonStyle(bgcolor=t.colors.bg3, color=t.colors.fg2),
                ),
            ],
            spacing=t.spacing.sm,
        )

        self._about_text = ft.Text(
            "Cerebro Duplicate File Finder v0.1.0\nBuilt with Flet + Flutter",
            size=t.typography.size_sm,
            color=t.colors.fg_muted,
        )

        self.controls = [
            ft.Container(content=self._title, padding=t.spacing.xl),
            ft.Container(
                content=ft.Column(
                    [
                        self._theme_label,
                        self._theme_buttons,
                        ft.Divider(),
                        self._about_text,
                    ],
                    spacing=t.spacing.md,
                ),
                padding=ft.padding.symmetric(horizontal=t.spacing.xl),
            ),
        ]

    def _set_theme(self, mode: str) -> None:
        self._bridge.set_theme(mode)
        self._t = theme_for_mode(mode)
        for btn in self._theme_buttons.controls:
            is_light = btn.text == "Light"
            btn.style = ft.ButtonStyle(
                bgcolor=self._t.colors.primary if (is_light and mode == "light") or (not is_light and mode == "dark") else self._t.colors.bg3,
                color=self._t.colors.bg if (is_light and mode == "light") or (not is_light and mode == "dark") else self._t.colors.fg2,
            )
            btn.update()

    def on_show(self) -> None:
        pass
