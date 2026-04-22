# path: cerebro/core/root_dedup.py
from __future__ import annotations

from pathlib import Path
import logging

log = logging.getLogger(__name__)


def dedupe_roots(roots: list[Path]) -> list[Path]:
    """Collapse roots that are descendants of other roots.

    When the user specifies both a parent and a child folder as scan roots,
    the child is fully covered by the parent's recursive walk. Including both
    causes double-enumeration of every file under the child, inflating
    downstream counts.

    Returns a list of roots with no root being a descendant of any other root
    in the list.

    Bug 1 (root overlap) — Phase 2a fix ``b0e94d6`` (2026-04, post-v1 audit).
    Regression indicators: missing ``[ROOT_DEDUP]`` lines when the user passes
    overlapping roots; discovery / candidate counts that jump non-monotonically
    vs. a build without ``dedupe_roots``. Investigation:
    ``docs/bug-investigations/bug1-canonical-path-dedup.md``.
    """
    resolved = sorted(
        {Path(r).resolve() for r in roots},
        key=lambda p: len(str(p)),
    )
    kept: list[Path] = []
    for r in resolved:
        if any(
            _is_relative_to(r, k) and r != k
            for k in kept
        ):
            log.info(
                "[ROOT_DEDUP] collapsing %s into parent root (already covered)",
                r,
            )
            continue
        kept.append(r)

    if len(kept) < len(resolved):
        log.info(
            "[ROOT_DEDUP] %d roots → %d after dedup",
            len(resolved), len(kept),
        )
    return kept


def _is_relative_to(child: Path, parent: Path) -> bool:
    """Python <3.9 compatible Path.is_relative_to."""
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False
