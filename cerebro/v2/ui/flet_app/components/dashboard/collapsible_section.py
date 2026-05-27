"""Collapsible section wrapper for Home control-center bands."""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

import flet as ft

from cerebro.v2.ui.flet_app.design_system.cards import apply_minimal_style, minimal_surface
from cerebro.v2.ui.flet_app.theme import ThemeTokens
from cerebro.v2.ui.flet_app.utils.motion import animation_or_none, should_animate

if TYPE_CHECKING:
    from cerebro.v2.ui.flet_app.services.state_bridge import StateBridge

# Flet 0.84.x exposes FADE / ROTATION / SCALE only — not SIZE (added in later releases).
_SWITCHER_TRANSITION = getattr(
    ft.AnimatedSwitcherTransition,
    "SIZE",
    ft.AnimatedSwitcherTransition.FADE,
)


class CollapsibleSection(ft.Container):
    """Title row with expand/collapse and optional default-expanded state."""

    def __init__(
        self,
        bridge: "StateBridge",
        t: ThemeTokens,
        title: str,
        body: ft.Control,
        *,
        expanded: bool = True,
        on_toggle: Callable[[bool], None] | None = None,
    ) -> None:
        self._bridge = bridge
        self._expanded = expanded
        self._on_toggle = on_toggle
        self._body_content = body
        self._use_motion = bridge is not None and should_animate(bridge)
        chevron_anim = animation_or_none(
            bridge, ft.Animation(250, ft.AnimationCurve.EASE_IN_OUT)
        ) if bridge else ft.Animation(250, ft.AnimationCurve.EASE_IN_OUT)
        self._chevron = ft.Icon(
            ft.icons.Icons.EXPAND_MORE,
            size=18,
            color=t.colors.fg_muted,
            animate_rotation=chevron_anim,
            rotate=ft.Rotate(3.14159 if expanded else 0, alignment=ft.Alignment(0, 0)),
        )
        header = ft.Row(
            [
                ft.Text(
                    title,
                    size=t.typography.size_base,
                    weight=ft.FontWeight.W_700,
                    color=t.colors.fg,
                    text_align=ft.TextAlign.CENTER,
                ),
                ft.Container(width=6),
                self._chevron,
            ],
            alignment=ft.MainAxisAlignment.CENTER,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        if self._use_motion:
            self._collapsed_slot = ft.Container(height=0)
            self._expanded_slot = ft.Container(content=body)
            switch_duration = 250
            self._body_host = ft.AnimatedSwitcher(
                content=self._expanded_slot if expanded else self._collapsed_slot,
                transition=_SWITCHER_TRANSITION,
                duration=switch_duration,
                reverse_duration=switch_duration,
                switch_in_curve=ft.AnimationCurve.EASE_OUT,
                switch_out_curve=ft.AnimationCurve.EASE_IN,
            )
        else:
            self._body_host = ft.Container(content=body, visible=expanded)
        self._shell = minimal_surface(
            padding=ft.Padding.symmetric(horizontal=t.spacing.md, vertical=t.spacing.xs),
            width=860,
            content=ft.Column(
                [
                    ft.Container(
                        content=header,
                        on_click=self._toggle,
                        ink=False,
                    ),
                    ft.Container(
                        content=self._body_host,
                        alignment=ft.Alignment(0, 0),
                    ),
                ],
                spacing=t.spacing.sm,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        )
        self._title_text = header.controls[0]
        super().__init__(content=self._shell, alignment=ft.Alignment(0, 0))

    def sync_theme(self, t: ThemeTokens) -> None:
        apply_minimal_style(self._shell)
        if isinstance(self._title_text, ft.Text):
            self._title_text.color = t.colors.fg
        self._chevron.color = t.colors.fg_muted

    def _toggle(self, _e: ft.ControlEvent | None = None) -> None:
        self._expanded = not self._expanded
        if self._use_motion:
            self._body_host.content = (
                self._expanded_slot if self._expanded else self._collapsed_slot
            )
        else:
            self._body_host.visible = self._expanded
        self._chevron.rotate = ft.Rotate(
            3.14159 if self._expanded else 0,
            alignment=ft.Alignment(0, 0),
        )
        if self._on_toggle is not None:
            self._on_toggle(self._expanded)
        try:
            if self.page is not None:
                self.update()
        except RuntimeError:
            pass

    def set_reduce_motion(self, enabled: bool) -> None:
        """Disable chevron rotation animation when reduce motion is on."""
        if self._bridge is None:
            return
        self._chevron.animate_rotation = (
            None
            if enabled
            else animation_or_none(self._bridge, ft.Animation(250, ft.AnimationCurve.EASE_IN_OUT))
        )
