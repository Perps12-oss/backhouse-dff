"""
Side-effect boundary for the v2 shell (Blueprints §0.3, Implementation Rules §3–4).

Sprint 1: forwards scan/review events into :class:`cerebro.v2.state.StateStore`
so the AppShell can react in one place. File I/O and the scan thread remain in
:mod:`cerebro.engines` and ``ScanPage``; later sprints can move more work here
without adding UI imports under ``cerebro.engines`` — see Blueprint §0.3 / §6.
"""

from __future__ import annotations

import time
from typing import Iterable, Optional, Sequence, Tuple

from cerebro.engines.base_engine import DuplicateGroup, ScanProgress, ScanState
from cerebro.v2.state import (
    DeletionHistoryDataLoaded,
    HistoryDataLoaded,
    HistoryGridFilterChanged,
    HistoryGridPageChanged,
    HistoryGridSortChanged,
    HistorySubTabChanged,
    ReviewNavigate,
    ReviewViewFilterChanged,
    ResultsViewFilterChanged,
    ResultsFilesRemoved,
    ResultsViewSortChanged,
    ScanCompleted,
    ScanEnded,
    ScanProgressSnapshot,
    ScanStarted,
    SetActiveTab,
    StateStore,
)
from cerebro.v2.state.deletion_history_view import deletion_db_row_to_dict
from cerebro.v2.state.history_view import scan_entry_to_row
from cerebro.v2.state.scan_progress import scan_progress_to_dict


class CerebroCoordinator:
    """Entry point for app-level side effects that should end in a state change."""

    def __init__(self, store: StateStore) -> None:
        self._store = store
        self._last_progress_mon: float = 0.0

    @property
    def store(self) -> StateStore:
        return self._store

    def set_active_tab(self, key: str) -> None:
        """Top-level main tab: single entry for shell + TabBar (Blueprint §0.1)."""
        self._store.dispatch(SetActiveTab(key))

    def scan_started(self, scan_mode: str = "files") -> None:
        """Call from the main thread when ``orchestrator.start_scan`` has been scheduled."""
        self._store.dispatch(ScanStarted(scan_mode or "files"))

    def report_scan_progress(self, p: ScanProgress) -> None:
        """Mirror engine progress into the store (throttled to ~10 Hz, Blueprint §5)."""
        st = p.state
        is_terminal = st in (
            ScanState.COMPLETED,
            ScanState.CANCELLED,
            ScanState.ERROR,
        )
        if not is_terminal:
            t = time.monotonic()
            if t - self._last_progress_mon < 0.1:
                return
            self._last_progress_mon = t
        self._store.dispatch(ScanProgressSnapshot(scan_progress_to_dict(p)))

    def scan_ended(self, reason: str) -> None:
        """Cancel or error: clears scanning phase in state (not used for success)."""
        r = (reason or "").lower()
        if r in ("cancelled", "error"):
            self._store.dispatch(ScanEnded(r))

    def scan_completed(
        self,
        groups: Iterable[DuplicateGroup],
        scan_mode: str = "files",
    ) -> None:
        """Call from the main thread when a scan finishes (ScanPage path)."""
        self._store.dispatch(ScanCompleted(list(groups), scan_mode or "files"))

    def review_open_group(
        self,
        group_id: int,
        groups: Optional[Sequence[DuplicateGroup]] = None,
    ) -> None:
        """Navigate to Review for a duplicate group (Results double-click path)."""
        snap: Optional[Tuple[DuplicateGroup, ...]] = (
            tuple(groups) if groups is not None else None
        )
        self._store.dispatch(ReviewNavigate(int(group_id), snap))

    def history_data_loaded(self, entries: Iterable) -> None:
        """Main thread: replace ``AppState.history_scan_rows`` from DB rows."""
        rows = tuple(scan_entry_to_row(e) for e in entries)
        self._store.dispatch(HistoryDataLoaded(rows))

    def history_set_sort(self, column: str, sort_asc: bool) -> None:
        self._store.dispatch(HistoryGridSortChanged(column, sort_asc))

    def history_set_filter(self, text: str) -> None:
        self._store.dispatch(HistoryGridFilterChanged(text))

    def history_set_page(self, page_index: int) -> None:
        self._store.dispatch(HistoryGridPageChanged(page_index))

    def deletion_history_data_loaded(self, rows: Iterable) -> None:
        """Call from the main thread; ``rows`` are raw tuples from the deletion history DB."""
        t = tuple(deletion_db_row_to_dict(r) for r in rows)
        self._store.dispatch(DeletionHistoryDataLoaded(t))

    def history_set_subtab(self, key: str) -> None:
        self._store.dispatch(HistorySubTabChanged(key))

    def review_set_filter(self, filter_key: str) -> None:
        self._store.dispatch(ReviewViewFilterChanged(filter_key))

    def results_set_sort(self, column: str, sort_asc: bool) -> None:
        self._store.dispatch(ResultsViewSortChanged(column, sort_asc))

    def results_set_filter(self, filter_key: str) -> None:
        self._store.dispatch(ResultsViewFilterChanged(filter_key))

    def results_files_removed(self, paths: Iterable[str]) -> None:
        self._store.dispatch(ResultsFilesRemoved(tuple(str(p) for p in paths)))
