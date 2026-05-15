"""Trust-oriented copy and short “why” strings for the review flow (v0)."""

from __future__ import annotations

from cerebro.engines.base_engine import DuplicateFile, DuplicateGroup
from cerebro.v2.ui.flet_app.pages.review.smart_rules import RULE_LABELS, normalized_rule, paths_to_delete


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


def smart_rule_label(rule_key: str) -> str:
    r = normalized_rule(rule_key)
    for key, label in RULE_LABELS:
        if key == r:
            return label
    return r


def selection_reason_for_file(
    group: DuplicateGroup,
    file: DuplicateFile,
    *,
    smart_rule_key: str,
) -> str:
    """One-line explanation for file row when marked vs not (relative to current smart rule)."""
    if not group.files or len(group.files) < 2:
        return "Single file in group — nothing to compare."
    r = normalized_rule(smart_rule_key)
    to_delete = set(paths_to_delete(r, group.files))
    p = str(file.path)
    if p in to_delete:
        return f"Smart rule ({smart_rule_label(r)}): this copy is not the keeper."
    if to_delete:
        return f"Kept by smart rule ({smart_rule_label(r)})."
    return "Not targeted by the current smart rule — adjust checkbox if needed."


def protected_skip_label() -> str:
    return "Skipped automatically — protected location"
