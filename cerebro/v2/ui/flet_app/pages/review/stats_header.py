from __future__ import annotations

from typing import TYPE_CHECKING, Dict, List, Set

import flet as ft

from cerebro.engines.base_engine import DuplicateGroup
from cerebro.v2.ui.flet_app.pages.review._types import RC
from cerebro.v2.ui.flet_app.pages.review.theme_detect import app_theme_is_light
from cerebro.v2.ui.flet_app.theme import ThemeTokens, fmt_size

if TYPE_CHECKING:
    from cerebro.v2.ui.flet_app.services.state_bridge import StateBridge


class StatsHeader(ft.Container):
    """Compact workstation toolbar: title, reclaim-focused chips, utility cluster on the right."""

    def __init__(
        self,
        bridge: "StateBridge",
        t: ThemeTokens,
        back_btn: ft.TextButton,
        *,
        right_tools: ft.Row,
    ) -> None:
        self._t = t
        self._right_tools = right_tools
        self._title_lbl = ft.Text(
            "Review Workspace",
            size=t.typography.size_base,
            weight=ft.FontWeight.W_700,
            color=t.colors.fg,
        )
        self._subtext_lbl = ft.Text("", size=t.typography.size_sm, color=t.colors.fg_muted)
        left_block = ft.Row(
            [
                back_btn,
                ft.Column(
                    [self._title_lbl, self._subtext_lbl],
                    spacing=2,
                    tight=True,
                    alignment=ft.MainAxisAlignment.CENTER,
                ),
            ],
            spacing=t.spacing.sm,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        self._stats_row = ft.Row(
            spacing=t.spacing.sm,
            tight=True,
            scroll=ft.ScrollMode.AUTO,
            alignment=ft.MainAxisAlignment.CENTER,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        self._marked_chip_value = ft.Text(
            f"0 · {fmt_size(0)}",
            size=11,
            weight=ft.FontWeight.W_700,
            color=RC.stats_chip_files,
        )
        chips_wrap = ft.Row(
            [
                ft.Container(expand=True),
                self._stats_row,
                ft.Container(expand=True),
            ],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        main_row = ft.Row(
            [
                left_block,
                ft.Container(expand=True, content=chips_wrap),
                self._right_tools,
            ],
            alignment=ft.MainAxisAlignment.START,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        is_light = app_theme_is_light(bridge)
        bg = ft.Colors.with_opacity(0.04, ft.Colors.BLACK if is_light else ft.Colors.WHITE)
        border_color = ft.Colors.with_opacity(0.1, ft.Colors.BLACK if is_light else ft.Colors.WHITE)
        super().__init__(
            content=main_row,
            padding=ft.Padding.symmetric(horizontal=14, vertical=10),
            bgcolor=bg,
            border=ft.border.only(bottom=ft.BorderSide(1, border_color)),
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

    def _metric_chip(self, label: str, value: str, accent: str) -> ft.Container:
        t = self._t
        return ft.Container(
            content=ft.Row(
                [
                    ft.Text(label, size=10, color=t.colors.fg_muted, weight=ft.FontWeight.W_500),
                    ft.Text(value, size=11, weight=ft.FontWeight.W_700, color=accent),
                ],
                spacing=4,
                tight=True,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.Padding.symmetric(horizontal=8, vertical=4),
            bgcolor=ft.Colors.with_opacity(0.1, t.colors.glass_bg),
            border_radius=999,
        )

    def _metric_chip_row(self, label: str, value_text: ft.Text, accent: str) -> ft.Container:
        t = self._t
        return ft.Container(
            content=ft.Row(
                [
                    ft.Text(label, size=10, color=t.colors.fg_muted, weight=ft.FontWeight.W_500),
                    value_text,
                ],
                spacing=4,
                tight=True,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.Padding.symmetric(horizontal=8, vertical=4),
            bgcolor=ft.Colors.with_opacity(0.1, t.colors.glass_bg),
            border_radius=999,
        )

    def update_marked_metrics(self, marked_count: int, marked_bytes: int) -> None:
        """Update only the Marked chip without scanning all groups (hot path for checkbox toggles)."""
        self._marked_chip_value.value = f"{marked_count:,} · {fmt_size(marked_bytes)}"
        self._marked_chip_value.color = RC.stats_chip_files
        StatsHeader._safe_update(self._marked_chip_value)

    def refresh(
        self,
        mode: str,
        filter_label: str,
        filter_key: str,
        filter_counts: Dict[str, int],
        filter_sizes: Dict[str, int],
        filter_group_counts: Dict[str, int],
        reviewed_ids: Set[int],
        groups: List[DuplicateGroup],
        t: ThemeTokens,
        *,
        marked_count: int = 0,
        marked_bytes: int = 0,
    ) -> None:
        self._t = t
        self._title_lbl.size = t.typography.size_base
        self._title_lbl.color = t.colors.fg
        self._subtext_lbl.size = t.typography.size_sm
        self._subtext_lbl.color = t.colors.fg_muted
        self.padding = ft.Padding.symmetric(horizontal=14, vertical=10)

        reviewed_in_filter = sum(1 for g in groups if g.group_id in reviewed_ids)
        total_filtered = len(groups)
        groups_left = max(0, total_filtered - reviewed_in_filter)
        remaining_reclaimable = int(
            sum(int(getattr(g, "reclaimable", 0) or 0) for g in groups if g.group_id not in reviewed_ids)
        )
        mode_label_map = {
            "grid": "Tiles",
            "groups": "Details",
            "loading": "Loading",
            "empty": "Empty",
        }
        mode_label = mode_label_map.get(mode, mode)
        self._subtext_lbl.value = (
            f"{filter_label} · {mode_label} · {reviewed_in_filter}/{total_filtered} reviewed"
        )

        self._marked_chip_value.value = f"{marked_count:,} · {fmt_size(marked_bytes)}"
        self._marked_chip_value.color = RC.stats_chip_files
        self._stats_row.controls = [
            self._metric_chip("Reclaimable", fmt_size(remaining_reclaimable), RC.success),
            self._metric_chip("Groups left", f"{groups_left:,}", RC.side_b),
            self._metric_chip_row("Marked", self._marked_chip_value, RC.stats_chip_files),
        ]

        StatsHeader._safe_update(self._title_lbl)
        StatsHeader._safe_update(self._subtext_lbl)
        StatsHeader._safe_update(self._stats_row)
        StatsHeader._safe_update(self)
