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
    AdvancedModeToggled,
    ThemeChanged,
    FileSelectionChanged,
    FileSelectionCleared,
    DeletionHistoryDataLoaded,
    HistoryDataLoaded,
    HistoryGridFilterChanged,
    HistoryGridPageChanged,
    HistoryGridSortChanged,
    HistorySubTabChanged,
    ResultsFilesRemoved,
    GroupsPruned,
    ReviewNavigate,
    ReviewViewFilterChanged,
    ResultsViewFilterChanged,
    ResultsGroupGridSortChanged,
    ResultsViewTextFilterChanged,
    ScanCompleted,
    ScanEnded,
    ScanPaused,
    ScanProgressSnapshot,
    ScanResumed,
    ScanStarted,
    SetActiveTab,
    SetDryRun,
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
    "AdvancedModeToggled",
    "AppMode",
    "AppState",
    "DeletionHistoryDataLoaded",
    "FileSelectionChanged",
    "FileSelectionCleared",
    "HISTORY_SCAN_VALID_COLUMNS",
    "HistoryDataLoaded",
    "HistoryGridFilterChanged",
    "HistoryGridPageChanged",
    "HistoryGridSortChanged",
    "HistorySubTabChanged",
    "Listener",
    "ResultsFilesRemoved",
    "GroupsPruned",
    "ResultsGroupGridSortChanged",
    "ResultsViewFilterChanged",
    "ResultsViewTextFilterChanged",
    "ReviewNavigate",
    "ReviewViewFilterChanged",
    "ScanCompleted",
    "ScanEnded",
    "ScanPaused",
    "ScanProgressSnapshot",
    "ScanResumed",
    "ScanStarted",
    "SetActiveTab",
    "SetDryRun",
    "StateStore",
    "ThemeChanged",
    "VALID_MAIN_TAB_KEYS",
    "apply_scan_history_view",
    "create_initial_state",
    "deletion_db_row_to_dict",
    "default_sort_asc_for_column",
    "prune_paths_from_groups",
    "reduce",
    "row_to_entry_proxy",
    "scan_entry_to_row",
    "scan_progress_to_dict",
]
