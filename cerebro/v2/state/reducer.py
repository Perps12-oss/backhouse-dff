from __future__ import annotations

from dataclasses import replace

from cerebro.v2.state.actions import (
    Action,
    DeletionHistoryDataLoaded,
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
    ScanProgressSnapshot,
    ScanStarted,
    SetActiveTab,
)
from cerebro.v2.state.app_state import AppMode, AppState, VALID_MAIN_TAB_KEYS
from cerebro.v2.state.groups_prune import prune_paths_from_groups
from cerebro.v2.state.history_view import HISTORY_SCAN_VALID_COLUMNS


RESULTS_FILE_VALID_FILTERS: frozenset[str] = frozenset(
    (
        "all",
        "pictures",
        "music",
        "videos",
        "documents",
        "archives",
        "other",
    )
)
RESULTS_GROUP_VALID_SORT: frozenset[str] = frozenset(
    ("reclaimable", "files", "group_id", "path")
)
HISTORY_PAGE_VALID_SUBTABS: frozenset[str] = frozenset(("scan", "deletion"))

def _mode_for_main_tab(key: str) -> AppMode:
    if key in ("welcome", "scan", "history", "diagnostics"):
        return AppMode.IDLE
    if key == "results":
        return AppMode.RESULTS
    if key == "review":
        return AppMode.REVIEW
    return AppMode.IDLE


def reduce(state: AppState, action: Action) -> AppState:
    """
    Pure transition (Blueprint §0.1). No I/O, no UI imports.
    """
    if isinstance(action, SetActiveTab):
        key = action.key
        if key not in VALID_MAIN_TAB_KEYS:
            return state
        if key == "review" and not state.review_unlocked:
            return state
        if key == state.active_tab:
            return state
        new_sel = state.selected_group_id if key == "review" else None
        if state.mode == AppMode.SCANNING:
            return replace(
                state,
                active_tab=key,
                selected_group_id=new_sel,
            )
        return replace(
            state,
            active_tab=key,
            mode=_mode_for_main_tab(key),
            selected_group_id=new_sel,
        )

    if isinstance(action, ScanStarted):
        return replace(
            state,
            mode=AppMode.SCANNING,
            scan_mode=action.scan_mode or "files",
            scan_progress={},
        )

    if isinstance(action, ScanProgressSnapshot):
        return replace(state, scan_progress=dict(action.data))

    if isinstance(action, ScanEnded):
        if action.reason not in ("cancelled", "error"):
            return state
        return replace(
            state,
            mode=AppMode.IDLE,
            scan_progress={},
        )

    if isinstance(action, ScanCompleted):
        g = list(action.groups)
        sm = action.scan_mode or "files"
        return replace(
            state,
            mode=AppMode.RESULTS,
            groups=g,
            scan_mode=sm,
            selected_group_id=None,
            active_tab="results",
            review_unlocked=True,
            scan_progress={},
            results_file_filter="all",
            results_group_sort_column="reclaimable",
            results_group_sort_asc=False,
            results_text_filter="",
            review_file_filter="all",
        )

    if isinstance(action, ReviewNavigate):
        gid = int(action.group_id)
        return replace(
            state,
            mode=AppMode.REVIEW,
            selected_group_id=gid,
            active_tab="review",
            review_unlocked=True,
        )

    if isinstance(action, HistoryDataLoaded):
        return replace(
            state,
            history_scan_rows=[dict(r) for r in action.rows],
            history_page=0,
        )

    if isinstance(action, HistoryGridSortChanged):
        col = action.column
        if col not in HISTORY_SCAN_VALID_COLUMNS:
            col = "date"
        return replace(
            state,
            history_sort_column=col,
            history_sort_asc=bool(action.sort_asc),
            history_page=0,
        )

    if isinstance(action, HistoryGridFilterChanged):
        return replace(
            state,
            history_filter=str(action.text),
            history_page=0,
        )

    if isinstance(action, HistoryGridPageChanged):
        return replace(
            state,
            history_page=max(0, int(action.page_index)),
        )

    if isinstance(action, ResultsGroupGridSortChanged):
        col = action.column
        if col not in RESULTS_GROUP_VALID_SORT:
            col = "reclaimable"
        return replace(
            state,
            results_group_sort_column=col,
            results_group_sort_asc=bool(action.sort_asc),
        )

    if isinstance(action, ResultsViewFilterChanged):
        fk = action.filter_key
        if fk not in RESULTS_FILE_VALID_FILTERS:
            fk = "all"
        return replace(
            state,
            results_file_filter=fk,
        )

    if isinstance(action, ResultsViewTextFilterChanged):
        raw = str(action.text) if action.text is not None else ""
        if len(raw) > 2000:
            raw = raw[:2000]
        return replace(state, results_text_filter=raw)

    if isinstance(action, SetDryRun):
        return replace(state, dry_run=bool(action.value))

    if isinstance(action, ResultsFilesRemoved):
        if not action.paths:
            return state
        new_groups = prune_paths_from_groups(state.groups, action.paths)
        return replace(state, groups=new_groups)

    if isinstance(action, DeletionHistoryDataLoaded):
        return replace(
            state,
            history_deletion_rows=[dict(r) for r in action.rows],
        )

    if isinstance(action, HistorySubTabChanged):
        key = action.key
        if key not in HISTORY_PAGE_VALID_SUBTABS:
            key = "scan"
        ui = {**state.ui, "history_subtab": key}
        return replace(state, ui=ui)

    if isinstance(action, ReviewViewFilterChanged):
        fk = action.filter_key
        if fk not in RESULTS_FILE_VALID_FILTERS:
            fk = "all"
        return replace(state, review_file_filter=fk)

    raise TypeError(f"Unsupported action: {type(action).__name__}")
