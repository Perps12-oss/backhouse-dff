"""Deprecated glass API — delegates to flat flet-base cards."""

from __future__ import annotations

import flet as ft

from cerebro.v2.ui.flet_app.design_system.cards import apply_flat_style, flat_card
from cerebro.v2.ui.flet_app.theme import ThemeTokens


def adaptive_glass(
    content: ft.Control,
    t: ThemeTokens,
    page: ft.Page | None = None,
    *,
    padding: int | ft.Padding | float = 16,
    border_radius: int | None = None,
    expand: bool | int = False,
    blur: int = 0,
    **kwargs,
) -> ft.Container:
    """Flat card (legacy name kept for imports)."""
    _ = page, blur
    return flat_card(
        content,
        t,
        padding=padding,
        border_radius=border_radius or 12,
        expand=expand,
        **kwargs,
    )


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
    _ = blur
    return flat_card(
        content,
        t,
        padding=padding,
        border_radius=border_radius,
        expand=expand,
        **kwargs,
    )


def GlassContainer(content: ft.Control, t: ThemeTokens, **kwargs) -> ft.Container:
    return glass_container(content, t, **kwargs)


def apply_glass_style(container: ft.Container, t: ThemeTokens) -> None:
    apply_flat_style(container, t)
