from __future__ import annotations

from pathlib import Path

from cerebro.engines.base_engine import DuplicateFile
from cerebro.v2.ui.flet_app.pages.review_flow.screens.inspect import metadata_match_flags
from cerebro.v2.ui.flet_app.pages.review_flow.state import (
    inspect_left_right_indices,
    make_index_reference,
    normalize_inspect_ref_cmp,
    pin_compare_as_new_reference,
    step_inspect_cmp,
)


def test_normalize_inspect_ref_cmp_forces_distinct_pair() -> None:
    assert normalize_inspect_ref_cmp(4, 1, 1) == (1, 2)
    assert normalize_inspect_ref_cmp(4, 3, 3) == (3, 0)
    assert normalize_inspect_ref_cmp(2, 0, 0) == (0, 1)


def test_step_inspect_cmp_skips_reference() -> None:
    assert step_inspect_cmp(6, 0, 1, 1) == 2
    assert step_inspect_cmp(6, 0, 2, -1) == 1
    assert step_inspect_cmp(6, 2, 5, 1) == 0


def test_inspect_left_right_indices_respects_swap() -> None:
    assert inspect_left_right_indices(False, 0, 5) == (0, 5)
    assert inspect_left_right_indices(True, 0, 5) == (5, 0)


def test_pin_compare_as_new_reference_advances_compare() -> None:
    assert pin_compare_as_new_reference(6, 0, 3) == (3, 4)


def test_make_index_reference_long_press() -> None:
    assert make_index_reference(6, 0, 5, 2) == (2, 5)


def test_metadata_match_flags_exact_pair() -> None:
    left = DuplicateFile(path=Path("/a/file.jpg"), size=100, modified=1.0, extension="jpg", metadata={"hash": "abc"})
    right = DuplicateFile(path=Path("/b/file.jpg"), size=100, modified=1.0, extension="jpg", metadata={"hash": "abc"})
    rows = metadata_match_flags(left, right)
    assert rows[0][3] == "✓"
    assert rows[2][3] == "⚠"
