# CEREBRO Implementation Issues

Per **CEREBRO Implementation Rules** §6. Log blockers, platform issues, and architectural conflicts.

| Date (UTC) | Area | Note |
|------------|------|------|
| 2026-04-23 | State / UI | `SetActiveTab` + `review_unlocked` gating: all main-tab navigation goes through `CerebroCoordinator.set_active_tab` / store; `AppShell._on_app_state_changed` ends with `_sync_chrome_to_state` (tab strip + page stack). `switch_tab` is a thin dispatch wrapper. |
| 2026-04-23 | State | `AppMode.SCANNING` + `scan_progress` are driven by `ScanStarted`, throttled `ScanProgressSnapshot`, `ScanCompleted` (clears), and `ScanEnded` (cancel/error). `ScanPage` (with `StateStore`) subscribes to `ScanProgressSnapshot` / `ScanStarted` and drives `ScanInProgressView` from `AppState.scan_progress` only. |
| 2026-04-23 | Welcome / persistence | On successful scan, `~/.cerebro/scan_snapshots/last.json` + `scan_<ts>.json` (same `session_ts` as `scan_history` row). Welcome “open session” / recent chips: `load_scan_results_for_session_timestamp` or fall back to last snapshot if timestamps match. |
| 2026-04-23 | Engine | P0: `TurboScanner` no longer divides by zero when `elapsed==0` in the speed log line. Hash cache + Turbo use `cerebro.core.paths.default_cerebro_cache_dir()`. `ScanPage` passes `min_size_bytes` / `max_size_bytes` / `include_hidden` from `load_config()`. `RotatingFileHandler` hardening was already in `cerebro/services/logger.py`. |
| 2026-04-23 | Web / API | No JSON schema export yet; `DuplicateGroup` holds `Path` — boundary mapping deferred to Blueprint Sprint 6. |
| 2026-04-23 | History grid | Scan History sub-tab is state-driven: `history_scan_rows` + sort/filter/page actions; `Deletion History` sub-tab still loads its tree locally (same as before). |
| 2026-04-23 | Blueprint §7 | Dry run (`SetDryRun`, delete ceremony), filter-aware Smart Select, Results name search, `python -m cerebro`, `serialize.app_state_to_doc`, Recycle Bin opener (Diagnostics) — see `BLUEPRINT_SECTION7_STATUS.md` for the full matrix. |
| 2026-04-23 | A11y / render | Skip link + focus rings + keyboard main tabs (`a11y.py`, `TabBar`); store subscriber split into `_apply_*_to_pages` + `_sync_chrome_to_state` in `app_shell.py`. Full WCAG AA not claimed. |


