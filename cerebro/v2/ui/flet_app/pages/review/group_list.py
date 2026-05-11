"""Compare-mode sidebar: scrollable list of duplicate groups."""

from __future__ import annotations

from typing import Callable, Dict, List, Optional

import flet as ft

from cerebro.engines.base_engine import DuplicateGroup
from cerebro.v2.ui.flet_app.pages.review._types import RC
from cerebro.v2.ui.flet_app.pages.review.group_card import group_duplicate_summary, group_path_hint
from cerebro.v2.ui.flet_app.theme import ThemeTokens, fmt_size


class GroupListPanel:
    """Owns the ListView and incremental row state for compare-mode group navigation."""

    def __init__(self, t: ThemeTokens) -> None:
        self._t = t
        self._items: Dict[int, ft.Container] = {}
        self._order: List[int] = []
        self._active_row_id: Optional[int] = None
        self.list_view = ft.ListView(
            expand=True,
            spacing=6,
            padding=ft.padding.all(8),
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
        )

    def clear_tracking(self) -> None:
        """Drop all row widgets and order (e.g. new scan or group set replaced)."""
        self._items.clear()
        self._order.clear()
        self._active_row_id = None

    def invalidate_order(self) -> None:
        """Force a full rebuild on next ``refresh`` while keeping row map (optional)."""
        self._order.clear()

    def refresh(
        self,
        *,
        groups: List[DuplicateGroup],
        compare_gid: Optional[int],
        on_pick: Callable[[int], None],
        safe_update: Callable[[ft.Control | None], None],
    ) -> None:
        t = self._t

        def _set_row_style(row: ft.Container, active: bool) -> None:
            row.bgcolor = ft.Colors.with_opacity(0.10 if active else 0.04, RC.side_a if active else ft.Colors.WHITE)
            row.border = ft.border.all(
                1,
                ft.Colors.with_opacity(0.28 if active else 0.10, RC.side_a if active else ft.Colors.WHITE),
            )

        current_order = [g.group_id for g in groups]
        needs_full_build = not self._items or current_order != self._order

        if needs_full_build:
            self._items.clear()
            controls: list[ft.Control] = []
            for i, g in enumerate(groups):
                active = g.group_id == compare_gid
                row = ft.Container(
                    padding=ft.Padding.symmetric(horizontal=10, vertical=8),
                    border_radius=8,
                    ink=True,
                    on_click=lambda _e, gid=g.group_id: on_pick(gid),
                    content=ft.Column(
                        [
                            ft.Text(
                                f"Group {i + 1} · {fmt_size(g.reclaimable)}",
                                size=t.typography.size_sm,
                                weight=ft.FontWeight.W_700,
                            ),
                            ft.Text(
                                group_duplicate_summary(g),
                                size=t.typography.size_xs,
                                color=t.colors.fg_muted,
                                max_lines=2,
                            ),
                            ft.Text(
                                group_path_hint(list(g.files)),
                                size=t.typography.size_xs,
                                color=t.colors.fg2,
                                max_lines=2,
                                overflow=ft.TextOverflow.ELLIPSIS,
                            ),
                        ],
                        spacing=2,
                    ),
                )
                _set_row_style(row, active)
                self._items[g.group_id] = row
                controls.append(row)
            self._order = current_order
            self.list_view.controls = controls
            self._active_row_id = compare_gid
            safe_update(self.list_view)
            return

        prev_gid = self._active_row_id
        curr_gid = compare_gid
        if prev_gid == curr_gid:
            return
        if prev_gid is not None:
            prev = self._items.get(prev_gid)
            if prev is not None:
                _set_row_style(prev, False)
                safe_update(prev)
        if curr_gid is not None:
            curr = self._items.get(curr_gid)
            if curr is not None:
                _set_row_style(curr, True)
                safe_update(curr)
        self._active_row_id = curr_gid

    def sync_theme(self, t: ThemeTokens) -> None:
        """Store tokens for the next ``refresh`` (row text is rebuilt on refresh)."""
        self._t = t
