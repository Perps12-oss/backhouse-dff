# CEREBRO Implementation Issues

Per **CEREBRO Implementation Rules** §6. Log blockers, platform issues, and architectural conflicts.

| Date (UTC) | Area | Note |
|------------|------|------|
| 2026-04-23 | State / UI | `SetActiveTab` + `review_unlocked` gating: all main-tab navigation goes through `CerebroCoordinator.set_active_tab` / store; `AppShell._on_app_state_changed` ends with `_sync_chrome_to_state` (tab strip + page stack). `switch_tab` is a thin dispatch wrapper. |
| 2026-04-23 | State | `scan_progress` and `AppMode.SCANNING` are reserved; `ScanPage` still owns progress UI until progress is merged into the store. |
| 2026-04-23 | Web / API | No JSON schema export yet; `DuplicateGroup` holds `Path` — boundary mapping deferred to Blueprint Sprint 6. |
