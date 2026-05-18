"""
test_reducer_scanning_delete_guard.py — LT-2: Reducer rejects delete actions during SCANNING.
"""
from __future__ import annotations

import pytest

from cerebro.v2.state.app_state import AppMode, AppState
from cerebro.v2.state.actions import GroupsPruned, ResultsFilesRemoved
from cerebro.v2.state.reducer import reduce
from cerebro.engines.base_engine import DuplicateFile, DuplicateGroup
from pathlib import Path


def _make_group():
    f = DuplicateFile(path=Path("/a.txt"), size=100, modified=0.0, extension=".txt")
    return DuplicateGroup(group_id=1, files=[f])


def test_groups_pruned_rejected_during_scanning():
    """GroupsPruned action must be a no-op when mode == SCANNING."""
    g = _make_group()
    state = AppState(groups=[g], mode=AppMode.SCANNING)
    action = GroupsPruned(groups=[])
    new_state = reduce(state, action)
    assert len(new_state.groups) == 1, "Groups must NOT be pruned during SCANNING"


def test_results_files_removed_rejected_during_scanning():
    """ResultsFilesRemoved must be a no-op during SCANNING."""
    g = _make_group()
    state = AppState(groups=[g], mode=AppMode.SCANNING)
    action = ResultsFilesRemoved(paths=["/a.txt"])
    new_state = reduce(state, action)
    assert len(new_state.groups) == 1, "Files must NOT be removed during SCANNING"


def test_groups_pruned_allowed_outside_scanning():
    """GroupsPruned must be applied when not scanning."""
    g = _make_group()
    state = AppState(groups=[g], mode=AppMode.IDLE)
    action = GroupsPruned(groups=[])
    new_state = reduce(state, action)
    assert len(new_state.groups) == 0, "Groups must be pruned outside SCANNING"
