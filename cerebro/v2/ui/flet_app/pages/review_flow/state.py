from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Literal, Optional, Set, Tuple

from cerebro.engines.base_engine import DuplicateFile, DuplicateGroup
from cerebro.v2.ui.flet_app.pages.review_flow.media_filter import (
    file_media_bucket,
    normalized_media_type,
)
from cerebro.v2.ui.flet_app.pages.review_flow.selection_contract import (
    MarkSnapshot,
    SelectionOrigin,
    SelectionTransactionState,
    SelectionValidity,
    SnapshotCheckResult,
    SurvivorValidationResult,
    capture_mark_snapshot,
    check_mark_snapshot,
    compute_scan_id,
    compute_universe_fingerprint,
    delete_preparation_allowed,
    format_scope_change_hint,
    marks_need_auto_apply_on_open,
    provenance_label,
    selection_controls_frozen,
    validate_survivor_invariant,
)

ReviewScreen = Literal["overview", "browse", "inspect"]
BrowseViewMode = Literal["list", "grid", "tree", "folder_diff"]


@dataclass
class SetSelection:
    kept_paths: Set[str] = field(default_factory=set)
    deleted_paths: Set[str] = field(default_factory=set)
    protected_paths: Set[str] = field(default_factory=set)


@dataclass
class ReviewFlowState:
    active_screen: ReviewScreen = "overview"
    screen_stack: List[ReviewScreen] = field(default_factory=lambda: ["overview"])
    scan_results: List[DuplicateGroup] = field(default_factory=list)
    scan_mode: str = "files"
    selected_set_ids: Set[int] = field(default_factory=set)
    expanded_set_ids: Set[int] = field(default_factory=set)
    marked_paths: Set[str] = field(default_factory=set)
    set_selections: Dict[int, SetSelection] = field(default_factory=dict)
    browse_detail_group_id: Optional[int] = None
    browse_focus_index: int = 0
    browse_scroll_offset: int = 0
    inspect_set_id: Optional[int] = None
    # Side-by-side: semantic reference (pinned) vs compare (challenger). Invariant ref != cmp when n >= 2.
    inspect_ref_index: int = 0
    inspect_cmp_index: int = 1
    inspect_swap_panels: bool = False
    # Per duplicate set: (ref_index, cmp_index, swap_panels) for Browse ↔ Inspect continuity.
    inspect_layout_by_set_id: Dict[int, Tuple[int, int, bool]] = field(default_factory=dict)
    view_mode: BrowseViewMode = "list"
    sort_key: str = "size"
    sort_desc: bool = True
    dry_run: bool = False  # Dev/tests: host may treat CEREBRO_REVIEW_SIMULATE_APPLY as simulate-only
    execute_confirmed: bool = False
    execute_progress: Tuple[int, int] = (0, 0)
    execute_errors: List[str] = field(default_factory=list)
    execute_failures_detail: List[Tuple[str, str]] = field(default_factory=list)
    report_deleted_count: int = 0
    report_freed_bytes: int = 0
    tags_by_set: Dict[int, Set[str]] = field(default_factory=dict)
    notes_by_set: Dict[int, str] = field(default_factory=dict)
    protected_path_prefixes: Tuple[str, ...] = field(default_factory=tuple)
    undo_stack: List[Dict[str, object]] = field(default_factory=list)
    redo_stack: List[Dict[str, object]] = field(default_factory=list)
    # Smart Select — tracks which rule key was last applied per group (cleared on manual toggle).
    smart_rule_by_group: Dict[int, str] = field(default_factory=dict)
    text_filter: str = ""
    type_filter: Set[str] = field(default_factory=set)
    min_size_bytes: int = 0
    max_size_bytes: int = 0
    similarity_min: float = 0.0
    inspect_diff_enabled: bool = False
    inspect_blink_enabled: bool = False
    active_tag_filter: str = ""
    # When enabled, deletion marks and smart-select only affect files in selection_media_type.
    selection_media_filter_enabled: bool = False
    selection_media_type: str = "pictures"
    # Phase 3.2 — pagination
    page_index: int = 0
    page_size: int = 200
    # 1.3 — incremental cart counters
    cart_delete_count: int = 0
    cart_keep_count: int = 0
    cart_protected_count: int = 0
    cart_delete_bytes: int = 0
    # Simple review — selection contract (Phase 0)
    scan_id: str = ""
    mark_snapshot: Optional[MarkSnapshot] = None
    selection_origin: SelectionOrigin = "auto_rule"
    selection_rule: Optional[str] = None
    selection_validity: SelectionValidity = "valid"
    selection_transaction_state: SelectionTransactionState = "idle"
    scope_invalidation_hint: str = ""
    displayed_cart_delete_count: int = 0
    displayed_cart_delete_bytes: int = 0
    # Phase 3 — entered Browse from Simple summary ("Review details"); lighter chrome + Summary labels.
    simple_browse_session: bool = False
    # 1.1 — visible_groups() memoization cache (hidden from repr/eq)
    _visible_cache_key: object = field(default=None, repr=False, compare=False)
    _visible_cache_val: list = field(default_factory=list, repr=False, compare=False)
    # 1.2 — O(1) group lookup index (hidden from repr/eq)
    _group_index: dict = field(default_factory=dict, repr=False, compare=False)

    def file_in_selection_media_scope(self, f: DuplicateFile) -> bool:
        if not self.selection_media_filter_enabled:
            return True
        return file_media_bucket(f) == normalized_media_type(self.selection_media_type)

    def group_has_selection_media_files(self, group: DuplicateGroup) -> bool:
        """True when the group contains at least one file in the active media filter bucket."""
        if not self.selection_media_filter_enabled:
            return True
        return any(self.file_in_selection_media_scope(f) for f in group.files)

    def prune_marks_outside_media_scope(self) -> None:
        """Drop deletion marks on files outside the active media filter."""
        if not self.selection_media_filter_enabled:
            return
        for g in self.scan_results:
            sel = self.set_selections.get(g.group_id)
            for f in g.files:
                if self.file_in_selection_media_scope(f):
                    continue
                p = str(f.path)
                self.marked_paths.discard(p)
                if sel:
                    sel.deleted_paths.discard(p)

    def visible_groups(self) -> List[DuplicateGroup]:
        # 1.1 — memoization cache check
        cache_key = (
            len(self.scan_results),
            self.text_filter,
            frozenset(self.type_filter),
            self.min_size_bytes,
            self.max_size_bytes,
            self.similarity_min,
            self.active_tag_filter,
            self.selection_media_filter_enabled,
            self.selection_media_type,
            self.sort_key,
            self.sort_desc,
        )
        if cache_key == self._visible_cache_key:
            return list(self._visible_cache_val)

        groups = list(self.scan_results)
        if self.text_filter.strip():
            q = self.text_filter.strip().lower()
            groups = [
                g
                for g in groups
                if any(q in str(f.path).lower() or q in str(f.path.name).lower() for f in g.files)
            ]
        if self.type_filter:
            groups = [
                g
                for g in groups
                if any((f.extension or "").lower().lstrip(".") in self.type_filter for f in g.files)
            ]
        if self.min_size_bytes or self.max_size_bytes:
            lo = self.min_size_bytes
            hi = self.max_size_bytes or 10**15
            groups = [g for g in groups if any(lo <= int(f.size) <= hi for f in g.files)]
        if self.similarity_min > 0:
            groups = [
                g
                for g in groups
                if any(float(getattr(f, "similarity", 1.0) or 1.0) >= self.similarity_min for f in g.files)
            ]
        if self.active_tag_filter:
            tag = self.active_tag_filter.strip().lower()
            groups = [g for g in groups if tag in {t.lower() for t in self.tags_by_set.get(g.group_id, set())}]
        if self.selection_media_filter_enabled:
            groups = [g for g in groups if self.group_has_selection_media_files(g)]
        key = self.sort_key
        reverse = self.sort_desc

        def sort_val(g: DuplicateGroup) -> object:
            if key == "count":
                return len(g.files)
            if key == "name":
                return str(g.files[0].path.name).lower() if g.files else ""
            if key == "confidence":
                return max(float(getattr(f, "similarity", 1.0) or 1.0) for f in g.files) if g.files else 0.0
            return int(getattr(g, "reclaimable", 0) or 0)

        result = sorted(groups, key=sort_val, reverse=reverse)
        self._visible_cache_key = cache_key
        self._visible_cache_val = result
        return result

    # 1.1 — cache invalidation
    def invalidate_visible_cache(self) -> None:
        self._visible_cache_key = None
        self._visible_cache_val = []

    # 1.2 — O(1) group index
    def rebuild_group_index(self) -> None:
        self._group_index = {g.group_id: g for g in self.scan_results}

    def group_by_id(self, group_id: int) -> Optional[DuplicateGroup]:
        if self._group_index:
            return self._group_index.get(group_id)
        return next((g for g in self.scan_results if g.group_id == group_id), None)

    # 1.3 — incremental cart counters
    def _recompute_cart_counters(self) -> None:
        dc = kc = pc = db = 0
        for g in self.scan_results:
            sel = self.set_selections.get(g.group_id)
            for f in g.files:
                path = str(f.path)
                size = int(getattr(f, "size", 0) or 0)
                in_scope = self.file_in_selection_media_scope(f)
                if sel and path in sel.protected_paths:
                    if in_scope:
                        pc += 1
                elif in_scope and (path in self.marked_paths or (sel and path in sel.deleted_paths)):
                    dc += 1
                    db += size
                elif in_scope and sel and path in sel.kept_paths:
                    kc += 1
        self.cart_delete_count = dc
        self.cart_keep_count = kc
        self.cart_protected_count = pc
        self.cart_delete_bytes = db
        if self.selection_validity == "valid":
            self.displayed_cart_delete_count = dc
            self.displayed_cart_delete_bytes = db

    def sync_scan_id(self) -> None:
        """Refresh scan_id from current scan_results."""
        self.scan_id = compute_scan_id(self.scan_results)

    def universe_fingerprint(self) -> str:
        if not self.scan_id:
            self.sync_scan_id()
        return compute_universe_fingerprint(self)

    def check_mark_snapshot(self) -> SnapshotCheckResult:
        return check_mark_snapshot(self)

    def marks_need_auto_apply_on_open(self) -> bool:
        return marks_need_auto_apply_on_open(self)

    def selection_frozen(self) -> bool:
        return selection_controls_frozen(self)

    def delete_preparation_allowed(self) -> bool:
        return delete_preparation_allowed(self)

    def validate_survivor_invariant(self) -> SurvivorValidationResult:
        return validate_survivor_invariant(self)

    def provenance_label(self) -> str:
        return provenance_label(self)

    def finalize_rule_recompute(self, rule: str) -> None:
        """Complete rule Apply: update provenance and capture snapshot."""
        if self.selection_origin == "manual_review":
            origin: SelectionOrigin = "mixed"
        elif self.selection_origin == "mixed":
            origin = "mixed"
        else:
            origin = "auto_rule"
        self.end_selection_recompute(rule=rule, origin=origin)

    def begin_selection_recompute(self) -> None:
        self.selection_transaction_state = "recomputing"

    def end_selection_recompute(self, *, rule: Optional[str], origin: SelectionOrigin) -> None:
        self.selection_rule = rule
        self.selection_origin = origin
        self.selection_validity = "valid"
        self.scope_invalidation_hint = ""
        self.mark_snapshot = capture_mark_snapshot(self, rule=rule)
        self.selection_transaction_state = "idle"
        for g in self.scan_results:
            self.clamp_group_to_single_survivor(g)
        self._recompute_cart_counters()

    def begin_delete_preparation(self) -> bool:
        """Transition to preparing_delete if delete is allowed."""
        if not self.delete_preparation_allowed():
            return False
        self.selection_transaction_state = "preparing_delete"
        return True

    def begin_delete_execution(self) -> bool:
        """Transition to deleting after confirm if survivor invariant holds."""
        if self.selection_transaction_state != "preparing_delete":
            return False
        if not validate_survivor_invariant(self).ok:
            return False
        self.selection_transaction_state = "deleting"
        return True

    def finish_delete_transaction(self) -> None:
        self.selection_transaction_state = "idle"

    def cancel_delete_preparation(self) -> None:
        if self.selection_transaction_state == "preparing_delete":
            self.selection_transaction_state = "idle"

    def note_manual_selection_edit(self) -> None:
        if self.selection_origin == "auto_rule":
            self.selection_origin = "manual_review"
        elif self.selection_origin == "manual_review":
            pass
        else:
            self.selection_origin = "mixed"

    def invalidate_selection_for_scope_change(self, *, hint: str = "") -> None:
        """Universe changed — marks need explicit re-apply; keep displayed totals."""
        if self.mark_snapshot is not None:
            self.displayed_cart_delete_count = self.mark_snapshot.cart_delete_count
            self.displayed_cart_delete_bytes = self.mark_snapshot.cart_delete_bytes
            if not hint:
                hint = format_scope_change_hint(self.mark_snapshot, self)
        else:
            self.displayed_cart_delete_count = self.cart_delete_count
            self.displayed_cart_delete_bytes = self.cart_delete_bytes
        self.selection_validity = "invalidated_scope"
        self.scope_invalidation_hint = hint

    def on_scan_results_replaced(self) -> None:
        """Call when scan_results identity changes (new scan or full reload)."""
        prev = self.mark_snapshot
        self.sync_scan_id()
        if prev is None:
            self.selection_validity = "valid"
            self.scope_invalidation_hint = ""
            return
        if prev.scan_id != self.scan_id:
            self.mark_snapshot = None
            self.selection_validity = "valid"
            self.scope_invalidation_hint = ""
            self.displayed_cart_delete_count = 0
            self.displayed_cart_delete_bytes = 0
            return
        self.invalidate_selection_for_scope_change(hint="Scan results updated")

    def on_scope_fingerprint_changed(self, previous_fp: str) -> None:
        """Call after filter/media/exclude mutation when fingerprint differs."""
        new_fp = self.universe_fingerprint()
        if previous_fp == new_fp:
            return
        self.invalidate_selection_for_scope_change()

    def clear_selection_contract_for_empty_scan(self) -> None:
        self.mark_snapshot = None
        self.selection_validity = "valid"
        self.scope_invalidation_hint = ""
        self.selection_transaction_state = "idle"
        self.displayed_cart_delete_count = 0
        self.displayed_cart_delete_bytes = 0
        self.scan_id = ""

    # Phase 3.2 — pagination helpers
    def visible_group_count(self) -> int:
        return len(self.visible_groups())

    def paged_visible_groups(self) -> list:
        all_visible = self.visible_groups()
        start = self.page_index * self.page_size
        return all_visible[start:start + self.page_size]

    def marked_bytes(self) -> int:
        total = 0
        for g in self.scan_results:
            for f in g.files:
                if str(f.path) in self.marked_paths:
                    total += int(getattr(f, "size", 0) or 0)
        return total

    def selected_set_count(self) -> int:
        return len(self.selected_set_ids)

    def is_path_protected(self, path: str) -> bool:
        p = str(path).replace("\\", "/").lower()
        return any(p.startswith(prefix.replace("\\", "/").lower()) for prefix in self.protected_path_prefixes)

    def selection_pool(self, group: DuplicateGroup) -> list[DuplicateFile]:
        """In-scope, unprotected files that participate in mark-for-deletion."""
        return [
            f
            for f in group.files
            if self.file_in_selection_media_scope(f) and not self.is_path_protected(str(f.path))
        ]

    def path_marked_for_deletion(self, path: str, group_id: int) -> bool:
        p = str(path)
        if p in self.marked_paths:
            return True
        sel = self.set_selections.get(group_id)
        return bool(sel and p in sel.deleted_paths)

    def unmarked_survivor_count(self, group: DuplicateGroup) -> int:
        gid = group.group_id
        return sum(
            1 for f in self.selection_pool(group) if not self.path_marked_for_deletion(str(f.path), gid)
        )

    def is_mandatory_survivor(self, path: str, group: DuplicateGroup) -> bool:
        """True when this file must stay unmarked (only survivor left in the pool)."""
        p = str(path)
        pool = self.selection_pool(group)
        if not any(str(f.path) == p for f in pool):
            return False
        if len(pool) <= 1:
            return True
        if self.path_marked_for_deletion(p, group.group_id):
            return False
        return self.unmarked_survivor_count(group) == 1

    def can_mark_path_for_deletion(self, path: str, group: DuplicateGroup, *, mark: bool) -> bool:
        p = str(path)
        pool = self.selection_pool(group)
        if not any(str(f.path) == p for f in pool):
            return False
        if not mark:
            return True
        if self.path_marked_for_deletion(p, group.group_id):
            return True
        return self.unmarked_survivor_count(group) > 1

    def mark_checkbox_disabled(self, path: str, group: DuplicateGroup) -> bool:
        f = next((x for x in group.files if str(x.path) == str(path)), None)
        if f is None:
            return True
        if not self.file_in_selection_media_scope(f):
            return True
        if self.is_path_protected(str(path)):
            return True
        return self.is_mandatory_survivor(str(path), group)

    def clamp_group_to_single_survivor(self, group: DuplicateGroup) -> None:
        """Ensure at least one selection-pool file remains unmarked for deletion."""
        pool = self.selection_pool(group)
        if not pool:
            return
        gid = group.group_id
        sel = self.set_selections.setdefault(gid, SetSelection())
        if len(pool) == 1:
            p = str(pool[0].path)
            self.marked_paths.discard(p)
            sel.deleted_paths.discard(p)
            sel.kept_paths.add(p)
            return
        if self.unmarked_survivor_count(group) > 0:
            return
        keeper_path = str(pool[0].path)
        self.marked_paths.discard(keeper_path)
        sel.deleted_paths.discard(keeper_path)
        sel.kept_paths.add(keeper_path)

    def push_undo_snapshot(self) -> None:
        self.undo_stack.append(
            {
                "type": "selection",
                "marked_paths": set(self.marked_paths),
                "selected_set_ids": set(self.selected_set_ids),
                "set_selections": {
                    gid: SetSelection(
                        kept_paths=set(sel.kept_paths),
                        deleted_paths=set(sel.deleted_paths),
                        protected_paths=set(sel.protected_paths),
                    )
                    for gid, sel in self.set_selections.items()
                },
                "selection_origin": self.selection_origin,
                "selection_rule": self.selection_rule,
                "selection_validity": self.selection_validity,
                "mark_snapshot": self.mark_snapshot,
            }
        )
        self.redo_stack.clear()
        # P0-3 — cap undo stack at 50
        while len(self.undo_stack) > 50:
            self.undo_stack.pop(0)

    def restore_snapshot(self, snap: Dict[str, object]) -> None:
        self.marked_paths = set(snap.get("marked_paths", set()))
        self.selected_set_ids = set(snap.get("selected_set_ids", set()))
        restored = snap.get("set_selections", {})
        if isinstance(restored, dict):
            self.set_selections = dict(restored)
        origin = snap.get("selection_origin")
        if origin in ("auto_rule", "manual_review", "mixed"):
            self.selection_origin = origin  # type: ignore[assignment]
        rule = snap.get("selection_rule")
        self.selection_rule = str(rule) if rule else None
        validity = snap.get("selection_validity")
        if validity in ("valid", "invalidated_scope"):
            self.selection_validity = validity  # type: ignore[assignment]
        ms = snap.get("mark_snapshot")
        self.mark_snapshot = ms if isinstance(ms, MarkSnapshot) else None
        self._recompute_cart_counters()

    def cart_buckets(self) -> Dict[str, List[DuplicateFile]]:
        to_delete: List[DuplicateFile] = []
        to_keep: List[DuplicateFile] = []
        protected: List[DuplicateFile] = []
        for g in self.scan_results:
            sel = self.set_selections.get(g.group_id)
            for f in g.files:
                path = str(f.path)
                in_scope = self.file_in_selection_media_scope(f)
                if sel and path in sel.protected_paths:
                    if in_scope:
                        protected.append(f)
                elif in_scope and (path in self.marked_paths or (sel and path in sel.deleted_paths)):
                    to_delete.append(f)
                elif in_scope and sel and path in sel.kept_paths:
                    to_keep.append(f)
        return {"delete": to_delete, "keep": to_keep, "protected": protected}


