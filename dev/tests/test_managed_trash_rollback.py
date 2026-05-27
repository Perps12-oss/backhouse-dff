"""
test_managed_trash_rollback.py — H-4: Rollback on mid-batch failure.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from cerebro.v2.ui.flet_app.services.delete_service import DeleteService


def test_rollback_on_failure(tmp_path):
    """If a move fails mid-batch, already-moved files must be restored."""
    f1 = tmp_path / "f1.txt"
    f2 = tmp_path / "f2.txt"
    f3 = tmp_path / "f3.txt"
    for f in [f1, f2, f3]:
        f.write_text("data")

    svc = DeleteService()

    call_count = [0]
    original_move = __import__("shutil").move

    def _failing_move(src, dst):
        call_count[0] += 1
        if call_count[0] == 2:
            raise OSError("simulated disk full")
        original_move(src, dst)

    import shutil
    with patch.object(shutil, "move", side_effect=_failing_move):
        deleted_paths, failures = svc._delete_to_managed_trash(
            [str(f1), str(f2), str(f3)],
            {str(f1): f1.stat().st_size, str(f2): f2.stat().st_size, str(f3): f3.stat().st_size},
            None,
        )

    # Rollback must have restored f1 (the first move that succeeded before f2 failed).
    assert f1.exists(), "f1 should have been rolled back"
    assert len(deleted_paths) == 0, "No files should be reported as deleted on failure"
    assert len(failures) > 0, "Failure must be recorded"


def test_undo_last_trash_delete(tmp_path):
    """undo_last_trash_delete() restores files from the last transaction."""
    f1 = tmp_path / "x.txt"
    f1.write_text("hello")

    svc = DeleteService()
    deleted_paths, _ = svc._delete_to_managed_trash(
        [str(f1)], {str(f1): f1.stat().st_size}, None
    )
    assert not f1.exists(), "File should be moved to trash"

    ok, restored = svc.undo_last_trash_delete()
    assert ok
    assert restored == 1
    assert f1.exists(), "File should be restored"


def test_trash_history_is_instance_scoped():
    """MC-5: Two DeleteService instances must not share undo history."""
    svc1 = DeleteService()
    svc2 = DeleteService()
    # Artificially populate svc1's history.
    from cerebro.v2.ui.flet_app.services.delete_service import TrashUndoTransaction
    svc1._trash_history.append(TrashUndoTransaction(tx_id="t1", moved=[], created_at=0.0))
    assert len(svc2._trash_history) == 0, "svc2 must have its own empty history"
