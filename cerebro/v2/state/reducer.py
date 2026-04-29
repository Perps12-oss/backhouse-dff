from __future__ import annotations

from dataclasses import replace

from cerebro.v2.state.actions import (
    Action,
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
    GroupsPruned,
    ResultsGroupGridSortChanged,
    SetDryRun,
    ScanCompleted,
    ScanEnded,
    ScanPaused,
    ScanProgressSnapshot,
    ScanResumed,
    ScanStarted,
    SetActiveTab,
    ThemeChanged,
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
    if key in ("dashboard", "history", "settings"):
        return AppMode.IDLE
    if key == "duplicates":
        return AppMode.RESULTS
    if key == "review":
        return AppMode.REVIEW
    return AppMode.IDLE


def reduce(state: AppState, action: Action) -> AppState:
    """
    Pure transition (FINAL PLAN v2.0 §2.2). No I/O, no UI imports.
    User Action -> Dispatch -> State Update -> Render
    """
    # ------------------------------------------------------------------
    # Global Advanced Toggle (FINAL PLAN §1.2)
    # ------------------------------------------------------------------
    if isinstance(action, AdvancedModeToggled):
        new_val = action.value if action.value is not None else not state.advanced_mode
        return replace(state, advanced_mode=bool(new_val))

    # ------------------------------------------------------------------
    # Theme (FINAL PLAN §3)
    # ------------------------------------------------------------------
    if isinstance(action, ThemeChanged):
        t = action.theme
        if t not in ("light", "dark", "system"):
            return state
        return replace(state, theme=t)

    # ------------------------------------------------------------------
    # File Selection (FINAL PLAN §5.5)
    # ------------------------------------------------------------------
    if isinstance(action, FileSelectionChanged):
        return replace(state, selected_files=set(action.file_ids))

    if isinstance(action, FileSelectionCleared):
        return replace(state, selected_files=set())

    # ------------------------------------------------------------------
    # Tab Navigation (FINAL PLAN §1.1)
    # ------------------------------------------------------------------
    if isinstance(action, SetActiveTab):
        key = action.key
        if key not in VALID_MAIN_TAB_KEYS:
            return state
        if key == state.active_tab:
            return state
        if state.mode == AppMode.SCANNING:
            return replace(state, active_tab=key)
        return replace(
            state,
            active_tab=key,
            mode=_mode_for_main_tab(key),
        )

    # ------------------------------------------------------------------
    # Scan Lifecycle (FINAL PLAN §9)
    # ------------------------------------------------------------------
    if isinstance(action, ScanStarted):
        return replace(
            state,
            mode=AppMode.SCANNING,
            scan_mode=action.scan_mode or "files",
            scan_progress={},
            scan_can_pause=True,
            scan_can_resume=False,
            scan_is_cancelled=False,
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
            scan_can_pause=False,
            scan_can_resume=False,
            scan_is_cancelled=(action.reason == "cancelled"),
        )

    if isinstance(action, ScanPaused):
        return replace(
            state,
            scan_can_pause=False,
            scan_can_resume=True,
        )

    if isinstance(action, ScanResumed):
        return replace(
            state,
            scan_can_pause=True,
            scan_can_resume=False,
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
            active_tab="duplicates",
            review_unlocked=True,
            scan_progress={},
            scan_can_pause=False,
            scan_can_resume=False,
            scan_is_cancelled=False,
            results_file_filter="all",
            results_group_sort_column="reclaimable",
            results_group_sort_asc=False,
            results_text_filter="",
            review_file_filter="all",
            selected_files=set(),
        )

    if isinstance(action, ReviewNavigate):
        gid = int(action.group_id)
        return replace(
            state,
            mode=AppMode.REVIEW,
            selected_group_id=gid,
            review_unlocked=True,
        )

    # ------------------------------------------------------------------
    # History (FINAL PLAN §7)
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # Duplicates / Results (FINAL PLAN §5)
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # Delete Flow (FINAL PLAN §6)
    # ------------------------------------------------------------------
    if isinstance(action, SetDryRun):
        return replace(state, dry_run=bool(action.value))

    if isinstance(action, ResultsFilesRemoved):
        if not action.paths:
            return state
        new_groups = prune_paths_from_groups(state.groups, action.paths)
        return replace(state, groups=new_groups, selected_files=set())

    if isinstance(action, GroupsPruned):
        return replace(state, groups=list(action.groups), selected_files=set())

    if isinstance(action, ReviewViewFilterChanged):
        fk = action.filter_key
        if fk not in RESULTS_FILE_VALID_FILTERS:
            fk = "all"
        return replace(state, review_file_filter=fk)

    raise TypeError(f"Unsupported action: {type(action).__name__}")
