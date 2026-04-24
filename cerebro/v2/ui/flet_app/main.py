"""Cerebro Flet app entrypoint.

Creates the backend services, state bridge, page builders, and launches
the Flet application with the navigation-rail layout.
"""

from __future__ import annotations

import logging
from typing import Dict

import flet as ft

from cerebro.v2.state import StateStore
from cerebro.v2.state.actions import ResultsFilesRemoved, ScanCompleted
from cerebro.v2.state.app_state import AppState, create_initial_state
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
    page.theme_mode = ft.ThemeMode.SYSTEM
    page.padding = 0
    page.spacing = 0

    theme = theme_for_mode("light")
    page.theme = ft.Theme(
        color_scheme_seed=theme.colors.primary,
        font_family=theme.typography.family,
    )
    dark_theme = theme_for_mode("dark")
    page.dark_theme = ft.Theme(
        color_scheme_seed=dark_theme.colors.primary,
        font_family=dark_theme.typography.family,
    )

    store = StateStore(create_initial_state())
    coordinator = CerebroCoordinator(store)
    backend = BackendService()
    bridge = StateBridge(page, store, coordinator, backend)

    # Singleton pages so scan results / state survive tab switches.
    from cerebro.v2.ui.flet_app.pages.dashboard_page import DashboardPage
    from cerebro.v2.ui.flet_app.pages.results_page import ResultsPage
    from cerebro.v2.ui.flet_app.pages.review_page import ReviewPage
    from cerebro.v2.ui.flet_app.pages.history_page import HistoryPage
    from cerebro.v2.ui.flet_app.pages.settings_page import SettingsPage

    dashboard_page = DashboardPage(bridge)
    results_page = ResultsPage(bridge)
    review_page = ReviewPage(bridge)
    history_page = HistoryPage(bridge)
    settings_page = SettingsPage(bridge)

    builders: Dict[str, ...] = {
        "dashboard": lambda: dashboard_page,
        "duplicates": lambda: results_page,
        "review": lambda: review_page,
        "history": lambda: history_page,
        "settings": lambda: settings_page,
    }

    layout = AppLayout(page, bridge, builders)
    page.add(layout)

    def _on_route_change(e: ft.RouteChangeEvent) -> None:
        key = key_for_route(e.route)
        layout.navigate_to(key)

    page.on_route_change = _on_route_change
    page.route = default_route()

    def _sync_groups_from_state(s: AppState) -> None:
        groups = list(s.groups)
        mode = s.scan_mode or "files"
        if not groups:
            results_page.load_results([], mode)
            review_page.load_results([], mode)
            return
        results_page.load_results(groups, mode)
        if layout.current_key == "review":
            review_page.apply_pruned_groups(groups, mode)
        else:
            review_page.load_results(groups, mode)

    def _on_state_change(new_state: AppState, _old: AppState, action: object) -> None:
        tab = new_state.active_tab
        if tab and tab in builders and tab != layout.current_key:
            layout.navigate_to(tab)
        if isinstance(action, (ScanCompleted, ResultsFilesRemoved)):
            _sync_groups_from_state(new_state)

    bridge.set_on_state_change(_on_state_change)
    bridge.subscribe()

    def _on_scan_complete(results, mode) -> None:
        bridge.dispatch_scan_complete(results, mode)

    backend.set_on_complete(_on_scan_complete)

    _log.info("Cerebro Flet UI initialized")
