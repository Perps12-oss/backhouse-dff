"""Bottom sticky bar: selection summary, trust line, Apply Cleanup."""

from __future__ import annotations

from typing import Callable, Optional

import flet as ft

from cerebro.v2.ui.flet_app.pages.review.theme_detect import app_theme_is_light
from cerebro.v2.ui.flet_app.pill_button_styles import pill_filled_accent, pill_text_button_style
from cerebro.v2.ui.flet_app.theme import ThemeTokens, fmt_size


class ReviewActionBar(ft.Container):
    def __init__(
        self,
        bridge,
        t: ThemeTokens,
        *,
        on_apply: Callable[[Optional[ft.ControlEvent]], None],
        on_undo: Callable[[Optional[ft.ControlEvent]], None],
    ) -> None:
        self._bridge = bridge
        self._t = t
        self._summary = ft.Text(size=t.typography.size_sm, color=t.colors.fg2, weight=ft.FontWeight.W_600)
        self._trust = ft.Text(size=t.typography.size_sm, color=t.colors.fg_muted)
        self._apply_btn = ft.FilledButton(
            "Apply Cleanup",
            icon=ft.icons.Icons.AUTO_FIX_HIGH_OUTLINED,
            on_click=on_apply,
            style=pill_filled_accent(t, text_size=13, weight=ft.FontWeight.W_700),
        )
        self._undo_btn = ft.TextButton(
            "Undo last delete",
            on_click=on_undo,
            style=pill_text_button_style(t, variant="muted"),
        )

        is_light = app_theme_is_light(bridge)
        edge = ft.Colors.with_opacity(0.14, ft.Colors.BLACK if is_light else ft.Colors.WHITE)
        bg = ft.Colors.with_opacity(0.06, ft.Colors.BLACK if is_light else ft.Colors.WHITE)

        super().__init__(
            visible=False,
            opacity=0.0,
            animate_opacity=ft.Animation(180, ft.AnimationCurve.EASE_OUT),
            bgcolor=bg,
            border=ft.border.only(top=ft.BorderSide(1, edge)),
            padding=ft.padding.symmetric(horizontal=16, vertical=10),
            content=ft.Row(
                [
                    ft.Container(content=self._summary, expand=True),
                    ft.Container(
                        content=self._trust,
                        alignment=ft.alignment.center,
                        expand=2,
                    ),
                    ft.Row(
                        [self._undo_btn, self._apply_btn],
                        spacing=t.spacing.sm,
                        tight=True,
                    ),
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        )

    @staticmethod
    def _safe_update(ctrl: ft.Control | None) -> None:
        if ctrl is None:
            return
        try:
            if ctrl.page is not None:
                ctrl.update()
        except RuntimeError:
            pass

    def refresh(self, mode: str, marked_n: int, marked_bytes: int, trust_line: str) -> None:
        should_show = mode not in ("empty", "loading", "compare") and marked_n > 0
        if should_show:
            self.visible = True
            self.opacity = 1.0
            self._summary.value = f"{marked_n:,} file(s) marked · {fmt_size(marked_bytes)}"
            self._trust.value = trust_line
        else:
            self.opacity = 0.0
            self.visible = False
        self._apply_btn.disabled = marked_n <= 0 or mode in ("empty", "loading", "compare")
        ReviewActionBar._safe_update(self._summary)
        ReviewActionBar._safe_update(self._trust)
        ReviewActionBar._safe_update(self._apply_btn)
        ReviewActionBar._safe_update(self)

    def sync_theme(self, t: ThemeTokens) -> None:
        self._t = t
        is_light = app_theme_is_light(self._bridge)
        edge = ft.Colors.with_opacity(0.14, ft.Colors.BLACK if is_light else ft.Colors.WHITE)
        bg = ft.Colors.with_opacity(0.06, ft.Colors.BLACK if is_light else ft.Colors.WHITE)
        self.bgcolor = bg
        self.border = ft.border.only(top=ft.BorderSide(1, edge))
        self._summary.color = t.colors.fg2
        self._summary.size = t.typography.size_sm
        self._trust.color = t.colors.fg_muted
        self._trust.size = t.typography.size_sm
        self._apply_btn.style = pill_filled_accent(t, text_size=13, weight=ft.FontWeight.W_700)
        self._undo_btn.style = pill_text_button_style(t, variant="muted")
        ReviewActionBar._safe_update(self)
