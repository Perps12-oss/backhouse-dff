"""Dashboard page — home/landing page with quick-start scan controls."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import flet as ft

from cerebro.v2.ui.flet_app.theme import ThemeTokens, theme_for_mode, fmt_size, SCAN_MODES

if TYPE_CHECKING:
    from cerebro.v2.ui.flet_app.services.state_bridge import StateBridge

_log = logging.getLogger(__name__)


class DashboardPage(ft.Column):
    """Home page with scan configuration and quick-start."""

    def __init__(self, bridge: "StateBridge"):
        super().__init__(expand=True, scroll=ft.ScrollMode.AUTO)
        self._bridge = bridge
        self._t = theme_for_mode("light")
        self._selected_mode = "files"
        self._build()

    def _build(self) -> None:
        t = self._t
        s = t.spacing

        # Hero section
        self._hero = ft.Container(
            content=ft.Column(
                [
                    ft.Icon(ft.icons.Icons.SEARCH, size=48, color=t.colors.primary),
                    ft.Text(
                        "Cerebro Duplicate Finder",
                        size=t.typography.size_xxl,
                        weight=ft.FontWeight.BOLD,
                        color=t.colors.fg,
                    ),
                    ft.Text(
                        "Find and remove duplicate files to reclaim disk space.",
                        size=t.typography.size_md,
                        color=t.colors.fg2,
                        text_align=ft.TextAlign.CENTER,
                    ),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=s.sm,
            ),
            padding=t.spacing.xxl,
            alignment=ft.alignment.center,
        )

        # Scan mode selector
        self._mode_row = ft.Row(
            [
                ft.ElevatedButton(
                    m["label"],
                    icon=m["icon"],
                    on_click=lambda e, k=m["key"]: self._select_mode(k),
                    data=m["key"],
                    style=ft.ButtonStyle(
                        bgcolor=t.colors.primary if m["key"] == self._selected_mode else t.colors.bg3,
                        color=t.colors.bg if m["key"] == self._selected_mode else t.colors.fg2,
                    ),
                )
                for m in SCAN_MODES
            ],
            alignment=ft.MainAxisAlignment.CENTER,
            wrap=True,
            spacing=s.sm,
        )

        # Folder list
        self._folder_chips: list[ft.Chip] = []
        self._folder_row = ft.Row(
            [ft.Text("No folders selected", color=t.colors.fg_muted, size=t.typography.size_base)],
            wrap=True,
            spacing=s.xs,
        )

        # Action buttons
        self._actions = ft.Row(
            [
                ft.OutlinedButton(
                    "Browse Folders",
                    icon=ft.icons.Icons.FOLDER_OPEN,
                    on_click=self._browse_folders,
                ),
                ft.FilledButton(
                    "Start Scan",
                    icon=ft.icons.Icons.PLAY_ARROW,
                    on_click=self._start_scan,
                    style=ft.ButtonStyle(
                        bgcolor=t.colors.primary,
                        color=t.colors.bg,
                    ),
                ),
            ],
            alignment=ft.MainAxisAlignment.CENTER,
            spacing=s.lg,
        )

        # Progress bar (hidden initially)
        self._progress = ft.ProgressBar(
            width=400,
            bar_height=6,
            visible=False,
            color=t.colors.primary,
            bgcolor=t.colors.bg3,
        )
        self._progress_label = ft.Text("", color=t.colors.fg2, size=t.typography.size_sm, visible=False)

        # Status text
        self._status = ft.Text(
            "Select folders and start a scan to find duplicates.",
            color=t.colors.fg_muted,
            size=t.typography.size_base,
            text_align=ft.TextAlign.CENTER,
        )

        self.controls = [
            self._hero,
            ft.Container(content=self._mode_row, padding=ft.padding.only(bottom=s.lg),
                         alignment=ft.alignment.center),
            ft.Container(content=self._folder_row, padding=ft.padding.symmetric(horizontal=s.xl)),
            ft.Container(content=self._actions, padding=ft.padding.only(top=s.md, bottom=s.md),
                         alignment=ft.alignment.center),
            ft.Container(content=self._progress, padding=ft.padding.only(bottom=s.xs),
                         alignment=ft.alignment.center),
            ft.Container(content=self._progress_label, alignment=ft.alignment.center),
            ft.Container(content=self._status, padding=ft.padding.only(top=s.md),
                         alignment=ft.alignment.center),
        ]

    def _select_mode(self, key: str) -> None:
        self._selected_mode = key
        for btn in self._mode_row.controls:
            is_active = btn.data == key
            btn.style = ft.ButtonStyle(
                bgcolor=self._t.colors.primary if is_active else self._t.colors.bg3,
                color=self._t.colors.bg if is_active else self._t.colors.fg2,
            )
            btn.update()

    def _browse_folders(self, e: ft.ControlEvent) -> None:
        self._page.open(
            ft.FilePicker(
                on_result=self._on_folder_pick,
            )
        )

    def _on_folder_pick(self, e: ft.FilePickerResultEvent) -> None:
        if e.path:
            from pathlib import Path
            self._add_folder(Path(e.path))

    def _add_folder(self, path) -> None:
        if not hasattr(self, "_folders"):
            self._folders: list = []
        if path in self._folders:
            return
        self._folders.append(path)
        self._refresh_folder_chips()

    def _refresh_folder_chips(self) -> None:
        t = self._t
        self._folder_row.controls = [
            ft.Chip(
                label=ft.Text(str(f), size=t.typography.size_sm),
                on_delete=lambda e, p=f: self._remove_folder(p),
            )
            for f in getattr(self, "_folders", [])
        ]
        self._folder_row.update()

    def _remove_folder(self, path) -> None:
        if path in self._folders:
            self._folders.remove(path)
        self._refresh_folder_chips()

    def _start_scan(self, e: ft.ControlEvent) -> None:
        folders = getattr(self, "_folders", [])
        if not folders:
            self._status.value = "Please select at least one folder first."
            self._status.update()
            return

        self._progress.visible = True
        self._progress_label.visible = True
        self._status.value = "Starting scan..."
        self._progress.update()
        self._progress_label.update()
        self._status.update()

        backend = self._bridge.backend
        backend.set_on_progress(self._on_scan_progress)
        backend.set_on_complete(self._on_scan_complete)
        backend.set_on_error(self._on_scan_error)
        backend.start_scan(folders, mode=self._selected_mode)

    def _on_scan_progress(self, data: dict) -> None:
        stage = data.get("stage", "")
        scanned = data.get("files_scanned", 0)
        total = data.get("files_total", 0)
        elapsed = data.get("elapsed_seconds", 0.0)
        current = data.get("current_file", "")

        self._status.value = f"Scanning... {stage}"
        self._progress_label.value = f"{scanned:,} files scanned  ·  {elapsed:.1f}s"
        if total > 0:
            self._progress.value = scanned / total
        self._status.update()
        self._progress.update()
        self._progress_label.update()

    def _on_scan_complete(self, results: list, mode: str) -> None:
        self._progress.visible = False
        self._progress_label.visible = False
        self._status.value = f"Scan complete — {len(results):,} duplicate groups found."
        self._status.update()
        self._progress.update()
        self._progress_label.update()

        self._bridge.dispatch_scan_complete(results, mode)
        self._bridge.navigate("duplicates")

    def _on_scan_error(self, msg: str) -> None:
        self._progress.visible = False
        self._progress_label.visible = False
        self._status.value = f"Scan error: {msg}"
        self._status.update()
        self._progress.update()
        self._progress_label.update()
