"""Global shell background: vertical gradient + uniform dot grid."""

from __future__ import annotations

import base64
import io
from typing import TYPE_CHECKING

import flet as ft

if TYPE_CHECKING:
    from cerebro.v2.ui.flet_app.multigradient_themes import GradientTheme

_DOT_SPACING_PX = 20
_DOT_OPACITY = 0.12
_TILE_CACHE: dict[tuple[str, int], str] = {}


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = (hex_color or "").lstrip("#")
    if len(h) == 6:
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return 156, 163, 175


def _dot_tile_data_url(dot_color: str, *, spacing: int = _DOT_SPACING_PX) -> str:
    key = (dot_color.lower(), spacing)
    cached = _TILE_CACHE.get(key)
    if cached:
        return cached
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return ""

    r, g, b = _hex_to_rgb(dot_color)
    alpha = int(255 * _DOT_OPACITY)
    tile = Image.new("RGBA", (spacing, spacing), (0, 0, 0, 0))
    draw = ImageDraw.Draw(tile)
    cx, cy = spacing // 2, spacing // 2
    draw.ellipse((cx - 1, cy - 1, cx + 1, cy + 1), fill=(r, g, b, alpha))
    buf = io.BytesIO()
    tile.save(buf, format="PNG")
    url = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
    _TILE_CACHE[key] = url
    return url


def build_shell_background_stack(
    theme: "GradientTheme",
) -> ft.Stack:
    """Gradient layer + repeating dot tile; both expand to fill the content area."""
    gradient_layer = ft.Container(
        expand=True,
        gradient=ft.LinearGradient(
            begin=ft.Alignment(0, -1),
            end=ft.Alignment(0, 1),
            colors=[theme.gradient_top, theme.gradient_bottom],
        ),
    )
    tile_url = _dot_tile_data_url(theme.dot_color)
    if tile_url:
        dot_layer = ft.Container(
            expand=True,
            image=ft.DecorationImage(
                src=tile_url,
                repeat=ft.ImageRepeat.REPEAT,
            ),
        )
        return ft.Stack([gradient_layer, dot_layer], expand=True)

    dot_layer = ft.Container(expand=True, bgcolor=ft.Colors.TRANSPARENT)
    return ft.Stack([gradient_layer, dot_layer], expand=True)


def apply_shell_theme(shell_stack: ft.Stack, theme: "GradientTheme") -> None:
    """Update an existing shell stack in place (theme switch)."""
    if len(shell_stack.controls) < 1:
        shell_stack.controls[:] = list(build_shell_background_stack(theme).controls)
        return
    grad = shell_stack.controls[0]
    if isinstance(grad, ft.Container):
        grad.gradient = ft.LinearGradient(
            begin=ft.Alignment(0, -1),
            end=ft.Alignment(0, 1),
            colors=[theme.gradient_top, theme.gradient_bottom],
        )
    if len(shell_stack.controls) > 1:
        dots = shell_stack.controls[1]
        if isinstance(dots, ft.Container):
            tile_url = _dot_tile_data_url(theme.dot_color)
            if tile_url:
                dots.image = ft.DecorationImage(
                    src=tile_url,
                    repeat=ft.ImageRepeat.REPEAT,
                )
