from __future__ import annotations

import flet as ft

from cerebro.v2.ui.flet_app.pages.review_flow.state import ReviewFlowState
from cerebro.v2.ui.flet_app.theme import ThemeTokens, fmt_size


def build_execute_screen(
    t: ThemeTokens,
    state: ReviewFlowState,
    *,
    on_back,
    on_confirm_toggle,
    on_execute,
    on_cancel_remaining,
) -> ft.Column:
    buckets = state.cart_buckets()
    delete_count = len(buckets["delete"])
    freed = sum(int(f.size) for f in buckets["delete"])
    done, total = state.execute_progress
    progress = ft.ProgressBar(value=(done / total) if total else 0)
    errors = ft.Column([ft.Text(err, color=t.colors.danger, size=t.typography.size_xs) for err in state.execute_errors])
    return ft.Column(
        [
            ft.Row([ft.TextButton("← Review Cart", on_click=on_back), ft.Text("Confirm Actions", weight=ft.FontWeight.W_700)]),
            ft.Text("You are about to:"),
            ft.Text(f"• Move {delete_count} files to Trash"),
            ft.Text(f"• Free {fmt_size(freed)}"),
            ft.Checkbox(label="I understand these files will be removed", value=state.execute_confirmed, on_change=on_confirm_toggle),
            progress,
            errors,
            ft.Row(
                [
                    ft.OutlinedButton("Cancel", on_click=on_back),
                    ft.FilledButton("Execute" if not state.dry_run else "Simulate Execute", on_click=on_execute),
                    ft.TextButton("Cancel Remaining", on_click=on_cancel_remaining),
                ]
            ),
        ],
        expand=True,
        spacing=8,
    )
