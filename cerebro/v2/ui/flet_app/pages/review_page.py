"""Review page — visual grid + side-by-side compare for duplicate groups with glass morphism."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, List, Optional

import flet as ft

from cerebro.engines.base_engine import DuplicateFile, DuplicateGroup
from cerebro.v2.state.actions import FileSelectionChanged
from cerebro.v2.ui.flet_app.services.delete_service import DeleteService
from cerebro.v2.ui.flet_app.pages.review.compare_view import ReviewCompareView
from cerebro.v2.ui.flet_app.pages.review.filter_bar import FilterBar, _FILTER_TABS
from cerebro.v2.ui.flet_app.pages.review.grid_view import ReviewGridView
from cerebro.v2.ui.flet_app.pages.review.review_mixins import (
    ReviewPageChromeMixin,
    ReviewPageCompareNavMixin,
    ReviewPageFilterMixin,
    ReviewPageGroupsGridMixin,
    ReviewPageKeyboardMixin,
    ReviewPageModeMixin,
    ReviewPageNavThemeMixin,
    ReviewPageSmartMixin,
)
from cerebro.v2.ui.flet_app.pages.review.shell_attach import attach_review_shell
from cerebro.v2.ui.flet_app.pages.review.stats_header import StatsHeader
from cerebro.v2.ui.flet_app.pages.review.safe_controls import safe_update
from cerebro.v2.ui.flet_app.theme import theme_for_mode

if TYPE_CHECKING:
    from cerebro.v2.ui.flet_app.services.state_bridge import StateBridge

_log = logging.getLogger(__name__)
_UI_SLOW_MS = 80.0


class ReviewPage(
    ft.Column,
    ReviewPageChromeMixin,
    ReviewPageModeMixin,
    ReviewPageGroupsGridMixin,
    ReviewPageSmartMixin,
    ReviewPageCompareNavMixin,
    ReviewPageFilterMixin,
    ReviewPageKeyboardMixin,
    ReviewPageNavThemeMixin,
):
    """Grid and compare view for visual triage of duplicate groups."""

    def __init__(self, bridge: "StateBridge"):
        super().__init__(expand=True, scroll=ft.ScrollMode.AUTO)
        self._bridge = bridge
        self._t = theme_for_mode("dark")
        self._groups: List[DuplicateGroup] = []
        self._group_index: dict[int, int] = {}
        self._group_files: dict[int, List[DuplicateFile]] = {}
        self._filter_key = "all"
        self._mode = "empty"
        self._compare_gid: Optional[int] = None
        self._compare_a: Optional[DuplicateFile] = None
        self._compare_b: Optional[DuplicateFile] = None
        self._marked_paths: set[str] = set()
        self._marked_bytes: int = 0
        self._reduce_motion: bool = self._bridge.is_reduce_motion_enabled()
        self._delete_service = DeleteService()
        self._reviewed_group_ids: set[int] = set()
        self._smart_rule = "keep_largest"
        self._loading = False
        self._files_by_filter: dict[str, List[DuplicateFile]] = {k: [] for k, _ in _FILTER_TABS}
        self._glass_cache: dict = {}
        self._filter_counts: dict[str, int] = {k: 0 for k, _ in _FILTER_TABS}
        self._filter_sizes: dict[str, int] = {k: 0 for k, _ in _FILTER_TABS}
        self._filter_group_counts: dict[str, int] = {k: 0 for k, _ in _FILTER_TABS}
        self._pending_deferred_render: bool = False
        self._cmp_smart_rule: str = "keep_largest"
        self._compare_nav_in_flight = False

        self._stats_header: StatsHeader
        self._smart_apply_all_btn: ft.FilledButton
        self._smart_seg: ft.SegmentedButton
        self._smart_row: ft.Row
        self._grid_view: ReviewGridView
        self._compare_ui: ReviewCompareView
        self._cmp_bar: ft.Container
        self._filter_bar: FilterBar
        self._content: ft.Column
        self._empty_state: ft.Container
        self._loading_state: ft.Container
        self._grid: ft.GridView
        self._compare_view: ft.Column
        self._groups_overview: ft.ListView
        self._view_toggle_row: ft.Row
        self._group_sort_dd: ft.Dropdown
        self._group_sort_key: str
        self._group_sort_row: ft.Row
        self._btn_back: ft.TextButton
        self._btn_view_groups: ft.TextButton
        self._btn_view_tiles: ft.TextButton
        self._empty_go_home_btn: ft.FilledButton

        self._build_ui()

    def _build_ui(self) -> None:
        attach_review_shell(self)

    def load_group(self, groups: List[DuplicateGroup], group_id: int, mode: Optional[str] = None) -> None:
        self._groups = list(groups)
        self._group_files = {g.group_id: list(g.files) for g in self._groups}
        self._compare_ui.group_list.clear_tracking()
        self._rebuild_group_index()
        self._rebuild_filter_index()
        if not self._groups:
            self._enter_mode("empty")
            return
        self._loading = True
        self._enter_mode("loading")
        page = self._bridge.flet_page
        if hasattr(page, "run_task"):
            page.run_task(self._finish_load_to_compare_async, group_id)
        else:
            self._loading = False
            self._enter_compare(group_id)

    def _schedule_load_to_groups(self) -> None:
        self._loading = True
        self._enter_mode("loading")
        page = self._bridge.flet_page
        if hasattr(page, "run_task"):
            page.run_task(self._finish_load_to_groups_async)
        else:
            self._loading = False
            self._enter_mode("groups")

    def load_results(
        self,
        groups: List[DuplicateGroup],
        mode: str = "files",
        defer_render: bool = False,
    ) -> None:
        self._groups = list(groups)
        self._group_files = {g.group_id: list(g.files) for g in self._groups}
        self._compare_ui.group_list.clear_tracking()
        self._rebuild_group_index()
        self._rebuild_filter_index()
        if defer_render:
            self._pending_deferred_render = True
            if not self._groups:
                self._mode = "empty"
            return
        self._pending_deferred_render = False
        if not self._groups:
            self._enter_mode("empty")
            return
        self._schedule_load_to_groups()

    def apply_pruned_groups(self, groups: List[DuplicateGroup], mode: str = "files") -> None:
        old_ids = {g.group_id for g in self._groups}
        self._groups = list(groups)
        self._group_files = {g.group_id: list(g.files) for g in self._groups}
        new_ids = {g.group_id for g in self._groups}
        if old_ids != new_ids:
            self._compare_ui.group_list.clear_tracking()
        else:
            self._compare_ui.group_list.invalidate_order()
        self._rebuild_group_index()
        self._rebuild_filter_index()
        if not self._groups:
            self._enter_mode("empty")
            return
        if self._mode == "compare":
            if self._compare_gid is None or self._compare_gid not in self._group_files:
                self._enter_compare(self._groups[0].group_id)
                return
            files = self._group_files[self._compare_gid]
            if not files:
                self._enter_compare(self._groups[0].group_id)
                return
            self._compare_a = files[0]
            self._compare_b = files[1] if len(files) > 1 else None
            self._update_compare_panels()
            self._update_compare_chrome()
            self._refresh_group_list_panel()
        elif self._mode == "groups":
            self._refresh_groups_overview()
            safe_update(self._content)
        elif self._mode == "grid":
            self._refresh_grid()
        else:
            self._schedule_load_to_groups()

    def on_show(self) -> None:
        self._reduce_motion = self._bridge.is_reduce_motion_enabled()
        self._grid_view.set_reduce_motion(self._reduce_motion)
        self._marked_paths = set(self._bridge.state.selected_files)
        self._recompute_marked_bytes()
        if self._pending_deferred_render:
            self._pending_deferred_render = False
            if self._groups:
                self._schedule_load_to_groups()
            self._refresh_stats_header()
            return
        if not self._groups:
            self._enter_mode("empty")
            return
        if self._mode in ("empty", "loading"):
            self._schedule_load_to_groups()
            self._refresh_stats_header()
            return
        if self._mode == "grid":
            self._refresh_grid()
            safe_update(self._content)
        self._refresh_stats_header()

    def get_groups(self) -> List[DuplicateGroup]:
        return list(self._groups)

    def _is_mounted(self) -> bool:
        try:
            return self.page is not None
        except RuntimeError:
            return False

    def _push_marked_paths_to_store(self) -> None:
        self._bridge.store.dispatch(FileSelectionChanged(file_ids=tuple(self._marked_paths)))

    @staticmethod
    def _safe_update(ctrl: ft.Control | None) -> None:
        safe_update(ctrl)

    @staticmethod
    def _log_if_slow(label: str, started_at: float) -> None:
        # Kept on ReviewPage (not mixins) so compare-nav code can call self._log_if_slow; stubs that
        # only partial-mock mixins must still provide this on the concrete page class.
        elapsed_ms = (time.perf_counter() - started_at) * 1000.0
        if elapsed_ms > _UI_SLOW_MS:
            _log.debug("[UI_SLOW] %s took %.1f ms", label, elapsed_ms)
