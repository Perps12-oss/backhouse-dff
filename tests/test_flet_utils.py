"""Unit tests for Flet UI utilities (motion, shortcuts)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from cerebro.v2.ui.flet_app.utils.motion import animate_if, should_animate, should_animate_page
from cerebro.v2.ui.flet_app.utils.shortcuts import nav_digit_key_to_route_key


class _Bridge:
    def __init__(self, reduce_motion: bool, *, flet_page=None) -> None:
        self._reduce = reduce_motion
        self.flet_page = flet_page

    def is_reduce_motion_enabled(self) -> bool:
        return self._reduce


class _StoragePage:
    class _Storage:
        def __init__(self, outer: "_StoragePage") -> None:
            self._outer = outer

        def get(self, _key: str):
            return self._outer._reduced

    def __init__(self, reduced: bool | None) -> None:
        self._reduced = reduced
        self.client_storage = self._Storage(self)


def test_should_animate_page_prefers_client_storage():
    page = _StoragePage(True)
    assert should_animate_page(page, _Bridge(False)) is False
    page_off = _StoragePage(False)
    assert should_animate_page(page_off, _Bridge(True)) is True


def test_should_animate_page_falls_back_to_bridge():
    assert should_animate_page(None, _Bridge(False)) is True
    assert should_animate_page(None, _Bridge(True)) is False


def test_should_animate_respects_reduce_motion():
    assert should_animate(_Bridge(False)) is True
    assert should_animate(_Bridge(True)) is False


def test_animate_if_returns_zero_animation_when_reduced():
    import flet as ft

    anim = ft.Animation(200, ft.AnimationCurve.EASE_OUT)
    reduced = animate_if(_Bridge(True), anim)
    assert reduced.duration == 0
    assert reduced.curve == ft.AnimationCurve.LINEAR
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
