# Review flow — manual smoke checklist

Run after changes to `review_flow/host.py`, `review_flow/screens/browse.py`, `review_flow/screens/inspect.py`, or `review_flow/apply_sheet.py`.

1. **Navigate to Review** — From the app shell, open the Review tab; `ReviewFlowHost` loads without errors.
2. **Overview** — After a scan, overview shows summary stats; **Continue to browse** (or equivalent) enters browse.
3. **Browse — list mode** — Group rows render; checkboxes mark files for deletion; sidebar shows marked count and reclaim estimate.
4. **Browse — grid mode** — Toggle thumbnail grid; tiles load incrementally; marks stay in sync with list mode.
5. **Filters** — Text/type/size filters narrow visible groups without blanking the central pane (no full-host rebuild regressions).
6. **Apply cleanup** — With manual marks only: **Apply cleanup** opens the 4-step dialog (summary → confirm → progress → outcome); deletion completes; browse list updates; undo (Trash) when applicable.
7. **Inspect** — Open a group; side-by-side previews, ref/compare navigation, and back-to-browse work.
8. **Regression** — Theme toggle; keyboard shortcuts on review tab; scan-complete returns to overview when configured.

## Not in scope (removed until redesign)

- **Smart Select** bulk rule apply was removed from browse (Flet 0.84 repaint bug). Reintroduce only via new code under `review_flow/` with a strict no-partial-`ListView.update()` contract.

## Implementation pointers

| Concern | Location |
|--------|----------|
| Tab host + delete ceremony | `review_flow/host.py`, `review_flow/apply_sheet.py` |
| Browse list/grid | `review_flow/screens/browse.py` |
| Inspect A/B | `review_flow/screens/inspect.py` |
| Flow state | `review_flow/state.py` |
| Smart rules (settings only) | `review_flow/smart_rules.py` |
| UI copy strings | `review_flow/labels.py` |

## Script pointer

See `scripts/review_smoke.md` for a compile check command (no automated runner).
