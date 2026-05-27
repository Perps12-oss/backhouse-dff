# Cerebro v2 History Facade

This document describes the v2 history persistence model introduced for the
CustomTkinter-only runtime.

## What is persisted

- `~/.cerebro/settings.json`
  - app behavior and defaults (`default_mode`, delete confirmation, thresholds)
- `~/.cerebro/scan_history.db`
  - completed scan sessions (mode, folders, duration, reclaimable bytes)
- `~/.cerebro/deletion_history.db`
  - each deleted file (name, original path, size, mode, timestamp)

## Facade entrypoints

- Settings
  - `cerebro.v2.ui.settings_dialog.get_settings_path()`
  - `Settings.load(...)` and `Settings.save(...)`
- Scan history
  - `cerebro.v2.core.scan_history_db.get_scan_history_db()`
  - `record_scan(...)` in `cerebro.v2.ui.scan_history_dialog`
- Deletion history
  - `cerebro.v2.core.deletion_history_db.get_default_history_manager()`
  - `cerebro.services.history_manager.get_history_manager()` (compat shim)

## UI integration

- `AppShell` loads and applies settings on startup.
- `SettingsDialog` edits and persists config.
- Help menu exposes:
  - Keyboard Shortcuts
  - Scan History
  - Deletion History
- Delete action logs every successful send-to-trash event into sqlite.

## Notes

- Scan history migrates legacy JSON from `~/.cerebro/scan_history.json` into sqlite when the history dialog opens.
- The compatibility shim in `cerebro/services/history_manager.py` allows legacy callers to continue working while using v2 sqlite storage.
