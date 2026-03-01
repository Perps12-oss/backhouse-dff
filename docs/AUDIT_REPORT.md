# CEREBRO Audit Report — `audit-stabilize-stress-v1`

**Date:** 2026-02-28
**Branch:** `audit-stabilize-stress-v1` (from `main`)
**Auditor:** Opus 4.6 — single-agent pass

---

## P0 — Blockers (app crash / data-loss risk)

### P0-1  ReviewPage `_build()` references undefined scaffold (BOOT CRASH)
**File:** `cerebro/ui/pages/review_page.py` — `_build()` lines 953-964
**Symptom:** `AttributeError` on `self._scaffold` — ReviewPage cannot be constructed; app cannot start.
**Root cause:** Lines 953-964 reference `content_wrapper` (never assigned), `self._scaffold` (never created), and `StickyActionBar` (never imported). These are stale leftover code from a scaffold refactor.
**Fix:** Delete lines 953-964. The layout is already complete via the QSplitter added at line 947.

### P0-2  `_norm_path` undefined (DELETE CRASH)
**File:** `cerebro/ui/pages/review_page.py` — `_open_ceremony()` lines 1593-1594, `refresh_after_deletion()` lines 1688, 1694
**Symptom:** `NameError: name '_norm_path' is not defined` when user confirms deletion or after deletion completes.
**Fix:** Add module-level helper:
```python
def _norm_path(p) -> str:
    return os.path.normcase(os.path.normpath(str(p)))
```

### P0-3  `_compute_group_size` undefined (POST-DELETE CRASH)
**File:** `cerebro/ui/pages/review_page.py` — `refresh_after_deletion()` line 1699
**Symptom:** `NameError` after successful deletion when UI tries to recompute group sizes.
**Fix:** Add module-level helper:
```python
def _compute_group_size(paths) -> int:
    total = 0
    for p in paths:
        try:
            total += os.path.getsize(p)
        except OSError:
            pass
    return total
```

### P0-4  `_refresh_delete_button` undefined (POST-DELETE CRASH)
**File:** `cerebro/ui/pages/review_page.py` — `refresh_after_deletion()` line 1728
**Symptom:** `AttributeError` — method never defined on `ReviewPage`.
**Fix:** Replace call with `self._update_stats()` which already syncs the floating delete button.

### P0-5  `_on_export_list` undefined (STALE SCAFFOLD)
**File:** `cerebro/ui/pages/review_page.py` — line 961
**Symptom:** Part of the stale scaffold block (P0-1). Removed when scaffold lines are deleted.
**Fix:** Covered by P0-1 removal.

### P0-6  ScanPage `LayoutMetrics` missing `COMBO_MIN_WIDTH`, `BUTTON_MIN_HEIGHT`
**File:** `cerebro/ui/pages/scan_page.py` — lines 347-348, 355-356
**Symptom:** `AttributeError` on `LayoutMetrics.COMBO_MIN_WIDTH` — ScanPage cannot be constructed.
**Fix:** Add to `LayoutMetrics`:
```python
COMBO_MIN_WIDTH = 120
BUTTON_MIN_HEIGHT = 32
```

### P0-7  `HashCache()` called with no args (audit_page + hub_page)
**Files:**
- `cerebro/ui/pages/audit_page.py` — `ReportAuditWorker` (line 264), `VerifyAuditWorker` (line 375), `ExportAuditWorker` (line 453)
- `cerebro/ui/pages/hub_page.py` — lines 376, 935

**Symptom:** `TypeError: __init__() missing 1 required positional argument: 'db_path'`
**Root cause:** `HashCache.__init__(self, db_path: Path)` requires a path. These callers pass nothing.
**Fix:** Get db_path via `get_cache_dir() / "hash_cache.sqlite"`, wrap in try/except.

### P0-8  `HashCache.vacuum()` does not exist (hub_page)
**File:** `cerebro/ui/pages/hub_page.py` — line 936
**Symptom:** `AttributeError: 'HashCache' object has no attribute 'vacuum'`
**Fix:** Add `vacuum()` method to HashCache or use raw SQL `VACUUM`.

### P0-9  `cerebro.services.history_manager` module does not exist
**File:** `cerebro/ui/pages/audit_page.py` — `ReportAuditWorker` (line 244), `HistoryAuditWorker` (line 318)
**Symptom:** `ModuleNotFoundError` — every audit that tries to read scan history crashes.
**Fix:** These imports are already inside try/except blocks, so the crash is caught. But the functionality silently fails. Mark as non-fatal but broken feature.

### P0-10  Duplicate import + unused import
**File:** `cerebro/ui/pages/review_page.py` — lines 23, 25
**Symptom:** `from PySide6.QtCore import QItemSelectionModel` imported twice. Harmless but indicates stale code.
**Fix:** Remove duplicate line 25.

---

## P1 — Significant Issues (data correctness / UX)

### P1-1  Smart Select does not guarantee delete_count reflects selection
**File:** `cerebro/ui/pages/review_page.py` — `_apply_smart_to_filtered()`
**Detail:** Smart select mutates `_keep_states` dicts and calls `_update_stats()`. The stats loop iterates only `_filtered_groups` (not `_all_groups`), so unfiltered groups' selections are invisible to the count. The floating delete button and status bar only reflect filtered-group counts, but `_open_ceremony` also only iterates `_filtered_groups`. This is consistent but potentially confusing — selecting "All Files" filter after Smart Select on a sub-filter shows outdated counts.
**Fix:** Ensure `_update_stats` always computes over `_all_groups` for the authoritative total.

