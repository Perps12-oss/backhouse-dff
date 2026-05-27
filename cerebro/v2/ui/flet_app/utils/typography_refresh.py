"""Apply Settings font-size changes to already-built Flet controls."""

from __future__ import annotations

import logging
from typing import Any, Iterable

import flet as ft

_log = logging.getLogger(__name__)

_MIN_TEXT_PX = 6
_MAX_TEXT_PX = 56

_BUTTON_TYPES = (
    ft.TextButton,
    ft.OutlinedButton,
    ft.FilledButton,
    ft.ElevatedButton,
)


def _clamp_size(n: float) -> int:
    return max(_MIN_TEXT_PX, min(_MAX_TEXT_PX, int(round(n))))


def _scale_text_style(style: ft.TextStyle | None, factor: float) -> ft.TextStyle | None:
    if style is None:
        return None
    size = getattr(style, "size", None)
    if size is None:
        return style
    return ft.TextStyle(
        size=_clamp_size(float(size) * factor),
        weight=getattr(style, "weight", None),
        color=getattr(style, "color", None),
        font_family=getattr(style, "font_family", None),
        italic=getattr(style, "italic", None),
        letter_spacing=getattr(style, "letter_spacing", None),
        decoration=getattr(style, "decoration", None),
    )


def _scale_button_style(style: ft.ButtonStyle | None, factor: float) -> ft.ButtonStyle | None:
    if style is None:
        return None
    text_style = _scale_text_style(getattr(style, "text_style", None), factor)
    if text_style is getattr(style, "text_style", None):
        return style
    return ft.ButtonStyle(
        bgcolor=getattr(style, "bgcolor", None),
        color=getattr(style, "color", None),
        icon_color=getattr(style, "icon_color", None),
        overlay_color=getattr(style, "overlay_color", None),
        elevation=getattr(style, "elevation", None),
        animation_duration=getattr(style, "animation_duration", None),
        padding=getattr(style, "padding", None),
        side=getattr(style, "side", None),
        shape=getattr(style, "shape", None),
        text_style=text_style,
    )


def _rescale_text_control(text: ft.Text, factor: float) -> None:
    if text.size is not None:
        text.size = _clamp_size(float(text.size) * factor)
    for attr in ("style", "text_style"):
        style = getattr(text, attr, None)
        if style is not None and getattr(style, "size", None) is not None:
            scaled = _scale_text_style(style, factor)
            try:
                setattr(text, attr, scaled)
            except Exception:
                pass


def _rescale_button_control(button: ft.Control, factor: float) -> None:
    style = getattr(button, "style", None)
    if style is None:
        return
    scaled = _scale_button_style(style, factor)
    if scaled is not style:
        button.style = scaled


def _iter_child_controls(control: Any) -> Iterable[Any]:
    if control is None:
        return
    controls = getattr(control, "controls", None)
    if controls:
        for child in controls:
            yield child
    content = getattr(control, "content", None)
    if content is not None:
        yield content
    for attr in (
        "title",
        "subtitle",
        "leading",
        "trailing",
        "label",
        "badge",
        "active_content",
        "inactive_content",
    ):
        child = getattr(control, attr, None)
        if isinstance(child, ft.Control):
            yield child


def rescale_text_in_tree(root: ft.Control | None, factor: float) -> None:
    """Multiply explicit ``Text``/button label sizes under ``root`` by ``factor``."""
    if root is None or abs(factor - 1.0) < 1e-6:
        return
    stack = [root]
    seen: set[int] = set()
    while stack:
        control = stack.pop()
        oid = id(control)
        if oid in seen:
            continue
        seen.add(oid)
        try:
            if isinstance(control, ft.Text):
                _rescale_text_control(control, factor)
            elif isinstance(control, _BUTTON_TYPES):
                _rescale_button_control(control, factor)
        except Exception:
            _log.debug("Could not rescale control %r", type(control).__name__, exc_info=True)
        for child in _iter_child_controls(control):
            if isinstance(child, ft.Control):
                stack.append(child)


def sync_page_font_scale(page: ft.Page | None) -> None:
    """Rescale built UI when ``set_ui_font_size_px`` changed the global scale."""
    if page is None:
        return
    from cerebro.v2.ui.flet_app.theme import (
        get_tree_font_scale_applied,
        get_ui_font_scale,
        set_tree_font_scale_applied,
    )

    current = get_ui_font_scale()
    applied = get_tree_font_scale_applied()
    if abs(current - applied) < 1e-6:
        return
    factor = current / applied if applied > 0 else current
    for root in list(getattr(page, "controls", None) or []):
        rescale_text_in_tree(root, factor)
    set_tree_font_scale_applied(current)
