"""Theme-driven pill button styles aligned with ``AppLayout`` top nav pills.

Use these for TextButton / OutlinedButton / FilledButton so chrome matches the
home nav (rounded pill, accent border/overlay) and respects ``ThemeTokens``.
"""

from __future__ import annotations

import flet as ft

from cerebro.v2.ui.flet_app.theme import ThemeTokens

_PILL_PAD = ft.padding.symmetric(horizontal=12, vertical=8)
_PILL_SHAPE = ft.RoundedRectangleBorder(radius=999)


def _luminance(hex_color: str) -> float:
    h = (hex_color or "").lstrip("#")
    if len(h) != 6:
        return 0.5
    try:
        r = int(h[0:2], 16)
        g = int(h[2:4], 16)
        b = int(h[4:6], 16)
    except ValueError:
        return 0.5
    return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255.0


def on_accent_contrast_text(colors: object) -> str:
    """Readable label on ``colors.accent`` fill: dark ink on bright accent, else theme fg."""
    bg = str(getattr(colors, "bg", "#0B1220"))
    fg = str(getattr(colors, "fg", "#0B1220"))
    lum = _luminance(bg)
    return fg if lum > 0.42 else bg


def pill_text_button_style(
    t: ThemeTokens,
    *,
    variant: str = "default",
) -> ft.ButtonStyle:
    """Ghost pill: matches nav unselected / hover language."""
    c = t.colors
    if variant == "muted":
        fg = c.fg_muted
        icon_c = c.fg_muted
    elif variant == "primary":
        fg = c.fg
        icon_c = c.accent
    else:
        fg = c.fg2
        icon_c = c.fg_muted
    return ft.ButtonStyle(
        color=fg,
        icon_color=icon_c,
        bgcolor=ft.Colors.TRANSPARENT,
        overlay_color=ft.Colors.with_opacity(0.08, c.accent),
        padding=_PILL_PAD,
        shape=_PILL_SHAPE,
        side=ft.BorderSide(1, ft.Colors.with_opacity(0.20, c.border)),
        text_style=ft.TextStyle(size=11, weight=ft.FontWeight.W_600),
    )


def pill_text_button_selected(t: ThemeTokens) -> ft.ButtonStyle:
    """Ghost pill in selected state (matches nav selected pill)."""
    c = t.colors
    return ft.ButtonStyle(
        color=c.fg,
        icon_color=c.accent,
        bgcolor=ft.Colors.with_opacity(0.18, c.accent),
        overlay_color=ft.Colors.with_opacity(0.10, c.accent),
        padding=_PILL_PAD,
        shape=_PILL_SHAPE,
        side=ft.BorderSide(1, ft.Colors.with_opacity(0.44, c.accent)),
        text_style=ft.TextStyle(size=11, weight=ft.FontWeight.W_700),
    )


def pill_outlined_button_style(
    t: ThemeTokens,
    *,
    danger: bool = False,
    success: bool = False,
) -> ft.ButtonStyle:
    c = t.colors
    if danger:
        edge = c.danger
        fg = c.danger
        bg = ft.Colors.with_opacity(0.08, c.danger)
        ov = ft.Colors.with_opacity(0.14, c.danger)
    elif success:
        edge = c.success
        fg = c.success
        bg = ft.Colors.with_opacity(0.08, c.success)
        ov = ft.Colors.with_opacity(0.14, c.success)
    else:
        edge = c.accent
        fg = c.fg2
        bg = ft.Colors.with_opacity(0.06, c.accent)
        ov = ft.Colors.with_opacity(0.12, c.accent)
    return ft.ButtonStyle(
        color=fg,
        icon_color=fg,
        bgcolor=bg,
        overlay_color=ov,
        side=ft.BorderSide(1, ft.Colors.with_opacity(0.35, edge)),
        padding=_PILL_PAD,
        shape=_PILL_SHAPE,
        text_style=ft.TextStyle(size=11, weight=ft.FontWeight.W_600),
    )


def pill_filled_accent(
    t: ThemeTokens,
    *,
    padding: ft.Padding | None = None,
    text_size: int = 11,
    weight: str = ft.FontWeight.W_700,
    border_radius: int | None = None,
) -> ft.ButtonStyle:
    c = t.colors
    label = on_accent_contrast_text(c)
    br = border_radius if border_radius is not None else 999
    shape = ft.RoundedRectangleBorder(radius=br)
    return ft.ButtonStyle(
        bgcolor=c.accent,
        color=label,
        icon_color=label,
        overlay_color=ft.Colors.with_opacity(0.18, c.accent),
        padding=padding or _PILL_PAD,
        shape=shape,
        text_style=ft.TextStyle(size=text_size, weight=weight),
    )


def pill_filled_danger(t: ThemeTokens) -> ft.ButtonStyle:
    c = t.colors
    return ft.ButtonStyle(
        bgcolor=c.danger,
        color="#FFFFFF",
        icon_color="#FFFFFF",
        overlay_color=ft.Colors.with_opacity(0.20, c.danger_hover),
        padding=_PILL_PAD,
        shape=_PILL_SHAPE,
        text_style=ft.TextStyle(size=11, weight=ft.FontWeight.W_700),
    )
