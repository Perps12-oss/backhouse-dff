"""Unit tests for Flet UI utilities (motion, shortcuts)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from cerebro.v2.ui.flet_app.utils.motion import animate_if, should_animate
from cerebro.v2.ui.flet_app.utils.shortcuts import nav_digit_key_to_route_key


class _Bridge:
    def __init__(self, reduce_motion: bool) -> None:
        self._reduce = reduce_motion

    def is_reduce_motion_enabled(self) -> bool:
        return self._reduce


def test_should_animate_respects_reduce_motion():
    assert should_animate(_Bridge(False)) is True
    assert should_animate(_Bridge(True)) is False


def test_animate_if_returns_none_when_reduced():
    import flet as ft

    anim = ft.Animation(200, ft.AnimationCurve.EASE_OUT)
    assert animate_if(_Bridge(True), anim) is None
    assert animate_if(_Bridge(False), anim) is anim


@pytest.mark.parametrize(
    "digit,expected",
    [
        ("1", "dashboard"),
        ("2", "review"),
        ("3", "history"),
        ("4", "settings"),
        ("5", None),
        ("x", None),
    ],
)
def test_nav_digit_key_to_route_key(digit: str, expected: str | None):
    assert nav_digit_key_to_route_key(digit) == expected
