"""Tests for live font-size rescaling on built controls."""

from __future__ import annotations

import flet as ft

from cerebro.v2.ui.flet_app.theme import (
    get_tree_font_scale_applied,
    get_ui_font_scale,
    set_tree_font_scale_applied,
    set_ui_font_size_px,
)
from cerebro.v2.ui.flet_app.utils.typography_refresh import rescale_text_in_tree


def test_set_ui_font_size_px_updates_scale() -> None:
    set_ui_font_size_px(13)
    assert get_ui_font_scale() == 1.0
    set_ui_font_size_px(16)
    assert abs(get_ui_font_scale() - (16 / 13)) < 0.01


def test_rescale_text_in_tree_multiplies_sizes() -> None:
    label = ft.Text("Hello", size=13)
    col = ft.Column([label])
    rescale_text_in_tree(col, 1.2)
    assert label.size == 16


def test_tree_scale_tracking_avoids_double_apply() -> None:
    set_ui_font_size_px(13)
    set_tree_font_scale_applied(get_ui_font_scale())
    set_ui_font_size_px(16)
    assert get_ui_font_scale() != get_tree_font_scale_applied()
