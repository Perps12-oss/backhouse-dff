"""Selected-folder chips and browse target for Home."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Callable

import flet as ft

from cerebro.v2.ui.flet_app.design_system.glass import adaptive_glass
from cerebro.v2.ui.flet_app.theme import ThemeTokens, apply_glass_style
from cerebro.v2.ui.flet_app.utils.motion import animation_or_none, should_animate

if TYPE_CHECKING:
    from cerebro.v2.ui.flet_app.services.state_bridge import StateBridge

_FOLDER_DRAG_GROUP = "cerebro_folder_drop"


def _dash_segment_row(
    *,
    color: str,
    thickness: int,
    dash: int,
    gap: int,
    count: int = 48,
) -> ft.Row:
    parts: list[ft.Control] = []
    for i in range(count):
        if i % 2 == 0:
            parts.append(
                ft.Container(
                    width=dash,
                    height=thickness,
                    bgcolor=color,
                    border_radius=1,
                )
            )
        else:
            parts.append(ft.Container(width=gap, height=thickness))
    return ft.Row(parts, spacing=0, tight=True)


def _dashed_border_overlay(
    *,
    color: str,
    radius: int,
    thickness: int = 2,
    dash: int = 6,
    gap: int = 4,
) -> ft.Stack:
    """Four-segment dashed frame (Flet has no native dashed border)."""
    top = _dash_segment_row(color=color, thickness=thickness, dash=dash, gap=gap)
    bottom = _dash_segment_row(color=color, thickness=thickness, dash=dash, gap=gap)
    left = ft.Column(
        [
            ft.Container(width=thickness, height=dash, bgcolor=color, border_radius=1)
            if i % 2 == 0
            else ft.Container(width=thickness, height=gap)
            for i in range(28)
        ],
        spacing=0,
        tight=True,
    )
    right = ft.Column(
        [
            ft.Container(width=thickness, height=dash, bgcolor=color, border_radius=1)
            if i % 2 == 0
            else ft.Container(width=thickness, height=gap)
            for i in range(28)
        ],
        spacing=0,
        tight=True,
    )
    return ft.Stack(
        [
            ft.Container(
                top=0,
                left=radius // 2,
                right=radius // 2,
                content=top,
            ),
            ft.Container(
                bottom=0,
                left=radius // 2,
                right=radius // 2,
                content=bottom,
            ),
            ft.Container(top=radius // 2, bottom=radius // 2, left=0, content=left),
            ft.Container(top=radius // 2, bottom=radius // 2, right=0, content=right),
        ],
        clip_behavior=ft.ClipBehavior.NONE,
    )


class DashboardFolderPanel:
    """Folder drop/browse surface and quick-add affordance."""

    def __init__(
        self,
        bridge: "StateBridge",
        t: ThemeTokens,
        page: ft.Page | None,
        *,
        on_browse: Callable[[ft.ControlEvent], None],
        on_quick_add: Callable[[ft.ControlEvent | None], None],
        on_hover: Callable[[ft.ControlEvent, ft.Container], None],
        on_remove_folder: Callable[[Path], None],
        on_drag_accept: Callable[[object], None] | None = None,
    ) -> None:
        self._bridge = bridge
        self._page = page
        self._on_remove_folder = on_remove_folder
        self._on_hover_external = on_hover
        self._on_drag_accept = on_drag_accept
        self._t = t
        self._empty_drop_state = True
        self._drag_over = False
        self._hovering = False
        self._float_task_active = False
        self._drop_icon: ft.Icon | None = None
        s = t.spacing
        self._folder_chips_row = ft.Row([], wrap=True, spacing=s.xs)
        self._folder_section_icon = ft.Icon(
            ft.icons.Icons.FOLDER_OPEN, size=18, color=t.colors.accent
        )
        self._inner_container = adaptive_glass(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            self._folder_section_icon,
                            ft.Text(
                                "Selected folders",
                                color=t.colors.fg_muted,
                                size=t.typography.size_sm,
                                weight=ft.FontWeight.W_600,
                            ),
                            ft.Container(expand=True),
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    self._folder_chips_row,
                    ft.Container(
                        content=ft.FilledTonalButton(
                            "+ Quick Add: Desktop & Downloads",
                            on_click=on_quick_add,
                            style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=999)),
                        ),
                        padding=ft.padding.only(top=s.xs),
                    ),
                ],
                spacing=s.xs,
            ),
            t=t,
            page=page,
            padding=s.md,
        )
        self._inner_container.on_click = on_browse
        self._inner_container.on_hover = self._on_hover
        self._inner_container.ink = True
        scale_anim = animation_or_none(bridge, ft.Animation(160, ft.AnimationCurve.EASE_OUT))
        self._scale_host = ft.Container(
            content=self._inner_container,
            animate_scale=scale_anim,
            scale=1.0,
        )
        self._drag_target = ft.DragTarget(
            content=self._scale_host,
            group=_FOLDER_DRAG_GROUP,
            on_will_accept=self._on_drag_will_accept,
            on_accept=self._on_drag_accept_event,
            on_leave=self._on_drag_leave,
            on_move=self._on_drag_will_accept,
        )

    @property
    def container(self) -> ft.DragTarget:
        return self._drag_target

    @property
    def chips_row(self) -> ft.Row:
        return self._folder_chips_row

    @property
    def section_icon(self) -> ft.Icon:
        return self._folder_section_icon

    def sync_theme(self, t: ThemeTokens) -> None:
        self._t = t
        apply_glass_style(self._inner_container, t)
        self._folder_section_icon.color = t.colors.accent
        self._apply_border_style()

    def set_reduce_motion(self, enabled: bool) -> None:
        """Refresh motion-gated chrome when accessibility setting changes."""
        scale_anim = animation_or_none(self._bridge, ft.Animation(160, ft.AnimationCurve.EASE_OUT))
        self._scale_host.animate_scale = scale_anim
        if enabled:
            self._scale_host.scale = 1.0
            self._stop_icon_float()
        elif self._empty_drop_state and self._drop_icon is not None:
            self._start_icon_float()
        self._apply_border_style()

    def _border_glow_color(self) -> str:
        return str(self._t.colors.primary)

    def _apply_border_style(self) -> None:
        accent = self._t.colors.accent
        if self._drag_over:
            glow = self._border_glow_color()
            self._inner_container.border = ft.border.all(2, glow)
            self._inner_container.shadow = ft.BoxShadow(
                spread_radius=0,
                blur_radius=20,
                color=ft.Colors.with_opacity(0.35, accent),
                offset=ft.Offset(0, 0),
            )
        elif self._hovering:
            self._inner_container.border = ft.border.all(2, accent)
            self._inner_container.shadow = None
        elif self._empty_drop_state:
            self._inner_container.border = None
            self._inner_container.shadow = None
        else:
            self._inner_container.border = ft.border.all(
                1, ft.Colors.with_opacity(0.35, accent)
            )
            self._inner_container.shadow = None

    def _on_hover(self, e: ft.ControlEvent) -> None:
        self._hovering = e.data == "true"
        if not self._drag_over:
            self._apply_border_style()
        self._on_hover_external(e, self._inner_container)
        try:
            if self._inner_container.page is not None:
                self._inner_container.update()
        except RuntimeError:
            pass

    def _set_drag_over(self, active: bool) -> None:
        if self._drag_over == active:
            return
        self._drag_over = active
        self._scale_host.scale = 1.02 if active else 1.0
        self._apply_border_style()
        try:
            if self._scale_host.page is not None:
                self._scale_host.update()
        except RuntimeError:
            pass

    def _on_drag_will_accept(self, _e: ft.DragWillAcceptEvent | ft.DragTargetEvent) -> None:
        self._set_drag_over(True)

    def _on_drag_leave(self, _e: ft.DragTargetLeaveEvent) -> None:
        self._set_drag_over(False)

    def _on_drag_accept_event(self, e: ft.DragTargetEvent) -> None:
        self._set_drag_over(False)
        if self._on_drag_accept is None:
            return
        try:
            data = getattr(e.src, "data", None)
        except Exception:
            data = None
        if data is not None:
            self._on_drag_accept(data)

    def _start_icon_float(self) -> None:
        if self._drop_icon is None or not should_animate(self._bridge):
            return
        self._drop_icon.animate_offset = ft.Animation(3000, ft.AnimationCurve.EASE_IN_OUT)
        page = self._page or getattr(self._bridge, "flet_page", None)
        if page is None or self._float_task_active:
            return
        self._float_task_active = True
        page.run_task(self._icon_float_loop)

    def _stop_icon_float(self) -> None:
        self._float_task_active = False
        if self._drop_icon is not None:
            self._drop_icon.animate_offset = None
            self._drop_icon.offset = ft.Offset(0, 0)

    async def _icon_float_loop(self) -> None:
        up = False
        while self._float_task_active and self._drop_icon is not None:
            await asyncio.sleep(1.5)
            if not self._float_task_active or self._drop_icon is None:
                break
            self._drop_icon.offset = ft.Offset(0, -0.02 if up else 0)
            up = not up
            try:
                if self._drop_icon.page is not None:
                    self._drop_icon.update()
            except RuntimeError:
                break

    def refresh_chips(self, folders: list[Path], *, mounted: bool) -> None:
        t = self._t
        accent = t.colors.accent
        if not folders:
            self._empty_drop_state = True
            self._inner_container.height = 108
            dash_color = ft.Colors.with_opacity(0.55, accent)
            drop_icon = ft.Icon(
                ft.icons.Icons.FOLDER_OPEN,
                size=28,
                color=accent,
                offset=ft.Offset(0, 0),
            )
            self._drop_icon = drop_icon
            drop_card = ft.Container(
                border_radius=10,
                padding=ft.Padding.symmetric(horizontal=12, vertical=14),
                bgcolor=ft.Colors.with_opacity(0.07, accent),
                content=ft.Column(
                    [
                        ft.Row(
                            [
                                drop_icon,
                                ft.Text(
                                    "Drop a folder here or click to browse",
                                    color=t.colors.fg2,
                                    size=t.typography.size_base,
                                    weight=ft.FontWeight.W_600,
                                ),
                            ],
                            spacing=8,
                        ),
                        ft.Text(
                            "Add folders to scan for duplicate files and similar images",
                            color=t.colors.fg2,
                            size=t.typography.size_sm,
                            weight=ft.FontWeight.W_500,
                        ),
                    ],
                    spacing=6,
                ),
            )
            self._folder_chips_row.controls = [
                ft.Stack(
                    [
                        drop_card,
                        _dashed_border_overlay(color=dash_color, radius=10),
                    ],
                    clip_behavior=ft.ClipBehavior.NONE,
                )
            ]
            self._start_icon_float()
        else:
            self._empty_drop_state = False
            self._stop_icon_float()
            self._drop_icon = None
            self._inner_container.height = None
            self._folder_chips_row.controls = [
                ft.Chip(
                    label=ft.Text(str(folder), size=t.typography.size_sm),
                    on_delete=lambda e, p=folder: self._on_remove_folder(p),
                    shape=ft.RoundedRectangleBorder(radius=8),
                    bgcolor=ft.Colors.with_opacity(0.1, t.colors.primary),
                    tooltip=str(folder),
                )
                for folder in folders
            ]
        self._apply_border_style()
        if mounted:
            self._folder_chips_row.update()
