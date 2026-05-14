from __future__ import annotations

import flet as ft

from cerebro.v2.ui.flet_app.pages.review_flow.state import ReviewScreen
from cerebro.v2.ui.flet_app.theme import ThemeTokens


_STEPS: list[tuple[ReviewScreen, str, str]] = [
    ("overview", "Overview", "Scan complete"),
    ("browse", "Browse", "Review duplicates"),
    ("inspect", "Inspect", "Compare and decide"),
    ("cart", "Review Cart", "Audit selections"),
    ("execute", "Execute", "Confirm and run"),
    ("report", "Report", "Summary and export"),
]


def build_progress_sidebar(t: ThemeTokens, active: ReviewScreen, on_jump) -> ft.Container:
    items: list[ft.Control] = []
    active_idx = next((i for i, (sid, _, _) in enumerate(_STEPS) if sid == active), 0)
    for idx, (sid, title, subtitle) in enumerate(_STEPS):
        reached = idx <= active_idx
        dot = ft.Text("✓" if idx < active_idx else str(idx + 1), size=11, color=t.colors.fg if reached else t.colors.fg_muted)
        row = ft.Container(
            content=ft.Row(
                [
                    ft.Container(width=24, content=dot, alignment=ft.Alignment.CENTER),
                    ft.Column(
                        [
                            ft.Text(title, size=t.typography.size_sm, weight=ft.FontWeight.W_600, color=t.colors.fg if reached else t.colors.fg_muted),
                            ft.Text(subtitle, size=t.typography.size_xs, color=t.colors.fg_muted),
                        ],
                        spacing=0,
                    ),
                ],
                spacing=8,
            ),
            padding=ft.padding.symmetric(vertical=6, horizontal=8),
            border_radius=8,
            bgcolor=ft.Colors.with_opacity(0.06, t.colors.primary) if sid == active else None,
            on_click=(lambda e, s=sid: on_jump(s)) if reached else None,
        )
        items.append(row)
    return ft.Container(
        width=220,
        padding=12,
        border=ft.border.only(right=ft.BorderSide(1, t.colors.border)),
        content=ft.Column(items, spacing=4),
    )
