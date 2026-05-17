"""Hero strip, scan CTA, status, and checkpoint chrome for Home."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

import flet as ft

from cerebro.v2.ui.flet_app.components.dashboard.hero_button import HeroScanButton
from cerebro.v2.ui.flet_app.design_system.cards import apply_flat_style, flat_card
from cerebro.v2.ui.flet_app.pill_button_styles import (
    pill_outlined_button_style,
    pill_text_button_style,
)
from cerebro.v2.ui.flet_app.theme import ThemeTokens
from cerebro.v2.ui.flet_app.utils.motion import should_animate

if TYPE_CHECKING:
    from cerebro.v2.ui.flet_app.services.state_bridge import StateBridge

_TAGLINE = "Scan intelligently. Review safely."


@dataclass
class DashboardHomeChrome:
    hero: ft.Container
    hero_tagline_icon: ft.Icon
    last_session_btn: ft.TextButton
    start_btn: HeroScanButton
    pause_scan_btn: ft.OutlinedButton
    scan_safety_note: ft.Text
    actions: ft.Column
    status: ft.Text
    cancelled_results_text: ft.Text
    cancelled_results_btn: ft.TextButton
    cancelled_results_banner: ft.Container
    paused_scans_col: ft.Column
    paused_scans_section: ft.Container

    @classmethod
    def build(
        cls,
        bridge: "StateBridge",
        t: ThemeTokens,
        page: ft.Page | None,
        *,
        on_open_last_session: Callable[[ft.ControlEvent | None], None],
        on_start_scan: Callable[[ft.ControlEvent], None],
        on_pause_scan: Callable[[ft.ControlEvent], None],
        on_partial_results: Callable[[ft.ControlEvent], None],
        set_container_glow: Callable[..., None],
    ) -> "DashboardHomeChrome":
        s = t.spacing
        accent_icon = t.colors.primary
        last_session_btn = ft.TextButton(
            "Open Last Session",
            icon=ft.icons.Icons.HISTORY,
            on_click=on_open_last_session,
            style=pill_text_button_style(t, variant="muted"),
        )
        hero_tagline_icon = ft.Icon(ft.icons.Icons.AUTO_AWESOME, size=16, color=accent_icon)
        tagline = ft.Text(
            _TAGLINE if not should_animate(bridge) else "",
            size=t.typography.size_base,
            weight=ft.FontWeight.W_600,
            color=t.colors.fg,
            font_family="Consolas",
            expand=True,
        )
        tagline_cursor = ft.Text(
            "|",
            size=t.typography.size_base,
            weight=ft.FontWeight.W_300,
            color=accent_icon,
            visible=should_animate(bridge),
        )
        hero = flat_card(
            content=ft.Row(
                [
                    hero_tagline_icon,
                    tagline,
                    tagline_cursor,
                    last_session_btn,
                ],
                spacing=s.sm,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            t=t,
            padding=ft.Padding.symmetric(horizontal=t.spacing.lg, vertical=t.spacing.sm),
            width=860,
        )
        pause_scan_btn = ft.OutlinedButton(
            "Pause scan",
            icon=ft.icons.Icons.PAUSE,
            on_click=on_pause_scan,
            visible=False,
            style=pill_outlined_button_style(t),
        )
        start_btn = HeroScanButton(t, bridge=bridge, on_tap=on_start_scan, width=368)
        scan_safety_note = ft.Text(
            "Nothing is deleted automatically • Content-aware matching enabled",
            size=t.typography.size_xs,
            color=t.colors.fg_muted,
            text_align=ft.TextAlign.CENTER,
            italic=True,
        )
        actions = ft.Column(
            [start_btn, scan_safety_note, pause_scan_btn],
            horizontal_alignment=ft.CrossAxisAlignment.START,
            spacing=s.xs,
        )
        status = ft.Text(
            "",
            color=t.colors.fg_muted,
            size=t.typography.size_base,
            text_align=ft.TextAlign.CENTER,
        )
        cancelled_results_text = ft.Text("", color=t.colors.fg2, size=t.typography.size_sm)
        cancelled_results_btn = ft.TextButton(
            "View Partial Results",
            icon=ft.icons.Icons.CHECKLIST,
            on_click=on_partial_results,
            style=pill_text_button_style(t, variant="primary"),
        )
        cancelled_results_banner = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.icons.Icons.INFO_OUTLINE, color=accent_icon, size=18),
                    cancelled_results_text,
                    ft.Container(expand=True),
                    cancelled_results_btn,
                ],
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.Padding.symmetric(horizontal=12, vertical=8),
            border=ft.border.all(1, ft.Colors.with_opacity(0.35, accent_icon)),
            border_radius=10,
            bgcolor=ft.Colors.with_opacity(0.08, accent_icon),
            visible=False,
        )
        paused_scans_col = ft.Column([], spacing=s.xs, visible=False)
        paused_scans_section = flat_card(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Container(
                                width=4,
                                height=18,
                                border_radius=2,
                                bgcolor=t.colors.warning,
                            ),
                            ft.Icon(ft.icons.Icons.PAUSE_CIRCLE, size=16, color=t.colors.warning),
                            ft.Text(
                                "CHECKPOINT RESTORE",
                                size=t.typography.size_xs,
                                weight=ft.FontWeight.W_700,
                                color=t.colors.warning,
                            ),
                        ],
                        spacing=s.xs,
                    ),
                    paused_scans_col,
                ],
                spacing=s.sm,
            ),
            t=t,
            width=620,
            padding=ft.Padding.symmetric(horizontal=s.md, vertical=s.sm),
            visible=False,
        )
        built = cls(
            hero=hero,
            hero_tagline_icon=hero_tagline_icon,
            last_session_btn=last_session_btn,
            start_btn=start_btn,
            pause_scan_btn=pause_scan_btn,
            scan_safety_note=scan_safety_note,
            actions=actions,
            status=status,
            cancelled_results_text=cancelled_results_text,
            cancelled_results_btn=cancelled_results_btn,
            cancelled_results_banner=cancelled_results_banner,
            paused_scans_col=paused_scans_col,
            paused_scans_section=paused_scans_section,
        )
        built._tagline = tagline
        built._tagline_cursor = tagline_cursor
        built._bridge = bridge
        built._accent_color = accent_icon
        if should_animate(bridge) and page is not None:
            page.run_task(built._tagline_typewriter_loop)
        return built

    async def _tagline_typewriter_loop(self) -> None:
        cursor_on = True
        chars = 0
        while chars <= len(_TAGLINE):
            self._tagline.value = _TAGLINE[:chars]
            self._tagline_cursor.visible = cursor_on
            try:
                if self._tagline.page is not None:
                    self._tagline.update()
                    self._tagline_cursor.update()
            except RuntimeError:
                return
            if chars >= len(_TAGLINE):
                await asyncio.sleep(0.55)
                cursor_on = not cursor_on
                continue
            chars += 1
            cursor_on = True
            await asyncio.sleep(0.045)

    def sync_theme(self, t: ThemeTokens) -> None:
        apply_flat_style(self.hero, t)
        apply_flat_style(self.paused_scans_section, t)
        accent = t.colors.primary
        self._accent_color = accent
        self.hero_tagline_icon.color = accent
        self._tagline_cursor.color = accent
        self.start_btn.sync_theme(t)
        self.last_session_btn.style = pill_text_button_style(t, variant="muted")
        self.pause_scan_btn.style = pill_outlined_button_style(t)
        self.cancelled_results_btn.style = pill_text_button_style(t, variant="primary")

    def set_reduce_motion(self, enabled: bool) -> None:
        self.start_btn.set_reduce_motion(enabled)
        accent = getattr(self, "_accent_color", self.start_btn._accent)
        self.hero_tagline_icon.color = accent
        if enabled:
            self._tagline.value = _TAGLINE
            self._tagline_cursor.visible = False
        else:
            self._tagline.value = ""
            self._tagline_cursor.visible = True
            page = getattr(self._bridge, "flet_page", None)
            if page is not None:
                page.run_task(self._tagline_typewriter_loop)
        try:
            if self._tagline.page is not None:
                self._tagline.update()
                self._tagline_cursor.update()
        except RuntimeError:
            pass
