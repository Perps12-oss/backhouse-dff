"""Cerebro Flet app entrypoint.

Creates the backend services, state bridge, page builders, and launches
the Flet application with the navigation-rail layout.
"""

from __future__ import annotations

import logging
from typing import Dict

import flet as ft

from cerebro.v2.state import StateStore
from cerebro.v2.state.app_state import create_initial_state
from cerebro.v2.coordinator import CerebroCoordinator
from cerebro.v2.ui.flet_app.layout import AppLayout
from cerebro.v2.ui.flet_app.routes import ROUTE_MAP, default_route, key_for_route
from cerebro.v2.ui.flet_app.services.backend_service import BackendService
from cerebro.v2.ui.flet_app.services.state_bridge import StateBridge
from cerebro.v2.ui.flet_app.theme import theme_for_mode

_log = logging.getLogger(__name__)


def run_flet_app() -> None:
    """Launch the Cerebro Flet UI."""
    ft.app(target=_main)


def _main(page: ft.Page) -> None:
    """Configure the page and wire up all services."""
    page.title = "Cerebro — Duplicate File Finder"
    page.window.width = 1200
    page.window.height = 800
    page.window.min_width = 800
    page.window.min_height = 600
    page.theme_mode = ft.ThemeMode.LIGHT
    page.padding = 0
    page.spacing = 0

    theme = theme_for_mode("light")
    page.theme = ft.Theme(
        color_scheme_seed=theme.colors.primary,
        font_family=theme.typography.family,
    )

    # -- Services -------------------------------------------------------------
    store = StateStore(create_initial_state())
    coordinator = CerebroCoordinator(store)
    backend = BackendService()
    bridge = StateBridge(page, store, coordinator, backend)

    # -- Page builders --------------------------------------------------------
    def _build_dashboard() -> ft.Control:
        from cerebro.v2.ui.flet_app.pages.dashboard_page import DashboardPage
        return DashboardPage(bridge)

    def _build_results() -> ft.Control:
        from cerebro.v2.ui.flet_app.pages.results_page import ResultsPage
        return ResultsPage(bridge)

    def _build_review() -> ft.Control:
        from cerebro.v2.ui.flet_app.pages.review_page import ReviewPage
        return ReviewPage(bridge)

    def _build_history() -> ft.Control:
        from cerebro.v2.ui.flet_app.pages.history_page import HistoryPage
        return HistoryPage(bridge)

    def _build_settings() -> ft.Control:
        from cerebro.v2.ui.flet_app.pages.settings_page import SettingsPage
        return SettingsPage(bridge)

    builders: Dict[str, ...] = {
        "dashboard": _build_dashboard,
        "duplicates": _build_results,
        "review": _build_review,
        "history": _build_history,
        "settings": _build_settings,
    }

    # -- Layout ---------------------------------------------------------------
    layout = AppLayout(page, bridge, builders)
    page.add(layout)

    # -- Route handling -------------------------------------------------------
    def _on_route_change(e: ft.RouteChangeEvent) -> None:
        key = key_for_route(e.route)
        layout.navigate_to(key)

    page.on_route_change = _on_route_change
    page.route = default_route()

    # -- State bridge subscription ---------------------------------------------
    def _on_state_change(new_state) -> None:
        mode = new_state.active_tab
        if mode and mode != layout.current_key:
            layout.navigate_to(mode)

    bridge.set_on_state_change(_on_state_change)
    bridge.subscribe()

    # -- Wire scan completion to results page ----------------------------------
    def _on_scan_complete(results, mode) -> None:
        bridge.dispatch_scan_complete(results, mode)

    backend.set_on_complete(_on_scan_complete)

    _log.info("Cerebro Flet UI initialized")
