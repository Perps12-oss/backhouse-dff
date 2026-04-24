"""State bridge: connects the existing StateStore to Flet's UI thread.

Subscribes to the StateStore and triggers page.update() on every state
change so Flet re-renders the affected controls. Also provides helpers
to read current state without direct store access.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, List, Optional, TYPE_CHECKING

import flet as ft

from cerebro.engines.base_engine import DuplicateGroup
from cerebro.v2.coordinator import CerebroCoordinator
from cerebro.v2.state import StateStore
from cerebro.v2.state.app_state import AppState

if TYPE_CHECKING:
    from cerebro.v2.ui.flet_app.services.backend_service import BackendService

_log = logging.getLogger(__name__)


class StateBridge:
    """Single bridge between StateStore and Flet page updates.

    Usage:
        bridge = StateBridge(page, store, coordinator, backend)
        bridge.subscribe()  # starts listening to store changes
    """

    def __init__(
        self,
        page: ft.Page,
        store: StateStore,
        coordinator: CerebroCoordinator,
        backend: "BackendService",
    ) -> None:
        self._page = page
        self._store = store
        self._coordinator = coordinator
        self._backend = backend
        self._unsubscribe: Optional[Callable[[], None]] = None
        self._on_state_change: Optional[Callable[[AppState, AppState, object], None]] = None
        self._on_theme_change: Optional[Callable[[str], None]] = None

    @property
    def flet_page(self) -> ft.Page:
        """Root Flet page — use this when a tab control may be off-screen (not mounted)."""
        return self._page

    @property
    def store(self) -> StateStore:
        return self._store

    @property
    def coordinator(self) -> CerebroCoordinator:
        return self._coordinator

    @property
    def backend(self) -> "BackendService":
        return self._backend

    @property
    def state(self) -> AppState:
        return self._store.get_state()

    def subscribe(self) -> None:
        """Start listening to store changes."""
        self._unsubscribe = self._store.subscribe(self._on_store_change)

    def unsubscribe(self) -> None:
        if self._unsubscribe:
            self._unsubscribe()
            self._unsubscribe = None

    def set_on_state_change(self, cb: Callable[[AppState, AppState, object], None]) -> None:
        """Register a callback fired on every state change (new, old, action)."""
        self._on_state_change = cb

    def set_on_theme_change(self, cb: Callable[[str], None]) -> None:
        """Register a callback fired when the user switches light/dark mode."""
        self._on_theme_change = cb

    def _on_store_change(self, new: AppState, old: AppState, action: object) -> None:
        """Store listener: triggers UI refresh via page.update()."""
        if self._on_state_change:
            try:
                self._on_state_change(new, old, action)
            except Exception:
                _log.exception("State change callback failed")
        try:
            self._page.update()
        except Exception:
            pass

    # -- Convenience dispatchers -----------------------------------------------

    def navigate(self, key: str) -> None:
        self._coordinator.set_active_tab(key)

    def set_theme(self, mode: str) -> None:
        self._page.theme_mode = (
            ft.ThemeMode.DARK if mode == "dark" else ft.ThemeMode.LIGHT
        )
        self._page.update()
        if self._on_theme_change:
            try:
                self._on_theme_change(mode)
            except Exception:
                _log.exception("Theme change callback failed")

    def dispatch_scan_complete(
        self, groups: List[DuplicateGroup], mode: str
    ) -> None:
        self._coordinator.scan_completed(groups, mode)
