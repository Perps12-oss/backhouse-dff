# Cursor Prompt: Implement Performance and Sync Fixes for ReviewPage

Use this prompt when modifying `cerebro/ui/pages/review_page.py` to apply or verify the following fixes.

---

## Summary of Issues

1. **Filter change corrupts selection state**  
   When switching filters (e.g. "All Files" → "Images"), the group list is rebuilt and checkboxes are set without blocking signals. That causes `_on_group_checkbox_changed` to fire and overwrite `_keep_states` with a binary "all keep" / "all delete" state, resetting user selections and breaking the delete button.

2. **Group checkbox out of sync after per-file toggles**  
   When a file is toggled in the table, `_keep_states` is updated but the corresponding `GroupListItem` checkbox in the left panel does not reflect the new group state (e.g. remains partially checked even after all files are kept).

3. **UI freezes when selecting many groups**  
   "Select All" or Smart Select over thousands of groups calls `_on_group_checkbox_changed` per group, which each time calls `_update_display()` and `_update_stats()`. That gives O(n²) behavior and UI hangs.

---

## Proposed Fixes (Implementation Checklist)

### 1. Fix filter-change corruption

In **`_populate_group_list()`**, when creating each `GroupListItem`:

- Compute `keep_map`, `delete_count`, and tristate (`Unchecked` / `Checked` / `PartiallyChecked`) from `_keep_states` and `group.paths` (use `_norm_path(p)` for lookups).
- **Block signals** on the checkbox before setting state:
  - `item.checkbox.blockSignals(True)`
  - `item.checkbox.setCheckState(state)`  (use `setCheckState`, not `setChecked`, for tristate)
  - `item.checkbox.blockSignals(False)`
- Ensure `GroupListItem` uses a tristate checkbox: `self.checkbox.setTristate(True)` in `_build()`.

### 2. Group checkbox tristate and click behavior

In **`GroupListItem._on_checkbox_changed`**:

- If `state == Qt.PartiallyChecked`: set checkbox to `Qt.Checked` (with signals blocked), then emit `self.checkbox_changed.emit(self.group_id, True)` so the slot applies "mark all for delete (keep one)".
- Otherwise emit `self.checkbox_changed.emit(self.group_id, state == Qt.Checked)`.

### 3. Sync group checkbox after file-level changes

- Add **`_update_group_list_item(self, group_id: int)`**: find the visible `GroupListItem` for `group_id` in `group_list_layout`, compute delete count from `_keep_states` and `group.paths` (using `_norm_path`), set checkbox to Unchecked / Checked / PartiallyChecked with signals blocked, then `break`.
- Call `_update_group_list_item(group_id)` after modifying `_keep_states` for a single group in:
  - `_on_file_table_changed` (current group)
  - `_on_comparison_keep_selected` (current group)
  - `_on_group_checkbox_changed` (that group_id)
  - `_keep_file_by_index` (current group)

Do **not** call it from inside batch operations; batch uses `_sync_group_checkboxes()` instead.

### 4. Batch updates to prevent freezes

- In **`__init__`**: add `self._batch_updating = False`.
- Add **`_sync_group_checkboxes(self)`**: iterate `group_list_layout`, for each `GroupListItem` widget get `group_id`, resolve `GroupData` from `_all_groups`, compute delete count from `_keep_states` (with `_norm_path`), set checkbox to Unchecked / Checked / PartiallyChecked with signals blocked. Skip non-`GroupListItem` items (e.g. labels, spacers).
- Add **`_refresh_all_ui(self)`**: call `_sync_group_checkboxes()`, then `_update_display()`, then `_update_stats()`.
- **`_on_select_all_changed`**: set `_batch_updating = True`, loop over `_filtered_groups` and update `_keep_states[g.group_id]` directly (keep only first if checked, else keep all; use `_norm_path(p)` as keys). Set `_batch_updating = False` in a `finally`, then call `_refresh_all_ui()` once. Do **not** call `_on_group_checkbox_changed` per group.
- **`_on_smart_select_finished`**: set `_batch_updating = True`, merge result into `_keep_states` (normalize path keys with `_norm_path`). Set `_batch_updating = False` in a `finally`, then call `_refresh_all_ui()`, then update status text and `_bus.notify`. Do **not** call `_update_group_list_item` per group here; `_sync_group_checkboxes()` inside `_refresh_all_ui()` handles all visible items.
- **Guards**: at the start of `_on_group_checkbox_changed`, `_on_file_table_changed`, and `_on_comparison_keep_selected`, add `if self._batch_updating: return` so no per-group UI work runs during a batch; the final `_refresh_all_ui()` does it once.

