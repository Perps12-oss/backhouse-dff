# Deferred Legacy Revivals

Running backlog of features that exist in the legacy `MainWindow`-era code
but are **not yet** wired into the new `AppShell`. Maintained across phases
so we don't lose sight of useful work already paid for — or spend time
rebuilding something the old UI already solved.

Rules:
- A feature lands here when we skip it during a phase to stay on-scope.
- A feature is removed from this list when it's revived into AppShell or
  explicitly retired with a brief note (replaced by X, no longer wanted, …).
- "Piggyback-cheap" means < ~50 lines of new code and only touches a file
  we're already editing for another task.

---

## Revived to date
| Feature | Source | Phase revived |
|---|---|---|
| Delete ceremony (4 dialogs + celebration) | `main_window.py _DeleteDialog/_DeleteProgressDialog/_DeleteSummaryDialog/_DeleteCelebration` | Phase 4.1 (lazy import) |
| Zoom/pan canvas + synced A/B comparison | `widgets/zoom_canvas.py`, `preview_panel.py` | Phase 6 (grid → comparison view) |
| MetadataTable inside side preview | `widgets/metadata_table.py` | Phase 6 (via PreviewPanel composition) |
| Undo toast after delete | `main_window.py _UndoToast` | Phase 6 (piggyback lazy import) |

---

## Deferred

### 1. Scan mode tabs (Files / Photos / Video / Music)
**Source**: `cerebro/v2/ui/mode_tabs.py` — `ScanMode`, `_Tab`
**Cost**: medium. New widget row on Scan/Welcome page; mode threaded through `ScanOrchestrator`, per-mode UI layout adjustments, settings bucket already exists (`photo_mode`, `video_mode`, `music_mode`).
**Value**: media-aware defaults (file size, hash algorithm, extensions filter) without pushing users into the Settings dialog.
**Suggested phase**: next phase that touches the Scan page.
**Acceptance**: tab row visible on `ScanPage`; picking "Photos" pre-fills extensions from `settings.photo_mode.formats`; orchestrator passed the picked mode so the scanner picks the right engine.

### 2. Animated "Scan complete" banner
**Source**: `cerebro/v2/ui/results_panel.py _ScanCompleteBanner` (lines 61–303)
**Cost**: medium. Self-contained widget but uses a color-blend animation loop with timed `after()` chains. ~150 lines to port.
**Value**: small — nice-to-have visual signal that the scan has finished. Current `ResultsPage` shows stats immediately; banner adds polish, not function.
**Suggested phase**: UX polish phase (unplanned).

### 3. `CheckTreeview` (legacy list view)
**Source**: `cerebro/v2/ui/widgets/check_treeview.py`
**Cost**: N/A.
**Status**: **retire**. Phase 5's `VirtualFileGrid` already replaces this with better performance. Keep the file for one release cycle as reference, then delete.

### 4. `ScanFolderList` / `ProtectFolderList`
**Source**: `cerebro/v2/ui/folder_panel.py`
**Cost**: N/A.
**Status**: **retire**. Phase 4 replaced these with `_SearchFoldersList` in `scan_page.py`. Pattern is kept in this backlog only so we don't rebuild them by accident.

### 5. `SelectionBar` with `SelectionRule` catalog
**Source**: `cerebro/v2/ui/selection_bar.py` (84–401)
**Cost**: small. Mostly-static rule catalog + display-name table; the "selected count / total items" chip is the only live UI.
**Value**: two wins — (a) the Auto Mark dropdown in the Results toolbar could share `SelectionRule.all_rules()` instead of hard-coding `_AUTO_MARK_OPTS` in `_ActionToolbar._AUTO_MARK_OPTS`; (b) a persistent "N selected / M total" chip on the Results page.
**Suggested phase**: next phase that touches `ResultsPage._ActionToolbar`.
**Acceptance**: `_AUTO_MARK_OPTS` gone, menu driven by `SelectionRule.all_rules()`; a right-anchored chip in the stats bar shows "N selected / total".

### 6. Video player in side-by-side comparison
**Source**: none yet; legacy simply shows "Video preview" placeholder in `ThumbnailGrid._mode_placeholder`.
**Cost**: large. Requires a new dependency (`tkvideoplayer` or `python-vlc`) plus build/test gating.
**Value**: closes the Phase-6 rule gap — today grid double-click on a video routes to Review instead of opening a side-by-side viewer.
**Suggested phase**: stand-alone phase if the user requests video support; not worth doing for free.
**Acceptance**: grid double-click on a video plays both sides with synced scrub; otherwise routes to Review.

### 7. Pixel-diff overlay in `PreviewPanel`
**Source**: `preview_panel.py _on_diff_toggled` is a TODO stub; `_diff_switch` widget exists but is not packed.
**Cost**: small-to-medium. Use PIL.ImageChops.difference on the loaded A/B pair, overlay as a red-channel heatmap on one side.
**Value**: fast "where do these two images actually differ?" answer — useful during manual review of near-duplicates.
**Suggested phase**: next phase that touches `PreviewPanel`.
**Acceptance**: `_diff_switch` is packed; toggling it overlays a difference heatmap on side B; zoom sync still works.

### 8. `HistoryRecorder` / `PreviewCoordinator` / `ScanController`
**Source**: `cerebro/v2/ui/main_window_controllers.py`
**Cost**: N/A architectural reference only.
**Status**: **retire when `main_window.py` is finally deleted**. Not reused by AppShell; equivalent logic lives in `app_shell.py` and `scan_page.py` today.

---

## Implementation-order proposal

If we ever pick up this backlog as its own phase, the cheapest→richest
order is:

1. **SelectionRule reuse** (#5 part a) — purely a refactor, no UX change.
2. **Pixel-diff overlay** (#7) — small, self-contained, improves an
   existing feature.
3. **Selected/total chip** (#5 part b) — small UI add.
4. **Scan mode tabs** (#1) — biggest user-visible improvement but cross-file.
5. **Scan-complete banner** (#2) — pure polish.
6. **Video player** (#6) — new dependency; only if users ask for it.
