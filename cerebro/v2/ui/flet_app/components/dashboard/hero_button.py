"""Gradient hero CTA with hover scale and glow (GestureDetector + Container)."""

from __future__ import annotations

from typing import Callable

import flet as ft

from cerebro.v2.ui.flet_app.design_system.tokens import SCAN_GRADIENT_END, SCAN_GRADIENT_START
from cerebro.v2.ui.flet_app.theme import ThemeTokens


class HeroScanButton(ft.Container):
    """Full-width START SCAN control; call ``on_tap`` like a button handler."""

    def __init__(
        self,
        t: ThemeTokens,
        *,
        on_tap: Callable[[ft.ControlEvent], None],
        disabled: bool = False,
        width: float | int | None = None,
    ) -> None:
        self._t = t
        self._disabled = disabled
        self._on_tap = on_tap
        self._hovered = False
        self._pressed = False

        self._label = ft.Text(
            "START SCAN",
            size=t.typography.size_xl,
            weight=ft.FontWeight.W_800,
            color="#0A0E14",
        )
        self._icon = ft.Icon(ft.icons.Icons.ROCKET_LAUNCH, color="#0A0E14", size=22)
        self._sweep = ft.Container(
            height=2,
            left=0,
            top=0,
            right=None,
            width=0,
            bgcolor=ft.Colors.with_opacity(0.30, "#FFFFFF"),
            animate=ft.Animation(280, ft.AnimationCurve.EASE_OUT),
        )
        inner = ft.Row(
            [self._icon, self._label],
            alignment=ft.MainAxisAlignment.CENTER,
            spacing=t.spacing.sm,
        )
        self._face = ft.Container(
            content=inner,
            height=56,
            alignment=ft.Alignment(0, 0),
            border_radius=12,
            gradient=ft.LinearGradient(
                begin=ft.alignment.top_left,
                end=ft.alignment.bottom_right,
                colors=[SCAN_GRADIENT_START, SCAN_GRADIENT_END],
            ),
            animate_scale=ft.Animation(160, ft.AnimationCurve.EASE_OUT),
            scale=1.0,
            shadow=ft.BoxShadow(
                spread_radius=0,
                blur_radius=12,
                color=ft.Colors.with_opacity(0.25, t.colors.accent),
                offset=ft.Offset(0, 4),
            ),
        )
        stack = ft.Stack([self._face, self._sweep], height=56)
        gesture = ft.GestureDetector(
            content=stack,
            on_tap=self._handle_tap,
            on_hover=self._handle_hover,
            on_tap_down=lambda _e: self._set_pressed(True),
            on_tap_up=lambda _e: self._set_pressed(False),
            on_tap_cancel=lambda _e: self._set_pressed(False),
        )
        super().__init__(
            content=gesture,
            width=width,
            opacity=0.45 if disabled else 1.0,
        )

    def _handle_tap(self, _e: ft.ControlEvent) -> None:
        if self._disabled:
            return
        self._on_tap(_e)

    def _handle_hover(self, e: ft.ControlEvent) -> None:
        if self._disabled:
            return
        self._hovered = bool(e.data)
        self._apply_visual_state()
        try:
            if self.page is not None:
                self.update()
        except RuntimeError:
            pass

    def _set_pressed(self, pressed: bool) -> None:
        if self._disabled:
            return
        self._pressed = pressed
        self._apply_visual_state()
        try:
            if self.page is not None:
                self.update()
        except RuntimeError:
            pass

    def _apply_visual_state(self) -> None:
        accent = self._t.colors.accent
        if self._pressed:
            self._face.scale = 0.98
            self._face.shadow = ft.BoxShadow(
                spread_radius=-2,
                blur_radius=8,
                color=ft.Colors.with_opacity(0.35, accent),
                offset=ft.Offset(0, 2),
            )
            self._sweep.width = 0
        elif self._hovered:
            self._face.scale = 1.02
            self._face.shadow = ft.BoxShadow(
                spread_radius=0,
                blur_radius=24,
                color=ft.Colors.with_opacity(0.45, accent),
                offset=ft.Offset(0, 6),
            )
            self._sweep.width = int(self.width or 368)
        else:
            self._face.scale = 1.0
            self._face.shadow = ft.BoxShadow(
                spread_radius=0,
                blur_radius=12,
                color=ft.Colors.with_opacity(0.25, accent),
                offset=ft.Offset(0, 4),
            )
            self._sweep.width = 0

    def set_disabled(self, disabled: bool) -> None:
        self._disabled = disabled
        self.opacity = 0.45 if disabled else 1.0
