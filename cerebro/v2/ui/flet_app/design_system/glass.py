"""Theme-aware glass surfaces."""

from __future__ import annotations

import flet as ft

from cerebro.v2.ui.flet_app.design_system.tokens import (
    GLASS_BG_OPACITY,
    GLASS_BORDER_OPACITY,
    GLOW_SHADOW_OPACITY,
)
from cerebro.v2.ui.flet_app.theme import ThemeTokens, glass_container as _glass_container


def _is_web_page(page: ft.Page | None) -> bool:
    if page is None:
        return False
    platform = str(getattr(page, "platform", "") or "").lower()
    if platform in ("web", "browser"):
        return True
    return bool(getattr(page, "web", False))


def adaptive_glass(
    content: ft.Control,
    t: ThemeTokens,
    page: ft.Page | None = None,
    *,
    padding: int | ft.Padding | float = 16,
    border_radius: int | None = None,
    expand: bool | int = False,
    blur: int = 12,
    **kwargs,
) -> ft.Container:
    """Glass surface with runtime-specific blur vs solid fallback."""
    br = border_radius or t.border_radius_lg
    accent = t.colors.accent
    glow = ft.BoxShadow(
        spread_radius=0,
        blur_radius=20,
        color=ft.Colors.with_opacity(GLOW_SHADOW_OPACITY, accent),
        offset=ft.Offset(0, 0),
    )

    if page is not None and not _is_web_page(page) and blur > 0:
        return _glass_container(
            content,
            t,
            padding=padding,
            border_radius=br,
            expand=expand,
            blur=blur,
            shadow=glow,
            **kwargs,
        )

    # Web / mobile fallback: higher-opacity surface, no blur
    bgcolor = ft.Colors.with_opacity(GLASS_BG_OPACITY, t.colors.glass_bg)
    border_color = ft.Colors.with_opacity(GLASS_BORDER_OPACITY, t.colors.glass_border)
    return ft.Container(
        content=content,
        padding=padding,
        border_radius=br,
        bgcolor=bgcolor,
        border=ft.border.all(1, border_color),
        shadow=glow,
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
