"""Shared layout shell for the Cerebro Flet app.

Provides the NavigationRail-based shell with a content area that pages
are swapped into. All pages receive the same consistent chrome.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable

import flet as ft

from cerebro.v2.ui.flet_app.routes import ROUTE_MAP, ROUTES
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
        # Start "uninitialized" so first navigate_to("dashboard") mounts content.
        self._current_key: str = ""

        # Plain container (not AnimatedSwitcher): with singleton tab pages, the
        # switcher often failed to replace visible content while the rail updated.
        # Clip so wide / overflowing results subtree cannot sit on top of the rail in hit-testing.
        self._content_host = ft.Container(expand=True, clip_behavior=ft.ClipBehavior.HARD_EDGE)

        nav_destinations = [
            ft.NavigationRailDestination(
                icon=r.icon,
                selected_icon=r.icon,
                label=r.label,
            )
            for r in ROUTES
        ]

        _t = theme_for_mode("dark")

        # App wordmark shown at the top of the rail
        _wordmark = ft.Container(
            content=ft.Column(
                [
                    ft.Icon(ft.icons.Icons.AUTO_AWESOME, color="#22D3EE", size=22),
                    ft.Text(
                        "CEREBRO",
                        size=8,
                        weight=ft.FontWeight.BOLD,
                        color="#22D3EE",
                    ),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=2,
            ),
            padding=ft.padding.only(top=8, bottom=4),
        )

        # Version badge pinned at the bottom of the rail
        _version_badge = ft.Container(
            content=ft.Text("v2.0", size=8, color="#6E7681"),
            padding=ft.padding.only(bottom=8),
        )

        self._nav = ft.NavigationRail(
            selected_index=0,
            destinations=nav_destinations,
            on_change=self._on_nav_change,
            min_width=72,
            min_extended_width=200,
            label_type=ft.NavigationRailLabelType.ALL,
            bgcolor="#080C11",
            indicator_color=ft.Colors.with_opacity(0.15, "#22D3EE"),
            indicator_shape=ft.RoundedRectangleBorder(radius=8),
            leading=_wordmark,
            trailing=_version_badge,
        )

        self.controls = [
            self._nav,
            ft.VerticalDivider(width=1, color="#30363D", thickness=1),
            self._content_host,
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
        # If already on this key and content is mounted, skip redundant rebuild.
        # If content host is unexpectedly empty, force remount for resilience.
        if key == self._current_key and self._content_host.content is not None:
            return
        self._current_key = key
        idx = next((i for i, r in enumerate(ROUTES) if r.key == key), 0)
        self._nav.selected_index = idx
        self._nav.update()

        builder = self._builders.get(key)
        inner = None
        if builder:
            inner = builder()
            # Per-tab key forces a distinct subtree so Flet remounts singleton pages.
            self._content_host.content = ft.Container(
                expand=True,
                content=inner,
                key=f"cerebro-tab-{key}",
                clip_behavior=ft.ClipBehavior.HARD_EDGE,
            )
        else:
            self._content_host.content = ft.Container(
                expand=True,
                alignment=ft.Alignment(0.5, 0.5),
                content=ft.Text("Page not found"),
                key="cerebro-tab-missing",
            )
        self._content_host.update()

        route_info = ROUTE_MAP[key]
        self._page.route = route_info.route
        # Flush the page tree first so new ``inner`` is attached before lifecycle hooks run.
        self._page.update()

        # Keep StateStore.active_tab in sync with the rail. Otherwise global listeners
        # (e.g. on ThemeChanged) still see the old tab and call navigate_to(old), which
        # immediately replaces Settings and looks like "Settings does nothing".
        try:
            self._bridge.navigate(key)
        except Exception:
            _log.exception("Failed to sync active_tab for route key %s", key)

        if inner is not None and hasattr(inner, "on_show"):
            try:
                inner.on_show()
            except Exception:
                _log.exception("on_show failed for route key %s", key)

    def refresh_current(self) -> None:
        """Rebuild the current page (e.g., after theme or state change)."""
        key = self._current_key or "dashboard"
        self._current_key = ""
        self.navigate_to(key)

    @property
    def current_key(self) -> str:
        return self._current_key
