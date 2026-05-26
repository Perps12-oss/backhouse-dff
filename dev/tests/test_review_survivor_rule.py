"""Each duplicate group must retain at least one unmarked survivor."""

from __future__ import annotations

from pathlib import Path

from cerebro.engines.base_engine import DuplicateFile, DuplicateGroup
from cerebro.v2.ui.flet_app.pages.review_flow.state import ReviewFlowState


def _group(n: int = 3) -> DuplicateGroup:
    files = [
        DuplicateFile(
            path=Path(f"/tmp/a_{i}.jpg"),
            size=100,
            modified=float(i),
            extension=".jpg",
        )
        for i in range(n)
    ]
    return DuplicateGroup(group_id=1, files=files, reclaimable=200)


def test_mandatory_survivor_when_one_unmarked_left() -> None:
    state = ReviewFlowState()
    group = _group(3)
    state.scan_results = [group]
    p0, p1, p2 = (str(f.path) for f in group.files)
    state.marked_paths = {p1, p2}
    assert state.is_mandatory_survivor(p0, group) is True
    assert state.is_mandatory_survivor(p1, group) is False
    assert state.can_mark_path_for_deletion(p0, group, mark=True) is False


def test_clamp_restores_survivor_when_all_marked() -> None:
    state = ReviewFlowState()
    group = _group(2)
    state.scan_results = [group]
    p0, p1 = (str(f.path) for f in group.files)
    state.marked_paths = {p0, p1}
    state.clamp_group_to_single_survivor(group)
    assert state.unmarked_survivor_count(group) == 1
    assert p0 not in state.marked_paths
