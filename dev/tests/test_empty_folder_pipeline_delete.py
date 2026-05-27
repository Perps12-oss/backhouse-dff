"""
test_empty_folder_pipeline_delete.py — C-3: EmptyFolderEngine results (directories)
must be deletable through the pipeline when allow_directory_delete=True.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from cerebro.core.deletion import DeletionEngine, DeletionPolicy, DeletionRequest


def test_empty_folder_deleted_via_engine(tmp_path):
    d = tmp_path / "empty"
    d.mkdir()

    engine = DeletionEngine()
    req = DeletionRequest(policy=DeletionPolicy.PERMANENT, allow_directory_delete=True)
    result = engine.delete_one(d, req)

    assert result.success is True
    assert not d.exists()


def test_empty_folder_blocked_without_flag(tmp_path):
    d = tmp_path / "empty"
    d.mkdir()

    engine = DeletionEngine()
    req = DeletionRequest(policy=DeletionPolicy.PERMANENT, allow_directory_delete=False)
    result = engine.delete_one(d, req)

    assert result.success is False
    assert d.exists()


def test_execute_plan_with_directory_operations(tmp_path):
    """Batch execution with allow_directory_delete=True deletes directory targets."""
    d1 = tmp_path / "d1"
    d2 = tmp_path / "d2"
    d1.mkdir()
    d2.mkdir()

    class FakeOp:
        def __init__(self, path):
            self.path = path
            self.size = 0

    class FakePlan:
        scan_id = "test"
        mode = "permanent"
        operations = [FakeOp(d1), FakeOp(d2)]

    engine = DeletionEngine()
    req = DeletionRequest(policy=DeletionPolicy.PERMANENT, allow_directory_delete=True)
    result = engine.execute_plan(FakePlan(), request=req)

    assert len(result.deleted) == 2
    assert not d1.exists()
    assert not d2.exists()
