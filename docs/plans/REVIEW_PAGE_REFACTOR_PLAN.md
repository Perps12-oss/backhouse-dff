# Review Page Refactor Plan
**Target:** `cerebro/v2/ui/flet_app/pages/review_page.py`
**Build:** 0.0.24.1 → target 0.0.25.0
**Scope:** Architecture decomposition, state correctness, deletion safety, performance

---

## Overview

The refactor is organized into **5 phases**, ordered by risk and dependency.
Each phase is self-contained and shippable independently. Phases 1–2 are
non-negotiable foundation work. Phases 3–5 are improvements that build on top.

```
Phase 1 — Extract sub-components (decompose the monolith)
Phase 2 — Fix state correctness (sync marked_paths → AppState)
Phase 3 — Fix deletion safety (all deletes go async)
Phase 4 — Performance fixes (O(n) hot paths, cache leaks)
Phase 5 — Polish (dead code removal, color tokens, imports)
```

---

## Phase 1 — Decompose the Monolith

### 1.1 New File Structure

Split `review_page.py` (2,411 lines) into these files:

```
pages/
  review_page.py              ← Shell only: owns mode FSM, wires sub-components (~300 lines)
  review/
    __init__.py
    filter_bar.py             ← FilterBar widget + filter index logic
    stats_header.py           ← StatsHeader widget (metric chips, summary, workflow label)
    group_list.py             ← GroupListPanel widget (left sidebar in compare mode)
    group_card.py             ← GroupCard widget (used in groups overview)
    grid_view.py              ← GridView widget + tile builder + thumbnail loading
    compare_view.py           ← CompareView widget + panel A/B builder
    smart_rules.py            ← Pure rule engine (no UI, no state, no Flet)
    deletion_dialog.py        ← Reusable deletion confirmation dialog builder
    _types.py                 ← Local type aliases (ReviewMode literal, etc.)
```

### 1.2 `smart_rules.py` — Extract First (Zero Risk)

The keep-rule selection logic is copy-pasted 4 times in the current file.
Extract into a pure module with no Flet or state dependencies:

```python
# review/smart_rules.py

from __future__ import annotations
from typing import List
from cerebro.engines.base_engine import DuplicateFile

_RULES = {
    "keep_largest":  lambda files: max(files, key=lambda f: f.size),
    "keep_smallest": lambda files: min(files, key=lambda f: f.size),
    "keep_newest":   lambda files: max(files, key=_mtime),
    "keep_oldest":   lambda files: min(files, key=_mtime),
}
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
```

**Migration:** Replace all 4 if-elif chains with `smart_rules.paths_to_delete(rule, files)`.

### 1.3 `stats_header.py` — Extract StatsHeader

```python
# review/stats_header.py

class StatsHeader(ft.Container):
    """Top bar: title, summary, workflow hint, metric chips."""

    def __init__(self, bridge: StateBridge, back_btn: ft.TextButton): ...

    def refresh(
        self,
        mode: str,
        filter_key: str,
        filter_counts: dict,
        filter_sizes: dict,
        filter_group_counts: dict,
        reviewed_ids: set,
        groups: list,
    ) -> None:
        """Recompute and update all child controls. Called by ReviewPage."""
        ...
```

**What moves here:**
- `_title_lbl`, `_summary_lbl`, `_workflow_lbl`, `_stats_row`, `_stats_row_wrap`
- `_metric_chip()` builder
- `_update_top_stats()` logic

### 1.4 `filter_bar.py` — Extract FilterBar

```python
# review/filter_bar.py

class FilterBar(ft.Container):
    """Segmented filter strip with per-bucket file/size counts."""

    def __init__(self, on_change: Callable[[str], None]): ...

    def update_counts(
        self,
        counts: Dict[str, int],
        sizes: Dict[str, int],
        active_key: str,
    ) -> None: ...
```

**What moves here:**
- `_filter_seg`, `_filter_seg_lines`
- `_refresh_filter_labels()`
- `_FILTER_TABS`, `_FILTER_ACCENT` constants (move to this module)

### 1.5 `grid_view.py` — Extract GridView

