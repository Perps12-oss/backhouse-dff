"""Fixed-layout mount for compare mode inside the shared review content slot."""

from __future__ import annotations

import flet as ft

from cerebro.v2.ui.flet_app.theme import ThemeTokens


class CompareWorkspace(ft.Container):
    """Shrink-wrapped compare mount (no expand) for thumbnail probe."""

    def __init__(self, body: ft.Control, *, tokens: ThemeTokens) -> None:
        self._body = body
        super().__init__(
            content=body,
            expand=False,
            padding=ft.Padding.all(tokens.spacing.sm),
            alignment=ft.Alignment(-1, -1),
            visible=False,
        )
