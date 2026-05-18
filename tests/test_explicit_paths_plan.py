"""
test_explicit_paths_plan.py — build_explicit_paths_plan: no keeper invariant,
still enforces hardlink/directory blocks.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from cerebro.core.pipeline import CerebroPipeline


def test_explicit_paths_plan_basic(tmp_path):
    """Files passed to build_explicit_paths_plan appear as operations."""
    f1 = tmp_path / "a.txt"
    f2 = tmp_path / "b.txt"
    f1.write_text("a")
    f2.write_text("b")

    pipeline = CerebroPipeline()
    plan = pipeline.build_explicit_paths_plan([str(f1), str(f2)], mode="trash")

    assert plan.total_files == 2
    assert {op.path for op in plan.operations} == {f1, f2}
    assert plan.mode == "trash"


def test_explicit_paths_plan_skips_missing():
    """Non-existent paths are silently skipped."""
    pipeline = CerebroPipeline()
    plan = pipeline.build_explicit_paths_plan(["/nonexistent/x.txt"])
    assert plan.total_files == 0


@pytest.mark.skipif(sys.platform == "win32", reason="hardlinks require elevated privileges on Windows")
def test_explicit_paths_plan_blocks_hardlink(tmp_path):
    """Hardlinked files are blocked even with no keeper invariant."""
    original = tmp_path / "orig.txt"
    original.write_text("data")
    link = tmp_path / "link.txt"
    os.link(original, link)

    pipeline = CerebroPipeline()
    plan = pipeline.build_explicit_paths_plan([str(link)])
    assert plan.total_files == 0, "Hardlinked file must be blocked from explicit paths plan"


def test_explicit_paths_plan_kept_path_is_none(tmp_path):
    """kept_path must be None for explicit path plans (no keeper concept)."""
    f = tmp_path / "c.txt"
    f.write_text("c")
    pipeline = CerebroPipeline()
    plan = pipeline.build_explicit_paths_plan([str(f)])
    assert all(op.kept_path is None for op in plan.operations)
