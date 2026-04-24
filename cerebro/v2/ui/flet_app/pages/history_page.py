"""History page — scan history display (stub for future implementation)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import flet as ft

from cerebro.v2.ui.flet_app.theme import fmt_size as _fmt, theme_for_mode

if TYPE_CHECKING:
    from cerebro.v2.ui.flet_app.services.state_bridge import StateBridge

_log = logging.getLogger(__name__)


class HistoryPage(ft.Column):
    """Scan history log — placeholder."""

    def __init__(self, bridge: "StateBridge"):
        super().__init__(expand=True, scroll=ft.ScrollMode.AUTO)
        self._bridge = bridge
        self._t = theme_for_mode("light")
        self._build()

    def _build(self) -> None:
        t = self._t

        self._rows_list = ft.ListView(
            expand=True,
            spacing=t.spacing.xs,
            padding=ft.padding.symmetric(horizontal=t.spacing.lg, vertical=t.spacing.sm),
        )

        self._empty_label = ft.Text(
            "No scans yet — run a scan from the Home page.",
            size=t.typography.size_base,
            color=t.colors.fg_muted,
            text_align=ft.TextAlign.CENTER,
        )

        self._empty_state = ft.Container(
            content=ft.Column(
                [
                    ft.Icon(ft.icons.Icons.HISTORY, size=64, color=t.colors.fg_muted),
                    self._empty_label,
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=t.spacing.md,
            ),
            expand=True,
            alignment=ft.Alignment(0.5, 0.5),
        )

        self.controls = [
            ft.Container(
                content=ft.Text(
                    "Scan History",
                    size=t.typography.size_xl,
                    weight=ft.FontWeight.BOLD,
                    color=t.colors.fg,
                ),
                padding=ft.padding.only(
                    left=t.spacing.xl, right=t.spacing.xl,
                    top=t.spacing.xl, bottom=t.spacing.md,
                ),
            ),
            self._empty_state,
        ]

    def load_history(self, rows: list) -> None:
        """Refresh the history list from AppState.history_scan_rows."""
        t = self._t
        if not rows:
            if self._empty_state not in self.controls:
                self.controls = [self.controls[0], self._empty_state]
            try:
                self.update()
            except Exception:
                pass
            return

        if self._empty_state in self.controls:
            self.controls = [self.controls[0], self._rows_list]

        def _row_card(row: dict) -> ft.Container:
            date_str = str(row.get("date", ""))
            folder = str(row.get("folder", ""))
            groups = row.get("groups_found", 0)
            files = row.get("files_scanned", 0)
            size = row.get("bytes_reclaimable", 0)
            mode = str(row.get("mode", "files"))
            return ft.Container(
                content=ft.Row(
                    [
                        ft.Icon(ft.icons.Icons.CHECK_CIRCLE_OUTLINE, color=t.colors.success, size=18),
                        ft.Column(
                            [
                                ft.Text(folder or "—", size=t.typography.size_sm, weight=ft.FontWeight.W_600, color=t.colors.fg, overflow=ft.TextOverflow.ELLIPSIS),
                                ft.Text(
                                    f"{files:,} files scanned  ·  {groups:,} groups  ·  {_fmt(size)} reclaimable  ·  {mode}",
                                    size=t.typography.size_xs,
                                    color=t.colors.fg2,
                                ),
                            ],
                            spacing=2,
                            expand=True,
                        ),
                        ft.Text(date_str, size=t.typography.size_xs, color=t.colors.fg_muted),
                    ],
                    spacing=t.spacing.sm,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                padding=t.spacing.md,
                border=ft.border.all(1, t.colors.border),
                border_radius=t.border_radius,
                bgcolor=t.colors.bg,
            )

        self._rows_list.controls = [_row_card(r) for r in rows]
        try:
            self._rows_list.update()
            self.update()
        except Exception:
            pass

    def apply_theme(self, mode: str) -> None:
        self._t = theme_for_mode(mode)
        self._build()
        self.update()
