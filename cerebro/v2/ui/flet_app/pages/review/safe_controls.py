"""Shared safe ``update()`` helper for Flet controls (review package + page).

Delete progress uses this callable directly (see ``run_delete_with_progress``). Tests or
integrations that monkeypatch ``ReviewPage._safe_update`` will *not* affect that path;
patch ``cerebro.v2.ui.flet_app.pages.review.safe_controls.safe_update`` instead if needed.
"""

from __future__ import annotations

import flet as ft


def safe_update(ctrl: ft.Control | None) -> None:
    """Call ``update()`` only if *ctrl* is attached to a page."""
    if ctrl is None:
        return
    try:
        if ctrl.page is not None:
            ctrl.update()
    except RuntimeError:
        pass
