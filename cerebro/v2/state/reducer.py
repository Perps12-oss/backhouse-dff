from __future__ import annotations

from dataclasses import replace

from cerebro.v2.state.actions import (
    Action,
    ReviewNavigate,
    ScanCompleted,
    ScanEnded,
    ScanProgressSnapshot,
    ScanStarted,
    SetActiveTab,
)
from cerebro.v2.state.app_state import AppMode, AppState, VALID_MAIN_TAB_KEYS


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

    raise TypeError(f"Unsupported action: {type(action).__name__}")
