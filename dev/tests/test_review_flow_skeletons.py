"""Smoke tests for review_flow skeleton builders."""

from __future__ import annotations

import flet as ft

from cerebro.v2.ui.flet_app.pages.review_flow import skeletons
from cerebro.v2.ui.flet_app.theme import theme_for_mode


def test_skeleton_builders_return_controls() -> None:
    t = theme_for_mode("dark")
    assert isinstance(skeletons.overview_skeleton(t), ft.Column)
    assert isinstance(skeletons.browse_skeleton(t), ft.Column)
    assert isinstance(skeletons.inspect_skeleton(t), ft.Column)
