# CHANGES — Post-Merge Integration

**Branch:** `merge-integrate-v6-into-main`
**Date:** 2026-03-01

---

## What was integrated

### From `ui/overhaul-v6` (7 commits):
- **ThemePage:** Premium theme page with filter chips, curated palettes, compact layout
- **ThemeEngine:** Gemini + Gemini Light themes (`#00C4B4` accent)
- **ScanPage:** Scan Complete state (QStackedWidget, 4 stat cards, Review Duplicates CTA)
- **ReviewPage:** Gemini 2 minimal layout (left collapsible nav, center hero comparison,
  Smart Select FAB + popover, DeletionPolicyChooserDialog, post-delete Refresh/Rescan)
- **MainWindow:** Global toolbar (scanner mode, nav buttons, theme toggle), keyboard
  shortcuts, Help menu, ThemedStack with stable size hints
- **StateBus:** `scan_requested`, `deletion_completed` signals
- **Other:** start_page hero, base_station, history_page, settings_page, station_navigator,
  delete_confirm_dialog, widgets, components, main.py Windows guard

### From `main` + `audit-stabilize-stress-v1` (7 commits preserved):
- **Pipeline:** Lenient pipeline, scan_id handling
- **MainWindow:** Unified PipelineCleanupWorker (off-thread plan building + execution,
  throttled progress at 50ms, plan_ready signal)
- **ReviewPage:** processEvents removal, duplicate import fix
- **Config:** get_cache_dir, scan_ui_mode persistence, Gemini theme key validation
- **HashCache:** Proper init with explicit db_path in audit_page + hub_page
- **Stress harness:** sanity/stress_scan.py, sanity/stress_delete.py

---

## Conflicts resolved

| File | Resolution |
|------|-----------|
| `main_window.py` | Overhaul UI (toolbar, shortcuts, Help) + audit-stabilize worker (unified plan+execute, throttled) |
| `review_page.py` | Overhaul UI (Gemini 2 layout) + P0 fixes (processEvents, import dedup) |
| `scan_page.py` | Overhaul version directly (already had all audit-stabilize features) |
| `config.py` | Audit-stabilize base + added get_cache_dir, scan_ui_mode, Gemini theme keys |
| `hash_cache.py` | Kept audit-stabilize version |
| `audit_page.py` | Kept audit-stabilize version (proper HashCache init) |
| `hub_page.py` | Kept audit-stabilize version (proper HashCache init) |

---

## Post-merge fixes applied

1. `get_cache_dir()` added to config.py (P0)
2. `scan_ui_mode` field added to `UISettings` dataclass (P1)
3. `fields` import added to config.py for `UISettings.from_dict` (P0)
4. Gemini/Gemini Light theme keys added to config validation whitelist (P1)
5. `QApplication.processEvents()` removed from review_page.py (P0)
6. Duplicate `QItemSelectionModel` import removed from review_page.py (P0)
7. `_normalize_deletion_plan` made lenient (skip ambiguous groups, don't raise) (P1)
