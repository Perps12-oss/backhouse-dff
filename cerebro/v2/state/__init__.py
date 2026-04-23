"""CEREBRO v2 app state: single object, dispatch/reducer, store."""

from __future__ import annotations

from cerebro.v2.state.app_state import (
    AppMode,
    AppState,
    VALID_MAIN_TAB_KEYS,
    create_initial_state,
)
from cerebro.v2.state.actions import Action, ReviewNavigate, ScanCompleted, SetActiveTab
from cerebro.v2.state.reducer import reduce
from cerebro.v2.state.store import StateStore, Listener

__all__ = [
    "Action",
    "AppMode",
    "AppState",
    "Listener",
    "ReviewNavigate",
    "ScanCompleted",
    "SetActiveTab",
    "StateStore",
    "VALID_MAIN_TAB_KEYS",
    "create_initial_state",
    "reduce",
]
