# Production Readiness Audit Report
**Cerebro v2 — Duplicate File Finder**
**Audit date:** 2026-04-16
**Auditor:** Claude Sonnet 4.6 (automated static analysis, full codebase read)

---

## Executive Summary

| Item | Value |
|------|-------|
| Overall health score | **6 / 10** |
| Critical issues | 2 |
| High issues | 4 |
| Medium issues | 5 |
| Low / informational | 4 |
| Recommended timeline to production readiness | 1–2 focused sprints |

**Top 3 risks to address first:**
1. **Thread-safety violation in scan error path** — Tkinter widget update called from background thread on any scan exception → silent crash or corrupted UI state.
2. **Deadlock potential in `cancel()`** — `ScanOrchestrator.cancel()` calls `thread.join()` while holding an `RLock`; if the scan thread calls any locked method on the orchestrator, both threads block forever.
3. **`update_checker.py` is wrong-framework dead code with an RCE vector** — imports PySide6 (not installed) and executes arbitrary scripts downloaded from an update URL.

---

## Critical Issues

### 🔴 C-1 — Thread-safety violation: error progress fired from background thread
- **File:** `cerebro/engines/orchestrator.py` lines 167–174
- **Category:** Reliability / Threading
- **Severity:** Critical
- **Description:** In `_run_scan()`, when an engine raises an exception the fallback code calls `self._progress_callback(error_progress)` **directly from the scan thread**. `_progress_callback` is the UI progress handler (typically marshalled on the Tk main thread), which updates Tkinter widgets. Tkinter is not thread-safe; calling it from a non-main thread causes silent corruption or segfaults depending on platform.
- **Current behaviour:** Any unhandled exception in an engine during a scan (e.g. `PermissionError` on a locked file) will call the UI callback from the wrong thread. The happy path is safe because engines emit progress through the same callback and the happy path wraps updates in `after(0, ...)`, but the *exception* path may bypass that wrapper.
- **Expected behaviour:** All callbacks to the UI must be dispatched via `root.after(0, ...)`.
- **Fix:**
  ```python
  # orchestrator.py _run_scan() except block — replace:
  self._progress_callback(error_progress)
  # with:
  import tkinter as _tk
  try:
      root = _tk._default_root  # type: ignore[attr-defined]
      if root:
          root.after(0, lambda p=error_progress: self._progress_callback(p))
          return
  except Exception:
      pass
  self._progress_callback(error_progress)  # fallback if no Tk root
  ```
- **Effort:** Small

---

### 🔴 C-2 — Deadlock: `cancel()` calls `thread.join()` while holding `RLock`
- **File:** `cerebro/engines/orchestrator.py` lines 188–196
- **Category:** Reliability / Threading
- **Severity:** Critical
- **Description:** `cancel()` acquires `self._lock` (an `RLock`) and then calls `self._scan_thread.join(timeout=5.0)`. If the scan thread, while winding down, calls any `ScanOrchestrator` method that also acquires `self._lock` (e.g. `is_scanning()`, `get_progress()`), the scan thread will block waiting for the lock while `cancel()` blocks waiting for the thread → deadlock. Both threads hang forever; the 5-second timeout is the only escape.
- **Current behaviour:** Intermittent hang on "Stop" or mode-switch during an active scan; resolves after 5 s timeout but leaves engine in undefined state.
- **Expected behaviour:** `join()` must be called **outside** the lock.
- **Fix:**
  ```python
  def cancel(self) -> None:
      with self._lock:
          if self._active_engine:
              self._active_engine.cancel()
          thread = self._scan_thread  # capture reference
      # join outside the lock
      if thread and thread.is_alive():
          thread.join(timeout=5.0)
  ```
- **Effort:** Small

---

## High Issues

### 🟠 H-1 — `update_checker.py`: wrong framework, dead import, arbitrary script execution
- **File:** `cerebro/services/update_checker.py` lines 21–23, 551–566
- **Category:** Security / Dead code
- **Severity:** High
- **Description:** This file imports `PySide6.QtCore` — a Qt binding not listed in `requirements.txt` and not used anywhere in the v2 CustomTkinter codebase. The import will raise `ModuleNotFoundError` if this module is ever triggered. More critically, lines 551–566 call `subprocess.run(["cmd", "/c", str(pre_script)])` and `subprocess.run(["bash", str(pre_script)])` where `pre_script` is a path to a script fetched as part of an update package. If the update download URL is ever compromised (MITM or supply-chain), an attacker can execute arbitrary code on the user's machine with no sandboxing.
- **Fix:** Remove `update_checker.py` from the v2 codebase entirely, or at minimum gate the file behind a `try/except ImportError` and never call the script-execution code paths without signature verification of the downloaded content.
- **Effort:** Small (delete) / Large (proper code-signing update flow)

---

