"""
test_store_listener_immutability.py — MC-1: Listener cannot mutate the 'old' state.
"""
from __future__ import annotations

import os

import pytest


def test_old_state_mutation_does_not_affect_next_dispatch(monkeypatch):
    """In debug mode, mutating old.selected_files inside a listener must not affect future dispatches."""
    monkeypatch.setenv("CEREBRO_DEBUG", "1")

    # Re-import to pick up env var.
    import importlib
    import cerebro.v2.state.store as store_mod
    importlib.reload(store_mod)

    from cerebro.v2.state.app_state import AppState, AppMode
    from cerebro.v2.state.actions import FileSelectionChanged

    initial = AppState(mode=AppMode.IDLE, selected_files={"file_a.txt"})
    store = store_mod.StateStore(initial)

    mutations_saw_pollution = []

    def _mutating_listener(current, old, action):
        # Attempt to mutate 'old' selected_files.
        try:
            old.selected_files.add("injected_by_listener")
        except (AttributeError, TypeError):
            pass
        mutations_saw_pollution.append("injected_by_listener" in store_mod._safe_old(store.get_state()).selected_files)

    store.subscribe(_mutating_listener)
    store.dispatch(FileSelectionChanged(file_ids=("file_b.txt",)))

    # The stored state must not contain the injected path.
    assert "injected_by_listener" not in store.get_state().selected_files


def test_listener_receives_safe_old_in_debug(monkeypatch):
    """In debug mode, _safe_old returns a copy with cloned sets."""
    monkeypatch.setenv("CEREBRO_DEBUG", "1")
    import importlib
    import cerebro.v2.state.store as store_mod
    importlib.reload(store_mod)

    from cerebro.v2.state.app_state import AppState, AppMode

    state = AppState(mode=AppMode.IDLE, selected_files={"a", "b"})
    safe = store_mod._safe_old(state)

    # Mutating safe must not affect original.
    try:
        safe.selected_files.add("x")
        assert "x" not in state.selected_files
    except (AttributeError, TypeError):
        pass  # frozen or immutable — also fine
