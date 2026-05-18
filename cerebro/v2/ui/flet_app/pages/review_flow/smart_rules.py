"""Pure smart-selection rule engine (no Flet, no Review v1 UI)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional

from cerebro.engines.base_engine import DuplicateFile

# Compiled once at module level — matches copy-like filename suffixes.
_COPY_PATTERN = re.compile(r'\s*\(\d+\)|\bcopy\b|copy\s+of\b', re.IGNORECASE)


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


def _avoid_copy(files: List[DuplicateFile]) -> DuplicateFile:
    originals = [f for f in files if not _COPY_PATTERN.search(Path(str(f.path)).name)]
    pool = originals if originals else files
    return max(pool, key=lambda f: int(getattr(f, "size", 0) or 0))


def _keep_shortest_path(files: List[DuplicateFile]) -> DuplicateFile:
    return min(files, key=lambda f: len(str(f.path)))


_RULES = {
    "keep_largest": lambda files: max(files, key=lambda f: f.size),
    "keep_smallest": lambda files: min(files, key=lambda f: f.size),
    "keep_newest": lambda files: max(files, key=_mtime),
    "keep_oldest": lambda files: min(files, key=_mtime),
    "keep_shortest_path": _keep_shortest_path,
    "avoid_copy": _avoid_copy,
    "keep_first": _keep_first,
}

KNOWN_RULES = frozenset(_RULES.keys())


def normalized_rule(rule: str) -> str:
    """Return a rule key accepted by ``paths_to_delete`` / ``apply_rule``."""
    r = (rule or "").strip()
    return r if r in KNOWN_RULES else "keep_largest"


RULE_LABELS = [
    ("keep_newest", "Keep Newest"),
    ("keep_oldest", "Keep Oldest"),
    ("keep_largest", "Keep Largest"),
    ("keep_smallest", "Keep Smallest"),
    ("keep_shortest_path", "Keep Shortest Path"),
    ("avoid_copy", 'Avoid "(1)" & "Copy"'),
]

# Deletion settings auto-mark: same rules plus list-order keeper.
AUTO_MARK_RULE_OPTIONS = [*RULE_LABELS, ("keep_first", "Keep First")]


def apply_rule(rule: str, files: List[DuplicateFile]) -> DuplicateFile:
    """Return the file to KEEP. Raises ValueError for unknown rule."""
    fn = _RULES.get(rule)
    if fn is None:
        raise ValueError(f"Unknown smart rule: {rule!r}")
    return fn(files)


def keeper_from_filename_regex(regex: str, files: List[DuplicateFile]) -> Optional[DuplicateFile]:
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


_KEEP_REASONS: dict[str, str] = {
    "keep_newest": "Kept: Newest modified version",
    "keep_oldest": "Kept: Oldest version",
    "keep_largest": "Kept: Largest file",
    "keep_smallest": "Kept: Smallest file",
    "keep_shortest_path": "Kept: Shortest path",
    "avoid_copy": "Kept: Cleanest filename",
    "keep_first": "Kept: First in list",
}

_SELECT_REASONS: dict[str, str] = {
    "keep_newest": "Selected: Older than newest",
    "keep_oldest": "Selected: Newer than oldest",
    "keep_largest": "Selected: Smaller than largest",
    "keep_smallest": "Selected: Larger than smallest",
    "keep_shortest_path": "Selected: Longer path",
    "avoid_copy": "Selected: Copy-like filename",
    "keep_first": "Selected: Lower list position",
}


def get_selection_reason(rule: str, file_path: str, keeper_path: str) -> str:
    """Return a short human-readable reason label for a file's KEPT/SELECTED status."""
    if file_path == keeper_path:
        return _KEEP_REASONS.get(rule, "Kept")
    if rule == "avoid_copy":
        name = Path(file_path).name
        if _COPY_PATTERN.search(name):
            return 'Selected: Copy-like filename pattern'
    return _SELECT_REASONS.get(rule, "Selected")
