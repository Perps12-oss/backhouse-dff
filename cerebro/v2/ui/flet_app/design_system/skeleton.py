"""Pulsing placeholder blocks for loading states."""

from __future__ import annotations

import flet as ft

from cerebro.v2.ui.flet_app.theme import ThemeTokens


def skeleton_block(
    t: ThemeTokens,
    *,
    width: int | float | None = None,
    height: int = 14,
    border_radius: int = 6,
) -> ft.Container:
    """Single skeleton line or tile with a soft pulse."""
    return ft.Container(
        width=width,
        height=height,
        border_radius=border_radius,
        bgcolor=ft.Colors.with_opacity(0.12, t.colors.fg_muted),
        animate_opacity=ft.Animation(900, ft.AnimationCurve.EASE_IN_OUT),
        opacity=0.55,
    )


def skeleton_card_row(t: ThemeTokens, *, count: int = 3) -> ft.Row:
    blocks = [skeleton_block(t, width=120, height=72, border_radius=10) for _ in range(count)]
    return ft.Row(blocks, spacing=t.spacing.md)
