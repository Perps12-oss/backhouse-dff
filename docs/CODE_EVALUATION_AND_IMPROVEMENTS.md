# CEREBRO Code Evaluation & Improvement Suggestions

This document summarizes a codebase evaluation and concrete areas to improve. It is organized by priority and category.

---

## Critical / High impact

### 1. **scan_options_panel.py – Broken `ScanOptionsContainer` class**

**Location:** `cerebro/ui/widgets/scan_options_panel.py` lines 26–65

**Issue:** `ScanOptionsContainer` declares a class, but the methods `emit_scan_request`, `set_scanning`, `apply_preset`, and `get_current_config` are **not indented** under the class. They are module-level functions, so:

- `ScanOptionsContainer` has no real behavior.
- Any code that uses `ScanOptionsContainer` and calls these methods will fail (e.g. `self._panel` does not exist on the class).

**Improvement:** Indent all four methods under `class ScanOptionsContainer` and ensure the class has `__init__` that sets `self._panel = ScanOptionsPanel()` (or receives it). Remove the duplicate/second `ScanOptionsPanel` definition later in the file if the intent is a single implementation.

---

### 2. **Config import inconsistency**

**Issue:** `cerebro/services/update_checker.py` imports from `cerebro.core.config`:

```python
from cerebro.core.config import AppConfig, load_config
```

The rest of the app (main_window, theme_engine, settings_page) uses `cerebro.services.config`. There is no `cerebro/core/config.py` in the tree; only `cerebro/services/config.py` exists.

**Improvement:** In `update_checker.py`, change to:

```python
from cerebro.services.config import load_config
# and use the AppConfig type from there, or from a shared types module
```

Ensure `AppConfig` (and any other types) are imported from the same place the rest of the app uses.

---

### 3. **Duplicate / legacy ScanOptionsPanel**

**Location:** `cerebro/ui/widgets/scan_options_panel.py`

**Issue:** There are two classes named `ScanOptionsPanel`: a minimal one around lines 74–~175 (with `get_config_dict`), and a larger one around line 436. The file also contains `ScanOptionsContainer`, legacy-style options, and preset UI. This makes the module hard to maintain and easy to break.

**Improvement:**

- Keep a single `ScanOptionsPanel` that matches what Settings and the bus expect (e.g. `get_config_dict()`, `config_changed`).
- Move preset UI and any “enhanced” behavior into that one class or into a small helper.
- Remove or clearly deprecate the duplicate class and document which one is canonical.

---

### 4. **Error handling – avoid swallowing exceptions**

**Pattern:** Several places use broad `except Exception:` and then `pass` or only log, with no re-raise or structured handling. Examples:

- `CerebroPipeline._log` and logger access in `__init__`
- `clamp_window_to_screen` / geometry restore paths
- Some worker `run()` methods

**Improvement:**

- In library/core code: catch specific exceptions where possible; let unexpected ones propagate or log and re-raise.
- In UI/startup: catch at a boundary, log with `log_exception()` or equivalent, and show a user-friendly message instead of failing silently.
- Prefer `except Exception as e: log_error(...); raise` or a dedicated error type over bare `except: pass`.

---

## Medium impact (maintainability & robustness)

### 5. **State bus – optional typing and single source of truth**

**Location:** `cerebro/ui/state_bus.py`

**Current:** Scan options are a free-form dict; `media_type` and `engine` are documented in comments.

**Improvement:**

- Introduce a small dataclass or TypedDict for scan options (e.g. `ScanOptions`) with default values and use it in `get_scan_options` / `set_scan_options` so that type checkers and IDEs help.
- Keep `MEDIA_EXTENSIONS` and `allowed_extensions_for_media_type` here; consider moving them to a small `scan_constants` or `media_types` module if reused outside the bus.

---

### 6. **Pipeline / deletion – logging and validation**

**Location:** `cerebro/core/pipeline.py`

**Current:** Pipeline uses an optional logger and validates deletion plans with ad-hoc error lists.

**Improvement:**

- Use a single, explicit logger (e.g. from `services.logger`) and log key steps (plan built, execution started, result summary).
- Return or emit a small result object that includes validation errors (e.g. list of group errors) so the UI can show “N groups skipped due to errors” instead of only failing at execution time.

---

### 7. **Window geometry – single place for “max size”**

**Location:** `cerebro/ui/main_window.py` and `cerebro/util/ui_utils.py`

**Current:** Max size is adjusted in `navigate_to` and in `clamp_window_to_screen`; logic is split.

**Improvement:**

