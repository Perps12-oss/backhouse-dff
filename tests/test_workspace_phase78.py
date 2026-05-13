"""Phase 7–8 workspace helpers: review scope, smart-rule pipeline, undo."""

from __future__ import annotations

from pathlib import Path

from cerebro.engines.base_engine import DuplicateFile, DuplicateGroup
from cerebro.v2.ui.flet_app.pages.review.review_scope import (
    REVIEW_SCOPE_UNREVIEWED,
    filter_groups_by_review_scope,
)
from cerebro.v2.ui.flet_app.pages.review.review_session_undo import ReviewSessionUndo
from cerebro.v2.ui.flet_app.pages.review.smart_rules import apply_rule_with_pipeline


def _group() -> DuplicateGroup:
    return DuplicateGroup(
        group_id=1,
        files=[
            DuplicateFile(path=Path("a/final.jpg"), size=10, modified=0.0, extension=".jpg"),
            DuplicateFile(path=Path("b/copy.jpg"), size=10, modified=0.0, extension=".jpg"),
        ],
        similarity_type="exact",
    )


def test_review_scope_unreviewed_filters_reviewed_groups() -> None:
    g = _group()
    groups = filter_groups_by_review_scope(
        [g],
        REVIEW_SCOPE_UNREVIEWED,
        reviewed_ids=set(),
        ignored_ids=set(),
        marked_paths=set(),
        smart_rule="keep_largest",
        keep_paths=set(),
    )
    assert groups == [g]
    reviewed = filter_groups_by_review_scope(
        [g],
        REVIEW_SCOPE_UNREVIEWED,
        reviewed_ids={1},
        ignored_ids=set(),
        marked_paths=set(),
        smart_rule="keep_largest",
        keep_paths=set(),
    )
    assert reviewed == []


def test_filename_regex_pipeline_keeps_matching_name() -> None:
    g = _group()
    keeper = apply_rule_with_pipeline("keep_largest", list(g.files), filename_regex=r"final")
    assert keeper.path.name == "final.jpg"


def test_review_session_undo_restores_snapshot() -> None:
    log = ReviewSessionUndo()
    log.record(
        marked_paths={"x"},
        reviewed_group_ids={1},
        ignored_group_ids={2},
        override_paths={"y"},
    )
    frame = log.pop()
    assert frame is not None
    assert frame.marked_paths == frozenset({"x"})
    assert frame.reviewed_group_ids == frozenset({1})
    assert frame.ignored_group_ids == frozenset({2})
    assert frame.override_paths == frozenset({"y"})
