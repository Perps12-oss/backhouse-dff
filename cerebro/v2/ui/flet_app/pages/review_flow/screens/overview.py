from __future__ import annotations

import flet as ft

from cerebro.v2.ui.flet_app.pages.review_flow.mock_data import mock_overview_metrics
from cerebro.v2.ui.flet_app.theme import ThemeTokens, fmt_size


def build_overview_screen(
    t: ThemeTokens,
    groups,
    *,
    on_start_review,
    on_auto_select,
    on_filter,
    on_export,
) -> ft.Column:
    metrics = mock_overview_metrics(groups)
    hero = ft.Text(
        f"{metrics['set_count']:,} duplicate sets found",
        size=t.typography.size_xxl,
        weight=ft.FontWeight.W_700,
        color=t.colors.fg,
        text_align=ft.TextAlign.CENTER,
    )
    sub = ft.Text(
        f"{metrics['file_count']:,} files • {fmt_size(int(metrics['reclaimable_bytes']))} recoverable",
        size=t.typography.size_md,
        color=t.colors.fg_muted,
        text_align=ft.TextAlign.CENTER,
    )

    def metric_card(label: str, value: str) -> ft.Container:
        return ft.Container(
            content=ft.Column(
                [
                    ft.Text(value, size=t.typography.size_xl, weight=ft.FontWeight.W_700, color=t.colors.fg),
                    ft.Text(label, size=t.typography.size_xs, color=t.colors.fg_muted),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=2,
            ),
            padding=16,
            border_radius=8,
            border=ft.border.all(1, t.colors.border),
            bgcolor=t.colors.surface,
            expand=True,
        )

    cards = ft.Row(
        [
            metric_card("files", f"{metrics['file_count']:,}"),
            metric_card("waste", fmt_size(int(metrics['reclaimable_bytes']))),
            metric_card("duration", "14m 32s"),
        ],
        spacing=12,
    )
    return ft.Column(
        [
            ft.Container(expand=True),
            ft.Icon(ft.icons.Icons.CHECK_CIRCLE, size=56, color=t.colors.success),
            hero,
            sub,
            ft.Container(height=16),
            cards,
            ft.Container(height=24),
            ft.FilledButton("Start Review", on_click=on_start_review, width=280),
            ft.Row(
                [
                    ft.TextButton("Auto-Select", on_click=on_auto_select),
                    ft.TextButton("Filter", on_click=on_filter),
                    ft.TextButton("Export", on_click=on_export),
                ],
                alignment=ft.MainAxisAlignment.CENTER,
            ),
            ft.Container(expand=True),
        ],
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        expand=True,
        scroll=ft.ScrollMode.AUTO,
    )
