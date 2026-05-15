"""One-time construction of ReviewPage controls (keeps ``review_page`` shell small)."""

from __future__ import annotations

from typing import Any

import flet as ft

from cerebro.v2.ui.flet_app.components.filters.workspace_filter_stack import WorkspaceFilterStack
from cerebro.v2.ui.flet_app.components.smart_selection import SmartSelectionRow
from cerebro.v2.ui.flet_app.pages.review._types import RC
from cerebro.v2.ui.flet_app.pages.review.grid_view import ReviewGridView
from cerebro.v2.ui.flet_app.pages.review.inspector_panel import ReviewInspectorPanel
from cerebro.v2.ui.flet_app.pages.review.review_action_bar import ReviewActionBar
from cerebro.v2.ui.flet_app.pages.review.stats_header import StatsHeader
from cerebro.v2.ui.flet_app.pages.review.workstation_sidebar import ReviewWorkstationSidebar
from cerebro.v2.ui.flet_app.pill_button_styles import pill_filled_accent, pill_text_button_style
from cerebro.v2.ui.flet_app.design_system.animations import fade_in
from cerebro.v2.ui.flet_app.design_system.glass import glass_container
from cerebro.v2.ui.flet_app.theme import ThemeTokens
from cerebro.v2.ui.flet_app.design_system.skeleton import skeleton_card_row


def _attach_header_grid_smart(page: Any, t: ThemeTokens, bridge: Any) -> None:
    page._btn_back = ft.TextButton(
        "← Back",
        on_click=page._go_back,
        style=pill_text_button_style(t, variant="primary"),
        tooltip="Group list when reviewing groups; returns here from Tiles.",
    )

    page._grid_view = ReviewGridView(
        bridge,
        t,
        reduce_motion=page._reduce_motion,
        on_tile_clicked=page._on_tile_clicked,
        on_toggle_mark=page._toggle_mark_file,
        is_grid_mode=lambda: page._mode == "grid",
    )
    page._grid = page._grid_view.grid

    page._smart_row = SmartSelectionRow(
        t,
        variant="review",
        on_rule_change=page._on_smart_seg_change,
        on_apply=page._apply_smart_select_review,
        on_clear=page._deselect_all,
        extra_controls=[page._grid_view.zoom_row],
    )
    page._smart_seg = page._smart_row.smart_seg


def _attach_content(page: Any) -> None:
    page._content = ft.Column(expand=True)


def _attach_empty_and_loading(page: Any, t: ThemeTokens, bridge: Any) -> None:
    page._empty_go_home_btn = ft.FilledButton(
        "Go Home",
        icon=ft.icons.Icons.LIST_ALT,
        on_click=lambda e: bridge.navigate("dashboard"),
        style=pill_filled_accent(t, text_size=12, weight=ft.FontWeight.W_700),
    )
    page._empty_title_lbl = ft.Text(
        "Nothing to review yet",
        size=t.typography.size_lg,
        weight=ft.FontWeight.W_600,
        color=t.colors.fg,
    )
    page._empty_body_lbl = ft.Text(
        "Run a scan first, then come here to visually triage duplicates.",
        size=t.typography.size_base,
        color=t.colors.fg_muted,
        text_align=ft.TextAlign.CENTER,
    )
    empty_column = ft.Column(
        [
            ft.Container(
                content=ft.Icon(ft.icons.Icons.GRID_VIEW, size=44, color=RC.side_a),
                bgcolor=ft.Colors.with_opacity(0.08, RC.side_a),
                border_radius=16,
                padding=20,
            ),
            page._empty_title_lbl,
            page._empty_body_lbl,
            page._empty_go_home_btn,
        ],
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        spacing=t.spacing.lg,
    )
    fade_in(empty_column)
    page._empty_state = glass_container(
        content=empty_column,
        expand=True,
        alignment=ft.Alignment(0, 0),
        t=t,
    )
    page._loading_lbl = ft.Text(
        "Preparing workspace…",
        color=t.colors.fg_muted,
        size=t.typography.size_sm,
    )
    loading_column = ft.Column(
        [
            ft.ProgressRing(width=28, height=28, stroke_width=3, color=RC.side_a),
            page._loading_lbl,
            skeleton_card_row(t, count=3),
        ],
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        spacing=t.spacing.md,
    )
    fade_in(loading_column)
    page._loading_state = glass_container(
        content=loading_column,
        expand=True,
        alignment=ft.Alignment(0, 0),
        t=t,
    )


