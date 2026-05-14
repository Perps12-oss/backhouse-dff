from __future__ import annotations

import flet as ft

from cerebro.v2.ui.flet_app.pages.review_flow.state import ReviewFlowState
from cerebro.v2.ui.flet_app.theme import ThemeTokens, fmt_size


def build_report_screen(
    t: ThemeTokens,
    state: ReviewFlowState,
    *,
    on_back_overview,
    on_export,
    on_new_scan,
) -> ft.Column:
    return ft.Column(
        [
            ft.Text("Done", size=t.typography.size_xxl, weight=ft.FontWeight.W_700, text_align=ft.TextAlign.CENTER),
            ft.Icon(ft.icons.Icons.CELEBRATION, size=48, color=t.colors.success),
            ft.Text(f"{state.report_deleted_count} files deleted", size=t.typography.size_lg, text_align=ft.TextAlign.CENTER),
            ft.Text(f"{fmt_size(state.report_freed_bytes)} freed", size=t.typography.size_md, color=t.colors.success, text_align=ft.TextAlign.CENTER),
            ft.Text(f"{len(state.execute_errors)} errors", color=t.colors.warning, text_align=ft.TextAlign.CENTER),
            ft.Row(
                [
                    ft.FilledButton("Export Report", on_click=on_export),
                    ft.OutlinedButton("Back to Overview", on_click=on_back_overview),
                    ft.TextButton("Start New Scan", on_click=on_new_scan),
                ],
                alignment=ft.MainAxisAlignment.CENTER,
                wrap=True,
            ),
        ],
        expand=True,
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        spacing=12,
    )
