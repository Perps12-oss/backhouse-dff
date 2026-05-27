from __future__ import annotations

from cerebro.v2.ui.flet_app.pages.review_flow.state import ReviewFlowState


def test_undo_restore_marked_paths() -> None:
    state = ReviewFlowState()
    state.marked_paths = {"a"}
    state.push_undo_snapshot()
    state.marked_paths = {"b"}
    snap = state.undo_stack.pop()
    state.restore_snapshot(snap)
    assert state.marked_paths == {"a"}
