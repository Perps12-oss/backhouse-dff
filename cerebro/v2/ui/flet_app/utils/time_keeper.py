"""Singleton relative-time refresh for Home checkpoint banners."""

from __future__ import annotations

import asyncio
import logging
from typing import Callable

import flet as ft

from cerebro.v2.ui.flet_app.design_system.tokens import RELATIVE_TIME_INTERVAL_S

_log = logging.getLogger(__name__)


class TimeKeeper:
    """App-level periodic tick; callbacks run only when Home tab is active."""

    _instance: "TimeKeeper | None" = None

    def __init__(self) -> None:
        self._callbacks: dict[str, Callable[[], None]] = {}
        self._page: ft.Page | None = None
        self._is_home_active: Callable[[], bool] = lambda: True
        self._paused = False
        self._loop_started = False

    @classmethod
    def instance(cls) -> "TimeKeeper":
        if cls._instance is None:
            cls._instance = TimeKeeper()
        return cls._instance

    def attach(
        self,
        page: ft.Page,
        *,
        is_home_active: Callable[[], bool],
    ) -> None:
        self._page = page
        self._is_home_active = is_home_active
        if self._loop_started:
            return
        self._loop_started = True
        if hasattr(page, "run_task"):
            page.run_task(self._tick_loop)

    def register(self, banner_id: str, callback: Callable[[], None]) -> None:
        self._callbacks[banner_id] = callback

    def unregister(self, banner_id: str) -> None:
        self._callbacks.pop(banner_id, None)

    def pause(self) -> None:
        self._paused = True

    def resume(self) -> None:
        self._paused = False

    async def _tick_loop(self) -> None:
        while True:
            await asyncio.sleep(RELATIVE_TIME_INTERVAL_S)
            if self._paused or not self._is_home_active():
                continue
            for cb in list(self._callbacks.values()):
                try:
                    cb()
                except Exception:
                    _log.debug("TimeKeeper callback failed", exc_info=True)

    def dispose(self) -> None:
        self._callbacks.clear()
        self._loop_started = False
        self._page = None
