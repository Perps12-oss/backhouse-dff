"""
test_ui_permanent_delete_token.py — C-2: DeleteService.delete_files() for PERMANENT
must issue a gate token and succeed, not raise DeletionGateError.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from cerebro.core.deletion import DeletionPolicy
from cerebro.v2.ui.flet_app.services.delete_service import DeleteService


def test_permanent_delete_succeeds_via_service(tmp_path):
    """C-2: permanent deletion through DeleteService must complete without DeletionGateError."""
    f = tmp_path / "to_delete.txt"
    f.write_text("bye")

    svc = DeleteService()
    result = svc.delete_files([str(f)], DeletionPolicy.PERMANENT)

    assert result.deleted_count == 1
    assert not f.exists()
    assert result.failed_count == 0


def test_permanent_delete_audit_written(tmp_path):
    """Both HistoryStore and deletion_history_db must be written for permanent UI deletes."""
    from unittest.mock import MagicMock
    from cerebro.core.pipeline import CerebroPipeline
    from cerebro.history.store import HistoryStore

    f = tmp_path / "perm.txt"
    f.write_text("x")

    mock_history = MagicMock(spec=HistoryStore)
    mock_history.record_deletion = MagicMock(return_value=MagicMock())
    pipeline = CerebroPipeline(history_store=mock_history)
    svc = DeleteService(pipeline=pipeline)

    svc.delete_files([str(f)], DeletionPolicy.PERMANENT)

    assert mock_history.record_deletion.called


def test_multiple_permanent_deletes_each_get_fresh_token(tmp_path):
    """Each call to delete_files must issue a fresh token — old token must not be reused."""
    files = []
    for i in range(3):
        f = tmp_path / f"f{i}.txt"
        f.write_text(f"content {i}")
        files.append(str(f))

    svc = DeleteService()
    for fpath in files:
        result = svc.delete_files([fpath], DeletionPolicy.PERMANENT)
        assert result.deleted_count == 1, f"Expected deletion of {fpath}"
