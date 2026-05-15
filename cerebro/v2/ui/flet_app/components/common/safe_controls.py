"""Safe Flet control updates shared across pages and components."""

from __future__ import annotations

import flet as ft

# Flet requires ``Image.src``; use until real thumbnail data is assigned.
IMAGE_PLACEHOLDER_SRC = (
    "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def safe_update(ctrl: ft.Control | None) -> None:
    """Call ``update()`` only when *ctrl* is attached to a page."""
    if ctrl is None:
        return
    try:
        if ctrl.page is not None:
            ctrl.update()
    except RuntimeError:
        pass
