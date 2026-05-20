"""Browse-mode workstation sidebar shell (tools column + scroll)."""

from __future__ import annotations

import flet as ft

from cerebro.v2.ui.flet_app.pages.review_flow.progress_sidebar import (
    ProgressSidebarRefs,
    update_progress_sidebar_refs,
)
from cerebro.v2.ui.flet_app.pages.review_flow.state import ReviewFlowState, ReviewScreen
from cerebro.v2.ui.flet_app.theme import ThemeTokens

BROWSE_SIDEBAR_WIDTH = 288


def build_browse_workstation_sidebar(
    t: ThemeTokens,
    state: ReviewFlowState,
    on_jump,
) -> tuple[ft.Container, ProgressSidebarRefs, ft.Container]:
    """Return sidebar shell, mutable stat refs, and empty slot for browse workbench."""
    refs = ProgressSidebarRefs(
        screen_label=ft.Text("", size=t.typography.size_sm, weight=ft.FontWeight.W_700, color=t.colors.fg),
        groups_text=ft.Text("", size=t.typography.size_xs, color=t.colors.fg_muted),
        marked_text=ft.Text("", size=t.typography.size_xs, color=t.colors.primary),
    )
    update_progress_sidebar_refs(refs, "browse", state)
    mode = (state.scan_mode or "files").replace("_", " ").title()
    workbench_slot = ft.Container(expand=True)
    container = ft.Container(
        width=BROWSE_SIDEBAR_WIDTH,
        padding=ft.padding.only(left=12, right=12, top=12, bottom=8),
        border=ft.border.only(right=ft.BorderSide(1, t.colors.border)),
        content=ft.Column(
            [
                ft.Text("Review", size=t.typography.size_xs, color=t.colors.fg_muted, weight=ft.FontWeight.W_600),
                refs.screen_label,
                ft.Divider(height=1, color=t.colors.border),
                ft.Text(f"Scan: {mode}", size=t.typography.size_xs, color=t.colors.fg_muted),
                refs.groups_text,
                refs.marked_text,
                ft.Container(
                    content=workbench_slot,
                    expand=True,
                    alignment=ft.Alignment(0, -1),
                ),
                ft.Divider(height=1, color=t.colors.border),
                ft.TextButton("Go to Overview", on_click=lambda e: on_jump("overview")),
            ],
            spacing=4,
            expand=True,
        ),
    )
    return container, refs, workbench_slot


def refresh_browse_workstation_sidebar(
    refs: ProgressSidebarRefs,
    container: ft.Container,
    state: ReviewFlowState,
) -> None:
    update_progress_sidebar_refs(refs, "browse", state)
    from cerebro.v2.ui.flet_app.components.common.safe_controls import safe_update

    safe_update(container)
