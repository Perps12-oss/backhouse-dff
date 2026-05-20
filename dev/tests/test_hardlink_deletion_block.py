"""
test_hardlink_deletion_block.py — C-3: Hardlinked files are blocked from deletion.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from cerebro.core.deletion import DeletionEngine, DeletionPolicy, DeletionRequest


@pytest.mark.skipif(sys.platform == "win32", reason="hardlinks on Windows require elevated privileges")
def test_delete_one_blocks_hardlink(tmp_path):
    """delete_one() must refuse to delete a hardlinked file."""
    original = tmp_path / "original.txt"
    original.write_text("data")
    link = tmp_path / "link.txt"
    os.link(original, link)

    engine = DeletionEngine()
    request = DeletionRequest(policy=DeletionPolicy.PERMANENT)
    result = engine.delete_one(link, request)

    assert not result.success
    assert "hardlink_protected" in (result.error or "")
    assert link.exists(), "Hardlinked file must still exist"


def test_delete_one_blocks_directory(tmp_path):
    """delete_one() must refuse to delete a directory (not a file)."""
    d = tmp_path / "subdir"
    d.mkdir()

    engine = DeletionEngine()
    request = DeletionRequest(policy=DeletionPolicy.PERMANENT)
    result = engine.delete_one(d, request)

    assert not result.success
    assert result.error == "is_directory"
    assert d.exists()


def test_delete_one_missing_file_is_skipped(tmp_path):
    """Missing file produces a non-success result without raising."""
    p = tmp_path / "nonexistent.txt"
    engine = DeletionEngine()
    request = DeletionRequest(policy=DeletionPolicy.PERMANENT)
    result = engine.delete_one(p, request)
    assert not result.success
    # error should be 'missing' from should_block_delete or 'File does not exist'
    assert result.error is not None


def test_build_delete_plan_blocks_hardlink(tmp_path):
    """build_delete_plan should skip hardlinked delete targets."""
    import os as _os, sys as _sys
    if _sys.platform == "win32":
        pytest.skip("hardlinks on Windows require elevated privileges")

    from cerebro.core.pipeline import CerebroPipeline

    keeper = tmp_path / "keeper.txt"
    dup = tmp_path / "dup.txt"
    keeper.write_text("data")
    dup.write_text("data")
    linked = tmp_path / "link.txt"
    _os.link(dup, linked)

    pipeline = CerebroPipeline()
    plan = {
        "scan_id": "test",
        "policy": {"mode": "trash"},
        "groups": [{"group_index": 0, "keep": str(keeper), "delete": [str(dup), str(linked)]}],
    }
    result_plan = pipeline.build_delete_plan(plan)
    # linked should be blocked; dup (not hardlinked beyond nlink==2) depends on platform
    blocked_paths = [str(op.path) for op in result_plan.operations]
    assert str(linked) not in blocked_paths, "Hardlinked path must be excluded from plan"
