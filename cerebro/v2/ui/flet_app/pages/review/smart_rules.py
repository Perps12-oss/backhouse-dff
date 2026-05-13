from __future__ import annotations

import re
from pathlib import Path
from typing import List

from cerebro.engines.base_engine import DuplicateFile


def _mtime(f: DuplicateFile) -> float:
    for attr in ("mtime", "modified"):
        v = getattr(f, attr, None)
        if v is None:
            continue
        try:
            return float(v)
        except (TypeError, ValueError):
            continue
    return 0.0


def _keep_first(files: List[DuplicateFile]) -> DuplicateFile:
    if not files:
        raise ValueError("keep_first requires at least one file")
    return files[0]


_RULES = {
    "keep_largest":  lambda files: max(files, key=lambda f: f.size),
    "keep_smallest": lambda files: min(files, key=lambda f: f.size),
    "keep_newest":   lambda files: max(files, key=_mtime),
    "keep_oldest":   lambda files: min(files, key=_mtime),
    "keep_first":    _keep_first,
}

KNOWN_RULES = frozenset(_RULES.keys())


def normalized_rule(rule: str) -> str:
    """Return a rule key accepted by ``paths_to_delete`` / ``apply_rule``."""
    r = (rule or "").strip()
    return r if r in KNOWN_RULES else "keep_largest"

RULE_LABELS = [
    ("keep_largest",  "Keep Largest"),
    ("keep_smallest", "Keep Smallest"),
    ("keep_newest",   "Keep Newest"),
    ("keep_oldest",   "Keep Oldest"),
]

# Deletion settings auto-mark: same four rules plus list-order keeper (not shown on Review segmented control).
AUTO_MARK_RULE_OPTIONS = [*RULE_LABELS, ("keep_first", "Keep First")]


def apply_rule(rule: str, files: List[DuplicateFile]) -> DuplicateFile:
    """Return the file to KEEP. Raises ValueError for unknown rule."""
    fn = _RULES.get(rule)
    if fn is None:
        raise ValueError(f"Unknown smart rule: {rule!r}")
    return fn(files)


def keeper_from_filename_regex(regex: str, files: List[DuplicateFile]) -> DuplicateFile | None:
    pattern = (regex or "").strip()
    if not pattern:
        return None
    try:
        compiled = re.compile(pattern, re.IGNORECASE)
    except re.error:
        return None
    for f in files:
        if compiled.search(Path(str(f.path)).name):
            return f
    return None


def apply_rule_with_pipeline(
    rule: str,
    files: List[DuplicateFile],
    *,
    filename_regex: str = "",
) -> DuplicateFile:
    """Apply optional filename regex keeper before attribute smart rules."""
    pre = keeper_from_filename_regex(filename_regex, files)
    if pre is not None:
        return pre
    return apply_rule(rule, files)


def paths_to_delete(rule: str, files: List[DuplicateFile]) -> List[str]:
    """Return paths of all files except the keeper."""
    if len(files) < 2:
        return []
    keeper = apply_rule(rule, files)
    return [str(f.path) for f in files if f is not keeper]
