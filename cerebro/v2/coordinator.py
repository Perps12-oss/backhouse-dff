"""
Side-effect boundary for the v2 shell (FINAL PLAN v2.0 §2.2).

User Action -> Dispatch -> State Update -> Render
File I/O and scan thread remain in :mod:`cerebro.engines`; coordinator
bridges engine events into state dispatches.
"""

from __future__ import annotations

import time
from typing import Iterable, Optional, Sequence, Tuple

from cerebro.engines.base_engine import DuplicateGroup, ScanProgress, ScanState
from cerebro.v2.state import (
    AdvancedModeToggled,
    DeletionHistoryDataLoaded,
    FileSelectionCleared,
    FileSelectionChanged,
    HistoryDataLoaded,
    HistoryGridFilterChanged,
    HistoryGridPageChanged,
    HistoryGridSortChanged,
    HistorySubTabChanged,
    ReviewNavigate,
    ReviewViewFilterChanged,
    ResultsViewFilterChanged,
    ResultsViewTextFilterChanged,
    ResultsFilesRemoved,
    ResultsGroupGridSortChanged,
    SetDryRun,
    ScanCompleted,
    ScanEnded,
    ScanPaused,
    ScanProgressSnapshot,
    ScanResumed,
    ScanStarted,
    SetActiveTab,
    StateStore,
)
from cerebro.v2.state.deletion_history_view import deletion_db_row_to_dict
from cerebro.v2.state.history_view import scan_entry_to_row
from cerebro.v2.state.scan_progress import scan_progress_to_dict


class CerebroCoordinator:
    """Entry point for app-level side effects that end in a state change."""

    def __init__(self, store: StateStore) -> None:
        self._store = store
        self._last_progress_mon: float = 0.0

    @property
    def store(self) -> StateStore:
        return self._store

    # ------------------------------------------------------------------
    # Global Advanced Toggle (FINAL PLAN §1.2)
    # ------------------------------------------------------------------

    def toggle_advanced(self, value: Optional[bool] = None) -> None:
        self._store.dispatch(AdvancedModeToggled(value))

    # ------------------------------------------------------------------
    # File Selection (FINAL PLAN §5.5)
    # ------------------------------------------------------------------

    def set_selected_files(self, file_ids: Iterable[str]) -> None:
        self._store.dispatch(FileSelectionChanged(tuple(file_ids)))

    def clear_selection(self) -> None:
        self._store.dispatch(FileSelectionCleared())

    # ------------------------------------------------------------------
    # Tab Navigation (FINAL PLAN §1.1)
    # ------------------------------------------------------------------

    def set_active_tab(self, key: str) -> None:
        self._store.dispatch(SetActiveTab(key))

    # ------------------------------------------------------------------
    # Scan Lifecycle (FINAL PLAN §9)
    # ------------------------------------------------------------------

    def scan_started(self, scan_mode: str = "files") -> None:
        self._store.dispatch(ScanStarted(scan_mode or "files"))

    def report_scan_progress(self, p: ScanProgress) -> None:
        st = p.state
        is_terminal = st in (
            ScanState.COMPLETED,
            ScanState.CANCELLED,
            ScanState.ERROR,
        )
        if not is_terminal:
            t = time.monotonic()
            if t - self._last_progress_mon < 0.05:
                return
            self._last_progress_mon = t
        self._store.dispatch(ScanProgressSnapshot(scan_progress_to_dict(p)))

    def scan_ended(self, reason: str) -> None:
        r = (reason or "").lower()
        if r in ("cancelled", "error"):
            self._store.dispatch(ScanEnded(r))

    def scan_paused(self) -> None:
        self._store.dispatch(ScanPaused())

    def scan_resumed(self) -> None:
        self._store.dispatch(ScanResumed())

    def scan_completed(
        self,
        groups: Iterable[DuplicateGroup],
        scan_mode: str = "files",
    ) -> None:
        self._store.dispatch(ScanCompleted(list(groups), scan_mode or "files"))

    # ------------------------------------------------------------------
    # Review / Group navigation (FINAL PLAN §5.8)
    # ------------------------------------------------------------------

    def review_open_group(
        self,
        group_id: int,
        groups: Optional[Sequence[DuplicateGroup]] = None,
    ) -> None:
        snap: Optional[Tuple[DuplicateGroup, ...]] = (
            tuple(groups) if groups is not None else None
        )
        self._store.dispatch(ReviewNavigate(int(group_id), snap))

    # ------------------------------------------------------------------
    # History (FINAL PLAN §7)
    # ------------------------------------------------------------------

    def history_data_loaded(self, entries: Iterable) -> None:
        rows = tuple(scan_entry_to_row(e) for e in entries)
        self._store.dispatch(HistoryDataLoaded(rows))

    def history_set_sort(self, column: str, sort_asc: bool) -> None:
        self._store.dispatch(HistoryGridSortChanged(column, sort_asc))

    def history_set_filter(self, text: str) -> None:
        self._store.dispatch(HistoryGridFilterChanged(text))

    def history_set_page(self, page_index: int) -> None:
        self._store.dispatch(HistoryGridPageChanged(page_index))

    def deletion_history_data_loaded(self, rows: Iterable) -> None:
        t = tuple(deletion_db_row_to_dict(r) for r in rows)
        self._store.dispatch(DeletionHistoryDataLoaded(t))

    def history_set_subtab(self, key: str) -> None:
        self._store.dispatch(HistorySubTabChanged(key))

    # ------------------------------------------------------------------
    # Duplicates / Results (FINAL PLAN §5)
    # ------------------------------------------------------------------

    def review_set_filter(self, filter_key: str) -> None:
        self._store.dispatch(ReviewViewFilterChanged(filter_key))

    def results_set_group_sort(self, column: str, sort_asc: bool) -> None:
        self._store.dispatch(ResultsGroupGridSortChanged(column, sort_asc))

    def results_set_filter(self, filter_key: str) -> None:
        self._store.dispatch(ResultsViewFilterChanged(filter_key))

    def results_set_text_filter(self, text: str) -> None:
        self._store.dispatch(ResultsViewTextFilterChanged(text))

    # ------------------------------------------------------------------
    # Delete Flow (FINAL PLAN §6)
    # ------------------------------------------------------------------

    def set_dry_run(self, value: bool) -> None:
        self._store.dispatch(SetDryRun(bool(value)))

    def results_files_removed(self, paths: Iterable[str]) -> None:
        self._store.dispatch(ResultsFilesRemoved(tuple(str(p) for p in paths)))
