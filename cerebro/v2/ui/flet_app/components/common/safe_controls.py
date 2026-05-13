"""Safe Flet control updates shared across pages and components."""

from __future__ import annotations

import flet as ft


def safe_update(ctrl: ft.Control | None) -> None:
    """Call ``update()`` only when *ctrl* is attached to a page."""
    if ctrl is None:
        return
    try:
        if ctrl.page is not None:
            ctrl.update()
    except RuntimeError:
        pass