### 🟠 H-2 — Column display corruption after sorting
- **File:** `cerebro/v2/ui/widgets/check_treeview.py` `sort_by_column()` lines 498–516
- **Category:** Reliability / UI correctness
- **Severity:** High
- **Description:** `sort_by_column()` reads the full stored values for each row via `self.item(child_id, "values")` — this includes the checkbox icon string (`☐`/`☑`) at index 0. It then re-inserts each row via `insert_item(..., values=full_values_with_icon)`. Inside `insert_item`, the method prepends **another** checkbox icon: `combined_values = (check_icon,) + tuple(file_values)`. After one sort the first column shows `☐☐` or `☑☑`; repeated sorts add more.
- **Current behaviour:** Checkbox column shows double (or more) icons after any column sort. First data column (`Name`) is pushed right.
- **Fix:** Strip the first element from `values` before re-inserting, or fetch values from `_item_values` cache instead:
  ```python
  # in sort_by_column, replace the values read with:
  cached = self._item_values.get(child_id)
  values = cached if cached is not None else self.item(child_id, "values")[1:]
  children_with_values.append((child_id, values))
  # then insert_item receives clean file values without icon
  ```
- **Effort:** Small

---

### 🟠 H-3 — O(n) `get_checked_item_ids()` scan on every row click
- **File:** `former monolithic UI module (deleted)` lines 1043–1045, 1050–1052
- **Category:** Performance
- **Severity:** High (becomes critical at 200k items)
- **Description:** `_on_tree_preview_focus()` and `_on_thumbnail_grid_focus()` both call `self._results_panel._get_checked_item_ids()` to update the preview panel. This triggers `self._treeview.get_checked()` which iterates the full `_item_states` dict. At 200k items this runs on **every single row click**, causing noticeable input lag.
- **Fix:** Cache the last known checked list in `ResultsPanel` and only recompute it when state actually changes (after `apply_selection_rule`, `set_check`, etc.). For preview focus specifically, `_get_checked_item_ids()` is only needed to pick the first two items; short-circuit once two are found.
- **Effort:** Medium

---

### 🟠 H-4 — F5 "Refresh" shortcut is a no-op (advertised in help)
- **File:** `former monolithic UI module (deleted)` lines 1088–1091
- **Category:** Reliability / UX
- **Severity:** High
- **Description:** `_on_refresh()` logs "Refresh / re-scan requested" and contains only a `# TODO` comment. The shortcut `F5` is listed in the Keyboard Shortcuts help dialog, so users will expect it to re-run the last scan. Pressing F5 silently does nothing.
- **Fix:** Implement `_on_refresh()` to call `self._scan_controller.start_search()` if folders are configured and no scan is running; or at minimum remove F5 from the help text until implemented.
- **Effort:** Small

---

## Medium Issues

### 🟡 M-1 — Escape key handler is a no-op outside scanning
- **File:** `former monolithic UI module (deleted)` lines 1093–1099
- **Category:** UX / Reliability
- **Severity:** Medium
- **Description:** `_on_escape()` stops the scan if running (correct), but the `else` branch is an empty `# TODO`. Per the help dialog, Escape should "close dialogs" — currently pressing Escape while in review mode does nothing.
- **Fix:** Call `self._complete_banner_dismiss()` or close the topmost open dialog on Escape.
- **Effort:** Small

---

### 🟡 M-2 — Preview pixel-diff overlay unimplemented
- **File:** `cerebro/v2/ui/preview_panel.py` line 343
- **Category:** UX
- **Severity:** Medium
- **Description:** The "Diff" toggle button in the preview panel calls `_on_diff_toggled()` which is a no-op (`pass # TODO`). The button is visible to the user and appears interactive.
- **Fix:** Either implement the diff overlay or hide/disable the button until implemented.
- **Effort:** Medium

---

### 🟡 M-3 — `pickle` imported but unused (dead import, confusion risk)
- **Files:** `cerebro/services/cache_manager.py` line 8, `cerebro/core/scanners/turbo_scanner.py` line 33
- **Category:** Code quality / Security (precautionary)
- **Severity:** Medium
- **Description:** Both files import `pickle` but no `pickle.load` / `pickle.dump` / `pickle.loads` / `pickle.dumps` calls exist anywhere in the codebase. The imports are dead. `pickle` deserialization of untrusted data is a known RCE vector; leaving the import suggests it may have been planned and leaving it is a code hygiene issue.
- **Fix:** Remove the unused `import pickle` lines.
- **Effort:** Trivial

---

### 🟡 M-4 — Turbo-scanner cache integration is a stub
- **File:** `cerebro/core/scanners/turbo_scanner.py` line 610
- **Category:** Reliability
- **Severity:** Medium
- **Description:** The incremental cache infrastructure (`cache_manager.py`) is built but the scanner has `# TODO: Load files from cache` at the integration point. Every scan re-hashes all files from scratch even if the directory is unchanged.
- **Fix:** Connect `CacheManager.load()` / `CacheManager.save()` at the stub location.
- **Effort:** Medium

---

### 🟡 M-5 — `explorer /select,` path argument not quoted on Windows
- **File:** `cerebro/v2/ui/results_panel.py` line 995
- **Category:** Reliability
- **Severity:** Medium
- **Description:** `subprocess.Popen(["explorer", "/select,", path])` passes the path as a separate list element. On some Windows versions, `explorer.exe` requires the flag and path to be a single concatenated argument (`/select,C:\path\to\file`). Paths with spaces currently open the wrong folder or do nothing silently.
- **Fix:** `subprocess.Popen(["explorer", f"/select,{path}"])`
- **Effort:** Trivial

