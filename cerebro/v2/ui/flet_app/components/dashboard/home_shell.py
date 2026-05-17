"""Home workflow stack layout."""

from __future__ import annotations

import flet as ft

from cerebro.v2.ui.flet_app.design_system.cards import flat_card
from cerebro.v2.ui.flet_app.theme import ThemeTokens


class DashboardHomeShell:
    """Hero, folder panel, scan options, and primary CTA stack."""

    @staticmethod
    def build_workflow_stack(
        t: ThemeTokens,
        *,
        page: ft.Page | None = None,
        hero: ft.Container,
        folder_panel: ft.Container,
        actions: ft.Column,
        scan_options_toggle_btn: ft.Control,
        scan_options_dropdown: ft.Control,
    ) -> ft.Container:
        _ = page
        s = t.spacing
        folder_section = ft.Column(
            [
                folder_panel,
                ft.Container(
                    content=actions,
                    padding=ft.padding.only(top=s.xs),
                    alignment=ft.Alignment(0.34, 0),
                ),
            ],
            spacing=s.xs,
        )
        folder_panel_host = ft.Container(content=folder_section, width=620)
        capability_hint = ft.Text(
            "Content-aware matching and perceptual image analysis",
            size=t.typography.size_xs,
            color=t.colors.fg_muted,
            text_align=ft.TextAlign.CENTER,
        )
        column = ft.Column(
            [
                hero,
                folder_panel_host,
                ft.Container(
                    content=scan_options_toggle_btn,
                    width=620,
                    padding=ft.padding.only(top=s.sm),
                    alignment=ft.Alignment(0.16, 0),
                ),
                scan_options_dropdown,
                capability_hint,
            ],
            spacing=s.xs,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        )
        return flat_card(
            column,
            t,
            width=840,
            padding=ft.Padding.symmetric(horizontal=s.lg, vertical=s.md),
        )
