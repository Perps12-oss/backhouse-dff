"""Typography helpers bound to ``ThemeTokens``."""

from __future__ import annotations

import flet as ft

from cerebro.v2.ui.flet_app.theme import ThemeTokens


def body_text(value: str, t: ThemeTokens, *, color: str | None = None) -> ft.Text:
    return ft.Text(value, size=t.typography.size_base, color=color or t.colors.fg)


def caption_text(value: str, t: ThemeTokens, *, color: str | None = None) -> ft.Text:
    return ft.Text(value, size=t.typography.size_sm, color=color or t.colors.fg_muted)


def heading_text(value: str, t: ThemeTokens, *, color: str | None = None) -> ft.Text:
    return ft.Text(
        value,
        size=t.typography.size_lg,
        weight=ft.FontWeight.W_700,
        color=color or t.colors.fg,
    )
