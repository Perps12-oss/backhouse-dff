"""CEREBRO v2 app state: single object, dispatch/reducer, store."""

from __future__ import annotations

from cerebro.v2.state.app_state import (
    AppMode,
    AppState,
    VALID_MAIN_TAB_KEYS,
    create_initial_state,
)
from cerebro.v2.state.actions import (
    Action,
    DeletionHistoryDataLoaded,
    HistoryDataLoaded,
    HistoryGridFilterChanged,
    HistoryGridPageChanged,
    HistoryGridSortChanged,
    HistorySubTabChanged,
    ResultsFilesRemoved,
    ReviewNavigate,
    ReviewViewFilterChanged,
    ResultsViewFilterChanged,
    ResultsViewSortChanged,
    ScanCompleted,
    ScanEnded,
    ScanProgressSnapshot,
    ScanStarted,
    SetActiveTab,
)
from cerebro.v2.state.history_view import (
    HISTORY_SCAN_VALID_COLUMNS,
    apply_scan_history_view,
    default_sort_asc_for_column,
    row_to_entry_proxy,
    scan_entry_to_row,
)
from cerebro.v2.state.scan_progress import scan_progress_to_dict
from cerebro.v2.state.deletion_history_view import deletion_db_row_to_dict
from cerebro.v2.state.groups_prune import prune_paths_from_groups
from cerebro.v2.state.reducer import reduce
from cerebro.v2.state.store import StateStore, Listener

__all__ = [
    "Action",
    "AppMode",
    "AppState",
    "HISTORY_SCAN_VALID_COLUMNS",
    "HistoryDataLoaded",
    "HistoryGridFilterChanged",
    "HistoryGridPageChanged",
    "HistoryGridSortChanged",
    "HistorySubTabChanged",
    "Listener",
    "DeletionHistoryDataLoaded",
    "deletion_db_row_to_dict",
    "ResultsFilesRemoved",
    "ResultsViewFilterChanged",
    "ResultsViewSortChanged",
    "ReviewNavigate",
    "ReviewViewFilterChanged",
    "ScanCompleted",
    "ScanEnded",
    "ScanProgressSnapshot",
    "ScanStarted",
    "SetActiveTab",
    "StateStore",
    "VALID_MAIN_TAB_KEYS",
    "apply_scan_history_view",
    "create_initial_state",
    "default_sort_asc_for_column",
    "prune_paths_from_groups",
    "reduce",
    "row_to_entry_proxy",
    "scan_entry_to_row",
    "scan_progress_to_dict",
]
