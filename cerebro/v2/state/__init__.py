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
    ReviewNavigate,
    ScanCompleted,
    ScanEnded,
    ScanProgressSnapshot,
    ScanStarted,
    SetActiveTab,
)
from cerebro.v2.state.scan_progress import scan_progress_to_dict
from cerebro.v2.state.reducer import reduce
from cerebro.v2.state.store import StateStore, Listener

__all__ = [
    "Action",
    "AppMode",
    "AppState",
    "Listener",
    "ReviewNavigate",
    "ScanCompleted",
    "ScanEnded",
    "ScanProgressSnapshot",
    "ScanStarted",
    "SetActiveTab",
    "StateStore",
    "VALID_MAIN_TAB_KEYS",
    "create_initial_state",
    "reduce",
    "scan_progress_to_dict",
]
