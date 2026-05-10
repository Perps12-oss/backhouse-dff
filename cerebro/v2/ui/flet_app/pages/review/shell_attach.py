"""One-time construction of ReviewPage controls (keeps ``review_page`` shell small)."""

from __future__ import annotations

from typing import Any

import flet as ft

from cerebro.v2.ui.flet_app.pages.review._types import RC
from cerebro.v2.ui.flet_app.pages.review.compare_delegate import ReviewCompareDelegateAdapter
from cerebro.v2.ui.flet_app.pages.review.compare_view import ReviewCompareView
from cerebro.v2.ui.flet_app.pages.review.grid_view import ReviewGridView
from cerebro.v2.ui.flet_app.pages.review.inspector_panel import ReviewInspectorPanel
from cerebro.v2.ui.flet_app.pages.review.review_action_bar import ReviewActionBar
from cerebro.v2.ui.flet_app.pages.review.smart_rules import RULE_LABELS
from cerebro.v2.ui.flet_app.pages.review.stats_header import StatsHeader
from cerebro.v2.ui.flet_app.pages.review.workstation_sidebar import ReviewWorkstationSidebar
from cerebro.v2.ui.flet_app.pill_button_styles import pill_filled_accent, pill_text_button_style
from cerebro.v2.ui.flet_app.theme import ThemeTokens


def _attach_header_grid_smart(page: Any, t: ThemeTokens, bridge: Any) -> None:
    page._btn_back = ft.TextButton(
        "← Back",
        on_click=page._go_back,
        style=pill_text_button_style(t, variant="primary"),
        tooltip="Group list when reviewing groups; returns here from Compare or Grid.",
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

    page._smart_seg = ft.SegmentedButton(
        selected=["keep_largest"],
        allow_multiple_selection=False,
        on_change=page._on_smart_seg_change,
        segments=[
            ft.Segment(value=val, label=ft.Text(label, size=12, weight=ft.FontWeight.W_600))
            for val, label in RULE_LABELS
        ],
    )
    page._btn_smart_select_all = ft.TextButton(
        "Select All per Rule",
        icon=ft.icons.Icons.CHECK_BOX_OUTLINED,
        on_click=page._apply_smart_select_review,
        style=pill_text_button_style(t, variant="muted"),
        tooltip="Apply the active smart rule to mark files across all groups.",
    )
    page._btn_deselect_all = ft.TextButton(
        "Clear Selection",
        icon=ft.icons.Icons.CHECK_BOX_OUTLINE_BLANK,
        on_click=page._deselect_all,
        style=pill_text_button_style(t, variant="muted"),
        tooltip="Remove all file selections.",
    )
    page._smart_row = ft.Row(
        [page._smart_seg, page._btn_smart_select_all, page._btn_deselect_all, page._grid_view.zoom_row],
        spacing=t.spacing.sm,
        visible=False,
        wrap=True,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )


def _attach_compare_and_content(page: Any, t: ThemeTokens, bridge: Any) -> None:
    page._compare_ui = ReviewCompareView(ReviewCompareDelegateAdapter(page), bridge, t)
    page._cmp_bar = page._compare_ui.cmp_bar
    page._compare_view = page._compare_ui.body
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
    page._empty_state = ft.Container(
        content=ft.Column(
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
        ),
        expand=True,
        alignment=ft.Alignment(0, 0),
        **page._get_glass_style(0.04),
    )
    page._loading_state = ft.Container(
        content=ft.Column(
            [
                ft.ProgressRing(width=28, height=28, stroke_width=3, color=RC.side_a),
                ft.Text("Loading review content...", color=t.colors.fg_muted, size=t.typography.size_sm),
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=t.spacing.md,
        ),
        expand=True,
        alignment=ft.Alignment(0, 0),
        **page._get_glass_style(0.04),
    )


def _attach_group_overview_and_page_controls(page: Any, t: ThemeTokens, bridge: Any) -> None:
    page._groups_overview = ft.Column(
        expand=True,
        scroll=ft.ScrollMode.AUTO,
        spacing=8,
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
        content_padding=ft.padding.symmetric(horizontal=10, vertical=8),
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

    page._search_field = ft.TextField(
        hint_text="Search files or paths…",
        width=220,
        height=36,
        text_size=12,
        content_padding=ft.padding.symmetric(horizontal=10, vertical=6),
        border_radius=8,
        visible=False,
        on_change=page._on_search_changed,
        prefix_icon=ft.icons.Icons.SEARCH,
    )

    def _toggle_search(_e):
        page._search_field.visible = not page._search_field.visible
        if not page._search_field.visible:
            page._search_field.value = ""
            page._search_query = ""
            if page._mode in ("groups", "grid"):
                if page._mode == "groups":
                    page._refresh_groups_overview()
                else:
                    page._refresh_grid()
        try:
            if page._search_field.page is not None:
                page._search_field.update()
        except RuntimeError:
            pass

    page._btn_toolbar_search = ft.IconButton(
        ft.icons.Icons.SEARCH,
        icon_size=20,
        tooltip="Search groups by filename or path",
        on_click=_toggle_search,
    )

    right_tools = ft.Row(
        [
            page._view_toggle_row,
            page._group_sort_row,
            page._search_field,
            page._btn_toolbar_search,
        ],
        spacing=t.spacing.sm,
        tight=True,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )

    page._stats_header = StatsHeader(bridge, t, back_btn=page._btn_back, right_tools=right_tools)

    page._workstation_sidebar = ReviewWorkstationSidebar(bridge, t, on_category_change=page._on_filter_changed)
    page._inspector_panel = ReviewInspectorPanel(
        bridge, t, on_compare_file=page._on_inspector_compare_file
    )
    page._review_action_bar = ReviewActionBar(
        bridge,
        t,
        on_apply=page._delete_marked_files,
        on_undo=page._undo_last_trash_delete,
    )

    strip_pad = ft.padding.symmetric(horizontal=t.spacing.lg)
    hwrap = page._hwrap_strip
    center_column = ft.Column(
        [
            page._stats_header,
            ft.Container(content=hwrap(page._smart_row), padding=strip_pad),
            ft.Container(
                content=hwrap(page._cmp_bar),
                padding=ft.padding.symmetric(horizontal=t.spacing.lg),
            ),
            ft.Container(content=page._content, expand=True),
            page._review_action_bar,
        ],
        expand=True,
        spacing=0,
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
    """Populate ``page`` with workstation layout, grid, compare, and empty/loading states."""
    t: ThemeTokens = page._t
    bridge = page._bridge
    _attach_header_grid_smart(page, t, bridge)
    _attach_compare_and_content(page, t, bridge)
    _attach_empty_and_loading(page, t, bridge)
    _attach_group_overview_and_page_controls(page, t, bridge)
    page._apply_pill_chrome()
