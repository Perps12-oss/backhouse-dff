from __future__ import annotations

from dataclasses import dataclass

import flet as ft

from cerebro.v2.ui.flet_app.components.common.safe_controls import safe_update
from cerebro.v2.ui.flet_app.pages.review_flow.state import ReviewFlowState, ReviewScreen
from cerebro.v2.ui.flet_app.theme import ThemeTokens, fmt_size


@dataclass
class ProgressSidebarRefs:
    """Mutable labels on the review sidebar — update in place instead of rebuilding the row."""

    screen_label: ft.Text
    groups_text: ft.Text
    marked_text: ft.Text


def build_progress_sidebar(
    t: ThemeTokens,
    active: ReviewScreen,
    state: ReviewFlowState,
    on_jump,
) -> tuple[ft.Container, ProgressSidebarRefs]:
    """Operational status strip (replaces linear wizard steps)."""
    refs = ProgressSidebarRefs(
        screen_label=ft.Text("", size=t.typography.size_sm, weight=ft.FontWeight.W_700, color=t.colors.fg),
        groups_text=ft.Text("", size=t.typography.size_xs, color=t.colors.fg_muted),
        marked_text=ft.Text("", size=t.typography.size_xs, color=t.colors.primary),
    )
    update_progress_sidebar_refs(refs, active, state)
    mode = (state.scan_mode or "files").replace("_", " ").title()
    container = ft.Container(
        width=220,
        padding=12,
        border=ft.border.only(right=ft.BorderSide(1, t.colors.border)),
        content=ft.Column(
            [
                ft.Text("Review", size=t.typography.size_xs, color=t.colors.fg_muted, weight=ft.FontWeight.W_600),
                refs.screen_label,
                ft.Divider(height=1, color=t.colors.border),
                ft.Text(f"Scan: {mode}", size=t.typography.size_xs, color=t.colors.fg_muted),
                refs.groups_text,
                refs.marked_text,
                ft.Container(height=8),
                ft.TextButton("Go to Overview", on_click=lambda e: on_jump("overview")),
                ft.TextButton("Go to Browse", on_click=lambda e: on_jump("browse")),
            ],
            spacing=4,
            tight=True,
        ),
    )
    return container, refs


def update_progress_sidebar_refs(refs: ProgressSidebarRefs, active: ReviewScreen, state: ReviewFlowState) -> None:
    screen_label = {"overview": "Overview", "browse": "Browse", "inspect": "Compare"}.get(active, active)
    n_groups = len(state.visible_groups())
    marked = state.cart_delete_count
    reclaim = state.cart_delete_bytes
    refs.screen_label.value = screen_label
    refs.groups_text.value = f"{n_groups:,} groups"
    refs.marked_text.value = f"{marked:,} marked · {fmt_size(reclaim)}"


def refresh_progress_sidebar(
    refs: ProgressSidebarRefs,
    container: ft.Container,
    active: ReviewScreen,
    state: ReviewFlowState,
) -> None:
    update_progress_sidebar_refs(refs, active, state)
    safe_update(container)
