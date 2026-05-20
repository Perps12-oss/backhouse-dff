# CEREBRO UI Architecture
_Last updated: 2026-05-18_

## Launch path

```
python -m cerebro.v2
  → cerebro/v2/__main__.py
  → cerebro/v2/ui/flet_app/main.py
```

## Runtime shell

The live desktop UI is Flet-based and route-driven:

```
main.py
├── StateBridge (store/theme/events bridge)
├── AppLayout (navigation rail + content host)
└── Pages
    ├── DashboardPage   (home / scan entry / progress / quick actions)
    ├── ReviewFlowHost  (overview → browse → inspect + apply cleanup)
    ├── HistoryPage     (scan/deletion history views)
    ├── ExcludeListPage (protected paths)
    └── SettingsPage    (theme and behavior preferences)
```

Legacy **ReviewPage** (`pages/review_page.py`, `pages/review/*`, `SmartSelectionRow`) was **retired** in favor of `ReviewFlowHost` only. There is no `review_flow_v2` toggle and no separate Results tab in the Flet shell.

## Navigation and routing

- Canonical tab keys: `dashboard`, `duplicates`, `review`, `history`, `exclude`, `settings`
- `duplicates` and `review` both mount `ReviewFlowHost` (same singleton instance)
- Route mapping is handled in `cerebro/v2/ui/flet_app/main.py`
- `AppLayout.navigate_to()` mounts the active page and coordinates shell updates
- Inactive pages receive deferred updates; active page is updated immediately

## Review flow (v2)

Three screens inside one host:

| Screen | Module | Purpose |
|--------|--------|---------|
| Overview | `review_flow/screens/overview.py` | Post-scan summary, entry to browse |
| Browse | `review_flow/screens/browse.py` | List/grid triage, checkboxes, apply cleanup |
| Inspect | `review_flow/screens/inspect.py` | Side-by-side file comparison |

Shared modules: `host.py`, `state.py`, `router.py`, `apply_sheet.py`, `progress_sidebar.py`, `smart_rules.py`, `labels.py`, `filters.py`.

Deletion intent uses `DeleteService` → `CerebroPipeline` with audit `source: "review_flow"` (legacy history rows may still say `review_page`).

## Engine and state integration

- Scan and orchestration logic remain in core/engines (unchanged contract)
- UI receives state via `StateBridge` subscriptions and coordinator callbacks
- `ScanCompleted` / `ResultsFilesRemoved` / `GroupsPruned` sync groups into `ReviewFlowHost.load_results()`
- `FileSelectionChanged` is **not** registered on the browse list (avoids partial list repaints on bulk mark)
- UI-only performance: chunked list build (`BROWSE_GROUPS_CHUNK` / `BROWSE_TILES_CHUNK`), deferred rendering, safe mount-aware updates

## Theme and tokens

- Theme tokens and palette behavior are defined in:
  `cerebro/v2/ui/flet_app/theme.py`
- Preset palettes are loaded via `palette_themes.py`
- Theme application flows through `StateBridge.apply_preset_theme()` and per-page
  `apply_theme()` methods

## Settings persistence

- UI settings persist in `~/.cerebro/flet_ui_settings.json`
- Includes onboarding completion, reduce-motion, sound effects, and window state
- Deletion auto-mark rule keys align with `review_flow/smart_rules.py` (`AUTO_MARK_RULE_OPTIONS`)

## Key implementation files

| Area | File |
|---|---|
| App entry | `cerebro/v2/ui/flet_app/main.py` |
| Shell layout | `cerebro/v2/ui/flet_app/layout.py` |
| Bridge/services | `cerebro/v2/ui/flet_app/services/state_bridge.py` |
| Home | `cerebro/v2/ui/flet_app/pages/dashboard_page.py` |
| Review | `cerebro/v2/ui/flet_app/pages/review_flow/host.py` |
| History | `cerebro/v2/ui/flet_app/pages/history_page.py` |
| Settings | `cerebro/v2/ui/flet_app/pages/settings_page.py` |
| Exclude list | `cerebro/v2/ui/flet_app/pages/exclude_list_page.py` |
| Theme tokens | `cerebro/v2/ui/flet_app/theme.py` |

## Notes

- This document reflects the current Flet architecture only.
- Archival docs under `docs/archive/` and `docs/plans/` may describe superseded ReviewPage decomposition.
