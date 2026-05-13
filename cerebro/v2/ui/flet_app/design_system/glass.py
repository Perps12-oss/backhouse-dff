"""Theme-aware glass surfaces."""

from __future__ import annotations

import flet as ft

from cerebro.v2.ui.flet_app.theme import ThemeTokens, glass_container as _glass_container


def glass_container(
    content: ft.Control,
    t: ThemeTokens,
    *,
    padding: int | ft.Padding | float = 16,
    border_radius: int | None = None,
    expand: bool | int = False,
    blur: int = 0,
    **kwargs,
) -> ft.Container:
    """Create a glassmorphism-styled container using theme tokens."""
    return _glass_container(
        content,
        t,
        padding=padding,
        border_radius=border_radius,
        expand=expand,
        blur=blur,
        **kwargs,
    )


def GlassContainer(
    content: ft.Control,
    t: ThemeTokens,
    **kwargs,
) -> ft.Container:
    """Factory alias for ``glass_container``."""
    return glass_container(content, t, **kwargs)
