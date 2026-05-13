"""Viewport helpers for stacking workspace panes on narrow windows."""

from __future__ import annotations

NARROW_BREAKPOINT_PX = 900


def is_narrow_viewport(width: float | int | None) -> bool:
    if width is None:
        return False
    try:
        return float(width) < NARROW_BREAKPOINT_PX
    except (TypeError, ValueError):
        return False


def inspector_overlay_width(page_width: float | int | None, *, default: int = 336) -> int | None:
    """Return full-width overlay on narrow viewports; fixed rail width otherwise."""
    if is_narrow_viewport(page_width):
        return None
    return default
