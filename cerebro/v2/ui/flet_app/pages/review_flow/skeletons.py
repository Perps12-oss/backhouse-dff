"""Placeholder skeleton UIs for review flow (pure Flet, no extra deps)."""

from __future__ import annotations

import flet as ft

from cerebro.v2.ui.flet_app.theme import ThemeTokens

BROWSE_SKELETON_ROW_H = 72


def _pulse_opacity_control(reduce_motion: bool) -> tuple[float, ft.Animation | None]:
    if reduce_motion:
        return 0.42, None
    return 0.45, ft.Animation(1600, ft.AnimationCurve.EASE_IN_OUT)


def overview_skeleton(t: ThemeTokens, *, reduce_motion: bool = False) -> ft.Column:
    op, anim = _pulse_opacity_control(reduce_motion)
    cards = []
    for _ in range(3):
        c = ft.Container(
            height=88,
            expand=True,
            border_radius=8,
            bgcolor=t.colors.border,
            opacity=op,
            animate_opacity=anim,
        )
        cards.append(c)
    return ft.Column(
        [
            ft.Container(height=24),
            ft.Row(cards, spacing=12),
            ft.Container(height=16),
            ft.Container(
                width=280,
                height=40,
                border_radius=8,
                bgcolor=t.colors.border,
                opacity=op,
                animate_opacity=anim,
            ),
        ],
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
    )


def browse_skeleton(t: ThemeTokens, *, reduce_motion: bool = False) -> ft.Column:
    op, anim = _pulse_opacity_control(reduce_motion)
    rows = []
    for _ in range(8):
        rows.append(
            ft.Container(
                height=BROWSE_SKELETON_ROW_H,
                border_radius=8,
                bgcolor=t.colors.border,
                opacity=op,
                animate_opacity=anim,
                border=ft.Border.all(1, t.colors.border),
            )
        )
    return ft.Column(rows, spacing=6, expand=True)


def inspect_skeleton(t: ThemeTokens, *, reduce_motion: bool = False) -> ft.Column:
    op, anim = _pulse_opacity_control(reduce_motion)
    box_w, box_h = 200, 220
    left = ft.Container(
        width=box_w,
        height=box_h,
        border_radius=8,
        bgcolor=t.colors.border,
        opacity=op,
        animate_opacity=anim,
    )
    right = ft.Container(
        width=box_w,
        height=box_h,
        border_radius=8,
        bgcolor=t.colors.border,
        opacity=op,
        animate_opacity=anim,
    )
    meta_lines = [
        ft.Container(height=10, border_radius=4, bgcolor=t.colors.border, opacity=op, animate_opacity=anim)
        for _ in range(4)
    ]
    return ft.Column(
        [
            ft.Row([left, right], spacing=12),
            ft.Column(meta_lines, spacing=6),
        ],
        spacing=12,
    )
