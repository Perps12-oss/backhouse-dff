"""Tests for Flet UI thread marshaling."""

from __future__ import annotations

import threading
from unittest.mock import MagicMock

import pytest

from cerebro.v2.ui.flet_app.services import ui_marshal


def test_run_on_ui_thread_no_page_calls_sync() -> None:
    called: list[int] = []

    def fn(x: int) -> None:
        called.append(x)

    ui_marshal.run_on_ui_thread(None, fn, 42)
    assert called == [42]


def test_run_on_ui_thread_uses_run_task() -> None:
    scheduled: list[str] = []
    page = MagicMock()
    page.session = MagicMock()
    page.session.connection = MagicMock()

    def fn() -> None:
        scheduled.append("fn")

    page.run_task = lambda coro: scheduled.append("task")  # noqa: ARG005

    ui_marshal.run_on_ui_thread(page, fn)
    assert "task" in scheduled


def test_run_on_ui_thread_skips_dead_session() -> None:
    called: list[int] = []

    def fn() -> None:
        called.append(1)

    page = MagicMock()
    page.session = None
    ui_marshal.run_on_ui_thread(page, fn)
    assert called == []


def test_flet_page_session_alive_destroyed() -> None:
    page = MagicMock()
    page.session = MagicMock()
    type(page.session).connection = property(
        lambda _self: (_ for _ in ()).throw(RuntimeError("destroyed session"))
    )
    assert ui_marshal.flet_page_session_alive(page) is False
