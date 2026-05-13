"""Advanced workspace tools gated by ``AppState.advanced_mode``."""

from __future__ import annotations

import json
from typing import Callable

import flet as ft

from cerebro.v2.ui.flet_app.theme import ThemeTokens


class AdvancedWorkspaceDrawer(ft.Container):
    def __init__(
        self,
        t: ThemeTokens,
        *,
        on_regex_change: Callable[[str], None],
        on_export_marked: Callable[[], None],
        on_rule_pipeline_change: Callable[[str], None],
    ) -> None:
        self._t = t
        self._on_regex_change = on_regex_change
        self._on_export_marked = on_export_marked
        self._on_rule_pipeline_change = on_rule_pipeline_change
        self._regex = ft.TextField(
            label="Path/name regex",
            hint_text=r"e.g. final|export",
            dense=True,
            text_size=12,
            on_change=lambda e: self._on_regex_change(str(e.control.value or "")),
        )
        self._pipeline = ft.TextField(
            label="Filename keep regex (pre-filter)",
            hint_text=r"Keep first match, else smart rule",
            dense=True,
            text_size=12,
            on_change=lambda e: self._on_rule_pipeline_change(str(e.control.value or "")),
        )
        super().__init__(
            content=ft.Column(
                [
                    ft.Text("Advanced", size=10, weight=ft.FontWeight.W_700, color=t.colors.fg_muted),
                    self._regex,
                    self._pipeline,
                    ft.OutlinedButton(
                        "Export marked paths (JSON)",
                        icon=ft.icons.Icons.DOWNLOAD,
                        on_click=lambda e: self._on_export_marked(),
                    ),
                ],
                spacing=t.spacing.sm,
            ),
            visible=False,
            padding=ft.Padding.only(top=t.spacing.md),
        )

    def sync_from_state(self, *, regex: str, pipeline: str, advanced_mode: bool) -> None:
        self.visible = bool(advanced_mode)
        if self._regex.value != regex:
            self._regex.value = regex
        if self._pipeline.value != pipeline:
            self._pipeline.value = pipeline

    @staticmethod
    def export_marked_json(marked_paths: set[str]) -> str:
        return json.dumps(sorted(marked_paths), indent=2)
