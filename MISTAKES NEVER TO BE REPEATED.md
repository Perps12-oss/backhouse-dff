# MISTAKES NEVER TO BE REPEATED

This document records regressions and migration mistakes encountered during the Flet v2 refactor, plus the fix that resolved each one.

## 1) File picker return type mismatch

- **Issue:** Folder picker crashed with `'str' object has no attribute 'path'`.
- **Root cause:** New Flet `FilePicker.get_directory_path()` returns `str | None`, but code expected an object with `.path`.
- **What fixed it:** Use returned string directly (`Path(result)`) and treat falsy result as cancel.
- **Avoid next time:** Always check the exact runtime/API signature when upgrading Flet control services.

## 2) Premature scan completion in UI bridge

- **Issue:** Turbo scanner logs showed many duplicate groups, but UI showed empty results/history with tiny duration.
- **Root cause:** `BackendService` read orchestrator results too early in an async/threaded flow.
- **What fixed it:** Wait for orchestrator completion, then read results and deliver completion on the page/UI thread.
- **Avoid next time:** Never assume `start_*` means completed work; verify if it only schedules background work.

## 3) Nested threading inside Turbo engine caused stale results timing

- **Issue:** UI still got empty/incomplete groups intermittently despite scanner finishing.
- **Root cause:** Turbo engine started its own internal thread from `start()`, so orchestrator completion semantics were broken.
- **What fixed it:** Run Turbo scan work on orchestrator-managed scan thread (single ownership of lifecycle).
- **Avoid next time:** Do not stack unmanaged worker threads in engine adapters unless lifecycle contracts explicitly require it.

## 4) Unsafe control updates before mount

- **Issue:** Runtime errors like `Control must be added to the page first` on results/review.
- **Root cause:** Calling `control.update()` on child controls before they were attached to a page.
- **What fixed it:** Introduced safe update pattern (`_safe_update`) and update parent after tree attachment.
- **Avoid next time:** Treat page attachment as a hard precondition for direct child updates.

## 5) Dialog API drift (`Page.open`/`Page.close`)

- **Issue:** Crashes: `AttributeError: 'Page' object has no attribute 'open'`.
- **Root cause:** Flet API uses `show_dialog` / `pop_dialog` in current versions.
- **What fixed it:** Centralized dialog calls in bridge helpers and replaced all direct open/close usages.
- **Avoid next time:** Abstract framework surface APIs behind bridge/service methods.

## 6) Navigation infinite loop from programmatic rail selection

- **Issue:** App became unresponsive; rail and page continuously re-triggered navigation.
- **Root cause:** `navigate_to()` updated rail `selected_index`, which fired `on_change`, which called `navigate_to()` again.
- **What fixed it:** Early-return guard when navigating to current key.
- **Avoid next time:** Protect all navigation dispatchers against re-entrant same-target transitions.

## 7) Results page froze interaction on large datasets

- **Issue:** Navigation/filter/expand became unresponsive after scans with very large group counts.
- **Root cause:** Synchronous construction of huge result card lists blocked UI event loop.
- **What fixed it:** Chunked/asynchronous incremental list building with cooperative yields.
- **Avoid next time:** Never build very large UI lists in one synchronous pass on the main UI thread.

## 8) State-driven tab sync overriding user navigation

- **Issue:** User selected Settings/Review but view snapped back to Duplicates.
- **Root cause:** Global state listener navigated on too many action types carrying stale `active_tab`.
- **What fixed it:** Restrict shell navigation sync to explicit tab-changing actions.
- **Avoid next time:** Drive route changes only from intentional navigation actions, not generic store churn.

## 9) Off-tab page access assumptions

- **Issue:** Theme/apply/update operations failed when page controls were not currently mounted.
- **Root cause:** Calling page-specific methods on controls that were alive but off-screen.
- **What fixed it:** Use bridge `flet_page` for global operations and guard updates by mounted state.
- **Avoid next time:** Design page components as mount-aware; separate view state mutation from render calls.

## 10) Missing route/state mapping for newly added tab

- **Issue:** Review tab selection/path inconsistencies and reducer mode mismatch.
- **Root cause:** Incomplete updates when adding `review` across valid tab keys + mode mapping.
- **What fixed it:** Add `review` in state constants and reducer tab->mode mapping.
- **Avoid next time:** For every new tab: update routes, valid keys, reducer mapping, and navigation tests together.

## 11) Flet component API migrations not fully applied

- **Issue:** Runtime breakages after dependency updates (`Tabs`, dropdown handlers, enum casing, etc.).
- **Root cause:** Partial migration from old Flet APIs to current APIs.
- **What fixed it:** Full migration sweep (`Colors`, `on_select`, segmented controls, tab labels, etc.).
- **Avoid next time:** Maintain a migration checklist and run a focused compatibility pass per control family.

## Working rules for future refactors

1. Keep framework APIs behind bridge/service wrappers.
2. Guard all UI updates with mount checks.
3. Avoid synchronous rendering of large datasets.
4. Prevent re-entrant navigation loops with same-target early returns.
5. Verify completion semantics in threaded/async orchestration paths.
6. Add regression tests for reducers and route-state sync when introducing tabs/modes.
