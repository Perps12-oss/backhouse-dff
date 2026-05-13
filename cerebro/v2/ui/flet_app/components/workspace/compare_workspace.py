"""Fixed-layout mount for compare mode inside the shared review content slot."""

from __future__ import annotations

import flet as ft

from cerebro.v2.ui.flet_app.theme import ThemeTokens


class CompareWorkspace(ft.Container):
    """Scrollable compare surface with explicit top alignment (no workspace_slot swap)."""

    def __init__(self, body: ft.Control, *, tokens: ThemeTokens) -> None:
        self._body = body
        super().__init__(
            content=ft.Column(
                [body],
                expand=True,
                scroll=ft.ScrollMode.AUTO,
                spacing=0,
                alignment=ft.MainAxisAlignment.START,
                horizontal_alignment=ft.CrossAxisAlignment.START,
            ),
            expand=True,
            padding=ft.Padding.symmetric(
                horizontal=tokens.spacing.md,
                vertical=tokens.spacing.sm,
            ),
            alignment=ft.Alignment(-1, -1),
            visible=False,
        )
