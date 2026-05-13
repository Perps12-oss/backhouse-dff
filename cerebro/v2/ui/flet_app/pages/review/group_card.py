"""Group overview card for the review page groups list."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Callable, List, Optional, Set

import flet as ft

from cerebro.engines.base_engine import DuplicateFile, DuplicateGroup
from cerebro.v2.ui.flet_app.pages.review._types import RC
from cerebro.v2.ui.flet_app.pages.review.smart_rules import apply_rule, normalized_rule
from cerebro.v2.ui.flet_app.pages.review.theme_detect import app_theme_is_light
from cerebro.v2.ui.flet_app.theme import ThemeTokens, fmt_size

if TYPE_CHECKING:
    from cerebro.v2.ui.flet_app.services.state_bridge import StateBridge

_GROUP_STRIPE = RC.group_stripe


def group_duplicate_summary(g: DuplicateGroup) -> str:
    n = len(g.files)
    sim = (getattr(g, "similarity_type", None) or "exact").lower()
    names = list(dict.fromkeys(Path(str(f.path)).name for f in g.files))
    if n < 2:
        return f"{n} file in this group"
    if sim == "exact":
        if len(names) == 1:
            return f'{n} byte-identical copies of "{names[0]}"'
        head = ", ".join(names[:3])
        tail = ", ..." if len(names) > 3 else ""
        return f"{n} byte-identical files · {head}{tail}"
    if len(names) == 1:
        return f'{n} similar matches for "{names[0]}"'
    head = ", ".join(names[:3])
    tail = ", ..." if len(names) > 3 else ""
    return f"{n} similar matches · {head}{tail}"


def group_path_hint(files: List[DuplicateFile]) -> str:
    if not files:
        return ""
    paths = [Path(str(f.path)) for f in files]
    if len(paths) == 1:
        return str(paths[0].parent)
    parents = [p.parent for p in paths]
    uniq_parents = {str(p) for p in parents}
    names = list(dict.fromkeys(p.name for p in paths))
    if len(uniq_parents) == 1:
        if len(names) <= 3:
            return f"Same folder · {', '.join(names)}"
        return f"Same folder · {', '.join(names[:3])}... (+{len(names) - 3} names)"
    try:
        common = os.path.commonpath([str(p) for p in paths])
    except ValueError:
        bits = [f"{p.parent.name}/{p.name}" for p in paths[:3]]
        return " · ".join(dict.fromkeys(bits))
    rel_bits: list[str] = []
    for p in paths:
        try:
            rel_bits.append(os.path.relpath(str(p), common))
        except ValueError:
            rel_bits.append(str(p))
    ordered = list(dict.fromkeys(rel_bits))
    return " · ".join(ordered[:3]) + (" ..." if len(ordered) > 3 else "")


class GroupCardWidget(ft.Container):
    """Stateful group card with expand/collapse file list and inspector/compare callbacks."""

    def __init__(
        self,
        t: ThemeTokens,
        bridge: "StateBridge",
        g: DuplicateGroup,
        idx: int,
        total_reclaim_scan: int,
        reviewed_ids: Set[int],
        *,
        smart_rule: str = "keep_largest",
        on_group_click: Optional[Callable[[DuplicateGroup], None]] = None,
        on_inspector_select: Optional[Callable[[DuplicateGroup], None]] = None,
        on_file_click: Optional[Callable[[DuplicateFile], None]] = None,
    ) -> None:
        self._t = t
        self._bridge = bridge
        self._g = g
        self._on_group_click = on_group_click
        self._on_inspector_select = on_inspector_select
        self._on_file_click = on_file_click
        self._expanded = False

        reclaim = int(getattr(g, "reclaimable", 0) or 0)
        pct = (100.0 * reclaim / total_reclaim_scan) if total_reclaim_scan > 0 else 0.0
        pct_s = f" · {pct:.1f}% of scan" if total_reclaim_scan > 0 and reclaim > 0 else ""
        stripe = _GROUP_STRIPE[g.group_id % len(_GROUP_STRIPE)]
        reviewed = g.group_id in reviewed_ids
        title_color = RC.group_title_reviewed if reviewed else t.colors.fg
        line_dup = group_duplicate_summary(g)
        line_path = group_path_hint(list(g.files))

        keep_line = ""
        files = list(g.files)
        if len(files) >= 2:
            try:
                keeper = apply_rule(normalized_rule(smart_rule), files)
                keep_line = f"Recommended keep: {Path(str(keeper.path)).name}"
            except Exception:
                keep_line = ""

        is_light = app_theme_is_light(bridge)
        edge = ft.Colors.with_opacity(0.1, ft.Colors.BLACK if is_light else ft.Colors.WHITE)
        thin = ft.BorderSide(1, edge)

        self._expanded_col = ft.Column([], spacing=0, visible=False)
        self._chevron_icon = ft.Icon(
            ft.icons.Icons.CHEVRON_RIGHT, size=16, color=t.colors.fg_muted
        )
        self._build_file_rows(files, reviewed_ids, smart_rule, t, is_light)

        # Expand toggle is a sibling of the clickable main area to avoid event bubbling.
        expand_btn = ft.Container(
            content=self._chevron_icon,
            padding=ft.padding.all(6),
            border_radius=6,
            ink=True,
            tooltip="Expand file list",
            on_click=self._on_expand_click,
        )

        text_col = ft.Column(
            [
                ft.Text(
                    f"Group {idx + 1} · {fmt_size(reclaim)} reclaimable{pct_s}",
                    size=t.typography.size_base,
                    weight=ft.FontWeight.W_700,
                    color=title_color,
                ),
                ft.Text(line_dup, size=t.typography.size_sm, color=t.colors.fg2, max_lines=2),
                *(
                    [
                        ft.Text(
                            keep_line,
                            size=t.typography.size_xs,
                            color=RC.group_title_reviewed,
                            max_lines=1,
                            overflow=ft.TextOverflow.ELLIPSIS,
                        )
                    ]
                    if keep_line
                    else []
                ),
                ft.Text(
                    line_path,
                    size=t.typography.size_xs,
                    color=t.colors.fg_muted,
                    overflow=ft.TextOverflow.ELLIPSIS,
                    max_lines=2,
                ),
            ],
            spacing=4,
            expand=True,
        )

        self._hover_bg_color = ft.Colors.with_opacity(0.04, ft.Colors.WHITE)
        # Main clickable area: icon + text. Expand button is a sibling (not inside) so clicks don't bubble.
        self._clickable_area = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.icons.Icons.LAYERS_OUTLINED, size=18, color=stripe),
                    text_col,
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=10,
            ),
            expand=True,
            ink=True,
            bgcolor=ft.Colors.TRANSPARENT,
            border_radius=6,
            animate=ft.Animation(100, ft.AnimationCurve.EASE_IN_OUT),
            on_click=self._on_header_click,
            on_hover=self._on_card_hover,
        )
        clickable_area = self._clickable_area

        header_row = ft.Row(
            [clickable_area, expand_btn],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=0,
        )

        super().__init__(
            padding=ft.padding.only(left=8, right=4, top=8, bottom=8),
            border=ft.Border(left=ft.BorderSide(2, stripe), top=thin, right=thin, bottom=thin),
            content=ft.Column([header_row, self._expanded_col], spacing=0),
            bgcolor=t.colors.glass_bg,
            border_radius=12,
        )

    def _build_file_rows(
        self,
        files: List[DuplicateFile],
        reviewed_ids: Set[int],
        smart_rule: str,
        t: ThemeTokens,
        is_light: bool,
    ) -> None:
        rule = normalized_rule(smart_rule)
        try:
            keeper = apply_rule(rule, files) if len(files) >= 2 else (files[0] if files else None)
        except Exception:
            keeper = None

        divider_color = ft.Colors.with_opacity(0.07, ft.Colors.BLACK if is_light else ft.Colors.WHITE)
        rows: list[ft.Control] = [
            ft.Container(
                height=1,
                bgcolor=divider_color,
                margin=ft.margin.only(top=4, bottom=4),
            )
        ]
        for f in files:
            p = Path(str(f.path))
            is_keeper = keeper is not None and str(f.path) == str(keeper.path)
            badge_txt = "KEEP" if is_keeper else "REMOVE"
            badge_color = RC.group_title_reviewed if is_keeper else RC.marked_label_soft
            badge_bg = (
                ft.Colors.with_opacity(0.18, ft.Colors.GREEN)
                if is_keeper
                else ft.Colors.with_opacity(0.18, ft.Colors.RED)
            )

            def _make_file_click(file: DuplicateFile) -> Callable:
                def _handler(e: ft.ControlEvent) -> None:
                    if self._on_file_click:
                        self._on_file_click(file)
                return _handler

            row = ft.Container(
                content=ft.Row(
                    [
                        ft.Container(
                            content=ft.Text(
                                badge_txt, size=8, weight=ft.FontWeight.W_800, color=badge_color
                            ),
                            bgcolor=badge_bg,
                            border_radius=3,
                            padding=ft.Padding.symmetric(horizontal=5, vertical=2),
                        ),
                        ft.Column(
                            [
                                ft.Text(
                                    p.name,
                                    size=t.typography.size_xs,
                                    weight=ft.FontWeight.W_600,
                                    color=t.colors.fg,
                                    overflow=ft.TextOverflow.ELLIPSIS,
                                    max_lines=1,
                                ),
                                ft.Text(
                                    str(p.parent),
                                    size=t.typography.size_xs,
                                    color=t.colors.fg_muted,
                                    overflow=ft.TextOverflow.ELLIPSIS,
                                    max_lines=1,
                                ),
                            ],
                            spacing=1,
                            expand=True,
                        ),
                        ft.Text(fmt_size(f.size), size=t.typography.size_xs, color=t.colors.fg2),
                    ],
                    spacing=8,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                padding=ft.padding.only(top=5, bottom=5, left=8, right=8),
                ink=True,
                on_click=_make_file_click(f),
            )
            rows.append(row)

        self._expanded_col.controls = rows

    def _on_card_hover(self, e: ft.ControlEvent) -> None:
        self._clickable_area.bgcolor = (
            self._hover_bg_color if e.data == "true" else ft.Colors.TRANSPARENT
        )
        try:
            if self._clickable_area.page is not None:
                self._clickable_area.update()
        except RuntimeError:
            pass

    def _on_header_click(self, e: ft.ControlEvent) -> None:
        if self._on_inspector_select:
            self._on_inspector_select(self._g)
        if self._on_group_click:
            self._on_group_click(self._g)

    def _on_expand_click(self, e: ft.ControlEvent) -> None:
        self._expanded = not self._expanded
        self._expanded_col.visible = self._expanded
        self._chevron_icon.name = (
            ft.icons.Icons.EXPAND_MORE if self._expanded else ft.icons.Icons.CHEVRON_RIGHT
        )
        try:
            if self.page is not None:
                self.update()
        except RuntimeError:
            pass


def build_group_card(
    t: ThemeTokens,
    bridge: "StateBridge",
    g: DuplicateGroup,
    idx: int,
    total_reclaim_scan: int,
    reviewed_ids: Set[int],
    *,
    smart_rule: str = "keep_largest",
    on_group_click: Optional[Callable[[DuplicateGroup], None]] = None,
    on_inspector_select: Optional[Callable[[DuplicateGroup], None]] = None,
    on_file_click: Optional[Callable[[DuplicateFile], None]] = None,
) -> GroupCardWidget:
    return GroupCardWidget(
        t,
        bridge,
        g,
        idx,
        total_reclaim_scan,
        reviewed_ids,
        smart_rule=smart_rule,
        on_group_click=on_group_click,
        on_inspector_select=on_inspector_select,
        on_file_click=on_file_click,
    )
