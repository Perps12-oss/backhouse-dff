"""Focused card stack for batch review mode."""

from __future__ import annotations

from typing import Callable, Optional

import flet as ft

from cerebro.engines.base_engine import DuplicateGroup
from cerebro.v2.ui.flet_app.design_system.glass import glass_container
from cerebro.v2.ui.flet_app.theme import ThemeTokens, fmt_size


class BatchReviewView(ft.Container):
    def __init__(
        self,
        t: ThemeTokens,
        *,
        on_keep: Callable[[], None],
        on_mark_extras: Callable[[], None],
        on_skip: Callable[[], None],
        on_next: Callable[[], None],
        on_exit: Callable[[], None],
    ) -> None:
        self._t = t
        self._on_keep = on_keep
        self._on_mark_extras = on_mark_extras
        self._on_skip = on_skip
        self._on_next = on_next
        self._on_exit = on_exit
        self._title = ft.Text("", size=t.typography.size_lg, weight=ft.FontWeight.W_700, color=t.colors.fg)
        self._meta = ft.Text("", size=t.typography.size_sm, color=t.colors.fg_muted)
        self._hint = ft.Text(
            "K keep · D mark extras · S skip · Enter next · Esc exit · Ctrl+Z undo",
            size=t.typography.size_xs,
            color=t.colors.fg_muted,
            italic=True,
        )
        body = ft.Column(
            [
                self._title,
                self._meta,
                ft.Row(
                    [
                        ft.FilledButton("Keep per rule", on_click=lambda e: self._on_keep()),
                        ft.OutlinedButton("Mark extras", on_click=lambda e: self._on_mark_extras()),
                        ft.TextButton("Skip group", on_click=lambda e: self._on_skip()),
                        ft.TextButton("Next", on_click=lambda e: self._on_next()),
                        ft.TextButton("Exit batch", on_click=lambda e: self._on_exit()),
                    ],
                    wrap=True,
                    spacing=t.spacing.sm,
                ),
                self._hint,
            ],
            spacing=t.spacing.md,
            tight=True,
        )
        super().__init__(
            content=glass_container(content=body, t=t, padding=t.spacing.lg),
            padding=ft.Padding.all(t.spacing.lg),
            expand=True,
            alignment=ft.Alignment(0, -1),
            visible=False,
        )

    def refresh(
        self,
        *,
        group: Optional[DuplicateGroup],
        index: int,
        total: int,
    ) -> None:
        if group is None:
            self._title.value = "No groups left in this review scope"
            self._meta.value = "Change review filters or exit batch mode."
            return
        reclaim = int(getattr(group, "reclaimable", 0) or 0)
        self._title.value = f"Group {index + 1} of {total}"
        self._meta.value = (
            f"{len(group.files)} files · {fmt_size(reclaim)} reclaimable · "
            f"similarity {getattr(group, 'similarity_type', 'exact') or 'exact'}"
        )
        self._title.color = self._t.colors.fg
        self._meta.color = self._t.colors.fg_muted
