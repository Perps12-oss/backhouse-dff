"""
test_unicode_paths_windows.py — Unicode file paths (e.g. CJK, Arabic, emoji) are handled.
"""
from __future__ import annotations

import sys

import pytest

from cerebro.core.pipeline import CerebroPipeline


@pytest.mark.skipif(sys.platform != "win32", reason="Unicode path test targets Windows")
def test_unicode_path_in_explicit_plan(tmp_path):
    """Files with Unicode names must appear in explicit plan without encoding errors."""
    f = tmp_path / "日本語ファイル_🐍.txt"
    f.write_text("unicode", encoding="utf-8")

    pipeline = CerebroPipeline()
    plan = pipeline.build_explicit_paths_plan([str(f)])
    assert plan.total_files == 1
    assert plan.operations[0].path.name == f.name


def test_unicode_path_non_windows(tmp_path):
    """Non-Windows: Unicode paths also work correctly."""
    f = tmp_path / "日本語.txt"
    f.write_text("unicode", encoding="utf-8")

    pipeline = CerebroPipeline()
    plan = pipeline.build_explicit_paths_plan([str(f)])
    assert plan.total_files == 1
