"""Horizontal filter toolbar for the review workstation."""

from __future__ import annotations

from typing import Callable

import flet as ft

from cerebro.v2.ui.flet_app.components.filters.filter_bar import FilterBar
from cerebro.v2.ui.flet_app.theme import ThemeTokens


class WorkspaceFilterStack(ft.Container):
    """Type pills, search, cross-folder toggle, and triage/dashboard view mode."""

    def __init__(
        self,
        t: ThemeTokens,
        *,
        on_filter_change: Callable[[str], None],
        on_text_filter: Callable[[str], None],
        on_cross_folder_change: Callable[[bool], None],
        on_view_mode_change: Callable[[str], None],
    ) -> None:
        self._t = t
        self._on_view_mode_change = on_view_mode_change
        self._filter_bar = FilterBar(t, on_filter_change, show_files_suffix=True)
        self._search = ft.TextField(
            hint_text="Search paths…",
            width=200,
            height=34,
            text_size=12,
            dense=True,
            content_padding=ft.Padding.symmetric(horizontal=10, vertical=6),
            border_radius=8,
            prefix_icon=ft.icons.Icons.SEARCH,
            on_change=lambda e: on_text_filter(str(e.control.value or "")),
        )
        self._cross_folder = ft.Switch(
            label="Cross-folder only",
            value=False,
            on_change=lambda e: on_cross_folder_change(bool(e.control.value)),
        )
        self._view_mode = ft.SegmentedButton(
            selected={"triage"},
            segments=[
                ft.Segment(value="triage", label=ft.Text("Triage")),
                ft.Segment(value="dashboard", label=ft.Text("Dashboard")),
            ],
            on_change=self._on_view_mode_segment,
        )
        super().__init__(
            content=ft.Column(
                [
                    self._filter_bar,
                    ft.Row(
                        [
                            self._search,
                            self._cross_folder,
                            ft.Container(expand=True),
                            self._view_mode,
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=t.spacing.md,
                    ),
                ],
                spacing=t.spacing.sm,
            ),
            padding=ft.Padding.symmetric(horizontal=t.spacing.lg, vertical=t.spacing.xs),
        )

    def _on_view_mode_segment(self, e: ft.ControlEvent) -> None:
        selected = next(iter(e.control.selected or {"triage"}), "triage")
        self._on_view_mode_change(str(selected))

    @property
    def filter_bar(self) -> FilterBar:
        return self._filter_bar

    def sync_from_state(
        self,
        *,
        filter_key: str,
        text_filter: str,
        cross_folder_only: bool,
        view_mode: str,
    ) -> None:
        self._filter_bar.set_active(filter_key)
        self._search.value = text_filter
        self._cross_folder.value = cross_folder_only
        mode = view_mode if view_mode in ("triage", "dashboard") else "triage"
        self._view_mode.selected = {mode}
