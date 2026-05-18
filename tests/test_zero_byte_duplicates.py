"""
test_zero_byte_duplicates.py — Zero-byte files must be handled without crashing the engine.
"""
from __future__ import annotations

from pathlib import Path

from cerebro.core.pipeline import CerebroPipeline


def test_zero_byte_file_in_plan(tmp_path):
    keeper = tmp_path / "keeper.txt"
    dup = tmp_path / "dup.txt"
    keeper.write_bytes(b"")
    dup.write_bytes(b"")

    pipeline = CerebroPipeline()
    plan = pipeline.build_delete_plan({
        "scan_id": "t",
        "policy": {"mode": "trash"},
        "groups": [{"group_index": 0, "keep": str(keeper), "delete": [str(dup)]}],
    })
    assert plan.total_files == 1
    assert plan.total_bytes == 0


def test_explicit_plan_zero_byte(tmp_path):
    f = tmp_path / "empty.txt"
    f.write_bytes(b"")

    pipeline = CerebroPipeline()
    plan = pipeline.build_explicit_paths_plan([str(f)])
    assert plan.total_files == 1
    assert plan.total_bytes == 0
