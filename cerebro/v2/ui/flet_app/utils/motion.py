"""Motion gating aligned with Settings and optional page client_storage."""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

import flet as ft

if TYPE_CHECKING:
    from cerebro.v2.ui.flet_app.services.state_bridge import StateBridge

_REDUCED_MOTION_KEY = "reduced_motion"


def should_animate_page(
    page: ft.Page | None,
    bridge: "StateBridge | None" = None,
) -> bool:
    """Read reduce-motion from client_storage when set; else fall back to bridge."""
    if page is not None:
        try:
            stored = page.client_storage.get(_REDUCED_MOTION_KEY)
            if stored is not None:
                return not bool(stored)
        except Exception:
            pass
    if bridge is not None:
        return not bridge.is_reduce_motion_enabled()
    return True


def should_animate(bridge: "StateBridge") -> bool:
    """True when decorative animations are allowed (Settings + client_storage)."""
    page = getattr(bridge, "flet_page", None)
    return should_animate_page(page, bridge)


def animate_if(
    bridge: "StateBridge",
    animation: ft.Animation | None,
) -> ft.Animation:
    """Return *animation* or zero-duration linear when reduce motion is on."""
    if should_animate(bridge):
        return animation or ft.Animation(0, ft.AnimationCurve.LINEAR)
    return ft.Animation(0, ft.AnimationCurve.LINEAR)


def animation_or_none(
    bridge: "StateBridge",
    duration_ms: int,
    curve: ft.AnimationCurve = ft.AnimationCurve.EASE_OUT,
) -> ft.Animation | None:
    """Build an Animation when motion is enabled."""
    if should_animate(bridge):
        return ft.Animation(duration_ms, curve)
    return None


def run_if_animated(bridge: "StateBridge", fn: Callable[[], None]) -> None:
    """Run *fn* only when motion is enabled."""
    if should_animate(bridge):
        fn()


def sync_reduce_motion_storage(page: ft.Page, bridge: "StateBridge") -> None:
    """Mirror Settings reduce_motion into client_storage for should_animate_page."""
    try:
        page.client_storage.set(_REDUCED_MOTION_KEY, bridge.is_reduce_motion_enabled())
    except Exception:
        pass
