from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Literal, Optional, Set, Tuple

from cerebro.engines.base_engine import DuplicateFile, DuplicateGroup

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
    # Phase 3.2 — pagination
    page_index: int = 0
    page_size: int = 200
    # 1.3 — incremental cart counters
    cart_delete_count: int = 0
    cart_keep_count: int = 0
    cart_protected_count: int = 0
    cart_delete_bytes: int = 0
    # 1.1 — visible_groups() memoization cache (hidden from repr/eq)
    _visible_cache_key: object = field(default=None, repr=False, compare=False)
    _visible_cache_val: list = field(default_factory=list, repr=False, compare=False)
    # 1.2 — O(1) group lookup index (hidden from repr/eq)
    _group_index: dict = field(default_factory=dict, repr=False, compare=False)

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
                if sel and path in sel.protected_paths:
                    pc += 1
                elif path in self.marked_paths or (sel and path in sel.deleted_paths):
                    dc += 1
                    db += size
                elif sel and path in sel.kept_paths:
                    kc += 1
        self.cart_delete_count = dc
        self.cart_keep_count = kc
        self.cart_protected_count = pc
        self.cart_delete_bytes = db

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

    def cart_buckets(self) -> Dict[str, List[DuplicateFile]]:
        to_delete: List[DuplicateFile] = []
        to_keep: List[DuplicateFile] = []
        protected: List[DuplicateFile] = []
        for g in self.scan_results:
            sel = self.set_selections.get(g.group_id)
            for f in g.files:
                path = str(f.path)
                if sel and path in sel.protected_paths:
                    protected.append(f)
                elif path in self.marked_paths or (sel and path in sel.deleted_paths):
                    to_delete.append(f)
                elif sel and path in sel.kept_paths:
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