```python
# review/grid_view.py

class ReviewGridView(ft.Container):
    """Tile grid with async thumbnail loading and zoom controls."""

    def __init__(self, bridge: StateBridge, on_tile_clicked: Callable): ...

    def load(self, files: List[DuplicateFile], marked_paths: set[str]) -> None:
        """Replace grid contents. Called by ReviewPage on filter/mode change."""
        ...

    def refresh_marks(self, marked_paths: set[str]) -> None:
        """Redraw checkbox states without rebuilding tiles."""
        ...
```

**What moves here:**
- `_grid`, `_rendering_badge`, `_tile_cache`, `_thumb_slots`
- `_tile_for_file_placeholder()`, `_load_thumbnails_async()`
- `_refresh_grid()`, `_append_grid_tiles_async()`
- `_grid_build_generation`, `_thumb_load_generation`
- `_zoom_row`, `_smart_seg`, `_smart_apply_all_btn`, `_smart_row`
- `_build_zoom_row()`, `_sync_zoom_pill_styles()`
- `_GRID_BUILD_ASYNC_THRESHOLD`, `_GRID_FIRST_SYNC_FILES`, `_GRID_ASYNC_BATCH`

**Delete:** `_build_tile()` (dead code — confirmed never called from live paths).

### 1.6 `compare_view.py` — Extract CompareView

```python
# review/compare_view.py

class CompareView(ft.Column):
    """Left group list + right A/B panels + progress/marked bar."""

    def __init__(self, bridge: StateBridge, callbacks: CompareCallbacks): ...

    def load_group(
        self,
        gid: int,
        files: List[DuplicateFile],
        compare_a: DuplicateFile,
        compare_b: Optional[DuplicateFile],
        all_groups: List[DuplicateGroup],
        marked_paths: set[str],
        reviewed_ids: set[int],
    ) -> None: ...

    def refresh_marks(self, marked_paths: set[str]) -> None: ...
    def refresh_progress(self, reviewed: int, total: int, marked_bytes: int, remaining: int) -> None: ...
```

**What moves here:**
- `_compare_panel_a`, `_compare_panel_b`, `_compare_view`, `_compare_columns`
- `_group_list_panel`, `_group_list_scroll_host`, `_group_list_items`, `_group_list_order`
- `_progress_bar`, `_progress_lbl`, `_marked_bar`, `_marked_lbl`
- `_compare_thumb_slots`, `_compare_dims_labels`
- `_cmp_bar`, `_cmp_title`, `_cmp_smart_seg`, `_delete_btn`, `_keep_btn`, `_cmp_apply_rule_btn`
- `_btn_cmp_grid`, `_btn_cmp_prev`, `_btn_cmp_next`
- `_build_compare_side()`, `_build_compare_file_column()` (latter can be deleted)
- `_build_compare_file_column()` → DELETE (dead code)
- `_refresh_group_list_panel()`, `_update_compare_panels()`, `_update_compare_chrome()`
- `_apply_compare_panel_tints()`, `_reset_compare_panels_idle_chrome()`
- `_populate_compare_media_async()`
- `_compare_render_generation`, `_compare_nav_in_flight`

### 1.7 `ReviewPage` Shell After Decomposition

After extraction, `ReviewPage` becomes a coordinator:

