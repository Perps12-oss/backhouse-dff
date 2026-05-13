"""Review-scope helpers for Workspace group filtering."""

from __future__ import annotations

from typing import Iterable, Set

from cerebro.engines.base_engine import DuplicateGroup

REVIEW_SCOPE_ALL = "all"
REVIEW_SCOPE_UNREVIEWED = "unreviewed"
REVIEW_SCOPE_REVIEWED = "reviewed"
REVIEW_SCOPE_IGNORED = "ignored"
REVIEW_SCOPE_OVERRIDES = "overrides"

REVIEW_SCOPE_LABELS: tuple[tuple[str, str, str], ...] = (
    (REVIEW_SCOPE_ALL, "All groups", "Every duplicate set in this scan"),
    (REVIEW_SCOPE_UNREVIEWED, "Unreviewed", "Groups you have not finished reviewing"),
    (REVIEW_SCOPE_REVIEWED, "Reviewed", "Groups marked as reviewed"),
    (REVIEW_SCOPE_IGNORED, "Ignored", "Groups you chose to skip for now"),
    (REVIEW_SCOPE_OVERRIDES, "Overrides", "Groups with manual marks that differ from the smart rule"),
)


def group_has_mark_overrides(
    group: DuplicateGroup,
    *,
    marked_paths: Set[str],
    smart_rule: str,
    keep_paths: Set[str],
) -> bool:
    for f in group.files:
        fp = str(f.path)
        implied_mark = fp not in keep_paths
        actual_mark = fp in marked_paths
        if implied_mark != actual_mark:
            return True
    return False


def filter_groups_by_review_scope(
    groups: Iterable[DuplicateGroup],
    scope: str,
    *,
    reviewed_ids: Set[int],
    ignored_ids: Set[int],
    marked_paths: Set[str],
    smart_rule: str,
    keep_paths: Set[str],
) -> list[DuplicateGroup]:
    key = scope if scope in {s[0] for s in REVIEW_SCOPE_LABELS} else REVIEW_SCOPE_ALL
    out: list[DuplicateGroup] = []
    for g in groups:
        gid = int(g.group_id)
        reviewed = gid in reviewed_ids
        ignored = gid in ignored_ids
        overrides = group_has_mark_overrides(
            g,
            marked_paths=marked_paths,
            smart_rule=smart_rule,
            keep_paths=keep_paths,
        )
        if key == REVIEW_SCOPE_ALL:
            out.append(g)
        elif key == REVIEW_SCOPE_UNREVIEWED:
            if not reviewed and not ignored:
                out.append(g)
        elif key == REVIEW_SCOPE_REVIEWED:
            if reviewed:
                out.append(g)
        elif key == REVIEW_SCOPE_IGNORED:
            if ignored:
                out.append(g)
        elif key == REVIEW_SCOPE_OVERRIDES and overrides:
            out.append(g)
    return out
