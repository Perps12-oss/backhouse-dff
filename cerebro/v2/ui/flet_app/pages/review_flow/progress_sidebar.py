from __future__ import annotations

import flet as ft

from cerebro.v2.ui.flet_app.pages.review_flow.state import ReviewFlowState, ReviewScreen
from cerebro.v2.ui.flet_app.theme import ThemeTokens, fmt_size


def build_progress_sidebar(t: ThemeTokens, active: ReviewScreen, state: ReviewFlowState, on_jump) -> ft.Container:
    """Operational status strip (replaces linear wizard steps)."""
    n_groups = len(state.scan_results)
    marked = len(state.cart_buckets()["delete"])
    reclaim = state.marked_bytes()
    mode = (state.scan_mode or "files").replace("_", " ").title()
    screen_label = {"overview": "Overview", "browse": "Browse", "inspect": "Compare"}.get(active, active)
    return ft.Container(
        width=220,
        padding=12,
        border=ft.border.only(right=ft.BorderSide(1, t.colors.border)),
        content=ft.Column(
            [
                ft.Text("Review", size=t.typography.size_xs, color=t.colors.fg_muted, weight=ft.FontWeight.W_600),
                ft.Text(screen_label, size=t.typography.size_sm, weight=ft.FontWeight.W_700, color=t.colors.fg),
                ft.Divider(height=1, color=t.colors.border),
                ft.Text(f"Scan: {mode}", size=t.typography.size_xs, color=t.colors.fg_muted),
                ft.Text(f"{n_groups:,} groups", size=t.typography.size_xs, color=t.colors.fg),
                ft.Text(f"{marked:,} marked · {fmt_size(reclaim)}", size=t.typography.size_xs, color=t.colors.primary),
                ft.Container(height=8),
                ft.TextButton("Go to Overview", on_click=lambda e: on_jump("overview")),
                ft.TextButton("Go to Browse", on_click=lambda e: on_jump("browse")),
            ],
            spacing=4,
            tight=True,
        ),
    )