```python
class ReviewPage(ft.Column):
    def __init__(self, bridge: StateBridge):
        # 1. Create sub-components
        self._filter_bar = FilterBar(on_change=self._on_filter_changed)
        self._stats_header = StatsHeader(bridge, back_btn=self._btn_back)
        self._grid_view = ReviewGridView(bridge, on_tile_clicked=self._on_tile_clicked)
        self._compare_view = CompareView(bridge, callbacks=self._make_callbacks())
        self._groups_overview = ft.ListView(...)

        # 2. Own mode FSM
        self._mode: ReviewMode = "empty"

        # 3. Own group index for O(1) prev/next
        self._groups: List[DuplicateGroup] = []
        self._group_index: Dict[int, int] = {}  # group_id → position

        # 4. Own marked state (→ Phase 2: sync to store)
        self._marked_paths: set[str] = set()

    def _enter_mode(self, mode: ReviewMode) -> None:
        """Single method. Visibility matrix applied from a dict."""
        VISIBILITY: Dict[ReviewMode, Dict[str, bool]] = {
            "empty":   {"filter": False, "cmp_bar": False, "smart": False, "toggle": False, "sort": False},
            "loading": {"filter": False, "cmp_bar": False, "smart": False, "toggle": False, "sort": False},
            "groups":  {"filter": True,  "cmp_bar": False, "smart": False, "toggle": True,  "sort": True},
            "grid":    {"filter": True,  "cmp_bar": False, "smart": True,  "toggle": True,  "sort": False},
            "compare": {"filter": False, "cmp_bar": True,  "smart": False, "toggle": False, "sort": False},
        }
        vis = VISIBILITY[mode]
        self._filter_bar.visible = vis["filter"]
        self._cmp_bar.visible    = vis["cmp_bar"]
        self._smart_row.visible  = vis["smart"]
        # ... etc.
        self._mode = mode
```

---

## Phase 2 — Fix State Correctness

### 2.1 Sync `_marked_paths` → `AppState.selected_files`

Currently `_marked_paths` is a local `set[str]` that never touches the store.
`AppState.selected_files` exists for exactly this purpose but is unused here.

**Fix:**

```python
def _toggle_mark_file(self, file: DuplicateFile) -> None:
    fp = str(file.path)
    if fp in self._marked_paths:
        self._marked_paths.discard(fp)
    else:
        self._marked_paths.add(fp)
    # Dispatch to store so selection survives tab switches
    from cerebro.v2.state.actions import FileSelectionChanged
    self._bridge.store.dispatch(
        FileSelectionChanged(file_ids=tuple(self._marked_paths))
    )
    self._compare_view.refresh_marks(self._marked_paths)
    self._grid_view.refresh_marks(self._marked_paths)
```

**On `on_show`:** Read back from store to restore selection across tab switches:
```python
def on_show(self) -> None:
    # Restore selection from store (survives tab navigation)
    self._marked_paths = set(self._bridge.state.selected_files)
    ...
```

### 2.2 Build a `_group_index` for O(1) Navigation

```python
def _rebuild_group_index(self) -> None:
    self._group_index = {g.group_id: i for i, g in enumerate(self._groups)}

def _prev_group(self, e=None) -> None:
    if self._compare_gid is None:
        return
    idx = self._group_index.get(self._compare_gid, 0)
    if idx > 0:
        self._enter_compare(self._groups[idx - 1].group_id)

def _next_group(self, e=None) -> None:
    if self._compare_gid is None:
        return
    idx = self._group_index.get(self._compare_gid, 0)
    if idx < len(self._groups) - 1:
        self._enter_compare(self._groups[idx + 1].group_id)
```

Call `_rebuild_group_index()` inside `load_results()`, `load_group()`, and
`apply_pruned_groups()` — anywhere `self._groups` is replaced.

### 2.3 Fix the Visibility Matrix

Replace 5 sets of 5 manual `visible =` assignments with the dict approach
shown in §1.7. One `_enter_mode()` call, one place to change.

### 2.4 Fix `_go_back` Dead Branch

```python
# Before (dead branch):
def _go_back(self, e=None) -> None:
    if self._mode == "compare":
        self._enter_mode("groups")
        return
    if self._mode == "grid":          # duplicate — same body
        self._enter_mode("groups")
        return
    self._bridge.navigate("dashboard")

# After:
def _go_back(self, e=None) -> None:
    if self._mode in ("compare", "grid"):
        self._enter_mode("groups")
    else:
        self._bridge.navigate("dashboard")
```

### 2.5 Extract `_schedule_load_to_groups()` Helper

This pattern appears 5 times verbatim:
```python
self._loading = True
self._enter_mode("loading")
page = self._bridge.flet_page
if hasattr(page, "run_task"):
    page.run_task(self._finish_load_to_groups_async)
else:
    self._loading = False
    self._enter_mode("groups")
```

