"""Theme-aware glass surfaces."""

from __future__ import annotations

import sys

import flet as ft

from cerebro.v2.ui.flet_app.design_system.tokens import GLOW_SHADOW_OPACITY
from cerebro.v2.ui.flet_app.theme import (
    ThemeTokens,
    apply_glass_style,
    glass_container as _glass_container,
    glass_surface_bg,
    is_dark_theme,
)


def _is_web_page(page: ft.Page | None) -> bool:
    if page is None:
        return False
    platform = str(getattr(page, "platform", "") or "").lower()
    if platform in ("web", "browser"):
        return True
    return bool(getattr(page, "web", False))


def _is_mobile_page(page: ft.Page | None) -> bool:
    if page is None:
        return False
    platform = str(getattr(page, "platform", "") or "").lower()
    return platform in ("android", "ios", "iphone", "ipad")


def _is_desktop() -> bool:
    return sys.platform in ("win32", "darwin", "linux")


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
    """Glass surface with runtime-specific blur vs solid fallback (single API)."""
    br = border_radius or t.border_radius_lg
    accent = t.colors.accent
    glow = ft.BoxShadow(
        spread_radius=0,
        blur_radius=20,
        color=ft.Colors.with_opacity(GLOW_SHADOW_OPACITY, accent),
        offset=ft.Offset(0, 0),
    )

    web = _is_web_page(page)
    mobile = _is_mobile_page(page)
    use_blur = blur > 0 and not web and not mobile and (_is_desktop() or page is not None)

    if mobile:
        container = ft.Container(
            content=content,
            padding=padding,
            border_radius=br,
            bgcolor=t.colors.bg2,
            border=ft.border.all(1, t.colors.glass_border),
            shadow=ft.BoxShadow(
                spread_radius=-1,
                blur_radius=6,
                color=ft.Colors.with_opacity(0.35, "#000000" if is_dark_theme(t) else "#94A3B8"),
                offset=ft.Offset(0, 2),
            ),
            expand=expand,
            **kwargs,
        )
        return container

    if web:
        container = ft.Container(
            content=content,
            padding=padding,
            border_radius=br,
            bgcolor=ft.Colors.with_opacity(0.6, t.colors.bg2),
            border=ft.border.all(1, ft.Colors.with_opacity(0.12, t.colors.glass_border)),
            shadow=glow,
            expand=expand,
            **kwargs,
        )
        return container

    container = _glass_container(
        content,
        t,
        padding=padding,
        border_radius=br,
        expand=expand,
        blur=blur if use_blur else 0,
        shadow=kwargs.pop("shadow", glow),
        **kwargs,
    )
    apply_glass_style(container, t)
    return container


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
