"""
test_delete_service_undo.py — DeleteService.undo_last_trash_delete() works correctly.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from cerebro.v2.ui.flet_app.services.delete_service import DeleteService
from cerebro.core.deletion import DeletionPolicy


def test_undo_restores_file(tmp_path):
    f = tmp_path / "file.txt"
    f.write_text("content")

    svc = DeleteService()
    result = svc.delete_files([str(f)], DeletionPolicy.TRASH)

    assert result.deleted_count == 1
    assert not f.exists()

    ok, count = svc.undo_last_trash_delete()
    assert ok
    assert count == 1
    assert f.exists(), "File must be restored after undo"


def test_undo_empty_history_returns_false():
    svc = DeleteService()
    ok, count = svc.undo_last_trash_delete()
    assert not ok
    assert count == 0


def test_undo_removes_transaction_from_history(tmp_path):
    f = tmp_path / "x.txt"
    f.write_text("x")

    svc = DeleteService()
    svc.delete_files([str(f)], DeletionPolicy.TRASH)
    assert len(svc._trash_history) == 1

    svc.undo_last_trash_delete()
    assert len(svc._trash_history) == 0, "Completed undo must remove transaction from history"