### P1-2  `os.path.getmtime/getsize` called on UI thread during Smart Select
**File:** `cerebro/ui/pages/review_page.py` — `_apply_smart_to_filtered()` lines 1550-1556
**Detail:** For each file in each group, `os.path.getmtime()` or `os.path.getsize()` is called synchronously. With 100+ groups × 2+ files each, this can block the UI for seconds on network drives.
**Fix:** Move to QRunnable or at minimum cache stat results from the scan result data.

### P1-3  `_update_stats` calls `os.path.getsize` per delete-candidate on UI thread
**File:** `cerebro/ui/pages/review_page.py` — lines 1380-1383
**Detail:** Each call to `_update_stats()` (triggered by every checkbox toggle) does I/O per file.
**Fix:** Use pre-cached sizes from scan result or accumulate from group metadata.

### P1-4  `_open_ceremony` calls `os.path.getsize/exists` on UI thread
**File:** `cerebro/ui/pages/review_page.py` — lines 1602-1610
**Detail:** Plan building does `os.path.exists(keep_path)` and `os.path.getsize(p)` per file on UI thread.
**Fix:** Move plan assembly to a worker thread.

### P1-5  `build_delete_plan` runs on UI thread (main_window)
**File:** `cerebro/ui/main_window.py` — `_on_cleanup_confirmed()` line 555
**Detail:** `self._pipeline.build_delete_plan()` does `Path.exists()`, `Path.resolve()`, `Path.stat()` per file. Blocks UI for large plans.
**Fix:** Move to worker thread, emit progress immediately.

### P1-6  `QApplication.processEvents()` in progress dialog
**File:** `cerebro/ui/pages/review_page.py` — `CleanupProgressDialog.update_progress()` line 313
**Detail:** Calling `processEvents()` during signal handling can cause reentrancy bugs.
**Fix:** Remove; the deletion worker already runs on a QThread so signals arrive asynchronously.

### P1-7  ScanPage Simple/Advanced mode not fully persisted
**File:** `cerebro/ui/pages/scan_page.py`
**Detail:** `_on_ui_mode_changed` saves to `scan_options` dict, and `_wire_signals` restores on init. But the toggle button visual state isn't restored from persisted option — only visibility of the advanced panel.
**Fix:** Restore button check state from persisted `scan_ui_mode` in `_wire_signals`.

---

## File Change Matrix

| # | File | Functions to change | Commit |
|---|------|-------------------|--------|
| 1 | `cerebro/ui/pages/review_page.py` | `_build()` remove 953-964; add `_norm_path`, `_compute_group_size`; fix `_refresh_delete_button` call; remove dup import | C1, C2 |
| 2 | `cerebro/ui/pages/scan_page.py` | Add `COMBO_MIN_WIDTH`, `BUTTON_MIN_HEIGHT` to `LayoutMetrics`; persist/restore mode toggle | C1, C4 |
| 3 | `cerebro/ui/pages/audit_page.py` | Fix `HashCache()` calls in 3 workers; wrap history_manager imports | C1 |
| 4 | `cerebro/ui/pages/hub_page.py` | Fix `HashCache()` calls; fix `vacuum()` call | C1 |
| 5 | `cerebro/services/hash_cache.py` | Add `vacuum()` method | C1 |
| 6 | `cerebro/ui/main_window.py` | Move `build_delete_plan` off UI thread | C3 |
| 7 | `sanity/stress_scan.py` | New stress harness | C5 |
| 8 | `sanity/stress_delete.py` | New stress harness | C5 |
| 9 | `docs/STRESS_TEST.md` | New test documentation | C5 |
| 10 | `docs/CHANGES.md` | Summary of all changes | C5 |

---

## Wiring Audit: scan → review → smart select → delete → refresh → history/audit

| Step | Status | Notes |
|------|--------|-------|
| ScanPage → LiveScanController → FastScanWorker | OK | Properly threaded |
| scan_completed → MainWindow → ReviewPage.load_scan_result | OK | Wired via StateBus |
| ReviewPage Smart Select | **BROKEN** (P0-2) | `_norm_path` undefined in downstream delete path |
| ReviewPage → _open_ceremony → cleanup_confirmed signal | **BROKEN** (P0-1, P0-2) | Scaffold crash prevents ReviewPage init; _norm_path NameError |
| MainWindow._on_cleanup_confirmed → Pipeline.build_delete_plan | OK once ReviewPage emits | Pipeline validation is sound |
| Pipeline → DeletionEngine (worker thread) | OK | Proper QThread usage |
| MainWindow._on_cleanup_finished → refresh_after_deletion | **BROKEN** (P0-3, P0-4) | `_compute_group_size` and `_refresh_delete_button` undefined |
| Audit page → HashCache/HistoryManager | **BROKEN** (P0-7, P0-9) | Wrong constructor, missing module |
| Hub page → HashCache | **BROKEN** (P0-7, P0-8) | Wrong constructor, missing vacuum() |

---

## Dependency Audit

| Package | requirements.txt | Actually used | Notes |
|---------|-----------------|---------------|-------|
| PySide6 | >=6.5.0 | Yes | Core GUI |
| Pillow | >=9.0.0 | Yes | Image processing |
| PyYAML | >=6.0 | **No** | `import yaml` was removed from config.py; no other yaml usage found. Can be removed from requirements. |

---

*End of audit. Proceed to Phase 2 implementation.*
