# Cursor Prompt: Review flow performance and sync fixes

> **Superseded paths:** V1 `review_page.py` is gone. Use **`cerebro/v2/ui/flet_app/pages/review_flow/`** (`host.py`, `screens/browse.py`, `screens/inspect.py`).

Use this prompt when fixing browse/inspect selection sync, filter rebuilds, or chunked list performance in the review flow.

---

## Summary of issues (historical + v2)

1. **Filter change corrupts selection state**  
   Rebuilding the browse list while toggling checkboxes can overwrite per-group selection. Ensure filter changes rebuild from `ReviewFlowState.marked_paths` / `set_selections` without spurious selection events.

2. **Bulk mark repaints (Flet 0.84)**  
   Partial `ListView.update()` after bulk smart-select blanked the browse pane. Do not register browse list controls for `FileSelectionChanged`; prefer one host-level refresh or in-place checkbox updates.

3. **UI freezes with many groups**  
   Use `ChunkedViewBuilder` presets `BROWSE_GROUPS_CHUNK_CONFIG` / `BROWSE_TILES_CHUNK_CONFIG` in `browse.py`; avoid synchronous full rebuilds on every mark.

4. **Apply cleanup**  
   Delete ceremony lives in `review_flow/apply_sheet.py` + `host._open_apply_sheet`; uses `DeleteService`, not per-screen delete dialogs.

---

## Files to touch

| Area | Path |
|------|------|
| Host / apply | `pages/review_flow/host.py`, `apply_sheet.py` |
| Browse | `pages/review_flow/screens/browse.py` |
| State | `pages/review_flow/state.py` |
| Bridge | `services/state_bridge.py` (`show_modal_dialog`) |

Do **not** reintroduce `pages/review_page.py`, `SmartSelectionRow`, or `pages/review/delete_flow.py`.
