"""Global navigation shortcuts (composed into main.on_keyboard_event)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

import flet as ft

from cerebro.v2.ui.flet_app.routes import ROUTES, ROUTE_MAP

if TYPE_CHECKING:
    from cerebro.v2.ui.flet_app.layout import AppLayout
    from cerebro.v2.ui.flet_app.services.state_bridge import StateBridge

_NAV_ROUTE_KEYS: tuple[str, ...] = tuple(r.key for r in ROUTES if r.key != "exclude")


def _is_macos(page: ft.Page) -> bool:
    platform = str(getattr(page, "platform", "") or "").lower()
    return platform in ("macos", "darwin", "mac")


def format_nav_shortcut_label(page: ft.Page, index: int) -> str:
    """Platform-aware shortcut hint for tooltips (1-based index)."""
    mod = "⌘" if _is_macos(page) else "Ctrl"
    return f"{mod}+{index}"


def nav_digit_key_to_route_key(digit: str) -> str | None:
    """Map '1'..'9' to a top-nav route key, or None."""
    if not digit.isdigit():
        return None
    idx = int(digit) - 1
    if idx < 0 or idx >= len(_NAV_ROUTE_KEYS):
        return None
    return _NAV_ROUTE_KEYS[idx]


def _text_field_has_focus(page: ft.Page) -> bool:
    focused = getattr(page, "focused_control", None)
    if focused is None:
        return False
    return isinstance(focused, ft.TextField)


def try_handle_nav_digit_shortcut(
    e: ft.KeyboardEvent,
    *,
    page: ft.Page,
    layout: "AppLayout",
    bridge: "StateBridge",
    on_navigate: Callable[[str], None] | None = None,
) -> bool:
    """Handle Ctrl/Cmd+1..4 tab jumps. Returns True if handled."""
    key = (e.key or "").lower().replace(" ", "")
    if key not in ("1", "2", "3", "4"):
        return False
    ctrl = bool(getattr(e, "ctrl", False) or getattr(e, "meta", False))
    if not ctrl:
        return False
    if _text_field_has_focus(page):
        return False

    route_key = nav_digit_key_to_route_key(key)
    if route_key is None or route_key not in ROUTE_MAP:
        return False

    if route_key == "review" and not bool(bridge.state.groups):
        bridge.show_snackbar("Run a scan first to open Review.", info=True)
        layout.navigate_to("dashboard")
        return True

    if on_navigate is not None:
        on_navigate(route_key)
    else:
        info = ROUTE_MAP[route_key]
        page.route = info.route
        layout.navigate_to(route_key)
    return True


def register_global_shortcuts(
    page: ft.Page,
    layout: "AppLayout",
    bridge: "StateBridge",
    *,
    on_unhandled: Callable[[ft.KeyboardEvent], None] | None = None,
) -> None:
    """Install ``page.on_keyboard_event``; nav digit shortcuts run first."""
    def _handler(e: ft.KeyboardEvent) -> None:
        if try_handle_nav_digit_shortcut(e, page=page, layout=layout, bridge=bridge):
            return
        if on_unhandled is not None:
            on_unhandled(e)

    page.on_keyboard_event = _handler
