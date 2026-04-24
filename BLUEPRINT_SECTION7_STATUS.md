# Cerebro Blueprint v2.0 - Section 7 (Acceptance Criteria) status

This file maps `Cerebro_Blueprint_v2.0.md` §7 to the current tree. "Met" does not imply zero follow-up (e.g. full WCAG audit).

| Criterion | Status | Notes |
|-----------|--------|--------|
| UI reflects state; no manual sync; render after dispatch | **Partial** | AppShell subscriber uses explicit `_apply_*_to_pages` methods + one `_sync_chrome_to_state`; per-page caches remain for performance. |
| No duplicate primary data (e.g. `tree_data`) | **Met** | No `tree_data`; v2 state holds canonical `groups` / history row lists. |
| Async does not block UI | **Met** | Scan and delete use worker threads; progress via `after(0, …)` / same patterns. |
| No ad-hoc cross-page wiring; state + coordinator | **Met** | Primary v2 path uses `CerebroCoordinator` and actions. |
| P0 engine bugs (rotation, 0s, hash cache, min size) | **Met (tracked)** | See `CEREBRO_IMPLEMENTATION_ISSUES.md` / prior fixes. |
| Dry-run (preview, no file changes) | **Met** | `SetDryRun` + `AppState.dry_run`; `run_delete_ceremony(..., dry_run=True)`; Review/Results checkboxes. |
| Filter-aware Smart Select (no incomplete groups) | **Met** | `ReviewPage._apply_smart_select` requires every group member in `self._rows`. |
| History + Duplicates: search, sort, filter, pagination | **Partial** | History: sort/filter/pagination in state. Results (Duplicates file list): search (`results_text_filter`) + type filter + sort; virtual list (not paged). |
| Recycle Bin + restorable | **Partial** | `send2trash` in delete path; `open_system_recycle_bin()` in Diagnostics; OS restore. |
| WCAG 2.1 AA | **Not met (incremental)** | 2.4.1 (skip to main), 2.4.7 (focus ring on main tabs + skip), keyboard tab bar (Left/Right/Home/End/Enter/Space), `focus_ring` token; color contrast and AT still need a full pass. |
| Engine / CLI without UI | **Met** | `python -m cerebro` via `cerebro/__main__.py`. |
| State JSON (web prep) | **Met** | `cerebro.v2.state.serialize.app_state_to_doc` (no raw `Path` in JSON). |

Document sources in repo root: `Cerebro_Blueprint_v2.0.md`, `CEREBRO_Implementation_Rules.md`.
