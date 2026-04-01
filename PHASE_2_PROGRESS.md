# Cerebro v2 — Phase 2 Progress

## Status: Phase 2 Complete ✅ | Ready for Phase 3

---

## Phase 2 — File Dedup Engine Wire-Up ✅ COMPLETE

**Goal:** Connect Phase 0 `FileDedupEngine` / `ScanOrchestrator` to the Phase 1 single-window shell.

### Tasks Completed

| Task | Status | Notes |
|------|--------|-------|
| Wire toolbar "Start Search" to orchestrator | ✅ | `_on_start_search()` fully implemented |
| Wire progress callback to status bar | ✅ | Thread-safe via `self.after(0, ...)` |
| Wire scan completion → results panel | ✅ | `orchestrator.get_results()` → `results_panel.load_results()` |
| Wire result file click → preview panel | ✅ | First click → A, next click → B (side-by-side) |
| Wire "Delete Selected" to send2trash | ✅ | Confirmation dialog + treeview removal + counter update |
| Wire results sub-filter tabs | ✅ | Already in ResultsPanel; fixed DuplicateFile attr access |
| Wire Stop / Cancel | ✅ | `_on_stop_search()` calls `orchestrator.cancel()` |
| Wire F5 Refresh | ✅ | Re-triggers `_on_start_search()` |
| Wire Keep A / Keep B in preview | ✅ | Unchecks corresponding file in results treeview |

### Bugs Fixed

| File | Bug | Fix |
|------|-----|-----|
| `results_panel.py` | Local `DuplicateGroup` stub used `List[Dict]` — incompatible with engine | Removed stub; import from `base_engine` |
| `results_panel.py` | `_refresh_treeview` used `.get("path", "")` on `DuplicateFile` dataclass | Fixed to `f.path`, `f.size`, `f.modified`, `f.similarity` |
| `results_panel.py` | `_apply_filter` created local groups with dict files | Rewired to use engine `DuplicateGroup(files=filtered_files)` |
| `results_panel.py` | `apply_selection_rule` used `.get("size")` / `.get("modified")` | Fixed to `.size` / `.modified` |
| `results_panel.py` | `get_reclaimable_space` used `.get("size", 0)` | Fixed to `.size` |
| `results_panel.py` | No single-click handler — `_on_file_selected` never fired | Added `<<TreeviewSelect>>` → `_on_single_click()` |
| `results_panel.py` | `_on_double_click` printed but didn't fire callback | Fixed to fire `_on_file_double_clicked` |
| `base_engine.py` | `DuplicateGroup` missing `file_count` property and `get_keeper_index()` | Added both |

### New Methods Added

**`cerebro/engines/base_engine.py` — `DuplicateGroup`:**
- `file_count` property → `len(self.files)`
- `get_keeper_index()` → returns index of keeper (flagged or largest)

**`cerebro/v2/ui/results_panel.py` — `ResultsPanel`:**
- `remove_paths(paths)` → removes deleted files from treeview + data, cleans empty groups
- `uncheck_path(path)` → unchecks a file row (used by Keep A/B)
- `_get_file_data_for_item(item_id)` → lookup helper
- `_on_single_click(event)` → fires `_on_file_selected` on click

**`cerebro/v2/ui/main_window.py` — `MainWindow`:**
- `_on_scan_progress(progress)` → thread bridge (calls `self.after(0, ...)`)
- `_apply_scan_progress(progress)` → updates status bar from ScanProgress
- `_on_scan_complete()` → populates results panel from orchestrator
- `_on_scan_error(msg)` → shows error dialog
- `_on_file_selected_in_results(file_data)` → routes to preview A/B

---

## Files Modified in Phase 2

| File | Changes |
|------|---------|
| `cerebro/engines/base_engine.py` | Added `file_count` + `get_keeper_index()` to `DuplicateGroup` |
| `cerebro/v2/ui/results_panel.py` | Removed local stub, fixed all dict→dataclass, added helpers |
| `cerebro/v2/ui/main_window.py` | Full Phase 2 wiring: orchestrator, progress, results, delete, preview |

---

## Phase 3 — Next Steps

**Goal:** Image Dedup Engine + Preview Panel enhancements

### Tasks
1. Create `cerebro/engines/image_dedup_engine.py`
   - pHash + dHash pipeline using `imagehash` library
   - Similarity threshold (default 90%)
   - Register as `"photos"` mode in orchestrator
2. Preview Panel enhancements for images:
   - Resolution badge (e.g. "3024×4032 · 12.1 MP")
   - Format badge (JPEG/PNG/HEIC/RAW)
   - Visual diff overlay
3. Acceptance criteria:
   - 10K images scanned in < 30s
   - Groups sorted by similarity score

### Dependencies to Install
```bash
pip install imagehash Pillow pillow-heif rawpy
```

---

## Summary

- **Phase 0:** ✅ Complete (engines + core utilities)
- **Phase 1:** ✅ Complete (single-window shell)
- **Phase 2:** ✅ Complete (file dedup wired end-to-end)
- **Phase 3:** 🔄 Next (image dedup + preview)
- **Total Progress:** ~55% complete

The first fully functional scan mode (exact file duplicates) is now working.
Start Search → progress → results → select → preview → delete.
