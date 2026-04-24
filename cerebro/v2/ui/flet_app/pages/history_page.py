"""History page — scan history display (stub for future implementation)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import flet as ft

from cerebro.v2.ui.flet_app.theme import theme_for_mode

if TYPE_CHECKING:
    from cerebro.v2.ui.flet_app.services.state_bridge import StateBridge

_log = logging.getLogger(__name__)


class HistoryPage(ft.Column):
    """Scan history log — placeholder."""

    def __init__(self, bridge: "StateBridge"):
        super().__init__(expand=True, scroll=ft.ScrollMode.AUTO)
        self._bridge = bridge
        self._t = theme_for_mode("light")
        self._build()

    def _build(self) -> None:
        t = self._t
        self.controls = [
            ft.Container(
                content=ft.Column(
                    [
                        ft.Text(
                            "Scan History",
                            size=t.typography.size_xl,
                            weight=ft.FontWeight.BOLD,
                            color=t.colors.fg,
                        ),
                        ft.Text(
                            "Scan history will appear here.",
                            size=t.typography.size_base,
                            color=t.colors.fg_muted,
                        ),
                    ],
                    spacing=t.spacing.md,
                ),
                padding=t.spacing.xxl,
                alignment=ft.alignment.center,
                expand=True,
            ),
        ]