---

## Low / Informational

### 🔵 L-1 — `_on_escape()` and `_on_refresh()` have empty `else` branches documented as TODO
Already captured in M-1 and H-4 above.

### 🔵 L-2 — `advanced_scanner.py` has an unimplemented CHECKPOINT TODO (line 1125)
Checkpoint/resume for long scans is wired but empty.

### 🔵 L-3 — `update_checker.py` makes HTTP requests with no certificate pinning
`urllib.request.urlopen` performs standard OS certificate validation but no pinning. Acceptable for a desktop app; worth noting for threat model documentation.

### 🔵 L-4 — Double-import of `sys` and `subprocess` inside methods
`results_panel.py` `_open_file` / `_open_folder` and `former monolithic UI module (deleted)` `_undo` do `import sys, subprocess` inside the method body on every call. These are module-level stdlib imports; move them to the top of the file.

---

## Stress Test Plan (Phase 2 — to run manually)

The following script exercises the core hot paths at 200k scale. Run from the project root with a folder containing ≥200k files:

```python
# stress_test.py
import time, tracemalloc, sys
from pathlib import Path
from cerebro.engines.orchestrator import ScanOrchestrator
from cerebro.engines.base_engine import ScanState

def run(folder: str) -> None:
    tracemalloc.start()
    t0 = time.perf_counter()

    orc = ScanOrchestrator()
    orc.set_mode("files")

    done = False
    def on_progress(p):
        nonlocal done
        if p.state in (ScanState.COMPLETED, ScanState.CANCELLED, ScanState.ERROR):
            done = True

    orc.start_scan([Path(folder)], [], {}, on_progress)
    while not done:
        time.sleep(0.2)

    elapsed = time.perf_counter() - t0
    results = orc.get_results()
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    print(f"Scan: {elapsed:.1f}s | Groups: {len(results):,} | "
          f"Files: {sum(len(g.files) for g in results):,} | "
          f"Peak RAM: {peak/1024/1024:.1f} MB")

if __name__ == "__main__":
    run(sys.argv[1])
```

**Scenarios to measure:**
1. Cold scan (no cache): `python stress_test.py D:\large_folder`
2. Warm scan (second run): repeat immediately — should be faster once cache is wired (M-4)
3. Cancel mid-scan: add `orc.cancel()` after 2 seconds — verify no deadlock (C-2)

---

## Summary Table

| # | Issue | Severity | Category | File |
|---|-------|----------|----------|------|
| C-1 | Thread-safety: error callback from scan thread | Critical | Reliability | orchestrator.py:167 |
| C-2 | Deadlock: join() inside RLock | Critical | Reliability | orchestrator.py:196 |
| H-1 | update_checker.py — dead code + RCE vector | High | Security | update_checker.py:21,551 |
| H-2 | Column corruption after sort (double icon) | High | UI Correctness | check_treeview.py:498 |
| H-3 | O(n) scan on every row click | High | Performance | former monolithic UI module (deleted):1043 |
| H-4 | F5 refresh is a no-op | High | UX | former monolithic UI module (deleted):1091 |
| M-1 | Escape key no-op outside scan | Medium | UX | former monolithic UI module (deleted):1098 |
| M-2 | Pixel-diff button no-op | Medium | UX | preview_panel.py:343 |
| M-3 | Unused `import pickle` | Medium | Code quality | cache_manager.py:8, turbo_scanner.py:33 |
| M-4 | Scan cache stub not connected | Medium | Reliability | turbo_scanner.py:610 |
| M-5 | explorer /select, path not concatenated | Medium | Reliability | results_panel.py:995 |
| L-1 | Dead `import sys, subprocess` inside methods | Low | Code quality | results_panel.py:979,991 |
| L-2 | Advanced scanner checkpoint is a stub | Low | Reliability | advanced_scanner.py:1125 |
| L-3 | HTTP update check, no certificate pinning | Low | Security | update_checker.py |
| L-4 | Keyboard shortcut help lists unimplemented keys | Low | UX | former monolithic UI module (deleted):441 |

---

## Recommended Fix Order

1. **C-2** — Deadlock in `cancel()` — 15 min, zero risk
2. **C-1** — Thread-safety in error path — 20 min, zero risk
3. **H-2** — Sort double-icon bug — 10 min, directly visible to users
4. **M-5** — `explorer /select,` concatenation — 5 min, trivial
5. **M-3** — Remove dead `import pickle` — 5 min, trivial
6. **L-4** — Move `import sys, subprocess` to module level — 5 min
7. **H-4** — Implement F5 refresh — 30 min
8. **M-1** — Escape key dismiss banner/dialog — 20 min
9. **H-3** — Cache checked list to avoid O(n) on every click — 1 hr
10. **M-2** — Hide diff button until implemented — 10 min
11. **H-1** — Remove / quarantine `update_checker.py` — 30 min
12. **M-4** — Connect scan cache — 2–4 hrs (larger scope)
