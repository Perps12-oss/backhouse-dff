"""Lightweight motion helpers for Flet controls."""

from __future__ import annotations

import flet as ft


def fade_in(
    control: ft.Control,
    *,
    duration_ms: int = 180,
    curve: ft.AnimationCurve = ft.AnimationCurve.EASE_OUT,
) -> None:
    """Apply a short opacity fade-in on *control*."""
    control.animate_opacity = ft.Animation(duration_ms, curve)
    control.opacity = 0.0
    control.opacity = 1.0


def fade_out(
    control: ft.Control,
    *,
    duration_ms: int = 140,
    curve: ft.AnimationCurve = ft.AnimationCurve.EASE_IN,
) -> None:
    control.animate_opacity = ft.Animation(duration_ms, curve)
    control.opacity = 0.0


def slide_in(
    control: ft.Control,
    *,
    duration_ms: int = 240,
    offset_y: float = 12.0,
    curve: ft.AnimationCurve = ft.AnimationCurve.EASE_OUT,
) -> None:
    """Fade and translate *control* into place (opacity + offset)."""
    control.animate_opacity = ft.Animation(duration_ms, curve)
    control.animate_offset = ft.Animation(duration_ms, curve)
    control.opacity = 0.0
    control.offset = ft.Offset(0, offset_y / 400.0)
    control.opacity = 1.0
    control.offset = ft.Offset(0, 0)
