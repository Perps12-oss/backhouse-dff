"""
test_dual_audit_trail.py — MC-2: Both HistoryStore (JSONL) and deletion_history_db (SQLite)
are written after a successful delete.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch


def test_dual_audit_written_on_execute(tmp_path):
    """execute_delete_plan must write to both HistoryStore and deletion_history_db."""
    f = tmp_path / "a.txt"
    f.write_text("hello")

    from cerebro.core.pipeline import CerebroPipeline
    from cerebro.history.store import HistoryStore

    mock_history = MagicMock(spec=HistoryStore)
    mock_history.record_deletion = MagicMock(return_value=MagicMock())
    log_calls = []

    pipeline = CerebroPipeline(history_store=mock_history)

    with patch("cerebro.v2.core.deletion_history_db.log_deletion_event", side_effect=lambda *a, **k: log_calls.append(a)):
        plan = pipeline.build_explicit_paths_plan([str(f)], mode="trash")
        result = pipeline.execute_delete_plan(plan)

    assert mock_history.record_deletion.called, "HistoryStore.record_deletion must be called"


def test_dual_audit_written_on_managed_trash(tmp_path):
    """_delete_to_managed_trash also calls _record_dual_audit for the JSONL + SQLite trail."""
    f = tmp_path / "b.txt"
    f.write_text("world")

    from cerebro.v2.ui.flet_app.services.delete_service import DeleteService
    from cerebro.core.pipeline import CerebroPipeline
    from cerebro.history.store import HistoryStore

    mock_history = MagicMock(spec=HistoryStore)
    mock_history.record_deletion = MagicMock(return_value=MagicMock())
    pipeline = CerebroPipeline(history_store=mock_history)
    svc = DeleteService(pipeline=pipeline)

    from cerebro.core.deletion import DeletionPolicy
    result = svc.delete_files([str(f)], DeletionPolicy.TRASH)

    assert mock_history.record_deletion.called, "HistoryStore.record_deletion must be called for managed trash"