### 5. Select All checkbox tristate (optional)

- In the build where **`select_all_cb`** is created: `self.select_all_cb.setTristate(True)` and update tooltip to describe Unchecked / Checked / Partially (mixed).
- In **`_update_stats()`**: while iterating `_filtered_groups` to compute `delete_count` and `delete_paths`, also count `n_none` (groups with 0 deletions) and `n_full` (groups with exactly one file kept). Then set `select_all_cb` with signals blocked: if `total_groups == 0` or `n_none == total_groups` → `Qt.Unchecked`; if `n_full == total_groups` → `Qt.Checked`; else → `Qt.PartiallyChecked`.

### 6. Path normalization

- Use **`_norm_path(p)`** (e.g. `os.path.normpath(os.path.normcase(str(p or "")))`) for every key in `_keep_states` and for every lookup (e.g. `keep_map.get(_norm_path(p), True)`). Apply consistently in `load_scan_result`, `_update_display`, `_populate_file_table`, `_populate_group_list`, `_update_stats`, `_open_ceremony`, `_on_file_table_changed`, `_on_comparison_keep_selected`, `_on_group_checkbox_changed`, `_update_group_list_item`, `_sync_group_checkboxes`, and when merging Smart Select result into `_keep_states`.

### 7. Preserve existing behavior

- Keep `_update_stats()` and any chunked/lazy size calculation as-is.
- Do not change signal/slot connections or payload shapes (e.g. `cleanup_confirmed` still emits the same dict; use `Signal(object)` to avoid Shiboken dict copy-convert if needed).
- Keep `MAX_GROUP_LIST_ITEMS` cap; `_sync_group_checkboxes` only updates visible items in the layout.

---

## Methods to Add or Modify

| Method | Action |
|--------|--------|
| `__init__` | Add `self._batch_updating = False`. |
| `_update_group_list_item(group_id)` | Add: find GroupListItem for group_id, set checkbox from _keep_states (tristate, block signals). |
| `_sync_group_checkboxes()` | Add: iterate visible group list items, set each checkbox from _keep_states (tristate, block signals). |
| `_refresh_all_ui()` | Add: call `_sync_group_checkboxes()`, `_update_display()`, `_update_stats()`. |
| `_populate_group_list()` | Set initial checkbox state with blockSignals + tristate logic. |
| `GroupListItem._on_checkbox_changed` | Handle PartiallyChecked → Checked and emit; else emit bool. |
| `_on_select_all_changed` | Batch-update _keep_states only; then _refresh_all_ui(). |
| `_on_smart_select_finished` | Batch-update _keep_states; then _refresh_all_ui(); no per-group _update_group_list_item. |
| `_on_group_checkbox_changed` | Early return if _batch_updating; else existing logic + _update_group_list_item. |
| `_on_file_table_changed` | Early return if _batch_updating; else existing logic + _update_group_list_item. |
| `_on_comparison_keep_selected` | Early return if _batch_updating; else existing logic + _update_group_list_item. |
| `_update_stats()` | Optionally update select_all_cb tristate from n_none/n_full. |

---

## Notes for the AI

- Work in `cerebro/ui/pages/review_page.py` only unless the prompt explicitly references other files.
- Preserve imports and existing code structure; only add or change the described logic.
- Ensure `item.widget()` is checked for `None` and `isinstance(w, GroupListItem)` before using in layout iteration (spacers/labels have no or different widgets).
- After changes, run linters and fix any new issues.
