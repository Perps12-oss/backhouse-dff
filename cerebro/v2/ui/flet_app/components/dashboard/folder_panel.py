"""Selected-folder chips and browse target for Home."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import flet as ft

from cerebro.v2.ui.flet_app.design_system.glass import glass_container
from cerebro.v2.ui.flet_app.theme import ThemeTokens


class DashboardFolderPanel:
    """Folder drop/browse surface and quick-add affordance."""

    def __init__(
        self,
        t: ThemeTokens,
        *,
        on_browse: Callable[[ft.ControlEvent], None],
        on_quick_add: Callable[[ft.ControlEvent | None], None],
        on_hover: Callable[[ft.ControlEvent, ft.Container], None],
        on_remove_folder: Callable[[Path], None],
    ) -> None:
        self._on_remove_folder = on_remove_folder
        self._t = t
        s = t.spacing
        self._folder_chips_row = ft.Row([], wrap=True, spacing=s.xs)
        self._folder_section_icon = ft.Icon(
            ft.icons.Icons.FOLDER_OPEN, size=18, color=t.colors.accent
        )
        self._folder_container = glass_container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            self._folder_section_icon,
                            ft.Text(
                                "Selected folders",
                                color=t.colors.fg_muted,
                                size=t.typography.size_sm,
                                weight=ft.FontWeight.W_600,
                            ),
                            ft.Container(expand=True),
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    self._folder_chips_row,
                    ft.Container(
                        content=ft.FilledTonalButton(
                            "+ Quick Add: Desktop & Downloads",
                            on_click=on_quick_add,
                            style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=999)),
                        ),
                        padding=ft.padding.only(top=s.xs),
                    ),
                ],
                spacing=s.xs,
            ),
            t=t,
            padding=s.md,
        )
        self._folder_container.on_click = on_browse
        self._folder_container.on_hover = on_hover
        self._folder_container.ink = True

    @property
    def container(self) -> ft.Container:
        return self._folder_container

    @property
    def chips_row(self) -> ft.Row:
        return self._folder_chips_row

    @property
    def section_icon(self) -> ft.Icon:
        return self._folder_section_icon

    def sync_theme(self, t: ThemeTokens) -> None:
        self._t = t
        self._folder_container.bgcolor = t.colors.glass_bg
        self._folder_container.border = ft.border.all(1, t.colors.glass_border)
        self._folder_section_icon.color = t.colors.accent

    def refresh_chips(self, folders: list[Path], *, mounted: bool) -> None:
        t = self._t
        if not folders:
            self._folder_container.height = 108
            self._folder_container.border = ft.border.all(1, ft.Colors.with_opacity(0.40, "#22D3EE"))
            self._folder_container.border_radius = 12
            self._folder_chips_row.controls = [
                ft.Container(
                    border=ft.border.all(1, ft.Colors.with_opacity(0.52, t.colors.border)),
                    border_radius=10,
                    padding=ft.Padding.symmetric(horizontal=12, vertical=14),
                    bgcolor=ft.Colors.with_opacity(0.07, t.colors.primary),
                    content=ft.Column(
                        [
                            ft.Row(
                                [
                                    ft.Icon(ft.icons.Icons.FILE_UPLOAD_OUTLINED, size=24, color="#22D3EE"),
                                    ft.Text(
                                        "Drop a folder here or click to browse",
                                        color=t.colors.fg2,
                                        size=t.typography.size_base,
                                        weight=ft.FontWeight.W_600,
                                    ),
                                ],
                                spacing=8,
                            ),
                            ft.Text(
                                "Add folders to scan for duplicate files and similar images",
                                color=t.colors.fg2,
                                size=t.typography.size_sm,
                                weight=ft.FontWeight.W_500,
                            ),
                        ],
                        spacing=6,
                    ),
                )
            ]
        else:
            self._folder_container.height = None
            self._folder_container.border = ft.border.all(1, ft.Colors.with_opacity(0.35, "#22D3EE"))
            self._folder_chips_row.controls = [
                ft.Chip(
                    label=ft.Text(str(folder), size=t.typography.size_sm),
                    on_delete=lambda e, p=folder: self._on_remove_folder(p),
                    shape=ft.RoundedRectangleBorder(radius=8),
                    bgcolor=ft.Colors.with_opacity(0.1, t.colors.primary),
                    tooltip=str(folder),
                )
                for folder in folders
            ]
        if mounted:
            self._folder_chips_row.update()
