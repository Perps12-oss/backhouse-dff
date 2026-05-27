"""Tests for :mod:`cerebro.v2.ui.flet_app.pages.review_flow.smart_rules`."""

from __future__ import annotations

from pathlib import Path

import pytest

from cerebro.engines.base_engine import DuplicateFile
from cerebro.v2.ui.flet_app.pages.review_flow.smart_rules import (
    apply_rule,
    normalized_rule,
    paths_to_delete,
)


def _f(path: str, *, size: int, modified: float) -> DuplicateFile:
    return DuplicateFile(
        path=Path(path),
        size=size,
        modified=modified,
        extension=Path(path).suffix or "",
    )


def test_paths_to_delete_empty_or_singleton() -> None:
    a = _f("/x/a", size=1, modified=0.0)
    assert paths_to_delete("keep_largest", []) == []
    assert paths_to_delete("keep_largest", [a]) == []


def test_keep_largest_and_newest() -> None:
    a = _f("small.txt", size=1, modified=100.0)
    b = _f("big.txt", size=10, modified=1.0)
    files = [a, b]
    assert apply_rule("keep_largest", files) is b
    assert apply_rule("keep_newest", files) is a
    rm_l = paths_to_delete("keep_largest", files)
    rm_n = paths_to_delete("keep_newest", files)
    assert len(rm_l) == 1 and Path(rm_l[0]) == a.path
    assert len(rm_n) == 1 and Path(rm_n[0]) == b.path


def test_normalized_rule_unknown() -> None:
    assert normalized_rule("") == "keep_largest"
    assert normalized_rule("nope") == "keep_largest"
    assert normalized_rule("keep_smallest") == "keep_smallest"
    assert normalized_rule("keep_first") == "keep_first"


def test_apply_rule_unknown_raises() -> None:
    a = _f("/x/a", size=1, modified=0.0)
    b = _f("/x/b", size=2, modified=0.0)
    with pytest.raises(ValueError, match="Unknown smart rule"):
        apply_rule("not_a_rule", [a, b])


def test_keep_first() -> None:
    a = _f("first.txt", size=5, modified=1.0)
    b = _f("second.txt", size=10, modified=99.0)
    files = [a, b]
    assert apply_rule("keep_first", files) is a
    rm = paths_to_delete("keep_first", files)
    assert len(rm) == 1 and Path(rm[0]) == b.path
