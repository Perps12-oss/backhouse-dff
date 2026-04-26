"""Cerebro Flet app entrypoint.

Creates the backend services, state bridge, page builders, and launches
the Flet application with the navigation-rail layout.
"""

from __future__ import annotations

import logging
from typing import Callable, Dict

import flet as ft

from cerebro.v2.state import StateStore
from cerebro.v2.state.actions import ResultsFilesRemoved, ScanCompleted, SetActiveTab
from cerebro.v2.state.app_state import AppState, create_initial_state
from cerebro.v2.coordinator import CerebroCoordinator
from cerebro.v2.ui.flet_app.layout import AppLayout
from cerebro.v2.ui.flet_app.routes import default_route, key_for_route
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
    page.bgcolor = "#0A0E14"
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
    backend = BackendService(page)
    bridge = StateBridge(page, store, coordinator, backend)

    # Singleton pages so scan results / state survive tab switches.
    from cerebro.v2.ui.flet_app.pages.dashboard_page import DashboardPage
    from cerebro.v2.ui.flet_app.pages.results_page import ResultsPage
    from cerebro.v2.ui.flet_app.pages.review_page import ReviewPage
    from cerebro.v2.ui.flet_app.pages.history_page import HistoryPage
    from cerebro.v2.ui.flet_app.pages.settings_page import SettingsPage

    # FilePicker is a Service: attach via page.services (not overlay) for Flet 0.80+.
    folder_picker = ft.FilePicker()
    page.services.append(folder_picker)

    dashboard_page = DashboardPage(bridge, folder_picker)
    results_page = ResultsPage(bridge)
    review_page = ReviewPage(bridge)
    history_page = HistoryPage(bridge)
    settings_page = SettingsPage(bridge)

    builders: Dict[str, Callable[[], ft.Control]] = {
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
        # Only tab-changing actions should drive the shell; other dispatches still
        # carry active_tab (e.g. duplicates) and would otherwise yank the user back
        # from Review/Settings while the rail already matched the new selection.
        take_nav = (
            tab
            and tab in builders
            and tab != layout.current_key
            and isinstance(action, (SetActiveTab, ScanCompleted))
        )
        if take_nav:
            layout.navigate_to(tab)
        if isinstance(action, (ScanCompleted, ResultsFilesRemoved)):
            _sync_groups_from_state(new_state)
        if isinstance(action, ScanCompleted):
            history_page.load_history(bridge.get_scan_history_table_rows())
        if isinstance(action, (ScanCompleted, ResultsFilesRemoved)):
            history_page.load_deletion_history(bridge.get_deletion_history_table_rows())

    bridge.set_on_state_change(_on_state_change)
    bridge.subscribe()

    def _on_theme_change(mode: str) -> None:
        for p in (dashboard_page, results_page, review_page, history_page, settings_page):
            try:
                p.apply_theme(mode)
            except Exception:
                _log.exception("apply_theme failed on %s", type(p).__name__)

    bridge.set_on_theme_change(_on_theme_change)

    history_page.load_history(bridge.get_scan_history_table_rows())
    history_page.load_deletion_history(bridge.get_deletion_history_table_rows())

    appearance = bridge.get_settings().get("appearance") or {}
    bridge.apply_preset_theme(str(appearance.get("ui_theme_preset", "arctic")))

    _log.info("Cerebro Flet UI initialized")
