# UI Overhaul Audit

## 1. Top-level window class and file

**Class:** `MainWindow` in `cerebro/v2/ui/main_window.py` (1,844 lines)  
Extends `ctk.CTk` (falls back to `tk.Tk`). Entry point: `run_app()` → `MainWindow().run()`.

---

## 2. How navigation currently works

**Single-window, no page stack.** The window is a horizontal `tk.PanedWindow` with three panes:
- Left: `FolderPanel` (folder list + scan options)
- Center: `ResultsPanel` OR `ThumbnailGrid` (swapped via pack/pack_forget)
- Right: `PreviewPanel` (always visible, togglable with Ctrl+P)

"Navigation" is:
- **Mode tabs** at top (`ModeNavPanel` / `ModeTabs` in `mode_tabs.py`) switch the scan engine mode (Files/Photos/Videos/Music/Empty Folders/Large Files) — they do NOT swap pages, they reconfigure the same panels.
- **View toggle** swaps `ResultsPanel` ↔ `ThumbnailGrid` in the center pane.
- **Empty state** (`_GettingStartedView`) is shown inside `ResultsPanel` when no results exist.
- **Scan progress** (`_ScanInProgressView`) overlays the center pane during scan.

The new design's 6-tab page stack (Welcome | Scan | Results | Review | History | Diagnostics) does **not** exist yet — everything is one flat layout.

---

## 3. Where scan progress lands on the main thread

`MainWindow._on_scan_progress()` (line 538) is the callback passed to the engine. It does:
```python
self.after(0, lambda p=progress: self._handle_progress_on_main(p))
```
`_handle_progress_on_main()` (line 548) then calls:
- `self._update_status_bar(progress)`
- `self._results_panel.update_scan_progress(...)` when state == SCANNING
- `self._on_scan_finished(progress.state)` when COMPLETED/CANCELLED/ERROR

A secondary polling loop (`_start_progress_polling`, line 601) also runs every 200ms via `self.after(200, poll)` to keep progress smooth if the engine throttles callbacks.

---

## 4. Where scan completion is handled

`MainWindow._on_scan_finished()` (line 641) → `ScanController.finish_scan()` in `main_window_controllers.py` (line 151).

`finish_scan()` does:
1. Hides scan progress view
2. Stops polling and status bar timer
3. Sets `_scanning = False`, resets toolbar/status bar
4. Calls `self._window._orchestrator.get_results()` to fetch results
5. Calls `_load_results_to_panel()` to populate tree + thumbnail grid
6. Shows `_ScanCompleteBanner` via `results_panel.show_scan_complete()`
7. Records history via `HistoryRecorder.record_completed_scan()`

---

## 5. What `_GettingStartedView` is and where it's shown

**File:** `cerebro/v2/ui/results_panel.py`, line 1782.  
A `CTkFrame` shown in the center panel when no scan results exist. Contains:
- "Find duplicate files" headline (22px bold)
- "Add the folders you want to scan, then hit Search Now." subtitle
- Step 1: `[+ Add Folder]` button
- Step 2: `[▶ Search Now]` button
- "Cerebro v2 — fast duplicate finder" tagline

It is instantiated inside `ResultsPanel.__init__` (line 647) and shown/hidden by `_show_empty_state()` / `_show_results()`. It maps to the new **Welcome page** but will be **REPLACED** (layout topology is completely different from the target spec).

---

## 6. Does `show_scanning_progress()` get called anywhere?

**YES — it is active and wired.** `ScanController.start_search()` in `main_window_controllers.py` (line 134) calls:
```python
self._window._results_panel.show_scanning_progress()
```
`ResultsPanel.show_scanning_progress()` (line 1365) hides the tree/empty view and shows `_ScanInProgressView`. This is the progress display during a live scan. **NOT dead code — keep and rewire.**

---

## 7. Existing WelcomePage equivalent

