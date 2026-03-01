# Changes — `audit-stabilize-stress-v1`

## File-by-file summary

### `cerebro/ui/pages/review_page.py`
- **Removed** stale scaffold code (lines referencing `self._scaffold`, `content_wrapper`, `StickyActionBar`, `_on_export_list`) that crashed ReviewPage on construction.
- **Removed** duplicate `from PySide6.QtCore import QItemSelectionModel` import.
- **Added** `_norm_path()` helper for case-insensitive path comparison (Windows-safe).
- **Added** `_compute_group_size()` helper for summing file sizes.
- **Fixed** `_refresh_delete_button()` call → replaced with existing `_update_stats()`.
- **Fixed** `_open_ceremony()`: keep_map lookup now uses raw paths (matching stored keys) instead of normalized paths that would mismatch on Windows.
- **Fixed** `_update_stats()`: iterates `_all_groups` (authoritative) instead of `_filtered_groups` for delete count.
- **Fixed** `refresh_after_deletion()`: keep_states pruning now normalizes both sides for cross-source comparison; removed double `_update_stats()` call.
- **Added** `_reconcile_exists()`: Refresh button handler — removes groups whose files no longer exist on disk.
- **Added** `_trigger_rescan()`: Rescan button handler — re-emits last scan config via StateBus.
- **Added** Refresh and Rescan buttons to the status bar.
- **Removed** `QApplication.processEvents()` from `CleanupProgressDialog.update_progress()` to prevent reentrancy.

### `cerebro/ui/pages/scan_page.py`
- **Added** `COMBO_MIN_WIDTH = 120` and `BUTTON_MIN_HEIGHT = 32` to `LayoutMetrics` (were referenced but undefined).
- **Fixed** Simple/Advanced toggle: button check state now restored from persisted `scan_ui_mode` on page init.
- **Added** `_on_scan_requested()` slot: wires `StateBus.scan_requested` so ReviewPage's Rescan button triggers a new scan.

### `cerebro/ui/pages/audit_page.py`
- **Fixed** `IntegrityAuditWorker`: already fixed on branch (uses `HashCache(db_path)` properly).
- **Fixed** `ReportAuditWorker`: `HashCache()` → `HashCache(db_path)` with proper open/close lifecycle.
- **Fixed** `VerifyAuditWorker`: same HashCache fix + early return when db doesn't exist.
- **Fixed** `ExportAuditWorker`: same HashCache fix.

### `cerebro/ui/pages/hub_page.py`
- **Fixed** cache stats update: `HashCache()` → `HashCache(db_path)` with open/close.
- **Fixed** `_optimize_database()`: same fix + calls `hc.vacuum()` properly.

### `cerebro/services/hash_cache.py`
- **Added** `get_stats()` method (total_entries, cache_size_mb).
- **Added** `vacuum()` method for database optimization.

### `cerebro/ui/main_window.py`
- **Refactored** `PipelineCleanupWorker`: now accepts raw `deletion_plan_dict` and calls `build_delete_plan()` inside `run()` (off UI thread). Added `plan_ready` signal.
- **Added** progress throttling (50ms min interval) to avoid flooding the UI.
- **Added** immediate first progress tick (`0/N Starting…`) before deletion begins.
- **Updated** `_on_cleanup_confirmed()`: no longer calls `build_delete_plan` on UI thread; passes dict to worker.
- **Added** `_on_plan_ready()` slot for plan-built notification.

### New files
- `docs/AUDIT_REPORT.md` — Full P0/P1 audit findings.
- `docs/CHANGES.md` — This file.
- `docs/STRESS_TEST.md` — Stress test usage and pass criteria.
- `sanity/__init__.py` — Package init.
- `sanity/stress_scan.py` — Headless scan stress test.
- `sanity/stress_delete.py` — Headless delete pipeline stress test.

## Checklist

| Item | Status |
|------|--------|
| Smart Select works (applies to all filtered groups, updates counts) | FIXED — keep_map lookup corrected, stats iterate all_groups |
| Delete removes files AND they disappear from Review | FIXED — `_norm_path` + `_compute_group_size` defined, `refresh_after_deletion` operational |
| Refresh/Rescan works | ADDED — Refresh (exists reconcile) + Rescan (re-emit config) buttons in status bar |
| App launches cleanly | FIXED — removed stale scaffold crash, added missing LayoutMetrics constants, fixed HashCache() calls |
| UI thread not blocked during delete | FIXED — build_delete_plan moved to worker thread, processEvents removed |
| Audit page non-fatal | FIXED — all HashCache calls use proper db_path + try/except |
