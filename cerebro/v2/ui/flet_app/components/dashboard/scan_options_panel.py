"""Advanced scan settings dropdown for Home."""

from __future__ import annotations

from typing import Callable

import flet as ft

from cerebro.v2.ui.flet_app.pill_button_styles import pill_outlined_button_style
from cerebro.v2.ui.flet_app.design_system.glass import glass_container
from cerebro.v2.ui.flet_app.theme import ThemeTokens


class DashboardScanOptionsPanel:
    """Scan mode checkboxes and advanced scan settings."""

    def __init__(
        self,
        t: ThemeTokens,
        *,
        on_archives_change: Callable[[ft.ControlEvent], None],
        on_toggle_advanced: Callable[[ft.ControlEvent], None],
        on_toggle_dropdown: Callable[[ft.ControlEvent], None],
        on_min_size_change: Callable[[ft.ControlEvent], None],
        on_exclude_paths_blur: Callable[[ft.ControlEvent], None],
        on_browse_exclude_path: Callable[[ft.ControlEvent], None],
        on_include_subfolders_change: Callable[[ft.ControlEvent], None],
    ) -> None:
        self._t = t
        self._advanced_options_visible = False
        self._scan_options_dropdown_open = False
        s = t.spacing

        self.mode_label = ft.Text(
            "Scan mode",
            size=t.typography.size_sm,
            weight=ft.FontWeight.W_600,
            color=t.colors.fg_muted,
        )
        self.mode_row = ft.Column(
            [],
            spacing=s.sm,
            horizontal_alignment=ft.CrossAxisAlignment.START,
            visible=True,
        )
        self.scan_type_summary = ft.Text(
            "1 type selected",
            size=t.typography.size_xs,
            color=t.colors.fg_muted,
            italic=True,
        )
        self.scan_archives_cb = ft.Checkbox(
            label="Scan inside archives",
            value=False,
            active_color="#F59E0B",
            label_style=ft.TextStyle(color=t.colors.fg2, size=t.typography.size_sm),
            on_change=on_archives_change,
        )
        self.archives_warning = ft.Text(
            "⚠ Very slow — archives may be gigabytes. Use only for forensic or backup dedup.",
            size=t.typography.size_xs,
            color="#F59E0B",
            italic=True,
            visible=False,
        )
        self.min_size_label = ft.Text(
            "Min file size: 0 MB",
            size=t.typography.size_sm,
            color=t.colors.fg2,
        )
        self.min_size_slider = ft.Slider(
            min=0,
            max=1024,
            divisions=128,
            value=0,
            label="{value} MB",
            on_change=on_min_size_change,
        )
        self.exclude_paths_tf = ft.TextField(
            label="Exclude paths (one per line)",
            hint_text="D:\\Photos\\Backups",
            multiline=True,
            min_lines=3,
            max_lines=6,
            on_blur=on_exclude_paths_blur,
        )
        self.exclude_paths_browse_btn = ft.OutlinedButton(
            "Browse",
            icon=ft.icons.Icons.FOLDER_OPEN,
            on_click=on_browse_exclude_path,
            style=pill_outlined_button_style(t),
        )
        self.include_subfolders_sw = ft.Switch(
            label="Include subfolders",
            value=True,
            on_change=on_include_subfolders_change,
        )
        self.advanced_panel = ft.Container(
            visible=False,
            content=ft.Column(
                [
                    self.include_subfolders_sw,
                    self.min_size_label,
                    self.min_size_slider,
                    ft.Row(
                        [
                            ft.Text(
                                "Exclude paths",
                                size=t.typography.size_sm,
                                color=t.colors.fg_muted,
                            ),
                            ft.Container(expand=True),
                            self.exclude_paths_browse_btn,
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    self.exclude_paths_tf,
                ],
                spacing=8,
                tight=True,
            ),
            padding=ft.padding.only(top=8),
        )
        self.advanced_toggle_btn = ft.IconButton(
            icon=ft.icons.Icons.SETTINGS,
            tooltip="Advanced scan options",
            on_click=on_toggle_advanced,
        )
        self.scan_options_row = ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            self.mode_label,
                            ft.Container(expand=True),
                            self.advanced_toggle_btn,
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    self.scan_type_summary,
                    self.mode_row,
                    ft.Text(
                        "Advanced scan settings",
                        size=t.typography.size_sm,
                        weight=ft.FontWeight.W_500,
                        color=t.colors.fg_muted,
                    ),
                    self.scan_archives_cb,
                    self.archives_warning,
                    self.advanced_panel,
                ],
                spacing=4,
                tight=True,
            ),
            padding=ft.Padding.symmetric(horizontal=s.md, vertical=s.sm),
        )
        self.scan_options_toggle_btn = ft.OutlinedButton(
            "Advanced scan settings",
            icon=ft.icons.Icons.KEYBOARD_ARROW_DOWN,
            on_click=on_toggle_dropdown,
            style=pill_outlined_button_style(t),
        )
        self.scan_options_dropdown = ft.Container(
            content=glass_container(
                content=self.scan_options_row,
                t=t,
                padding=ft.padding.all(s.xl),
            ),
            visible=False,
            width=620,
        )

    def sync_theme(self, t: ThemeTokens) -> None:
        self._t = t
        self.mode_label.color = t.colors.fg_muted
        self.exclude_paths_browse_btn.style = pill_outlined_button_style(t)
        self.scan_options_toggle_btn.style = pill_outlined_button_style(t)

    def toggle_advanced_panel(self, safe_update: Callable[[ft.Control | None], None]) -> None:
        self._advanced_options_visible = not self._advanced_options_visible
        self.advanced_panel.visible = self._advanced_options_visible
        self.advanced_toggle_btn.icon = (
            ft.icons.Icons.SETTINGS_SUGGEST
            if self._advanced_options_visible
            else ft.icons.Icons.SETTINGS
        )
        safe_update(self.advanced_panel)
        safe_update(self.advanced_toggle_btn)

    def toggle_dropdown(self, safe_update: Callable[[ft.Control | None], None]) -> None:
        self._scan_options_dropdown_open = not self._scan_options_dropdown_open
        self.scan_options_dropdown.visible = self._scan_options_dropdown_open
        self.scan_options_toggle_btn.icon = (
            ft.icons.Icons.KEYBOARD_ARROW_UP
            if self._scan_options_dropdown_open
            else ft.icons.Icons.KEYBOARD_ARROW_DOWN
        )
        safe_update(self.scan_options_dropdown)
        safe_update(self.scan_options_toggle_btn)
