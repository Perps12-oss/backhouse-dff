# MERGE PLAN — Integrate `ui/overhaul-v6` into `main`

**Date:** 2026-03-01
**Integration branch:** `merge-integrate-v6-into-main`
**Base:** `audit-stabilize-stress-v1` @ `3f2dcb8` (= main + 5 P0 fix commits)
**Source:** `ui/overhaul-v6` @ `f229979`

---

## Assumptions

1. **Branch base is `audit-stabilize-stress-v1`, not bare `main`.**
   The audit branch is 5 commits ahead of main with critical P0 fixes
   (boot crash, delete crash, UI-thread safety). Branching from bare main
   would lose them.

2. **Manual merge, not git merge.** Due to a locked log file preventing
   `git merge`, files were checked out individually from ui/overhaul-v6
   and conflicts resolved manually per the strategy below.

---

## Commits Integrated from `ui/overhaul-v6`

| Hash | Title | Status |
|------|-------|--------|
| `a32e9f6` | chore(ui): add overhaul v6 folder layout and spec | Integrated |
| `06bbd29` | feat(ui): Gemini 2 theme, Windows-only guard, global toolbar, tooltips | Integrated |
| `de31434` | feature: scan auto-navigation | Integrated |
| `52443ef` | chore: sync delete flow UI and add evaluation doc | Integrated |
| `dcc4841` | feat(ui): deletion refresh, Gemini 2 Review + Scan Complete | Integrated |
| `feff7a0` | Review & Scan UI: deletion fixes, bottom bar spacing, scan complete | Integrated |
| `f229979` | feat(ui): premium theme page with filter chips, curated palettes | Integrated |

## Commits Preserved from `main` + `audit-stabilize-stress-v1`

| Hash | Title | Status |
|------|-------|--------|
| `20f08fe` | fix: unified delete flow + scan Simple/Advanced mode toggle | Preserved |
| `f3e4fdf` | fix: best-of-5-agents improvements (shortcut conflict, pipeline, scan_id) | Preserved |
| `107b60c` | fix(P0): boot/integrity/deps — remove stale scaffold, fix HashCache init | Preserved |
| `592d03c` | fix(P0): review correctness — authoritative stats, keep_map, Refresh/Rescan | Preserved |
| `1e99ac0` | fix(P0): UI-thread safety — off-thread plan building, throttled progress | Preserved |
| `3337394` | feat(P1): ScanPage Simple/Advanced — persist toggle, wire scan_requested | Preserved |
| `3f2dcb8` | feat: stress harness + CHANGES.md + STRESS_TEST.md | Preserved |

---

## File-Level Conflict Resolution

### Non-conflicting (taken from ui/overhaul-v6 directly)
- `cerebro/ui/pages/theme_page.py` — premium ThemePage with filter chips
- `cerebro/ui/theme_engine.py` — Gemini/Gemini Light themes
- `cerebro/ui/components/modern/theme_card.py` — premium card presentation
- `cerebro/ui/components/modern/_tokens.py` — token additions
- `cerebro/ui/state_bus.py` — deletion_completed + scan_requested signals
- `cerebro/ui/pages/start_page.py` — hero drop zone, tooltips
- `cerebro/ui/pages/base_station.py`, `history_page.py`, `settings_page.py`, `station_navigator.py`
- `cerebro/ui/pages/delete_confirm_dialog.py` — DeletionPolicyChooserDialog
- `cerebro/ui/widgets/*` — intent_card, live_scan_panel, modern_card, page_card
- `cerebro/ui/components/modern/*` — content_card, folder_picker, etc.
- `cerebro/ui/components/section_card.py`, `cerebro/utils/ui_utils.py`
- `cerebro/ui/ui_state.py`, stub `__init__.py` files
- `main.py` — Windows platform guard
- `docs/UI_OVERHAUL_V6.md`, `docs/REFACTOR_ARCHITECTURE_V6.md`

### Kept from audit-stabilize (stability source)
- `cerebro/services/config.py` — get_cache_dir, removed yaml import
- `cerebro/services/hash_cache.py` — get_stats/vacuum with proper init
- `cerebro/ui/pages/audit_page.py` — HashCache init with explicit db_path
- `cerebro/ui/pages/hub_page.py` — HashCache init with explicit db_path
- `cerebro/core/pipeline.py` — lenient pipeline, scan_id handling
- `sanity/` stress harness scripts
- `docs/AUDIT_REPORT.md`, `docs/CHANGES.md`, `docs/STRESS_TEST.md`

### Manually Merged (conflict resolution)

#### `cerebro/ui/main_window.py`
- **Base:** overhaul version (global toolbar, navigation, keyboard shortcuts, Help menu)
- **Ported from audit-stabilize:**
  - Unified PipelineCleanupWorker (combines plan building + execution in one thread)
  - Removed separate PlanBuilderThread (race condition risk)
  - plan_ready signal (int) + _on_plan_ready slot
  - Throttled progress emission (50ms debounce)
  - Lenient _normalize_deletion_plan (skip ambiguous groups, don't raise)
- **Preserved from overhaul:**
  - Global toolbar with scanner mode combo, nav buttons, theme toggle
  - ThemedStack with QSize hint override (prevents layout thrashing)
  - Keyboard shortcuts (Ctrl+N, F5, Ctrl+S, Delete)
  - Help menu with About dialog
  - Window sizing (800×600 default, no max, no custom WindowFlags)
  - Scan complete: no auto-navigate (user clicks "Review Duplicates" CTA)
  - Post-delete: direct refresh + deletion_completed emit

#### `cerebro/ui/pages/scan_page.py`
- **Taken entirely from overhaul** — it already has all features:
  - Scan Complete state (QStackedWidget, stat cards, Review CTA)
  - Simple/Advanced mode with persistence
  - LayoutMetrics with COMBO_MIN_WIDTH, BUTTON_MIN_HEIGHT
  - scan_requested handling from StateBus
  - Drag-and-drop folder support

#### `cerebro/ui/pages/review_page.py`
- **Taken from overhaul** (Gemini 2 layout, Smart Select FAB, DeletionPolicyChooserDialog)
- **P0 fixes applied:**
  - Removed `QApplication.processEvents()` (UI thread safety)
  - Removed duplicate `QItemSelectionModel` import
  - Scaffold references are valid in overhaul (not stale like in degraded main version)
  - `_norm_path` already defined at module level in overhaul
  - `_refresh_delete_button` already defined in overhaul
  - `_compute_group_size` computed inline in overhaul (not needed as separate helper)

---

## Commit Discipline

1. `merge: restore ThemePage refactor from ui/overhaul-v6`
2. `merge: restore ScanPage refactor from ui/overhaul-v6 with main wiring preserved`
3. `merge: resolve Review/MainWindow integration conflicts (delete/smart select/persistence)`
4. `chore: update docs/MERGE_PLAN.md with final commit hashes applied`
