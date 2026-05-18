"""User-facing copy for browse/inspect rows (no Flet, no selection logic)."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List

from cerebro.engines.base_engine import DuplicateFile, DuplicateGroup


def duplicate_kind_label(similarity_type: str) -> str:
    st = (similarity_type or "").strip().lower()
    if st == "exact":
        return "Verified byte-identical"
    if st in {"visual", "image", "perceptual"}:
        return "Visually similar"
    return "Duplicate group"


def confidence_line(confidence: float) -> str:
    c = float(confidence or 0.0)
    if c >= 0.99:
        return "High confidence match"
    return f"Likely similar · {c:.0%} confidence"


def protected_skip_label() -> str:
    return "Skipped automatically — protected location"


def group_duplicate_summary(g: DuplicateGroup) -> str:
    n = len(g.files)
    sim = (getattr(g, "similarity_type", None) or "exact").lower()
    names = list(dict.fromkeys(Path(str(f.path)).name for f in g.files))
    if n < 2:
        return f"{n} file in this group"
    if sim == "exact":
        if len(names) == 1:
            return f'{n} byte-identical copies of "{names[0]}"'
        head = ", ".join(names[:3])
        tail = ", ..." if len(names) > 3 else ""
        return f"{n} byte-identical files · {head}{tail}"
    if len(names) == 1:
        return f'{n} similar matches for "{names[0]}"'
    head = ", ".join(names[:3])
    tail = ", ..." if len(names) > 3 else ""
    return f"{n} similar matches · {head}{tail}"


def is_machine_generated_name(name: str) -> bool:
    stem = Path(name).stem
    if len(stem) <= 40:
        return False
    digits = sum(1 for ch in stem if ch.isdigit())
    ratio = digits / max(1, len(stem))
    return ratio > 0.60 and bool(re.search(r"\d{8,}", stem))


def group_path_hint(files: List[DuplicateFile]) -> str:
    if not files:
        return ""
    paths = [Path(str(f.path)) for f in files]
    if len(paths) == 1:
        return str(paths[0].parent)
    parents = [p.parent for p in paths]
    uniq_parents = {str(p) for p in parents}
    names = list(dict.fromkeys(p.name for p in paths))
    if len(uniq_parents) == 1:
        if len(names) <= 3:
            return f"Same folder · {', '.join(names)}"
        return f"Same folder · {', '.join(names[:3])}... (+{len(names) - 3} names)"
    try:
        common = os.path.commonpath([str(p) for p in paths])
    except ValueError:
        bits = [f"{p.parent.name}/{p.name}" for p in paths[:3]]
        return " · ".join(dict.fromkeys(bits))
    rel_bits: list[str] = []
    for p in paths:
        try:
            rel_bits.append(os.path.relpath(str(p), common))
        except ValueError:
            rel_bits.append(str(p))
    head = ", ".join(dict.fromkeys(rel_bits[:3]))
    if len(rel_bits) > 3:
        head += f"... (+{len(rel_bits) - 3})"
    return f"Under {common} · {head}"
