"""
test_cli_delete.py — C-2: CLI deletion goes through CerebroPipeline.
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def _make_groups(tmp_path: Path):
    """Create two temporary duplicate files and a mock DuplicateGroup list."""
    f1 = tmp_path / "a.txt"
    f2 = tmp_path / "b.txt"
    f1.write_text("hello")
    f2.write_text("hello")

    FileObj = types.SimpleNamespace
    group = types.SimpleNamespace(
        group_id=1,
        reclaimable=f2.stat().st_size,
        files=[
            FileObj(path=str(f1), size=f1.stat().st_size, modified=0),
            FileObj(path=str(f2), size=f2.stat().st_size, modified=0),
        ],
    )
    return [group], f1, f2


def test_cli_delete_uses_pipeline(tmp_path):
    """--delete with no --permanent must route through CerebroPipeline.build_delete_plan."""
    from cerebro.cli import _delete_duplicates
    import argparse

    groups, keeper, dup = _make_groups(tmp_path)

    called_with = []

    class _FakePipeline:
        class gate:
            @staticmethod
            def issue_token(reason=""):
                return "tok"

        def build_delete_plan(self, plan_dict):
            called_with.append(("build", plan_dict["policy"]["mode"]))
            # Return a minimal plan object
            ops = []
            for g in plan_dict["groups"]:
                for p in g["delete"]:
                    pp = Path(p)
                    if pp.exists():
                        import types as _t
                        ops.append(_t.SimpleNamespace(path=pp, size=pp.stat().st_size, group_index=0, kept_path=Path(g["keep"]), mtime=0.0))
            import types as _t
            return _t.SimpleNamespace(scan_id="x", mode="trash", operations=ops, total_files=len(ops), total_bytes=0, stats={}, policy={"mode":"trash"}, source="cli")

        def execute_delete_plan(self, plan, progress_cb=None):
            called_with.append(("execute", plan.mode))
            from cerebro.core.pipeline import DeletionResult
            return DeletionResult(scan_id="x", mode="trash", deleted=[op.path for op in plan.operations], failed=[], bytes_reclaimed=0)

    with patch("cerebro.core.pipeline.CerebroPipeline", return_value=_FakePipeline()):
        args = argparse.Namespace(keep="largest", permanent=False, dry_run=False, quiet=True)
        rc = _delete_duplicates(groups, args)

    assert rc == 0
    assert any(m[0] == "build" for m in called_with), "build_delete_plan not called"
    assert any(m[0] == "execute" for m in called_with), "execute_delete_plan not called"
    assert any(m[1] == "trash" for m in called_with if m[0] == "build"), "mode should be trash"


def test_cli_delete_permanent_requires_confirmation(tmp_path, monkeypatch):
    """--permanent should ask for YES confirmation before issuing token."""
    from cerebro.cli import _delete_duplicates
    import argparse

    groups, keeper, dup = _make_groups(tmp_path)

    monkeypatch.setattr("builtins.input", lambda: "NO")

    args = argparse.Namespace(keep="largest", permanent=True, dry_run=False, quiet=True)
    rc = _delete_duplicates(groups, args)
    assert rc == 1, "Should abort when user types NO"


def test_cli_delete_dry_run_no_changes(tmp_path):
    """--dry-run should not delete anything."""
    from cerebro.cli import _delete_duplicates
    import argparse

    groups, keeper, dup = _make_groups(tmp_path)
    args = argparse.Namespace(keep="largest", permanent=False, dry_run=True, quiet=True)
    rc = _delete_duplicates(groups, args)
    assert rc == 0
    assert dup.exists(), "dry-run should not delete the file"
