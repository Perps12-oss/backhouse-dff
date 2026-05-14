from __future__ import annotations

import flet as ft

from cerebro.v2.ui.flet_app.pages.review_flow.state import ReviewFlowState
from cerebro.v2.ui.flet_app.theme import ThemeTokens, fmt_size


def build_cart_screen(
    t: ThemeTokens,
    state: ReviewFlowState,
    *,
    on_back,
    on_proceed,
    on_toggle_dry_run,
) -> ft.Column:
    buckets = state.cart_buckets()
    delete_files = buckets["delete"]
    keep_files = buckets["keep"]
    protected = buckets["protected"]
    freed = sum(int(f.size) for f in delete_files)
    warning = ft.Container(visible=False)
    if protected and delete_files:
        warning = ft.Container(
            content=ft.Text(f"⚠ {len(protected)} protected files in delete list", color=t.colors.danger),
            visible=True,
        )
    delete_list = ft.Column(
        [ft.Text(f"{f.path.name} — {fmt_size(int(f.size))}", size=t.typography.size_sm) for f in delete_files[:200]],
        scroll=ft.ScrollMode.AUTO,
        height=220,
    )
    dry = ft.Switch(label="Dry Run", value=state.dry_run, on_change=on_toggle_dry_run)
    return ft.Column(
        [
            ft.Row([ft.TextButton("← Browse", on_click=on_back), ft.Text("Review Cart", weight=ft.FontWeight.W_700)]),
            ft.Text(f"Delete {len(delete_files)} files • {fmt_size(freed)} recoverable"),
            ft.Text(f"Keep {len(keep_files)} files • Protected {len(protected)}"),
            warning,
            delete_list,
            dry,
            ft.Container(expand=True),
            ft.FilledButton("Proceed to Execute", on_click=on_proceed),
        ],
        expand=True,
        spacing=8,
    )
