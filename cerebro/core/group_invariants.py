"""
Shared group-level invariant checks for all active scan paths.

Extracted from cerebro/core/scanners/turbo_scanner.py at Phase 2d
(fix: 434fa7f ported to all paths) so that Paths A, B, C, and D
can all import the same guard without duplicating logic.

Strict mode:
    CEREBRO_STRICT=1   — guard raises AssertionError (tests, CI, dev runs)
    unset / empty      — guard logs warning and drops offending entry (default
                         production posture). ``CEREBRO_STRICT`` is evaluated on
                         each call so tests and shells can toggle without restart.
"""

from __future__ import annotations

import os
from typing import Tuple

from cerebro.services.logger import get_logger

logger = get_logger(__name__)


def _strict_enabled() -> bool:
    """Read on each call so tests (and shells) can toggle ``CEREBRO_STRICT``
    without restarting the interpreter."""
    return os.environ.get("CEREBRO_STRICT", "").lower() in ("1", "true", "yes")

# Defense-in-depth for Bug 1 (Phase 2c ``434fa7f``, 2026-04): catches self-duplicate
# groups that slip past ``dedupe_roots()`` (hardlinks, junctions, symlinks).
# Regression indicators: with DEBUG on ``turbo_scanner``, ``[DIAG:GUARD]``
# shows regressions > 0; with ``CEREBRO_STRICT=1``, scan raises during emit.
# Investigation: ``docs/bug-investigations/bug1-canonical-path-dedup.md``.


def _assert_no_self_duplicates(group: list, group_key: str = "?") -> Tuple[list, int]:
    """Regression guard: no emit-ready group may contain two entries resolving
    to the same canonical file.

    Phase 2a (dedupe_roots) fixes the root-overlap variant of Bug 1. This
    guard is defense-in-depth — catches any future regression where two paths
    resolve to the same inode through a mechanism dedupe_roots does not cover
    (hardlinks, junctions, symlinks, cross-drive aliases).

    Accepts heterogeneous group formats:
      - List of (path, mtime) tuples  — turbo_scanner (the sole live path)
      - List of Path objects          — accepted for historical callers

    Each item is returned as-is in the kept list; only the path is extracted
    for canonicalization.

    Strict mode (CEREBRO_STRICT=1): raises AssertionError with context.
    Default (unset): logs warning and drops the offending entry.

    Returns (kept_items, regression_count).
    """
    canonicals: dict = {}
    kept: list = []
    regressions = 0

    for item in group:
        # Extract path regardless of item format
        path = item[0] if isinstance(item, tuple) else item
        try:
            canonical = os.path.normcase(os.path.realpath(str(path)))
        except OSError as e:
            logger.warning("[GUARD] realpath failed for %s: %s — keeping as-is", path, e)
            kept.append(item)
            continue

        if canonical in canonicals:
            msg = (
                f"[GUARD] self-duplicate regression: group {group_key[:16]} "
                f"contains {path} resolving to {canonical}, already present "
                f"via {canonicals[canonical]}"
            )
            if _strict_enabled():
                raise AssertionError(msg)
            logger.warning(msg)
            regressions += 1
            continue

        canonicals[canonical] = str(path)
        kept.append(item)

    return kept, regressions