`_GettingStartedView` (results_panel.py:1782) is the closest equivalent. There is also a compat shim:
```python
def show_welcome_screen(self) -> None:
    self.clear()  # just calls clear()
```
Neither is a full-viewport welcome screen. The new Welcome page (Phase 2) with navy bg, logo, stats, and recent chips needs to be **built from scratch**.

History data source: `cerebro/v2/core/scan_history_db.py` via `get_scan_history_db()`. The DB already stores `timestamp`, `mode`, `folders`, `groups_found`, `files_found`, `bytes_reclaimable`, `duration_seconds`. The `record_scan()` helper lives in `scan_history_dialog.py`.

---

## 8. Existing widgets/components salvage decision

| File | Lines | Decision | Reason |
|------|-------|----------|--------|
| `main_window.py` | 1,844 | **REPLACE shell** | New 6-tab page-stack topology is fundamentally different; engine wiring (scan callbacks, polling, deletion flow) must be preserved and re-plumbed |
| `main_window_controllers.py` | 206 | **KEEP AS-IS** | `HistoryRecorder`, `PreviewCoordinator`, `ScanController` are pure logic, no visual output |
| `mode_tabs.py` | 264 | **RESTYLE IN-PLACE** | Already has 3px bottom underline indicator; just needs color token updates and relocation into Scan page mode bar |
| `toolbar.py` | 459 | **REPLACE** | New design splits this into TitleBar (32px) + TabBar (36px); topology is completely different |
| `folder_panel.py` | 623 | **RESTYLE IN-PLACE** | Structure correct; needs color + font updates; becomes left column of Scan page |
| `results_panel.py` | 2,000 | **PARTIAL REPLACE** | `_ScanInProgressView` + `_ScanCompleteBanner` + scan wiring → KEEP; `_GettingStartedView` → REPLACE; `CheckTreeview` → REPLACE with `VirtualFileGrid` canvas |
| `preview_panel.py` | 539 | **RESTYLE IN-PLACE** | Has ZoomCanvas image preview, side-by-side comparison, metadata table — maps directly to Review page; just needs layout + color updates |
| `scan_history_dialog.py` | 249 | **RESTYLE** | SQLite DB already working; keep all data logic, restyle card layout |
| `deletion_history_dialog.py` | 155 | **RESTYLE** | Keep functionality, restyle |
| `settings_dialog.py` | 784 | **KEEP + SURFACE** | Phase 7: open in CTkToplevel from title bar link |
| `theme_editor_dialog.py` | 355 | **KEEP + SURFACE** | Phase 7: open in CTkToplevel from title bar link |
| `status_bar.py` | 445 | **RESTYLE → Diagnostics** | Metrics display moves into Diagnostics page |
| `selection_bar.py` | 487 | **RESTYLE** | Becomes Results toolbar |
| `feedback.py` | 93 | **KEEP AS-IS** | Dialogs/toasts unchanged |
| `widgets/check_treeview.py` | 560 | **REPLACE** | New design uses canvas-based `VirtualFileGrid` for performance with 1000+ rows |
| `widgets/thumbnail_grid.py` | 510 | **KEEP AS-IS** | Grid view kept for Phase 4 view toggle |
| `widgets/zoom_canvas.py` | 489 | **KEEP AS-IS** | Used by PreviewPanel → Review page |
| `widgets/metadata_table.py` | 244 | **KEEP AS-IS** | Used by PreviewPanel → Review page |

---

## Key wiring to preserve (do not break)

- `ScanOrchestrator.start_scan(folders, protected, options, progress_callback)` — engine entry point
- `progress_callback` must call `self.after(0, ...)` to marshal to main thread
- `_handle_progress_on_main()` pattern — study before wiring new progress consumers
- `ScanController.finish_scan()` result loading sequence
- `HistoryRecorder.record_completed_scan()` — writes to SQLite history DB
- `DeletionEngine.delete_one()` + trash flow in `_on_delete_selected()`
