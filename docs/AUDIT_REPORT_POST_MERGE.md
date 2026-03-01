# CEREBRO Post-Merge Audit Report

**Date:** 2026-03-01
**Branch:** `merge-integrate-v6-into-main`
**Auditor:** Opus 4.6 — automated multi-agent pass

---

## Executive Summary

Integration branch merges all 7 ui/overhaul-v6 commits into the main+audit-stabilize
codebase. Post-merge audit found **3 P0 issues** (all fixed), **5 P1 issues** (2 fixed,
3 documented for future work), and **9 P2 issues** (documented).

---

## P0 — Critical (Fixed)

### P0-1  `get_cache_dir()` missing from config.py
**Status:** FIXED in commit `e50f7a2`
**Impact:** `audit_page.py`, `hub_page.py` import `get_cache_dir` — would crash on any
audit/hub operation.
**Fix:** Added `get_cache_dir()` to `cerebro/services/config.py`.

### P0-2  `QApplication.processEvents()` in review_page.py
**Status:** FIXED in commit `cf83d0c`
**Impact:** UI thread safety violation in `CleanupProgressDialog.update_progress()`.
**Fix:** Removed the call.

### P0-3  Duplicate `QItemSelectionModel` import in review_page.py
**Status:** FIXED in commit `cf83d0c`
**Impact:** Import error on some Python versions.
**Fix:** Removed duplicate import line.

---

## P1 — High (Partially Fixed)

### P1-1  `UISettings` missing `scan_ui_mode` field
**Status:** FIXED in commit `e50f7a2`
**Impact:** Setting wouldn't persist across restarts.
**Fix:** Added `scan_ui_mode: str = "simple"` to `UISettings`. Also made `from_dict`
resilient to unknown keys.

### P1-2  Gemini theme keys not in config validation whitelist
**Status:** FIXED in commit `328d12c`
**Impact:** "Invalid theme 'gemini'" warning on startup.
**Fix:** Added `gemini`, `gemini_light`, and other theme keys to `valid_themes`.

### P1-3  Logger class import in pipeline.py / deletion.py
**Status:** DOCUMENTED — not a crash (wrapped in try/except)
**Impact:** `self._logger` is None, so pipeline/deletion have no structured logging.
**Recommendation:** Replace `from ..services.logger import Logger` with
`from ..services.logger import get_logger; self._logger = get_logger(__name__)`.

### P1-4  I/O on UI thread in review_page.py
**Status:** DOCUMENTED — pre-existing from overhaul branch
**Impact:** `os.path.getsize()` loops in `_update_stats`, `_open_ceremony`,
`_reconcile_with_filesystem`, `refresh_after_deletion` can cause short UI freezes
with large datasets.
**Recommendation:** Move file-size computation to worker threads, or precompute
`recoverable_bytes` in scanner results.

### P1-5  Redundant refresh calls in delete flow
**Status:** DOCUMENTED
**Impact:** `refresh_after_deletion` called twice (directly from MainWindow +
via `deletion_completed` signal).
**Recommendation:** Remove one call path.

---

## P2 — Medium/Low (Documented)

| # | Issue | File | Notes |
|---|-------|------|-------|
| P2-1 | `QFrame.NoFrame` deprecated style | theme_page.py | Use `QFrame.Shape.NoFrame` |
| P2-2 | `_reconcile_with_filesystem` size calc not per-path try/except | review_page.py | One failing path zeros out entire group |
| P2-3 | Smart Select double UI update | review_page.py | `_refresh_all_ui()` + separate `_update_stats()` |
| P2-4 | `_compute_delete_count` uses `_filtered_groups` not `_all_groups` | review_page.py | Intentional (filter-scoped) but docs say otherwise |
| P2-5 | Synchronous `QPixmap` image loading | review_page.py | Can block for large images |
| P2-6 | `PerformanceSettings.from_dict` doesn't filter unknown keys | config.py | Will crash if config has extra keys |
| P2-7 | `requirements.txt` in wrong location | docs/read me/ | Should be at project root |
| P2-8 | `send2trash` not in requirements | — | Used by deletion.py for trash mode |
| P2-9 | Circular import risk tokens → theme_engine | _tokens.py | Low risk with lazy imports |

---

## Smoke Check Results

| Check | Status |
|-------|--------|
| App boots (MainWindow initializes) | PASS |
| All 8 pages registered | PASS |
| ThemePage loads | PASS |
| ScanPage loads (Scan Complete view present) | PASS |
| ReviewPage loads (floating delete button present) | PASS |
| Theme persistence (Gemini applies/persists) | PASS |
| DeletionPolicyChooserDialog importable | PASS |
| StateBus has scan_requested + deletion_completed | PASS |
| Pipeline importable and constructible | PASS |
| get_cache_dir() works | PASS |
| Config scan_ui_mode persists | PASS |

---

## Selection Model & Delete Flow Audit

| Aspect | Status |
|--------|--------|
| `_keep_states` structure (Dict[int, List[bool]]) | Correct |
| Keeper excluded from delete list in `_open_ceremony` | Correct |
| `refresh_after_deletion` removes deleted paths | Correct |
| `_reconcile_with_filesystem` handles missing files | Correct |
| `_refresh_delete_button` defined and wired | Correct |
| `_compute_delete_count` consistent with status bar | Correct |
| Floating delete button same source as status bar | Correct |
| `_norm_path` defined and used consistently | Correct |
| No accidental keeper-in-delete paths | Verified |

---

## HashCache / Service Init Audit

| Check | Status |
|-------|--------|
| audit_page.py: HashCache with explicit db_path + open/close | Correct |
| hub_page.py: HashCache with explicit db_path + open/close | Correct |
| No `HashCache()` calls without arguments | Verified |
| `get_cache_dir()` exists in config.py | Fixed (P0-1) |

---

## Stress Harness

Pre-existing stress scripts in `sanity/` directory:
- `sanity/stress_scan.py` — large scan test (500k+ files)
- `sanity/stress_delete.py` — deletion plan stress test

These were preserved from the audit-stabilize branch and remain functional.
