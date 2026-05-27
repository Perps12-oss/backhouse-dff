"""Browse-mode workstation sidebar shell (tools column + scroll)."""

from __future__ import annotations

import flet as ft

from cerebro.v2.ui.flet_app.components.common.safe_controls import safe_update
from cerebro.v2.ui.flet_app.pages.review_flow.progress_sidebar import (
    ProgressSidebarRefs,
    update_progress_sidebar_refs,
)
from cerebro.v2.ui.flet_app.pages.review_flow.state import ReviewFlowState, ReviewScreen
from cerebro.v2.ui.flet_app.theme import ThemeTokens

BROWSE_SIDEBAR_WIDTH = 288
BROWSE_SIDEBAR_WIDTH_SIMPLE = 252


def build_browse_workstation_sidebar(
    t: ThemeTokens,
    state: ReviewFlowState,
    on_jump,
    *,
    simple_details: bool = False,
) -> tuple[ft.Container, ProgressSidebarRefs, ft.Container]:
    """Return sidebar shell, mutable stat refs, and empty slot for browse workbench."""
    refs = ProgressSidebarRefs(
        screen_label=ft.Text("", size=t.typography.size_sm, weight=ft.FontWeight.W_700, color=t.colors.fg),
        groups_text=ft.Text("", size=t.typography.size_xs, color=t.colors.fg_muted),
        marked_text=ft.Text("", size=t.typography.size_xs, color=t.colors.primary),
    )
    update_progress_sidebar_refs(refs, "browse", state, simple_details=simple_details)
    mode = (state.scan_mode or "files").replace("_", " ").title()
    workbench_slot = ft.Container(expand=True)
    width = BROWSE_SIDEBAR_WIDTH_SIMPLE if simple_details else BROWSE_SIDEBAR_WIDTH
    up_nav = (
        ft.TextButton("← Summary", on_click=lambda e: on_jump("overview"))
        if simple_details
        else ft.TextButton("Go to Overview", on_click=lambda e: on_jump("overview"))
    )
    container = ft.Container(
        width=width,
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
                up_nav,
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
    *,
    simple_details: bool = False,
) -> None:
    update_progress_sidebar_refs(refs, "browse", state, simple_details=simple_details)
    safe_update(container)
