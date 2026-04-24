"""Results page — displays duplicate groups with filtering and actions."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, List, Optional

import flet as ft

from cerebro.engines.base_engine import DuplicateGroup
from cerebro.v2.ui.flet_app.theme import (
    FILTER_EXTS, EXT_ALL_KNOWN, ThemeTokens, classify_file, fmt_size, theme_for_mode,
)

if TYPE_CHECKING:
    from cerebro.v2.ui.flet_app.services.state_bridge import StateBridge

_log = logging.getLogger(__name__)

_FILTER_TABS = [
    ("all", "All"),
    ("pictures", "Images"),
    ("music", "Music"),
    ("videos", "Videos"),
    ("documents", "Docs"),
    ("archives", "Archives"),
    ("other", "Other"),
]


class ResultsPage(ft.Column):
    """Duplicate group listing with type filters and summary stats."""

    def __init__(self, bridge: "StateBridge"):
        super().__init__(expand=True, scroll=ft.ScrollMode.AUTO)
        self._bridge = bridge
        self._t = theme_for_mode("light")
        self._groups: List[DuplicateGroup] = []
        self._filter_key = "all"
        self._scan_mode = "files"
        self._build()

    def _build(self) -> None:
        t = self._t

        # Header
        self._header = ft.Row(
            [
                ft.Text(
                    "Scan Results",
                    size=t.typography.size_xl,
                    weight=ft.FontWeight.BOLD,
                    color=t.colors.fg,
                ),
                self._summary = ft.Text(
                    "",
                    size=t.typography.size_base,
                    color=t.colors.fg2,
                ),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        )

        # Filter tabs
        self._filter_bar = ft.Row(
            [
                ft.ElevatedButton(
                    label,
                    on_click=lambda e, k=key: self._set_filter(k),
                    data=key,
                    style=ft.ButtonStyle(
                        bgcolor=t.colors.primary if key == "all" else t.colors.bg3,
                        color=t.colors.bg if key == "all" else t.colors.fg2,
                    ),
                )
                for key, label in _FILTER_TABS
            ],
            spacing=t.spacing.xs,
            wrap=True,
        )

        # Group list
        self._group_list = ft.ListView(
            expand=True,
            spacing=t.spacing.sm,
            padding=t.spacing.lg,
        )

        # Empty state
        self._empty = ft.Container(
            content=ft.Column(
                [
                    ft.Icon(ft.icons.Icons.SEARCH_OFF, size=64, color=t.colors.fg_muted),
                    ft.Text("No results yet", size=t.typography.size_lg, color=t.colors.fg2),
                    ft.Text(
                        "Run a scan from the Home page to find duplicates.",
                        size=t.typography.size_base,
                        color=t.colors.fg_muted,
                        text_align=ft.TextAlign.CENTER,
                    ),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=t.spacing.md,
            ),
            expand=True,
            alignment=ft.alignment.center,
        )

        self.controls = [
            ft.Container(content=self._header, padding=ft.padding.only(left=t.spacing.lg, right=t.spacing.lg, top=t.spacing.md)),
            ft.Container(content=self._filter_bar, padding=ft.padding.only(left=t.spacing.lg, bottom=t.spacing.sm)),
            self._empty,
        ]

    # -- Public API (matches Tkinter ResultsPage contract) --------------------

    def load_results(self, groups: List[DuplicateGroup], mode: str = "files") -> None:
        self._groups = list(groups)
        self._scan_mode = mode or "files"
        self._refresh()

    def get_groups(self) -> List[DuplicateGroup]:
        return list(self._groups)

    # -- Internal -------------------------------------------------------------

    def _set_filter(self, key: str) -> None:
        self._filter_key = key
        for btn in self._filter_bar.controls:
            is_active = btn.data == key
            btn.style = ft.ButtonStyle(
                bgcolor=self._t.colors.primary if is_active else self._t.colors.bg3,
                color=self._t.colors.bg if is_active else self._t.colors.fg2,
            )
            btn.update()
        self._refresh()

    def _filtered_groups(self) -> List[DuplicateGroup]:
        if self._filter_key == "all":
            return self._groups
        exts = FILTER_EXTS.get(self._filter_key)
        if exts is None:
            return [
                g for g in self._groups
                if all(
                    classify_file(getattr(f, "extension", "")) == "other"
                    for f in g.files
                )
            ]
        return [
            g for g in self._groups
            if any(
                getattr(f, "extension", "").lower() in exts
                for f in g.files
            )
        ]

    def _refresh(self) -> None:
        filtered = self._filtered_groups()
        t = self._t

        total_files = sum(len(g.files) for g in filtered)
        recoverable = sum(g.reclaimable for g in filtered)
        self._summary.value = (
            f"{len(filtered):,} groups  ·  {total_files:,} files  ·  {fmt_size(recoverable)} recoverable"
        )
        self._summary.update()

        if not filtered:
            if self._empty not in self.controls:
                self.controls.append(self._empty)
            if self._group_list in self.controls:
                self.controls.remove(self._group_list)
            self._empty.update()
            self.update()
            return

        if self._empty in self.controls:
            self.controls.remove(self._empty)
        if self._group_list not in self.controls:
            self.controls.append(self._group_list)

        self._group_list.controls = [
            self._build_group_card(g) for g in filtered
        ]
        self._group_list.update()
        self.update()

    def _build_group_card(self, group: DuplicateGroup) -> ft.Container:
        t = self._t
        paths = [str(f.path) for f in group.files]
        sample = paths[0] if paths else ""
        folder = str(__import__("pathlib").Path(sample).parent) if sample else ""

        return ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.icons.Icons.CONTENT_COPY, color=t.colors.primary),
                    ft.Column(
                        [
                            ft.Text(
                                __import__("pathlib").Path(sample).name if sample else "Group",
                                weight=ft.FontWeight.W_600,
                                color=t.colors.fg,
                                size=t.typography.size_md,
                            ),
                            ft.Text(
                                f"{len(group.files)} files  ·  {fmt_size(group.total_size)}  ·  {folder}",
                                color=t.colors.fg2,
                                size=t.typography.size_sm,
                            ),
                        ],
                        spacing=2,
                        expand=True,
                    ),
                    ft.Text(
                        fmt_size(group.reclaimable),
                        weight=ft.FontWeight.BOLD,
                        color=t.colors.primary,
                        size=t.typography.size_md,
                    ),
                    ft.IconButton(
                        icon=ft.icons.Icons.VISIBILITY,
                        tooltip="Review group",
                        on_click=lambda e, g=group: self._open_group(g),
                    ),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            ),
            padding=t.spacing.md,
            border=ft.border.all(1, t.colors.border),
            border_radius=t.border_radius,
            bgcolor=t.colors.bg,
        )

    def _open_group(self, group: DuplicateGroup) -> None:
        from cerebro.v2.ui.flet_app.layout import AppLayout
        self._bridge.coordinator.review_open_group(group.group_id, self._groups)
        layout = self._page.controls[0] if self._page.controls else None
        if isinstance(layout, AppLayout):
            layout.navigate_to("review")
