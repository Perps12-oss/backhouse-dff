# CEREBRO Implementation Issues

Per **CEREBRO Implementation Rules** §6. Log blockers, platform issues, and architectural conflicts.

| Date (UTC) | Area | Note |
|------------|------|------|
| 2026-04-23 | State / UI | `SetActiveTab` + `review_unlocked` gating: all main-tab navigation goes through `CerebroCoordinator.set_active_tab` / store; `AppShell._on_app_state_changed` ends with `_sync_chrome_to_state` (tab strip + page stack). `switch_tab` is a thin dispatch wrapper. |
| 2026-04-23 | State | `AppMode.SCANNING` + `scan_progress` are driven by `ScanStarted`, throttled `ScanProgressSnapshot`, `ScanCompleted` (clears), and `ScanEnded` (cancel/error). `ScanPage` still updates `ScanInProgressView` locally; the store is the source of truth for other readers. |
| 2026-04-23 | Engine | P0: `TurboScanner` no longer divides by zero when `elapsed==0` in the speed log line. Hash cache + Turbo use `cerebro.core.paths.default_cerebro_cache_dir()`. `ScanPage` passes `min_size_bytes` / `max_size_bytes` / `include_hidden` from `load_config()`. `RotatingFileHandler` hardening was already in `cerebro/services/logger.py`. |
| 2026-04-23 | Web / API | No JSON schema export yet; `DuplicateGroup` holds `Path` — boundary mapping deferred to Blueprint Sprint 6. |
| 2026-04-23 | History grid | Scan History sub-tab is state-driven: `history_scan_rows` + sort/filter/page actions; `Deletion History` sub-tab still loads its tree locally (same as before). |
