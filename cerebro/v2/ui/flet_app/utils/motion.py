"""Motion gating aligned with Settings accessibility.reduce_motion."""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

import flet as ft

if TYPE_CHECKING:
    from cerebro.v2.ui.flet_app.services.state_bridge import StateBridge


def should_animate(bridge: "StateBridge") -> bool:
    """True when decorative animations are allowed."""
    return not bridge.is_reduce_motion_enabled()


def animate_if(
    bridge: "StateBridge",
    animation: ft.Animation | None,
) -> ft.Animation | None:
    """Return *animation* or None when reduce motion is on."""
    if should_animate(bridge):
        return animation
    return None


def animation_or_none(
    bridge: "StateBridge",
    duration_ms: int,
    curve: ft.AnimationCurve = ft.AnimationCurve.EASE_OUT,
) -> ft.Animation | None:
    """Build an Animation when motion is enabled."""
    return animate_if(bridge, ft.Animation(duration_ms, curve))


def run_if_animated(bridge: "StateBridge", fn: Callable[[], None]) -> None:
    """Run *fn* only when motion is enabled (e.g. stagger steps)."""
    if should_animate(bridge):
        fn()
