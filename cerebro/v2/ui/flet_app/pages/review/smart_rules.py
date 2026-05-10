from __future__ import annotations

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


_RULES = {
    "keep_largest":  lambda files: max(files, key=lambda f: f.size),
    "keep_smallest": lambda files: min(files, key=lambda f: f.size),
    "keep_newest":   lambda files: max(files, key=_mtime),
    "keep_oldest":   lambda files: min(files, key=_mtime),
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


def apply_rule(rule: str, files: List[DuplicateFile]) -> DuplicateFile:
    """Return the file to KEEP. Raises ValueError for unknown rule."""
    fn = _RULES.get(rule)
    if fn is None:
        raise ValueError(f"Unknown smart rule: {rule!r}")
    return fn(files)


def paths_to_delete(rule: str, files: List[DuplicateFile]) -> List[str]:
    """Return paths of all files except the keeper."""
    if len(files) < 2:
        return []
    keeper = apply_rule(rule, files)
    return [str(f.path) for f in files if f is not keeper]