Extract once:
```python
def _schedule_load_to_groups(self) -> None:
    self._loading = True
    self._enter_mode("loading")
    page = self._bridge.flet_page
    if hasattr(page, "run_task"):
        page.run_task(self._finish_load_to_groups_async)
    else:
        self._loading = False
        self._enter_mode("groups")
```

---

## Phase 3 — Fix Deletion Safety

### 3.1 Make All Delete Paths Async

`_delete_compare_side` currently calls `service.delete_and_prune()` — **blocking
on the UI thread**. This will freeze the app for large files or slow drives.

**Fix:** Route through `_execute_smart_delete` (which is already async) for
all single-file deletions too:

```python
def _delete_compare_side(self, side: str) -> None:
    f = self._compare_a if side == "a" else self._compare_b
    if not f:
        return
    name = Path(str(f.path)).name
    path = str(f.path)

    def _confirmed(policy: DeletionPolicy) -> None:
        self._bridge.dismiss_top_dialog()
        # Reuse the existing async path — no special case
        self._execute_smart_delete([path], policy)

    self._bridge.show_modal_dialog(
        _build_confirm_dialog(name, _confirmed, self._bridge, self._t)
    )
```

### 3.2 Move `DeleteService` to a Shared Instance

Stop instantiating `DeleteService()` inline per call. Inject it once:

```python
# In ReviewPage.__init__:
from cerebro.v2.ui.flet_app.services.delete_service import DeleteService
self._delete_service = DeleteService()
```

Remove the two inline `service = DeleteService()` instantiations.

### 3.3 Extract `_build_confirm_dialog()` to `deletion_dialog.py`

The confirmation dialog is copy-pasted between `_delete_compare_side` and
`_show_smart_delete_dialog`. Extract a builder:

```python
# review/deletion_dialog.py

def build_confirm_dialog(
    label: str,                        # "file.jpg" or "42 files"
    on_confirmed: Callable[[DeletionPolicy], None],
    t,                                 # theme
) -> ft.AlertDialog:
    def _cancel(e): ...
    def _perm(e): on_confirmed(DeletionPolicy.PERMANENT)
    def _trash(e): on_confirmed(DeletionPolicy.TRASH)
    return ft.AlertDialog(
        modal=True,
        title=ft.Text("Confirm Deletion"),
        content=ft.Text(f'Delete {label}?'),
        actions=[
            ft.TextButton("Cancel", on_click=_cancel),
            ft.OutlinedButton("Delete Permanently", on_click=_perm,
                              style=ft.ButtonStyle(color=t.colors.danger)),
            ft.ElevatedButton("Move to Trash", on_click=_trash,
                              style=ft.ButtonStyle(bgcolor=t.colors.danger, color=t.colors.bg)),
        ],
    )
```

---

## Phase 4 — Performance Fixes

### 4.1 Fix `_update_progress_and_marked_bar` O(n) on Every Mark Toggle

Currently: iterates all groups × all files to compute `marked_bytes` every time
the user ticks a checkbox.

**Fix:** Maintain a running `_marked_bytes: int` counter:

```python
def _toggle_mark_file(self, file: DuplicateFile) -> None:
    fp = str(file.path)
    size = int(getattr(file, "size", 0) or 0)
    if fp in self._marked_paths:
        self._marked_paths.discard(fp)
        self._marked_bytes -= size
    else:
        self._marked_paths.add(fp)
        self._marked_bytes += size
    self._update_progress_and_marked_bar()
```

Reset `_marked_bytes = 0` whenever `_marked_paths` is cleared or replaced wholesale.
For `_apply_rule_to_all_groups` (bulk mark), recompute once from scratch then cache.

### 4.2 Fix `_compare_thumb_slots` and `_compare_dims_labels` Memory Leak

These dicts grow unboundedly. Every `_build_compare_side` call adds entries
keyed by `f"{label}:{gen}"` and never removes old ones.

**Fix:** Clear both dicts at the start of `_update_compare_panels`:

```python
def _update_compare_panels(self) -> None:
    self._compare_render_generation += 1
    gen = self._compare_render_generation
    # Clear stale slot references from previous renders
    self._compare_thumb_slots.clear()
    self._compare_dims_labels.clear()
    ...
```

