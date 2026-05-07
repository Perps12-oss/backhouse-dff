"""Regression tests for ``cerebro.core.group_invariants`` (post-v1 audit Phase 2c / 2e)."""
from __future__ import annotations

import pytest

from cerebro.core.group_invariants import _assert_no_self_duplicates


def test_assert_no_self_duplicates_strict_off_drops_second_same_path(
    tmp_path, monkeypatch,
) -> None:
    monkeypatch.delenv("CEREBRO_STRICT", raising=False)
    f = tmp_path / "dup.txt"
    f.write_text("x", encoding="utf-8")
    group = [(f, 0.0), (f, 0.0)]
    kept, regressions = _assert_no_self_duplicates(group, group_key="test")
    assert regressions == 1
    assert len(kept) == 1
    assert kept[0][0] == f


def test_assert_no_self_duplicates_strict_on_raises(
    tmp_path, monkeypatch,
) -> None:
    monkeypatch.setenv("CEREBRO_STRICT", "1")
    f = tmp_path / "dup.txt"
    f.write_text("x", encoding="utf-8")
    group = [(f, 0.0), (f, 0.0)]
    with pytest.raises(ValueError, match="self-duplicate regression"):
        _assert_no_self_duplicates(group, group_key="test")


def test_assert_no_self_duplicates_unique_paths_unchanged(
    tmp_path, monkeypatch,
) -> None:
    monkeypatch.delenv("CEREBRO_STRICT", raising=False)
    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    a.write_text("1", encoding="utf-8")
    b.write_text("2", encoding="utf-8")
    group = [(a, 0.0), (b, 0.0)]
    kept, regressions = _assert_no_self_duplicates(group, group_key="test")
    assert regressions == 0
    assert len(kept) == 2