def _attach_group_overview_and_page_controls(page: Any, t: ThemeTokens, bridge: Any) -> None:
    page._groups_overview = ft.Column(
        expand=True,
        scroll=ft.ScrollMode.AUTO,
        spacing=8,
    )

    page._overview_grid_switch = ft.Switch(
        value=False,
        active_color=t.colors.accent,
        on_change=page._on_overview_grid_switch,
        tooltip="Switch to thumbnail grid",
    )
    page._overview_grid_switch_row = ft.Container(
        content=ft.Row(
            [
                ft.Icon(ft.icons.Icons.GRID_VIEW_OUTLINED, size=15, color=t.colors.fg_muted),
                ft.Text(
                    "Grid view",
                    size=t.typography.size_sm,
                    color=t.colors.fg_muted,
                    weight=ft.FontWeight.W_600,
                ),
                page._overview_grid_switch,
            ],
            spacing=t.spacing.xs,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            tight=True,
        ),
        padding=ft.padding.only(left=16, right=16, top=10, bottom=2),
    )

    page._btn_view_groups = ft.TextButton(
        "Details",
        tooltip="List duplicate sets with sizes (Explorer-style Details).",
        on_click=lambda e: page._enter_mode("groups"),
        style=pill_text_button_style(t, variant="primary"),
    )
    page._btn_view_tiles = ft.TextButton(
        "Tiles",
        tooltip="Thumbnail grid for visual triage (Explorer-style Tiles / Large icons).",
        on_click=lambda e: page._enter_mode("grid"),
        style=pill_text_button_style(t, variant="muted"),
    )
    page._view_toggle_row = ft.Row(
        [page._btn_view_groups, page._btn_view_tiles],
        spacing=t.spacing.sm,
        visible=False,
    )
    page._group_sort_key = "files_desc"
    page._group_sort_dd = ft.Dropdown(
        width=200,
        value=page._group_sort_key,
        options=[
            ft.dropdown.Option("files_desc", "Most copies in group"),
            ft.dropdown.Option("reclaimable_desc", "Highest reclaimable"),
            ft.dropdown.Option("path_asc", "Folder A-Z"),
        ],
        on_select=page._on_group_sort_changed,
        text_size=12,
        dense=True,
        content_padding=ft.Padding.symmetric(horizontal=10, vertical=8),
    )
    page._group_sort_row = ft.Row(
        [
            ft.Text(
                "Sort:",
                size=t.typography.size_sm,
                color=t.colors.fg_muted,
                weight=ft.FontWeight.W_600,
            ),
            page._group_sort_dd,
        ],
        spacing=t.spacing.sm,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
        visible=False,
    )

    right_tools = ft.Row(
        [
            page._view_toggle_row,
            page._group_sort_row,
        ],
        spacing=t.spacing.sm,
        tight=True,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )

    page._stats_header = StatsHeader(bridge, t, back_btn=page._btn_back, right_tools=right_tools)

    page._workspace_filter_stack = WorkspaceFilterStack(
        t,
        on_filter_change=page._on_filter_changed,
        on_text_filter=page._on_workspace_text_filter,
        on_cross_folder_change=page._on_cross_folder_only_changed,
    )
    page._filter_stack_host = ft.Container(content=page._workspace_filter_stack)

    page._workstation_sidebar = ReviewWorkstationSidebar(
        bridge,
        t,
        on_review_scope_change=page._on_review_scope_changed,
    )
    page._inspector_panel = ReviewInspectorPanel(bridge, t)
    page._review_action_bar = ReviewActionBar(
        bridge,
        t,
        on_trash=page._trash_marked_files,
        on_delete=page._delete_marked_permanently,
        on_undo=page._undo_last_trash_delete,
    )

    strip_pad = ft.Padding.symmetric(horizontal=t.spacing.lg)
    hwrap = page._hwrap_strip
    page._smart_host = ft.Container(content=hwrap(page._smart_row), padding=strip_pad)
    page._content_frame = ft.Container(
        content=page._content,
        expand=True,
        clip_behavior=ft.ClipBehavior.HARD_EDGE,
    )
    page._workspace_slot = ft.Container(expand=True, content=page._content_frame)
    center_column = ft.Column(
        [
            page._stats_header,
            page._filter_stack_host,
            page._smart_host,
            page._workspace_slot,
            page._review_action_bar,
        ],
        expand=True,
        spacing=0,
    )
    page._center_column = ft.Container(
        content=center_column,
        expand=True,
        clip_behavior=ft.ClipBehavior.HARD_EDGE,
    )

    page._main_workstation_row = ft.Row(
        [
            page._workstation_sidebar,
            center_column,
            page._inspector_panel,
        ],
        expand=True,
        spacing=0,
    )

    page.controls = [page._main_workstation_row]


def attach_review_shell(page: Any) -> None:
    """Populate ``page`` with workstation layout, grid, and empty/loading states."""
    t: ThemeTokens = page._t
    bridge = page._bridge
    _attach_header_grid_smart(page, t, bridge)
    _attach_content(page)
    _attach_empty_and_loading(page, t, bridge)
    _attach_group_overview_and_page_controls(page, t, bridge)
    page._apply_pill_chrome()
