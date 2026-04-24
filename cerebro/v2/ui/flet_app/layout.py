"""Shared layout shell for the Cerebro Flet app.

Provides the NavigationRail-based shell with a content area that pages
are swapped into. All pages receive the same consistent chrome.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable, Optional

import flet as ft

from cerebro.v2.ui.flet_app.routes import ROUTE_MAP, ROUTES, RouteInfo, key_for_route
from cerebro.v2.ui.flet_app.theme import theme_for_mode

if TYPE_CHECKING:
    from cerebro.v2.ui.flet_app.services.state_bridge import StateBridge

_log = logging.getLogger(__name__)


class AppLayout(ft.Row):
    """Root layout: navigation rail on the left, content area on the right."""

    def __init__(
        self,
        page: ft.Page,
        state_bridge: "StateBridge",
        page_builders: dict[str, Callable[[], ft.Control]],
    ):
        super().__init__(expand=True, spacing=0)
        self._page = page
        self._bridge = state_bridge
        self._builders = page_builders
        self._current_key: str = "dashboard"
        self._content_slot = ft.Container(expand=True)

        nav_destinations = [
            ft.NavigationRailDestination(
                icon=r.icon,
                selected_icon=r.icon,
                label=r.label,
            )
            for r in ROUTES
        ]

        self._nav = ft.NavigationRail(
            selected_index=0,
            destinations=nav_destinations,
            on_change=self._on_nav_change,
            min_width=72,
            min_extended_width=200,
            label_type=ft.NavigationRailLabelType.ALL,
            bgcolor=ft.Colors.SURFACE,
        )

        self.controls = [
            self._nav,
            ft.VerticalDivider(width=1),
            self._content_slot,
        ]

    def _on_nav_change(self, e: ft.ControlEvent) -> None:
        idx = e.control.selected_index
        if 0 <= idx < len(ROUTES):
            route = ROUTES[idx]
            self.navigate_to(route.key)

    def navigate_to(self, key: str) -> None:
        """Switch the content area to the page identified by *key*."""
        if key not in ROUTE_MAP:
            _log.warning("Unknown route key: %s", key)
            return
        self._current_key = key
        idx = next((i for i, r in enumerate(ROUTES) if r.key == key), 0)
        self._nav.selected_index = idx
        self._nav.update()

        builder = self._builders.get(key)
        if builder:
            self._content_slot.content = builder()
        else:
            self._content_slot.content = ft.Text("Page not found")
        self._content_slot.update()

        route_info = ROUTE_MAP[key]
        self._page.route = route_info.route
        self._page.update()

    def refresh_current(self) -> None:
        """Rebuild the current page (e.g., after theme or state change)."""
        self.navigate_to(self._current_key)

    @property
    def current_key(self) -> str:
        return self._current_key
