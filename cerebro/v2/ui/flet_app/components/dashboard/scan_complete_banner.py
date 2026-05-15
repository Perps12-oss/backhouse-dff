"""Sticky post-scan banner with Workspace handoff."""

from __future__ import annotations

from typing import Callable

import flet as ft

from cerebro.v2.ui.flet_app.design_system.animations import slide_in
from cerebro.v2.ui.flet_app.design_system.glass import glass_container
from cerebro.v2.ui.flet_app.pill_button_styles import pill_filled_accent, pill_text_button_style
from cerebro.v2.ui.flet_app.theme import ThemeTokens, fmt_size


class ScanCompleteBanner:
    """Above-the-fold scan-complete summary; independent of collapsible Home sections."""

    def __init__(
        self,
        t: ThemeTokens,
        *,
        on_open_workspace: Callable[[], None],
        on_dismiss: Callable[[], None] | None = None,
    ) -> None:
        self._t = t
        self._on_open_workspace = on_open_workspace
        self._on_dismiss = on_dismiss
        self._title = ft.Text(
            "Scan complete",
            size=t.typography.size_lg,
            weight=ft.FontWeight.W_700,
            color=t.colors.fg,
        )
        self._body = ft.Text(
            "",
            size=t.typography.size_sm,
            color=t.colors.fg_muted,
        )
        self._open_btn = ft.FilledButton(
            "Open review",
            icon=ft.icons.Icons.FIND_IN_PAGE,
            on_click=lambda _e: self._on_open_workspace(),
            style=pill_filled_accent(t, text_size=12, weight=ft.FontWeight.W_700),
        )
        self._dismiss_btn = ft.TextButton(
            "Dismiss",
            on_click=self._handle_dismiss,
            style=pill_text_button_style(t, variant="muted"),
        )
        inner = ft.Column(
            [
                self._title,
                self._body,
                ft.Row([self._open_btn, self._dismiss_btn], spacing=t.spacing.sm, tight=True),
            ],
            spacing=t.spacing.sm,
        )
        self.container = glass_container(
            content=inner,
            t=t,
            padding=ft.Padding.symmetric(horizontal=t.spacing.lg, vertical=t.spacing.md),
            visible=False,
        )

    def _handle_dismiss(self, _e: ft.ControlEvent) -> None:
        self.container.visible = False
        if self._on_dismiss is not None:
            self._on_dismiss()
        try:
            if self.container.page is not None:
                self.container.update()
        except RuntimeError:
            pass

    def show(self, *, group_count: int, reclaimable: int, elapsed_label: str = "") -> None:
        reclaim_txt = fmt_size(max(0, reclaimable))
        elapsed = f" in {elapsed_label}" if elapsed_label else ""
        self._body.value = (
            f"Found {group_count:,} duplicate groups — about {reclaim_txt} reclaimable{elapsed}."
        )
        self.container.visible = True
        if isinstance(self.container.content, ft.Column):
            slide_in(self.container.content)
        try:
            if self.container.page is not None:
                self.container.update()
        except RuntimeError:
            pass

    def hide(self) -> None:
        self.container.visible = False
        try:
            if self.container.page is not None:
                self.container.update()
        except RuntimeError:
            pass