- Centralize “max window size = available screen geometry” in one helper (e.g. in `ui_utils`).
- Call it from: (1) first show (after restore), (2) after navigation if needed. That way you avoid the window ever being larger than the screen and keep behavior consistent.

---

### 8. **Workers – consistent cancellation and progress**

**Current:** `FastScanWorker` uses a `_cancelled` flag and `FastPipeline.cancel()`; `BaseWorker` uses `_cancel_event`. Other workers use different patterns.

**Improvement:**

- Standardize on one cancellation mechanism (e.g. a shared `cancel_event` or a base method `request_cancel()` that subclasses respect).
- Document the contract: “after cancel, worker must emit cancelled/finished and not touch UI.”
- Where possible, use the same progress type (e.g. percent + message + optional stats) so the controller and UI can treat all workers similarly.

---

## Lower priority / nice-to-have

### 9. **Tests**

**Current:** No `test_*.py` (or similar) files were found.

**Improvement:**

- Add a small test suite for:
  - Core logic: e.g. `build_delete_plan` (valid/invalid inputs), `allowed_extensions_for_media_type`, `create_scan_config`.
  - Pure helpers: hashing, path filters, config defaults.
- Run tests in CI or pre-commit so refactors don’t break contracts.

---

### 10. **Type hints**

**Current:** Many modules use partial typing (`Optional`, `Dict`, etc.); some use `Any` heavily.

**Improvement:**

- Add return types to public functions and methods.
- Replace `Dict[str, Any]` with TypedDict or dataclasses for scan config, deletion plan, and snapshot updates so that breaking changes are caught by type checkers.

---

### 11. **Eye widget – optional “age” and menu sync**

**Current:** `reset_to_defaults` uses `hasattr(self, "_age_slider_setup")` to avoid crashes; control menu syncs from snapshot.

**Improvement:**

- If “age” is not a supported feature, remove the `_age_slider_setup` call and any related UI; otherwise implement `_age_slider_setup` and wire it.
- Ensure the eye control menu’s “Reset” and the snapshot stay in sync (e.g. after reset, refresh menu combo indices from the widget).

---

### 12. **Debug / environment**

**Current:** `main.py` forces `CEREBRO_DEBUG=1` and `CEREBRO_PAUSE_EXIT=1`.

**Improvement:**

- Make debug and pause-on-exit configurable (e.g. env only when `DEBUG` is set, or a `--debug` flag).
- Avoid forcing debug in production paths so that log volume and pause behavior are controllable.

---

### 13. **Dead or duplicate code**

**Candidates to review:**

- `cerebro/ui/pages/store.py` vs `cerebro/history/store.py` – ensure naming and usage are clear (history vs page state).
- `debug/` scripts – if they are one-off fixes, move any lasting logic into the main codebase and delete or archive the scripts.
- Second `ScanOptionsPanel` and unused `ScanOptionsContainer` once the single-panel refactor is done.

---

## Summary table

| Area                    | Priority  | Action |
|-------------------------|-----------|--------|
| ScanOptionsContainer    | Critical  | Fix indentation; add `__init__` and `_panel`. |
| update_checker config   | Critical  | Import from `services.config` (fix broken import). |
| Single ScanOptionsPanel | High     | One canonical panel; remove or merge duplicate. |
| Exception handling      | High     | Replace broad `except: pass` with specific handling and logging. |
| State bus typing        | Medium   | Dataclass/TypedDict for scan options. |
| Pipeline validation     | Medium   | Return validation errors; consistent logging. |
| Window geometry         | Medium   | Single helper for “clamp to screen”. |
| Worker cancellation     | Medium   | One cancellation pattern; document contract. |
| Tests                   | Low      | Add tests for core and helpers. |
| Type hints              | Low      | Stricter types for configs and plans. |
| Eye widget age          | Low      | Implement or remove age slider. |
| Debug flags             | Low      | Make debug/pause configurable. |
| Dead code               | Low      | Remove or archive debug scripts; clarify stores. |

---

## Suggested order of work

1. Fix **ScanOptionsContainer** indentation and `_panel` so no code path fails when using it.
2. Fix **update_checker** import so it uses `cerebro.services.config`.
3. Consolidate **ScanOptionsPanel** and remove the duplicate class.
4. Tighten **exception handling** in pipeline and UI-critical paths.
5. Add **ScanOptions** (or similar) typing and **clamp_window_to_screen** centralization.
6. Introduce **tests** for core and scan config.
7. Optionally standardize **worker cancellation** and **logging** across workers and pipeline.

If you tell me which area you want to tackle first (e.g. “fix ScanOptionsContainer” or “add tests for pipeline”), I can outline concrete code changes step by step.
