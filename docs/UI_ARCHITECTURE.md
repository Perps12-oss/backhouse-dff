# CEREBRO UI Architecture
_Last updated: 2026-04-26_

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
    ├── ResultsPage     (grouped duplicate list, filters, delete actions)
    ├── ReviewPage      (visual triage grid + compare flow)
    ├── HistoryPage     (scan/deletion history views)
    └── SettingsPage    (theme and behavior preferences)
```

## Navigation and routing

- Canonical tab keys: `dashboard`, `duplicates`, `review`, `history`, `settings`
- Route mapping is handled in `cerebro/v2/ui/flet_app/main.py`
- `AppLayout.navigate_to()` mounts the active page and coordinates shell updates
- Inactive pages receive deferred updates; active page is updated immediately

## Engine and state integration

- Scan and orchestration logic remain in core/engines (unchanged contract)
- UI receives state via `StateBridge` subscriptions and coordinator callbacks
- `ScanCompleted` / `ResultsFilesRemoved` synchronize Results and Review datasets
- UI-only performance techniques: deferred rendering, lazy card/tile construction,
  batched updates, and safe mount-aware updates

## Theme and tokens

- Theme tokens and palette behavior are defined in:
  `cerebro/v2/ui/flet_app/theme.py`
- Preset palettes are loaded via `palette_themes.py`
- Theme application flows through `StateBridge.apply_preset_theme()` and per-page
  `apply_theme()` methods
- Contrast and typography were tuned in the Phase 6 polish pass for readability

## Settings persistence

- UI settings persist in `~/.cerebro/flet_ui_settings.json`
- Includes onboarding completion, reduce-motion, sound effects, and window state

## Key implementation files

| Area | File |
|---|---|
| App entry | `cerebro/v2/ui/flet_app/main.py` |
| Shell layout | `cerebro/v2/ui/flet_app/layout.py` |
| Bridge/services | `cerebro/v2/ui/flet_app/services/state_bridge.py` |
| Home | `cerebro/v2/ui/flet_app/pages/dashboard_page.py` |
| Results | `cerebro/v2/ui/flet_app/pages/results_page.py` |
| Review | `cerebro/v2/ui/flet_app/pages/review_page.py` |
| History | `cerebro/v2/ui/flet_app/pages/history_page.py` |
| Settings | `cerebro/v2/ui/flet_app/pages/settings_page.py` |
| Theme tokens | `cerebro/v2/ui/flet_app/theme.py` |

## Notes

- This document intentionally reflects the current Flet architecture only.
- Legacy CTk/Tk shell references are retained in archival docs, not here.
