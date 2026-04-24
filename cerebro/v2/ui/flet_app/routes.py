"""Route definitions and navigation helpers for the Flet UI.

All page routes are defined here as constants. The main app uses these
to drive the NavigationRail and page swaps.
"""

from __future__ import annotations

import flet as ft
from dataclasses import dataclass
from typing import Callable, Optional


@dataclass(frozen=True)
class RouteInfo:
    """Metadata for a single app route."""

    key: str
    route: str
    icon: str
    label: str


ROUTES: list[RouteInfo] = [
    RouteInfo(key="dashboard", route="/dashboard", icon=ft.icons.Icons.HOME, label="Home"),
    RouteInfo(key="duplicates", route="/duplicates", icon=ft.icons.Icons.CONTENT_COPY, label="Results"),
    RouteInfo(key="review", route="/review", icon=ft.icons.Icons.GRID_VIEW, label="Review"),
    RouteInfo(key="history", route="/history", icon=ft.icons.Icons.HISTORY, label="History"),
    RouteInfo(key="settings", route="/settings", icon=ft.icons.Icons.SETTINGS, label="Settings"),
]

ROUTE_MAP: dict[str, RouteInfo] = {r.key: r for r in ROUTES}
ROUTE_BY_PATH: dict[str, str] = {r.route: r.key for r in ROUTES}


def key_for_route(route: str) -> str:
    """Return the page key for a route path, defaulting to dashboard."""
    return ROUTE_BY_PATH.get(route, "dashboard")


def default_route() -> str:
    return "/dashboard"
