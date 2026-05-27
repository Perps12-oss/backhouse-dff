"""
test_pipeline_symlink_keeper.py — Pipeline: symlink as keeper must not allow its resolution
to match a delete target and cause keeper-equals-delete invariant failure.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from cerebro.core.pipeline import CerebroPipeline


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks may require elevated permissions")
def test_symlink_keeper_not_deleted(tmp_path):
    """If keeper is a symlink pointing to a real file, the real file must not be deleted."""
    real = tmp_path / "real.txt"
    real.write_text("original")
    symlink = tmp_path / "link.txt"
    symlink.symlink_to(real)
    dup = tmp_path / "dup.txt"
    dup.write_text("original")

    pipeline = CerebroPipeline()
    plan_dict = {
        "scan_id": "t",
        "policy": {"mode": "trash"},
        "groups": [{"group_index": 0, "keep": str(symlink), "delete": [str(dup)]}],
    }
    plan = pipeline.build_delete_plan(plan_dict)
    assert all(op.path != real for op in plan.operations), "Real file behind symlink must never appear in delete ops"


def test_keeper_equals_delete_rejected(tmp_path):
    """build_delete_plan must skip any delete path that resolves to the same inode as the keeper."""
    f = tmp_path / "file.txt"
    f.write_text("data")

    pipeline = CerebroPipeline()
    plan_dict = {
        "scan_id": "t",
        "policy": {"mode": "trash"},
        "groups": [{"group_index": 0, "keep": str(f), "delete": [str(f)]}],
    }
    with pytest.raises(ValueError, match="no valid operations"):
        pipeline.build_delete_plan(plan_dict)
