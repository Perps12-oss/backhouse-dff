"""Advanced scan settings dropdown for Home."""

from __future__ import annotations

from typing import Callable

import flet as ft

from cerebro.v2.ui.flet_app.pill_button_styles import pill_outlined_button_style
from cerebro.v2.ui.flet_app.design_system.cards import apply_minimal_style, minimal_surface
from cerebro.v2.ui.flet_app.theme import ThemeTokens
from cerebro.v2.ui.flet_app.utils.motion import animation_or_none


class DashboardScanOptionsPanel:
    """Scan mode checkboxes and advanced scan settings."""

    def __init__(
        self,
        t: ThemeTokens,
        bridge=None,
        *,
        on_archives_change: Callable[[ft.ControlEvent], None],
        on_toggle_advanced: Callable[[ft.ControlEvent], None] | None = None,
        on_toggle_dropdown: Callable[[ft.ControlEvent], None],
        on_min_size_change: Callable[[ft.ControlEvent], None],
        on_exclude_paths_blur: Callable[[ft.ControlEvent], None],
        on_browse_exclude_path: Callable[[ft.ControlEvent], None],
        on_include_subfolders_change: Callable[[ft.ControlEvent], None],
        on_index_only_change: Callable[[ft.ControlEvent], None] | None = None,
        on_verify_duplicates_change: Callable[[ft.ControlEvent], None] | None = None,
    ) -> None:
        self._t = t
        self._on_toggle_advanced = on_toggle_advanced
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
        self.scan_archives_sw = ft.Switch(
            label="Scan inside archives (coming soon)",
            value=False,
            disabled=True,
            active_color="#F59E0B",
            label_text_style=ft.TextStyle(color=t.colors.fg_muted, size=t.typography.size_sm),
            tooltip="Archive extraction is not yet implemented; this option is disabled.",
            on_change=on_archives_change,
        )
        self.archives_warning = ft.Text(
            "Archive scanning is not available yet — enable when a future release adds extraction.",
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
        self.index_only_sw = ft.Switch(
            label="Index only (hash duplicates later)",
            value=False,
            label_text_style=ft.TextStyle(color=t.colors.fg2, size=t.typography.size_sm),
            on_change=on_index_only_change,
        )
        self.verify_duplicates_sw = ft.Switch(
            label="Deep verify (full-file hash)",
            value=False,
            label_text_style=ft.TextStyle(color=t.colors.fg2, size=t.typography.size_sm),
            on_change=on_verify_duplicates_change,
        )
        self._advanced_chevron = ft.Icon(
            ft.icons.Icons.EXPAND_MORE,
            size=18,
            color=t.colors.fg_muted,
            animate_rotation=ft.Animation(200, ft.AnimationCurve.EASE_IN_OUT),
            rotate=ft.Rotate(0, alignment=ft.Alignment(0, 0)),
        )
        self.advanced_panel = ft.Column(
            [
                self.include_subfolders_sw,
                self.index_only_sw,
                self.verify_duplicates_sw,
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
        )
        self._advanced_expanded_slot = ft.Container(
            key="advanced_expanded",
            content=self.advanced_panel,
            padding=ft.padding.only(top=8),
        )
        self._advanced_collapsed_slot = ft.Container(key="advanced_collapsed", height=0)
        self._advanced_switcher = ft.AnimatedSwitcher(
            duration=200,
            transition=ft.AnimatedSwitcherTransition.FADE,
            content=self._advanced_collapsed_slot,
            switch_in_curve=ft.AnimationCurve.EASE_OUT,
            switch_out_curve=ft.AnimationCurve.EASE_IN,
        )
        self.advanced_expansion = ft.ExpansionTile(
            title=ft.Text(
                "Advanced scan settings",
                size=t.typography.size_sm,
                weight=ft.FontWeight.W_500,
                color=t.colors.fg_muted,
            ),
            trailing=self._advanced_chevron,
            controls=[self._advanced_switcher],
            expanded=False,
            on_change=self._on_advanced_expansion_change,
        )
        self.scan_options_row = ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [self.mode_label, ft.Container(expand=True)],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    self.scan_type_summary,
                    self.mode_row,
                    self.scan_archives_sw,
                    self.archives_warning,
                    self.advanced_expansion,
                ],
                spacing=4,
                tight=True,
            ),
            padding=ft.Padding.symmetric(horizontal=s.md, vertical=s.sm),
        )
        self._dropdown_collapsed = ft.Container(key="scan_opts_collapsed", height=0)
        self._dropdown_expanded = ft.Container(key="scan_opts_expanded", content=self.scan_options_row)
        self._dropdown_switcher = ft.AnimatedSwitcher(
            duration=200,
            transition=ft.AnimatedSwitcherTransition.FADE,
            content=self._dropdown_collapsed,
            switch_in_curve=ft.AnimationCurve.EASE_OUT,
            switch_out_curve=ft.AnimationCurve.EASE_IN,
        )
        self.scan_options_toggle_btn = ft.OutlinedButton(
            "Advanced scan settings",
            icon=ft.icons.Icons.KEYBOARD_ARROW_DOWN,
            on_click=on_toggle_dropdown,
            style=pill_outlined_button_style(t),
        )
        self.scan_options_dropdown = ft.Container(
            content=minimal_surface(
                content=self._dropdown_switcher,
                padding=ft.padding.all(s.xl),
            ),
            visible=False,
            width=620,
            alignment=ft.Alignment(0, 0),
        )

    def _on_advanced_expansion_change(self, e: ft.ControlEvent) -> None:
        expanded = bool(getattr(e.control, "expanded", False))
        self._advanced_options_visible = expanded
        self._advanced_chevron.rotate = ft.Rotate(
            3.14159 if expanded else 0,
            alignment=ft.Alignment(0, 0),
        )
        self._advanced_switcher.content = (
            self._advanced_expanded_slot if expanded else self._advanced_collapsed_slot
        )
        if self._on_toggle_advanced is not None:
            self._on_toggle_advanced(e)
        try:
            if self._advanced_switcher.page is not None:
                self._advanced_switcher.update()
        except RuntimeError:
            pass

    def sync_theme(self, t: ThemeTokens) -> None:
        self._t = t
        self.mode_label.color = t.colors.fg_muted
        self.exclude_paths_browse_btn.style = pill_outlined_button_style(t)
        self.scan_options_toggle_btn.style = pill_outlined_button_style(t)
        self._advanced_chevron.color = t.colors.fg_muted
        inner = self.scan_options_dropdown.content
        if isinstance(inner, ft.Container):
            apply_minimal_style(inner)
            inner.border = ft.border.all(1, t.colors.border)

    def toggle_advanced_panel(self, safe_update: Callable[[ft.Control | None], None]) -> None:
        self._advanced_options_visible = not self._advanced_options_visible
        self.advanced_expansion.expanded = self._advanced_options_visible
        self._advanced_chevron.rotate = ft.Rotate(
            3.14159 if self._advanced_options_visible else 0,
            alignment=ft.Alignment(0, 0),
        )
        self._advanced_switcher.content = (
            self._advanced_expanded_slot
            if self._advanced_options_visible
            else self._advanced_collapsed_slot
        )
        safe_update(self.advanced_expansion)
        safe_update(self._advanced_switcher)

    def toggle_dropdown(self, safe_update: Callable[[ft.Control | None], None]) -> None:
        self._scan_options_dropdown_open = not self._scan_options_dropdown_open
        self.scan_options_dropdown.visible = self._scan_options_dropdown_open
        self._dropdown_switcher.content = (
            self._dropdown_expanded
            if self._scan_options_dropdown_open
            else self._dropdown_collapsed
        )
        self.scan_options_toggle_btn.icon = (
            ft.icons.Icons.KEYBOARD_ARROW_UP
            if self._scan_options_dropdown_open
            else ft.icons.Icons.KEYBOARD_ARROW_DOWN
        )
        safe_update(self.scan_options_dropdown)
        safe_update(self.scan_options_toggle_btn)
        safe_update(self._dropdown_switcher)
