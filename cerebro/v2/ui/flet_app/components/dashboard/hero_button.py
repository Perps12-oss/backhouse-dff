"""Hero CTA with hover scale (GestureDetector + Container)."""

from __future__ import annotations

import asyncio
import math
from typing import TYPE_CHECKING, Callable

import flet as ft

from cerebro.v2.ui.flet_app.pill_button_styles import text_on_fill
from cerebro.v2.ui.flet_app.theme import ThemeTokens
from cerebro.v2.ui.flet_app.utils.motion import animation_or_none, should_animate

if TYPE_CHECKING:
    from cerebro.v2.ui.flet_app.services.state_bridge import StateBridge


class HeroScanButton(ft.Container):
    """Full-width START SCAN control; call ``on_tap`` like a button handler."""

    def __init__(
        self,
        t: ThemeTokens,
        *,
        bridge: "StateBridge | None" = None,
        on_tap: Callable[[ft.ControlEvent], None],
        disabled: bool = False,
        width: float | int | None = None,
    ) -> None:
        self._t = t
        self._bridge = bridge
        self._motion = should_animate(bridge) if bridge is not None else True
        self._disabled = disabled
        self._on_tap = on_tap
        self._hovered = False
        self._pressed = False
        self._rumble_active = False
        self._accent = t.colors.primary

        self._label = ft.Text(
            "START SCAN",
            size=t.typography.size_xl,
            weight=ft.FontWeight.W_800,
            color=text_on_fill(self._accent),
        )
        self._icon = ft.Icon(
            ft.icons.Icons.ROCKET_LAUNCH,
            color=text_on_fill(self._accent),
            size=22,
        )
        if self._motion:
            self._icon.animate_rotation = ft.Animation(120, ft.AnimationCurve.EASE_IN_OUT)
        self._sweep = ft.Container(
            height=2,
            left=0,
            top=0,
            right=None,
            width=0,
            bgcolor=ft.Colors.with_opacity(0.30, "#FFFFFF"),
            animate=animation_or_none(bridge, ft.Animation(280, ft.AnimationCurve.EASE_OUT))
            if bridge
            else ft.Animation(280, ft.AnimationCurve.EASE_OUT),
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
            border_radius=10,
            bgcolor=self._accent,
            animate_scale=animation_or_none(bridge, ft.Animation(160, ft.AnimationCurve.EASE_OUT))
            if bridge
            else ft.Animation(160, ft.AnimationCurve.EASE_OUT),
            scale=1.0,
            shadow=None,
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

    def sync_theme(self, t: ThemeTokens) -> None:
        """Repaint CTA fill and label colors when the gradient theme changes."""
        self._t = t
        self._accent = t.colors.primary
        on_accent = text_on_fill(self._accent)
        self._face.bgcolor = self._accent
        self._label.color = on_accent
        self._icon.color = on_accent
        self._apply_visual_state()
        try:
            if self.page is not None:
                self.update()
        except RuntimeError:
            pass

    def set_reduce_motion(self, enabled: bool) -> None:
        """Gate hover/press/sweep/icon motion when accessibility setting changes."""
        self._motion = not enabled
        scale_anim = animation_or_none(self._bridge, ft.Animation(160, ft.AnimationCurve.EASE_OUT))
        self._face.animate_scale = scale_anim
        sweep_anim = animation_or_none(self._bridge, ft.Animation(280, ft.AnimationCurve.EASE_OUT))
        self._sweep.animate = sweep_anim
        if enabled:
            self._rumble_active = False
            self._icon.animate_rotation = None
            self._icon.rotate = ft.Rotate(0, alignment=ft.Alignment(0, 0))
            self._face.scale = 1.0
            self._sweep.width = 0
        else:
            self._icon.animate_rotation = ft.Animation(120, ft.AnimationCurve.EASE_IN_OUT)
            if self._hovered and self._bridge is not None and self._bridge.flet_page is not None:
                self._rumble_active = True
                self._bridge.flet_page.run_task(self._icon_rumble_loop)
        self._apply_visual_state()
        try:
            if self.page is not None:
                self.update()
        except RuntimeError:
            pass

    def _start_icon_rumble(self) -> None:
        if not self._motion or self._bridge is None:
            return
        page = self._bridge.flet_page
        if page is None or self._rumble_active:
            return
        self._rumble_active = True
        page.run_task(self._icon_rumble_loop)

    def _stop_icon_rumble(self) -> None:
        self._rumble_active = False
        self._icon.rotate = ft.Rotate(0, alignment=ft.Alignment(0, 0))

    async def _icon_rumble_loop(self) -> None:
        step = 0.0
        while self._rumble_active and self._motion and self._hovered:
            angle = 0.26 * math.sin(step)
            self._icon.rotate = ft.Rotate(angle, alignment=ft.Alignment(0, 0))
            step += 0.22
            try:
                if self._icon.page is not None:
                    self._icon.update()
            except RuntimeError:
                break
            await asyncio.sleep(0.08)
        self._stop_icon_rumble()

    def _handle_tap(self, _e: ft.ControlEvent) -> None:
        if self._disabled:
            return
        self._on_tap(_e)

    def _handle_hover(self, e: ft.ControlEvent) -> None:
        if self._disabled:
            return
        was_hovered = self._hovered
        self._hovered = bool(e.data)
        if self._hovered and not was_hovered:
            self._start_icon_rumble()
        elif was_hovered and not self._hovered:
            self._stop_icon_rumble()
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
        accent = self._accent
        if not self._motion:
            self._face.scale = 1.0
            self._face.shadow = None
            self._sweep.width = 0
            return
        if self._pressed:
            self._face.scale = 0.98
            self._face.shadow = None
            self._sweep.width = 0
        elif self._hovered:
            self._face.scale = 1.02
            self._face.shadow = ft.BoxShadow(
                spread_radius=0,
                blur_radius=8,
                color=ft.Colors.with_opacity(0.35, accent),
                offset=ft.Offset(0, 3),
            )
            self._sweep.width = int(self.width or 368)
        else:
            self._face.scale = 1.0
            self._face.shadow = None
            self._sweep.width = 0

    def set_disabled(self, disabled: bool) -> None:
        self._disabled = disabled
        self.opacity = 0.45 if disabled else 1.0
