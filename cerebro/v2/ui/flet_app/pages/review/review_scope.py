"""Review-scope helpers for Workspace group filtering."""

from __future__ import annotations

from typing import Iterable, Set

from cerebro.engines.base_engine import DuplicateGroup

REVIEW_SCOPE_ALL = "all"
REVIEW_SCOPE_UNREVIEWED = "unreviewed"
REVIEW_SCOPE_REVIEWED = "reviewed"

REVIEW_SCOPE_LABELS: tuple[tuple[str, str, str], ...] = (
    (REVIEW_SCOPE_ALL, "All groups", "Every duplicate set in this scan"),
    (REVIEW_SCOPE_UNREVIEWED, "Unreviewed", "Groups you have not finished reviewing"),
    (REVIEW_SCOPE_REVIEWED, "Reviewed", "Groups marked as reviewed"),
)


def filter_groups_by_review_scope(
    groups: Iterable[DuplicateGroup],
    scope: str,
    *,
    reviewed_ids: Set[int],
    marked_paths: Set[str],
    smart_rule: str,
    keep_paths: Set[str],
) -> list[DuplicateGroup]:
    del marked_paths, smart_rule, keep_paths
    key = scope if scope in {s[0] for s in REVIEW_SCOPE_LABELS} else REVIEW_SCOPE_ALL
    out: list[DuplicateGroup] = []
    for g in groups:
        gid = int(g.group_id)
        reviewed = gid in reviewed_ids
        if key == REVIEW_SCOPE_ALL:
            out.append(g)
        elif key == REVIEW_SCOPE_UNREVIEWED:
            if not reviewed:
                out.append(g)
        elif key == REVIEW_SCOPE_REVIEWED and reviewed:
            out.append(g)
    return out