### 4.3 Don't Rebuild Group List on Every `apply_pruned_groups` Call

Currently `apply_pruned_groups` always calls `self._group_list_items.clear()`,
forcing a full DOM rebuild even if only one file was removed from one group.

**Fix:** Only clear + rebuild if the set of group IDs has changed:

```python
def apply_pruned_groups(self, groups, mode="files") -> None:
    old_ids = {g.group_id for g in self._groups}
    self._groups = list(groups)
    new_ids = {g.group_id for g in self._groups}
    self._rebuild_group_index()
    self._rebuild_filter_index()

    if old_ids != new_ids:
        # Groups were removed — full rebuild needed
        self._group_list_items.clear()
        self._group_list_order = []

    ...  # rest of mode-specific refresh
```

### 4.4 Unify `_grid_build_generation` and `_rendering_generation`

Two separate int counters guard against stale async renders in the grid.
They increment together and are never checked independently.

**Fix:** Remove `_rendering_generation`; use `_grid_build_generation` for both.
The `_set_rendering` badge visibility should be controlled by the grid sub-component
(§1.5), not a second counter in the shell.

### 4.5 Cache `is_reduce_motion_enabled()` Per Session

`is_reduce_motion_enabled()` is called inside `_tile_for_file_placeholder` — once
per tile build. It reads a JSON settings file on every call via `get_settings()`.

**Fix:** Read once in `on_show()` or `load_results()` and cache:
```python
self._reduce_motion: bool = self._bridge.is_reduce_motion_enabled()
```

---

## Phase 5 — Polish & Cleanup

### 5.1 Delete Dead Code

| Symbol | Reason |
|---|---|
| `_build_tile()` | Superseded by `_tile_for_file_placeholder`; no call sites |
| `_build_compare_file_column()` | Superseded by `_build_compare_side`; no call sites |
| `_selected_nav_index_for_key()` call result | Assigned to `_` in `layout.py` — return value never used |

### 5.2 Move All Inline Imports to Top Level

These appear inside methods and should be moved to the file header:

```python
# Currently scattered inside methods — move to top of review_page.py
import asyncio
import datetime
from cerebro.v2.ui.flet_app.services.delete_service import DeleteService
```

### 5.3 Replace Hardcoded Hex Colors with Theme Tokens

Define the review-specific palette inside a `_ReviewColors` dataclass and
read from it instead of raw strings:

```python
# review/_types.py

@dataclass(frozen=True)
class ReviewColors:
    side_a:       str = "#22D3EE"
    side_b:       str = "#A78BFA"
    danger:       str = "#EF4444"
    success:      str = "#4ADE80"
    info:         str = "#93C5FD"
    muted_text:   str = "#9FB0D0"
    tile_bg:      str = "#0A0E14"
    group_stripe: tuple = ("#22D3EE", "#A78BFA", "#F472B6", "#34D399", "#FBBF24")

RC = ReviewColors()  # module-level singleton
```

Replace all 20+ raw hex strings with `RC.side_a`, `RC.danger`, etc.

### 5.4 Fix Logging Anti-patterns

```python
# Before (eager f-string formatting):
_log.error(f"Failed to open file: {e}")

# After:
_log.error("Failed to open file: %s", e)
```

Apply to all `_log.*` calls in the file.

### 5.5 Fix `_UI_SLOW_MS` Warning Noise

```python
# Before:
_log.warning("[UI_SLOW] %s took %.1f ms", label, elapsed_ms)

# After:
_log.debug("[UI_SLOW] %s took %.1f ms", label, elapsed_ms)
```

Or gate behind `if __debug__`. Warning-level logs are reserved for recoverable
errors, not performance profiling.

### 5.6 Remove Defensive `hasattr(self._bridge, 'app_theme')` Guards

`app_theme` is a declared `@property` on `StateBridge`. Replace:

```python
# Before:
is_light = "light" in self._bridge.app_theme.lower() if hasattr(self._bridge, 'app_theme') else False

# After:
is_light = self._bridge.app_theme == "light"
```

### 5.7 Unify `_safe_update` Call Style

