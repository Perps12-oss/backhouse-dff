"""One-time construction of ReviewPage controls (keeps ``review_page`` shell small)."""

from __future__ import annotations

from typing import Any

import flet as ft

from cerebro.v2.ui.flet_app.pages.review._types import RC
from cerebro.v2.ui.flet_app.pages.review.compare_delegate import ReviewCompareDelegateAdapter
from cerebro.v2.ui.flet_app.pages.review.compare_view import ReviewCompareView
from cerebro.v2.ui.flet_app.pages.review.filter_bar import FilterBar
from cerebro.v2.ui.flet_app.pages.review.grid_view import ReviewGridView
from cerebro.v2.ui.flet_app.pages.review.smart_rules import RULE_LABELS
from cerebro.v2.ui.flet_app.pages.review.stats_header import StatsHeader
from cerebro.v2.ui.flet_app.pill_button_styles import pill_filled_accent, pill_text_button_style
from cerebro.v2.ui.flet_app.theme import ThemeTokens


def _attach_header_grid_smart(page: Any, t: ThemeTokens, bridge: Any) -> None:
    page._btn_back = ft.TextButton(
        "← Back",
        on_click=page._go_back,
        style=pill_text_button_style(t, variant="primary"),
        tooltip="Group list when reviewing groups; returns here from Compare or Grid.",
    )
    page._stats_header = StatsHeader(bridge, t, back_btn=page._btn_back)

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
    page._smart_apply_all_btn = ft.FilledButton(
        "Apply Rule to Visible",
        icon=ft.icons.Icons.AUTO_FIX_HIGH,
        on_click=page._apply_smart_select_review,
        style=pill_filled_accent(
            t,
            padding=ft.padding.symmetric(horizontal=16, vertical=10),
            text_size=12,
            weight=ft.FontWeight.W_700,
        ),
    )
    page._smart_row = ft.Row(
        [page._smart_seg, page._grid_view.zoom_row, page._smart_apply_all_btn],
        spacing=t.spacing.sm,
        visible=False,
        wrap=True,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )


def _attach_compare_and_filter(page: Any, t: ThemeTokens, bridge: Any) -> None:
    page._compare_ui = ReviewCompareView(ReviewCompareDelegateAdapter(page), bridge, t)
    page._cmp_bar = page._compare_ui.cmp_bar
    page._compare_view = page._compare_ui.body
    page._filter_bar = FilterBar(t, on_change=page._on_filter_changed)
    page._content = ft.Column(expand=True)


def _attach_empty_and_loading(page: Any, t: ThemeTokens, bridge: Any) -> None:
    page._empty_go_home_btn = ft.FilledButton(
        "Go Home",
        icon=ft.icons.Icons.LIST_ALT,
        on_click=lambda e: bridge.navigate("dashboard"),
        style=pill_filled_accent(t, text_size=12, weight=ft.FontWeight.W_700),
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
                ft.Text(
                    "Nothing to review yet",
                    size=t.typography.size_lg,
                    weight=ft.FontWeight.W_600,
                    color=t.colors.fg,
                ),
                ft.Text(
                    "Run a scan first, then come here to visually triage duplicates.",
                    size=t.typography.size_base,
                    color=t.colors.fg_muted,
                    text_align=ft.TextAlign.CENTER,
                ),
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


def _attach_group_overview_and_page_controls(page: Any, t: ThemeTokens) -> None:
    page._groups_overview = ft.ListView(
        spacing=8,
        padding=ft.padding.all(16),
    )
    page._btn_view_groups = ft.TextButton(
        "Groups",
        on_click=lambda e: page._enter_mode("groups"),
        style=pill_text_button_style(t, variant="primary"),
    )
    page._btn_view_tiles = ft.TextButton(
        "Tiles",
        on_click=lambda e: page._enter_mode("grid"),
        style=pill_text_button_style(t, variant="muted"),
    )
    page._view_toggle_row = ft.Row(
        [page._btn_view_groups, page._btn_view_tiles],
        spacing=t.spacing.sm,
        visible=False,
    )
    page._group_sort_key = "reclaimable_desc"
    page._group_sort_dd = ft.Dropdown(
        width=240,
        value=page._group_sort_key,
        options=[
            ft.dropdown.Option("reclaimable_desc", "Highest reclaimable"),
            ft.dropdown.Option("files_desc", "Most copies"),
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
                "Sort groups:",
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

    strip_pad = ft.padding.symmetric(horizontal=t.spacing.lg)
    hwrap = page._hwrap_strip
    page.controls = [
        page._stats_header,
        ft.Container(content=hwrap(page._view_toggle_row), padding=strip_pad),
        ft.Container(
            content=hwrap(page._group_sort_row),
            padding=ft.padding.only(left=t.spacing.lg, right=t.spacing.lg, bottom=t.spacing.xs),
        ),
        ft.Container(content=hwrap(page._smart_row), padding=strip_pad),
        ft.Container(
            content=hwrap(page._cmp_bar),
            padding=ft.padding.symmetric(horizontal=t.spacing.lg),
        ),
        page._filter_bar,
        page._content,
    ]


def attach_review_shell(page: Any) -> None:
    """Populate ``page`` with stats header, grid, compare, filters, empty/loading states, and layout."""
    t: ThemeTokens = page._t
    bridge = page._bridge
    _attach_header_grid_smart(page, t, bridge)
    _attach_compare_and_filter(page, t, bridge)
    _attach_empty_and_loading(page, t, bridge)
    _attach_group_overview_and_page_controls(page, t)
    page._apply_pill_chrome()
