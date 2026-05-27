"""Phase 0 — selection contract: snapshots, scope invalidation, transactions."""

from __future__ import annotations

from pathlib import Path

from cerebro.engines.base_engine import DuplicateFile, DuplicateGroup
from cerebro.v2.ui.flet_app.pages.review_flow.selection_contract import marks_need_auto_apply_on_open
from cerebro.v2.ui.flet_app.pages.review_flow.state import ReviewFlowState


def _group(n: int = 3, gid: int = 1) -> DuplicateGroup:
    files = [
        DuplicateFile(
            path=Path(f"/tmp/g{gid}_a_{i}.jpg"),
            size=100,
            modified=float(i),
            extension=".jpg",
        )
        for i in range(n)
    ]
    return DuplicateGroup(group_id=gid, files=files, reclaimable=200)


def test_marks_need_auto_apply_when_snapshot_missing() -> None:
    state = ReviewFlowState()
    state.scan_results = [_group()]
    state.sync_scan_id()
    assert state.check_mark_snapshot() == "missing"
    assert marks_need_auto_apply_on_open(state) is True


def test_valid_snapshot_blocks_auto_apply() -> None:
    state = ReviewFlowState()
    state.scan_results = [_group()]
    state.sync_scan_id()
    state.finalize_rule_recompute("keep_newest")
    assert state.check_mark_snapshot() == "valid"
    assert marks_need_auto_apply_on_open(state) is False


def test_media_filter_change_invalidates_scope() -> None:
    state = ReviewFlowState()
    group = _group()
    state.scan_results = [group]
    state.sync_scan_id()
    p1, p2 = str(group.files[1].path), str(group.files[2].path)
    state.marked_paths = {p1, p2}
    state._recompute_cart_counters()
    state.finalize_rule_recompute("keep_newest")
    assert state.cart_delete_count == 2
    prev_fp = state.universe_fingerprint()
    state.selection_media_filter_enabled = True
    state.selection_media_type = "pictures"
    state.on_scope_fingerprint_changed(prev_fp)
    assert state.selection_validity == "invalidated_scope"
    assert marks_need_auto_apply_on_open(state) is False
    assert state.displayed_cart_delete_count == 2
    assert not state.delete_preparation_allowed()


def test_manual_edit_does_not_invalidate_snapshot() -> None:
    state = ReviewFlowState()
    group = _group()
    state.scan_results = [group]
    state.sync_scan_id()
    state.finalize_rule_recompute("keep_newest")
    state.note_manual_selection_edit()
    assert state.selection_origin == "manual_review"
    assert state.check_mark_snapshot() == "valid"
    assert state.selection_validity == "valid"


def test_rule_recompute_after_manual_sets_mixed() -> None:
    state = ReviewFlowState()
    state.scan_results = [_group()]
    state.sync_scan_id()
    state.finalize_rule_recompute("keep_newest")
    state.note_manual_selection_edit()
    state.begin_selection_recompute()
    state.finalize_rule_recompute("keep_oldest")
    assert state.selection_origin == "mixed"


def test_delete_transaction_gates() -> None:
    state = ReviewFlowState()
    group = _group(3)
    state.scan_results = [group]
    state.sync_scan_id()
    p1, p2 = (str(group.files[1].path), str(group.files[2].path))
    state.marked_paths = {p1, p2}
    state.finalize_rule_recompute("keep_newest")
    assert state.begin_delete_preparation() is True
    assert state.selection_transaction_state == "preparing_delete"
    assert state.begin_delete_execution() is True
    state.finish_delete_transaction()
    assert state.selection_transaction_state == "idle"


def test_delete_blocked_when_invalidated() -> None:
    state = ReviewFlowState()
    state.scan_results = [_group()]
    state.sync_scan_id()
    state.finalize_rule_recompute("keep_newest")
    state.selection_validity = "invalidated_scope"
    assert state.begin_delete_preparation() is False


def test_provenance_label_includes_out_of_date() -> None:
    state = ReviewFlowState()
    state.scan_results = [_group()]
    state.sync_scan_id()
    state.finalize_rule_recompute("keep_newest")
    state.selection_validity = "invalidated_scope"
    label = state.provenance_label()
    assert "out of date" in label.lower()
