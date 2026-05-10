from __future__ import annotations

from typing import TYPE_CHECKING, Dict, List, Set

import flet as ft

from cerebro.engines.base_engine import DuplicateGroup
from cerebro.v2.ui.flet_app.pages.review._types import RC
from cerebro.v2.ui.flet_app.theme import ThemeTokens, fmt_size

if TYPE_CHECKING:
    from cerebro.v2.ui.flet_app.services.state_bridge import StateBridge


class StatsHeader(ft.Container):
    """Top bar: title, summary, workflow hint, metric chips."""

    def __init__(self, bridge: "StateBridge", t, back_btn: ft.TextButton) -> None:
        self._t = t
        self._title_lbl = ft.Text(
            "Review Workspace",
            size=t.typography.size_lg,
            weight=ft.FontWeight.BOLD,
            color=t.colors.fg,
        )
        self._summary_lbl = ft.Text("", size=t.typography.size_sm, color=t.colors.fg2)
        self._workflow_lbl = ft.Text(
            "",
            size=t.typography.size_sm,
            color=t.colors.fg_muted,
            italic=True,
            text_align=ft.TextAlign.CENTER,
        )
        self._stats_row = ft.Row(
            spacing=t.spacing.xs,
            tight=True,
            scroll=ft.ScrollMode.AUTO,
            alignment=ft.MainAxisAlignment.CENTER,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        stats_row_wrap = ft.Row(
            [ft.Container(expand=True), self._stats_row, ft.Container(expand=True)],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        is_light = "light" in bridge.app_theme.lower() if hasattr(bridge, "app_theme") else False
        bg = ft.Colors.with_opacity(0.04, ft.Colors.BLACK if is_light else ft.Colors.WHITE)
        border_color = ft.Colors.with_opacity(0.12, ft.Colors.BLACK if is_light else ft.Colors.WHITE)
        super().__init__(
            content=ft.Column(
                [
                    ft.Row(
                        [back_btn, self._title_lbl, self._summary_lbl],
                        alignment=ft.MainAxisAlignment.CENTER,
                        wrap=True,
                    ),
                    stats_row_wrap,
                    self._workflow_lbl,
                ],
                spacing=t.spacing.xs,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=t.spacing.lg,
            bgcolor=bg,
            border=ft.border.all(1, border_color),
            border_radius=ft.border_radius.all(12),
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
            padding=ft.padding.symmetric(horizontal=7, vertical=4),
            bgcolor=ft.Colors.with_opacity(0.14, t.colors.glass_bg),
            border=ft.border.all(1, ft.Colors.with_opacity(0.35, t.colors.glass_border)),
            border_radius=999,
        )

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
    ) -> None:
        """Recompute and update all child controls. Called by ReviewPage after any state change."""
        self._t = t
        self._title_lbl.size = t.typography.size_lg
        self._title_lbl.color = t.colors.fg
        self._summary_lbl.size = t.typography.size_sm
        self._summary_lbl.color = t.colors.fg2
        self._workflow_lbl.size = t.typography.size_sm
        self._workflow_lbl.color = t.colors.fg_muted
        root = self.content
        if isinstance(root, ft.Column):
            root.spacing = t.spacing.xs
        self.padding = t.spacing.lg

        selected_files = filter_counts.get(filter_key, 0)
        selected_groups = filter_group_counts.get(filter_key, 0)
        reclaimable = fmt_size(filter_sizes.get(filter_key, 0))
        reviewed_in_filter = sum(1 for g in groups if g.group_id in reviewed_ids)
        total_filtered = len(groups)
        remaining_reclaimable = int(
            sum(int(getattr(g, "reclaimable", 0) or 0) for g in groups if g.group_id not in reviewed_ids)
        )
        mode_label_map = {
            "compare": "Compare",
            "grid": "Grid",
            "groups": "Groups",
            "loading": "Loading",
            "empty": "Empty",
        }
        mode_label = mode_label_map.get(mode, "Grid")
        self._summary_lbl.value = f"Filter: {filter_label} · Mode: {mode_label}"
        if mode == "compare":
            self._summary_lbl.value += " · Back returns to the group list"
        self._stats_row.controls = [
            self._metric_chip("Groups", f"{selected_groups:,}", RC.side_b),
            self._metric_chip("Files", f"{selected_files:,}", "#7DD3FC"),
            self._metric_chip("Total Size", reclaimable, RC.success),
            self._metric_chip("Reviewed", f"{reviewed_in_filter:,}/{total_filtered:,}", "#FBBF24"),
            self._metric_chip("Remaining", fmt_size(remaining_reclaimable), "#F87171"),
        ]
        if mode == "compare":
            self._workflow_lbl.value = (
                "Shortcuts: arrows change group; 1 or K deletes side A; 2 or D deletes side B; "
                "Enter next group; Space opens delete for extras the smart rule would remove."
            )
        elif groups:
            self._workflow_lbl.value = f"Progress: {reviewed_in_filter:,}/{total_filtered:,} groups reviewed"
        else:
            self._workflow_lbl.value = "Progress: no groups in current filter"
        StatsHeader._safe_update(self._title_lbl)
        StatsHeader._safe_update(self._summary_lbl)
        StatsHeader._safe_update(self._stats_row)
        StatsHeader._safe_update(self._workflow_lbl)
        StatsHeader._safe_update(self)
