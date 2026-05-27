"""Simple-review selection contract: snapshots, validity, transactions, survivor checks."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, List, Literal, Optional, Tuple

from cerebro.engines.base_engine import DuplicateGroup

if TYPE_CHECKING:
    from cerebro.v2.ui.flet_app.pages.review_flow.state import ReviewFlowState

SelectionOrigin = Literal["auto_rule", "manual_review", "mixed"]
SelectionValidity = Literal["valid", "invalidated_scope"]
SelectionTransactionState = Literal["idle", "recomputing", "preparing_delete", "deleting"]
SnapshotCheckResult = Literal["valid", "invalidated_scope", "missing"]


@dataclass(frozen=True)
class SurvivorValidationResult:
    ok: bool
    violating_group_ids: Tuple[int, ...] = ()


@dataclass
class MarkSnapshot:
    """Persisted context for when marks were last authoritative."""

    scan_id: str
    universe_fingerprint: str
    filter_fingerprint: str
    selection_rule: Optional[str]
    selection_origin: SelectionOrigin
    cart_delete_count: int
    cart_delete_bytes: int
    marked_path_count: int = 0
    media_filter_enabled: bool = False
    media_type: str = "pictures"


def compute_scan_id(groups: List[DuplicateGroup]) -> str:
    """Stable identity for the current scan result set."""
    if not groups:
        return ""
    h = hashlib.sha256()
    for g in sorted(groups, key=lambda x: int(x.group_id)):
        h.update(f"g:{g.group_id}:".encode())
        for f in sorted(g.files, key=lambda x: str(x.path)):
            h.update(str(f.path).encode())
            h.update(b"|")
    return h.hexdigest()[:16]


def compute_filter_fingerprint(state: "ReviewFlowState") -> str:
    """Fingerprint of filters that change the visible candidate universe."""
    parts = (
        state.text_filter.strip().lower(),
        frozenset(state.type_filter),
        state.min_size_bytes,
        state.max_size_bytes,
        state.similarity_min,
        state.active_tag_filter.strip().lower(),
        state.selection_media_filter_enabled,
        normalized_media_type_key(state.selection_media_type),
        tuple(sorted(state.protected_path_prefixes)),
    )
    raw = repr(parts).encode()
    return hashlib.sha256(raw).hexdigest()[:16]


def normalized_media_type_key(media_type: str) -> str:
    from cerebro.v2.ui.flet_app.pages.review_flow.media_filter import normalized_media_type

    return normalized_media_type(media_type)


def compute_universe_fingerprint(state: "ReviewFlowState") -> str:
    scan_id = state.scan_id or compute_scan_id(state.scan_results)
    fp = compute_filter_fingerprint(state)
    return f"{scan_id}:{fp}"


def capture_mark_snapshot(state: "ReviewFlowState", *, rule: Optional[str]) -> MarkSnapshot:
    """Record authoritative marks for the current universe."""
    return MarkSnapshot(
        scan_id=state.scan_id or compute_scan_id(state.scan_results),
        universe_fingerprint=compute_universe_fingerprint(state),
        filter_fingerprint=compute_filter_fingerprint(state),
        selection_rule=rule,
        selection_origin=state.selection_origin,
        cart_delete_count=state.cart_delete_count,
        cart_delete_bytes=state.cart_delete_bytes,
        marked_path_count=len(state.marked_paths),
        media_filter_enabled=state.selection_media_filter_enabled,
        media_type=normalized_media_type_key(state.selection_media_type),
    )


def check_mark_snapshot(state: "ReviewFlowState") -> SnapshotCheckResult:
    snap = state.mark_snapshot
    if snap is None:
        return "missing"
    current_scan = state.scan_id or compute_scan_id(state.scan_results)
    if snap.scan_id != current_scan:
        return "invalidated_scope"
    if snap.universe_fingerprint != compute_universe_fingerprint(state):
        return "invalidated_scope"
    return "valid"


def validate_survivor_invariant(state: "ReviewFlowState") -> SurvivorValidationResult:
    """Every group with 2+ pool files must have >= 1 unmarked survivor."""
    bad: list[int] = []
    for g in state.scan_results:
        pool = state.selection_pool(g)
        if len(pool) <= 1:
            continue
        if state.unmarked_survivor_count(g) < 1:
            bad.append(int(g.group_id))
    return SurvivorValidationResult(ok=not bad, violating_group_ids=tuple(bad))


def provenance_label(state: "ReviewFlowState") -> str:
    n = state.displayed_cart_delete_count
    origin = state.selection_origin
    rule = state.selection_rule
    rule_part = ""
    if rule:
        from cerebro.v2.ui.flet_app.pages.review_flow.smart_rules import RULE_LABELS

        label = next((lbl for k, lbl in RULE_LABELS if k == rule), rule.replace("_", " "))
        rule_part = f" using {label}"
    if origin == "auto_rule":
        base = f"{n:,} marked{rule_part}"
    elif origin == "manual_review":
        base = f"{n:,} marked — manually adjusted"
    else:
        base = f"{n:,} marked — mixed auto + manual"
    if state.selection_validity == "invalidated_scope":
        return f"{base} — out of date for current filters"
    return base


def selection_controls_frozen(state: "ReviewFlowState") -> bool:
    return state.selection_transaction_state != "idle"


def delete_preparation_allowed(state: "ReviewFlowState") -> bool:
    """Gate for opening delete confirm (simple mode will use this in Phase 1+)."""
    if state.selection_transaction_state != "idle":
        return False
    if state.selection_validity != "valid":
        return False
    if state.cart_delete_count <= 0:
        return False
    return validate_survivor_invariant(state).ok


def marks_need_auto_apply_on_open(state: "ReviewFlowState") -> bool:
    """True only when explicit auto-apply on Review open is allowed (not after scope invalidation)."""
    if state.selection_validity == "invalidated_scope":
        return False
    check = check_mark_snapshot(state)
    if check == "valid":
        return False
    if check == "invalidated_scope":
        return False
    return check == "missing"


def format_scope_change_hint(
    previous: MarkSnapshot,
    state: "ReviewFlowState",
) -> str:
    """Human-readable hint when universe fingerprint changes."""
    from cerebro.v2.ui.flet_app.pages.review_flow.media_filter import SELECTION_MEDIA_TYPES

    def _label(enabled: bool, media: str) -> str:
        if not enabled:
            return "All files"
        return next((lbl for k, lbl in SELECTION_MEDIA_TYPES if k == media), media.title())

    prev_label = _label(previous.media_filter_enabled, previous.media_type)
    cur_label = _label(state.selection_media_filter_enabled, normalized_media_type_key(state.selection_media_type))
    if prev_label != cur_label:
        return f"Media filter changed: {prev_label} → {cur_label}"
    if previous.filter_fingerprint != compute_filter_fingerprint(state):
        return "Filters changed"
    return "Scan or scope changed"
