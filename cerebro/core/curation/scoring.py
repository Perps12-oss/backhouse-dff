# path: cerebro/core/curation/scoring.py
"""
core/curation/scoring.py — CEREBRO Curation Scoring (v5)

Purpose:
- Assign a "story score" per item in each duplicate group.
- Higher score => more likely to be the survivor.

This is intentionally heuristic and explainable (no ML).
"""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any, Dict, List, Protocol, Tuple

from cerebro.core.models import PipelineRequest


class CancelToken(Protocol):
    def is_cancelled(self) -> bool: ...


_KEEP_TOKENS = ("final", "master", "approved", "best", "keep", "original")
_GHOST_TOKENS = ("copy", "duplicate", "backup", "temp", "export", "edited", "edit", "tmp")

_COPY_PATTERNS = (
    re.compile(r"\(\d+\)$"),   # name(1)
    re.compile(r"\s-\s*copy$"), # name - copy
    re.compile(r"\scopy$"),      # name copy
)


def _norm_name(p: Path) -> str:
    return p.stem.lower().strip()


def _token_score(name: str) -> float:
    s = 0.0
    for t in _KEEP_TOKENS:
        if t in name:
            s += 2.0
    for t in _GHOST_TOKENS:
        if t in name:
            s -= 2.0
    for pat in _COPY_PATTERNS:
        if pat.search(name):
            s -= 1.5
    return s


def _safe_get(obj: Any, attr: str, default: Any = None) -> Any:
    try:
        return getattr(obj, attr, default)
    except Exception:
        return default


def _size_bytes(item: Any) -> int:
    v = _safe_get(item, "size_bytes", None)
    if v is None:
        v = _safe_get(item, "size", 0)
    try:
        return int(v)
    except Exception:
        return 0


def _mtime(item: Any) -> float:
    v = _safe_get(item, "mtime", None)
    if v is not None:
        try:
            return float(v)
        except Exception:
            return 0.0
    v = _safe_get(item, "mtime_ns", None)
    try:
        return float(v) / 1_000_000_000.0
    except Exception:
        return 0.0


def _rank(values: List[float], *, higher_is_better: bool) -> List[float]:
    if not values:
        return []
    order = sorted(range(len(values)), key=lambda i: values[i], reverse=higher_is_better)
    ranks = [0.0] * len(values)
    denom = max(1, len(values) - 1)
    for pos, i in enumerate(order):
        ranks[i] = 1.0 - (pos / denom)  # best -> 1.0, worst -> 0.0
    return ranks


class ScoringEngine:
    """Concrete scoring port used by the pipeline."""

    def score(self, groups: List[Any], request: PipelineRequest, cancel: CancelToken) -> List[Any]:
        intent = (request.scan_intent or "").lower()
        nostalgic = "nostalgic" in intent
        evidentiary = any(k in intent for k in ("precious", "meticulous", "forensic"))

        for g in groups:
            if cancel.is_cancelled():
                break

            items = list(_safe_get(g, "items", []) or [])
            if len(items) < 2:
                continue

            sizes = [float(_size_bytes(it)) for it in items]
            mtimes = [_mtime(it) for it in items]

            size_rank = _rank(sizes, higher_is_better=True)
            time_rank = _rank(mtimes, higher_is_better=(not nostalgic))  # nostalgic prefers older

            for idx, it in enumerate(items):
                name = _norm_name(Path(_safe_get(it, "path")))
                s = 0.0

                # Relative quality signals
                s += 3.0 * size_rank[idx]
                s += 1.0 * time_rank[idx]

                # Semantic filename signals
                s += _token_score(name)

                # Enrichment signals (best-effort)
                exif_intact = _safe_get(it, "exif_intact", None)
                has_gps = _safe_get(it, "has_gps", None)
                if exif_intact is True:
                    s += 1.0
                elif exif_intact is False and evidentiary:
                    s -= 0.5

                if has_gps is True:
                    s += 0.3

                # Evidentiary mode makes ghost penalties bite harder
                if evidentiary and _token_score(name) < 0:
                    s -= 0.5

                # Store
                try:
                    setattr(it, "score", float(s))
                except Exception:
                    pass

                # Optional label for UI/debug
                try:
                    if _token_score(name) >= 2:
                        setattr(it, "label", "keeper:semantic")
                    elif _token_score(name) <= -2:
                        setattr(it, "label", "ghost:semantic")
                except Exception:
                    pass

        return groups


__all__ = ["ScoringEngine"]
