# Review page — manual smoke checklist

Run after changes to `review_page.py`, `review/grid_view.py`, or `review/compare_view.py`.

1. **Navigate to Review** — From the app shell, open the Review route; page loads without errors.
2. **Empty / loading** — With no scan results, empty state shows; starting a load shows loading, then content.
3. **Groups overview** — With results, group cards list appears; sort control changes order; “tiles” / “groups” toggles work.
4. **File-type filter buckets** — Use the top filter strip to switch **All** vs extension buckets (images, video, audio, documents, archives, code, other). Counts update; grid or group list reflects only files in that bucket (not “date/status” filters).
5. **Grid marks** — In tile grid, toggle “mark for deletion” on several files; checkboxes stay in sync and the UI stays responsive (no full compare-panel rebuild while in grid).
6. **Compare mode** — Open a group; A/B panels, thumbnails/meta, smart-rule strip, and prev/next navigation behave as before.
7. **Compare marks & delete** — Toggle marks on compare checkboxes; “Delete marked” / side A–B deletes show confirmation and complete; snackbars and undo (Trash) when applicable.
8. **Regression pass** — Back to groups/grid; theme toggle if available; keyboard shortcuts in compare (←/→, optional delete keys) still fire.

## Follow-ups

- Smart-delete confirmation and progress orchestration live in `review/delete_flow.py`; further shrinking `review_page.py` can move more post-delete refresh helpers there if needed.

## Script pointer

See `scripts/review_smoke.md` for a short command reference (no automated runner).
