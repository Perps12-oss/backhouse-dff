"""Headless import smoke for Flet UI modules (no window required)."""

from __future__ import annotations

import pytest


@pytest.mark.flet_e2e
def test_flet_app_modules_import() -> None:
    from cerebro.v2.ui.flet_app.services import ui_marshal  # noqa: F401
    from cerebro.v2.ui.flet_app.components.common import safe_controls  # noqa: F401
    from cerebro.v2.ui.flet_app.pages import settings_page  # noqa: F401
