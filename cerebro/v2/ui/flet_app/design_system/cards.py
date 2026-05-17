"""Flat flet-base card surfaces (no glass / neon glow)."""

from __future__ import annotations

import flet as ft

from cerebro.v2.ui.flet_app.theme import ThemeTokens


def flat_card(
    content: ft.Control,
    t: ThemeTokens,
    *,
    padding: int | ft.Padding | float = 16,
    border_radius: int | None = None,
    width: int | float | None = None,
    expand: bool | int = False,
    **kwargs,
) -> ft.Container:
    """Solid surface card matching flet-base ``build_container``."""
    br = border_radius if border_radius is not None else 12
    return ft.Container(
        content=content,
        bgcolor=t.colors.bg2,
        border=ft.border.all(1, t.colors.border),
        border_radius=br,
        padding=padding,
        shadow=None,
        width=width,
        expand=expand,
        **kwargs,
    )


def apply_flat_style(container: ft.Container, t: ThemeTokens) -> None:
    """Repaint an existing container as a flat card."""
    container.bgcolor = t.colors.bg2
    container.border = ft.border.all(1, t.colors.border)
    container.shadow = None
    if getattr(container, "blur", None) is not None:
        container.blur = None
