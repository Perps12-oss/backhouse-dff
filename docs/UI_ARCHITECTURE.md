# CEREBRO UI Architecture
_Last updated: 2026-04-18_

## Launch path

```
python -m cerebro.v2
  → cerebro/v2/__main__.py
  → app_shell.run_app()
  → AppShell (CTk root window)
```

## Shell structure

```
AppShell
├── TitleBar          (32px, #0B1929) — wordmark, Themes/Settings links
├── TabBar            (36px, #F0F0F0) — 6 tabs with active underline
└── Page frames (stacked via place/place_forget)
    ├── WelcomePage   — dark branded landing screen
    ├── ScanPage      — folder tree + mode bar + config + progress
    ├── ResultsPage   — virtual grid + stats + filters
    ├── ReviewPage    — large preview + copy list + group nav
    ├── HistoryPage   — scan/deletion history from SQLite
    └── DiagnosticsPage — engine status + DB info
```

## Engine integration

- Engine: `TurboFileEngine` via `ScanOrchestrator`
- Progress: `ScanProgress` events → `after(0, ...)` → UI update
- Thread rule: ALL file I/O and DB queries run in `threading.Thread(daemon=True)`
- Marshal rule: ALL UI updates from threads go through `self.after(0, lambda: ...)`

## Design tokens

All visual constants live in `cerebro/v2/ui/design_tokens.py`.
No hardcoded hex values in page files.

## Theme system

Themes are JSON files in `cerebro/themes/builtin/` and `~/.cerebro/themes/`.
`ThemeEngineV3` (`cerebro/core/theme_engine_v3.py`) loads all themes on startup.
Active theme is applied via `cerebro/v2/core/theme_bridge_v2.py`.
The **Cerebro Navy** palette (`cerebro_navy.json`) is the Phase 6/7 overhaul palette.

## Settings

`SettingsDialog` (`cerebro/v2/ui/settings_dialog.py`) is a `CTkToplevel` modal
opened from the Settings link in the title bar. Settings are persisted to
`~/.cerebro/settings.json`.

## Delete ceremony widgets

`cerebro/v2/ui/delete_ceremony_widgets.py` — modals and undo toast used by
`delete_flow.py` (Results / Review delete path). Not the app root; see
`app_shell.py` for the live window.

## Key components

| Component | File | Notes |
|---|---|---|
| AppShell | app_shell.py | CTk root window, 6-tab page stack |
| TitleBar | title_bar.py | 32px navy bar, traffic-light dots, Settings/Themes links |
| TabBar | tab_bar.py | 36px bar, 6 tabs, active underline, Results badge |
| WelcomePage | welcome_page.py | Dark branded landing, stats from SQLite in thread |
| ScanPage | scan_page.py | FolderTree (lazy ttk), ScanModeBar, ConfigSubTabs, ProgressView |
| ResultsPage | results_page.py | StatsBar, FilterTabBar, VirtualFileGrid |
| VirtualFileGrid | results_page.py | Canvas-based, only renders visible rows (ROW_H=24) |
| ReviewPage | review_page.py | PIL preview in thread, CopyList cards, GroupNav |
| HistoryPage | history_page.py | Scan + Deletion history sub-tabs, SQLite in thread |
| DiagnosticsPage | diagnostics_page.py | Engine status, DB info, app version — lazy-loaded |
| SettingsDialog | settings_dialog.py | Full CTkToplevel modal, 5 tabs, persisted to JSON |

## Tab switching

`AppShell._on_tab_changed(key)` hides the current page via `place_forget()`
and shows the new page via `place(relwidth=1, relheight=1)`. Pages that
implement `on_show()` receive a call to trigger lazy data loading.

## Phase delivery

| Phase | Deliverable |
|---|---|
| P1 | AppShell, TitleBar, TabBar |
| P2 | WelcomePage |
| P3 | ScanPage |
| P4 | ResultsPage (VirtualFileGrid) |
| P5 | ReviewPage |
| P6 | HistoryPage, DiagnosticsPage, design_tokens.py |
| P7 | Settings/Themes wired, cerebro_navy theme, legacy retirement, this doc |
