"""Viewport helpers for stacking workspace panes on narrow windows."""

from __future__ import annotations

from dataclasses import dataclass

NARROW_BREAKPOINT_PX = 900
WORKSTATION_SIDEBAR_WIDTH_PX = 268
WORKSTATION_INSPECTOR_WIDTH_PX = 336
MIN_CENTER_COLUMN_WIDTH_PX = 420


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


@dataclass(frozen=True, slots=True)
class WorkstationLayout:
    sidebar_visible: bool
    sidebar_width: int
    inspector_visible: bool
    inspector_width: int


def workstation_layout_for_viewport(
    page_width: float | int | None,
    *,
    sidebar_width: int = WORKSTATION_SIDEBAR_WIDTH_PX,
    inspector_width: int = WORKSTATION_INSPECTOR_WIDTH_PX,
    min_center_width: int = MIN_CENTER_COLUMN_WIDTH_PX,
) -> WorkstationLayout:
    """Choose which workstation rails fit without overlapping the center column."""
    if page_width is None:
        return WorkstationLayout(True, sidebar_width, True, inspector_width)

    try:
        width = float(page_width)
    except (TypeError, ValueError):
        return WorkstationLayout(True, sidebar_width, True, inspector_width)

    show_sidebar = True
    show_inspector = not is_narrow_viewport(width)

    def center_remaining() -> float:
        remaining = width
        if show_sidebar:
            remaining -= sidebar_width
        if show_inspector:
            remaining -= inspector_width
        return remaining

    while center_remaining() < min_center_width and show_inspector:
        show_inspector = False
    while center_remaining() < min_center_width and show_sidebar:
        show_sidebar = False

    return WorkstationLayout(
        sidebar_visible=show_sidebar,
        sidebar_width=sidebar_width if show_sidebar else 0,
        inspector_visible=show_inspector,
        inspector_width=inspector_width if show_inspector else 0,
    )