Pick one: call as `ReviewPage._safe_update(ctrl)` everywhere, or assign
`_su = ReviewPage._safe_update` at class level and use `self._su(ctrl)`.
Currently mixed between both forms — 42 call sites.

---

## Implementation Order

```
┌──────────────────────────────────────────────────────────────────────────┐
│ STEP  │ WHAT                                         │ RISK  │ LOC DELTA │
├──────────────────────────────────────────────────────────────────────────┤
│  1    │ Extract smart_rules.py                       │ None  │ -60       │
│  2    │ Fix _go_back dead branch                     │ None  │ -3        │
│  3    │ Move inline imports to top of file           │ None  │ 0         │
│  4    │ Fix logging anti-patterns                    │ None  │ 0         │
│  5    │ Delete _build_tile + _build_compare_file_col │ None  │ -70       │
│  6    │ Extract _schedule_load_to_groups()           │ Low   │ -50       │
│  7    │ Build _group_index, fix _prev/_next          │ Low   │ -30       │
│  8    │ Fix _compare_thumb_slots clear on render     │ Low   │ +3        │
│  9    │ Fix _update_progress O(n): add _marked_bytes │ Low   │ +10       │
│ 10    │ Cache is_reduce_motion_enabled()             │ Low   │ +3        │
│ 11    │ Route _delete_compare_side through async     │ Med   │ -20       │
│ 12    │ Inject DeleteService once in __init__        │ Low   │ -5        │
│ 13    │ Extract deletion_dialog.py builder           │ Low   │ -30       │
│ 14    │ Extract visibility matrix into dict          │ Low   │ -40       │
│ 15    │ Sync _marked_paths → AppState.selected_files │ Med   │ +15       │
│ 16    │ Extract ReviewColors / replace hex literals  │ Low   │ 0         │
│ 17    │ Extract stats_header.py                      │ Med   │ -200      │
│ 18    │ Extract filter_bar.py                        │ Med   │ -150      │
│ 19    │ Extract grid_view.py                         │ High  │ -400      │
│ 20    │ Extract compare_view.py                      │ High  │ -600      │
│ 21    │ Slim ReviewPage shell to coordinator         │ High  │ -800      │
│ 22    │ Fix group_list rebuild on apply_pruned       │ Low   │ +20       │
└──────────────────────────────────────────────────────────────────────────┘
```

Steps 1–10 are safe to do in a single PR with no behavioural changes.
Steps 11–16 are correctness fixes — each deserves its own PR and a smoke test.
Steps 17–22 are the decomposition — do in order, one sub-component at a time.

---

## Acceptance Criteria

After all phases are complete:

- [ ] `review_page.py` shell is under 400 lines
- [ ] No method in any file exceeds 80 lines
- [ ] `_marked_paths` dispatches `FileSelectionChanged` on every mutation
- [ ] `on_show()` restores selection from `AppState.selected_files`
- [ ] Zero blocking deletions on the UI thread
- [ ] `DeleteService` instantiated exactly once per `ReviewPage` instance
- [ ] `apply_rule` logic exists in exactly one place (`smart_rules.py`)
- [ ] `_prev_group` / `_next_group` use O(1) index lookup
- [ ] `_compare_thumb_slots` cleared before each panel rebuild
- [ ] No raw hex color literals outside `_types.py`
- [ ] All `import asyncio / datetime` at file top level
- [ ] All `_log.*` calls use `%s` formatting, not f-strings
- [ ] `_build_tile` and `_build_compare_file_column` deleted

---

## Files to Create / Modify

| Action | File |
|---|---|
| **Create** | `pages/review/_types.py` |
| **Create** | `pages/review/smart_rules.py` |
| **Create** | `pages/review/deletion_dialog.py` |
| **Create** | `pages/review/stats_header.py` |
| **Create** | `pages/review/filter_bar.py` |
| **Create** | `pages/review/grid_view.py` |
| **Create** | `pages/review/compare_view.py` |
| **Create** | `pages/review/group_card.py` |
| **Create** | `pages/review/__init__.py` |
| **Modify** | `pages/review_page.py` (becomes shell) |
| **Delete** | nothing deleted — old file becomes the shell |