def normalize_inspect_ref_cmp(n: int, ref: int, cmp_i: int) -> tuple[int, int]:
    """Clamp ref/cmp and enforce ref != cmp when n >= 2."""
    if n <= 0:
        return 0, 0
    if n == 1:
        return 0, 0
    ref = max(0, min(ref, n - 1))
    cmp_i = max(0, min(cmp_i, n - 1))
    if cmp_i == ref:
        cmp_i = (ref + 1) % n
    return ref, cmp_i


def step_inspect_cmp(n: int, ref: int, cmp_i: int, delta: int) -> int:
    """Move compare index by delta steps on a ring, skipping ref each step."""
    if n < 2:
        return cmp_i
    cur = cmp_i
    direction = 1 if delta > 0 else -1
    for _ in range(abs(delta)):
        for __ in range(n + 2):
            cur = (cur + direction) % n
            if cur != ref:
                break
    return cur


def inspect_left_right_indices(swap_panels: bool, ref: int, cmp_i: int) -> tuple[int, int]:
    """Physical left/right file indices (A/B columns)."""
    if swap_panels:
        return cmp_i, ref
    return ref, cmp_i


def pin_compare_as_new_reference(n: int, ref: int, cmp_i: int) -> tuple[int, int]:
    """Current compare becomes reference; compare advances to next index != new ref."""
    if n < 2:
        return ref, cmp_i
    new_ref = cmp_i
    new_cmp = step_inspect_cmp(n, new_ref, new_ref, 1)
    return normalize_inspect_ref_cmp(n, new_ref, new_cmp)


def make_index_reference(n: int, ref: int, cmp_i: int, new_ref: int) -> tuple[int, int]:
    """Context action: chip new_ref becomes reference; compare repaired to stay != ref."""
    if n < 2:
        return 0, 0
    new_ref = max(0, min(new_ref, n - 1))
    if cmp_i != new_ref:
        new_cmp = cmp_i
    elif ref != new_ref:
        new_cmp = ref
    else:
        new_cmp = (new_ref + 1) % n
    return normalize_inspect_ref_cmp(n, new_ref, new_cmp)


def marked_bytes_total(groups: List[DuplicateGroup], marked_paths: Set[str]) -> int:
    """Sum file sizes for paths currently marked for deletion."""
    total = 0
    for g in groups:
        for f in g.files:
            if str(f.path) in marked_paths:
                total += int(getattr(f, "size", 0) or 0)
    return total
