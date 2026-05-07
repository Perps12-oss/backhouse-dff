# Senior Engineer Review — CEREBRO v2 TODO

> Generated: 2026-05-07  
> Reviewer: Senior Engineer  
> Status legend: `[ ]` open · `[x]` resolved · `[-]` won't fix / accepted risk

---

## ANSWERS TO RAISED QUESTIONS

### 1. Entry Point & Production Readiness

**Q: Is there an `if __name__ == "__main__"` guard?**  
A: YES — properly done. `main.py:17-18`:
```python
if __name__ == "__main__":
    raise SystemExit(main())
```
Uses `raise SystemExit(main())` rather than `sys.exit()` — correct pattern for PyInstaller compatibility. PASS.

**Q: What's in CEREBRO.spec? Hidden path manipulation?**  
A: `pathex=[str(spec_root)]` — this is standard PyInstaller; spec_root is the project directory resolved from `SPECPATH`. No `sys.path.insert(0, '.')` hack. Correctly uses `collect_all()` for flet/PIL assets and `collect_submodules("cerebro")`. One issue noted — see TODO item #1.

---

### 2. Dependency Hell Audit

**Q: `pip check` conflicts?**  
A: `No broken requirements found.` PASS.

**Q: CVEs via `pip-audit`?**  
A: `No known vulnerabilities found.` PASS.

**Q: Outdated packages?**  
A: Only `pip` itself (26.1 → 26.1.1). All project dependencies are current. PASS.  
Note: pip cache has deserialization warnings — unrelated to this project, pip internal issue.

**Q: `pkg_resources` (deprecated) vs `importlib.metadata`?**  
A: `runtime_deps.py` correctly uses `importlib.util.find_spec()` (not `pkg_resources`). PASS.

---

### 3. Windows vs Cross-Platform

**Q: `os.path.join` or hardcoded backslashes?**  
A: Mostly `pathlib.Path` throughout. Some `os.path` usage remains (see TODO #2). No hardcoded backslashes in logic — the one backslash found (`dashboard_page.py:1238`) is a display formatting string only. PASS with caveat.

**Q: `multiprocessing` + `freeze_support()` missing?**  
A: `use_multiprocessing=False` is the default in `turbo_file_engine.py:189`. However `ProcessPoolExecutor` is still wired up and can be enabled. `freeze_support()` is **not called anywhere** in `main.py`. This is a real bug — see TODO #3.

**Q: `subprocess.Popen` with `shell=True`?**  
A: `grep shell=True` — **zero results** across the entire codebase. All `subprocess` calls use explicit argument lists. PASS.

---

### 4. The DFF I/O Check

**Q: Reading entire files into memory with `.read()`?**  
A: One instance found at `cerebro/history/store.py:155` — the audit log file is read fully into memory before atomic rewrite. Acceptable for an append-only audit log (small files), but will break at scale. See TODO #4.

**Q: `pathlib.Path` or `os.listdir` + string concatenation?**  
A: `pathlib.Path` is the primary pattern. Scanner (`turbo_scanner.py`) uses `os.scandir()` for performance — correct choice for high-throughput directory traversal. PASS.

**Q: File handles closed with `with` statements?**  
A: Yes, all file I/O uses context managers. No leaked handles found. PASS.

---

### 5. Logging

**Q: No `logging.conf` / structured logging (loguru, structlog)?**  
A: No `logging.conf`. Configured programmatically in `cerebro/services/logger.py`. No structured logging library used — stdlib `logging` only. See TODO #5.

**Q: `print()` in production code paths?**  
A: Findings:
- `cerebro/__main__.py` — 1 print (smoke test output, acceptable)
- `cerebro/runtime_deps.py` — 6 prints to `sys.stderr` (bootstrap messages shown to user, acceptable)
- `cerebro/cli.py` — multiple prints (this IS the CLI output, correct)
- **Zero debug `print()` calls in business logic.** PASS.

**Q: `logging.getLogger(__name__)` or root logger?**  
A: All modules use `logging.getLogger(__name__)` correctly. `logger.py` itself uses `logging.getLogger("CEREBRO")` as a named hierarchy root. See TODO #6 for a subtle propagation concern.

---

### 6. Threading vs Async

**Q: `threading` with GIL for CPU-bound work?**  
A: Hashing is I/O-bound (reading files), so `ThreadPoolExecutor` gives real parallelism. Directory traversal is also I/O-bound. The comment at `turbo_scanner.py:795-796` acknowledges this. PASS.

**Q: `asyncio` with blocking `time.sleep()` instead of `await asyncio.sleep()`?**  
A: `time.sleep()` calls in engines (`empty_folder_engine.py`, `large_file_engine.py`, `music_dedup_engine.py`, etc.) are inside **synchronous** scan worker threads — correct use. `asyncio.sleep()` is used in the Flet async UI handlers — correct. No crossover found. PASS.

**Q: `while True:` without break or timeout?**  
A: No unbounded `while True:` loops found in production code. PASS.

---

### 7. Silent Failure Audit

**Q: Bare `except:` clauses?**  
A: **Zero bare `except:` clauses** found. All catches are typed. PASS.

**Q: `except Exception` without logging or re-raise?**  
A: One case of concern — `CEREBRO.spec:37-38` silently swallows collection errors for flet/PIL assets. In application code, all `except Exception` catches either log via `_log.exception()`, `_log.error()`, or surface to UI. PASS for app code; see TODO #1 for spec.

**Q: `assert` for runtime validation?**  
A: No `assert` used for runtime validation in production paths. `group_invariants.py` uses them for data-integrity checks (acceptable in dev; see TODO #7 for -O flag risk).

---

## OPEN TODO ITEMS

### Priority: MEDIUM (Next sprint)

- [ ] **#2 — Mixed `os.path` and `pathlib` across the codebase**  
  Several files use `os.path.exists`, `os.path.basename`, `os.path.abspath`, `os.path.getsize` alongside `pathlib.Path`. This is inconsistent and creates UNC path / Windows long-path edge cases.  
  **Files:** `cerebro/services/config.py:543`, `cerebro/v2/core/deletion_history_db.py:33,64`, `cerebro/core/scanners/turbo_scanner.py:603`, `cerebro/core/group_invariants.py:66`  
  **Fix:** Standardise on `pathlib.Path` — replace `os.path.*` calls with their `Path` equivalents.

- [ ] **#7 — `assert` in `group_invariants.py` for runtime data checks**  
  `cerebro/core/group_invariants.py:66` uses `assert` to enforce that duplicate groups have exactly one survivor. Assertions are stripped when Python is run with `-O` (optimise flag) or `-OO`. PyInstaller does not use `-O` by default, but this is a latent footgun.  
  **Fix:** Replace `assert` with explicit `if not condition: raise ValueError(...)`.  
  **File:** `cerebro/core/group_invariants.py`

### Priority: LOW (Technical debt backlog)

- [ ] **#8 — No `run.sh` for Linux/macOS despite cross-platform Flet UI**  
  There is `Run CEREBRO.bat` for Windows but no shell script for Linux/macOS. The spec is also Windows-only (`CEREBRO.exe`). If cross-platform is a goal, add a `run.sh` and a platform-aware build script.  
  **Files:** repo root

- [ ] **#9 — `config.py` is 880 LOC — split into domains**  
  UI settings, scan config, performance config, notifications, and migration logic are all in one file. This makes it hard to test individual sub-systems and slows parsing.  
  **Fix:** Extract into `config_ui.py`, `config_scan.py`, `config_migration.py`.  
  **File:** `cerebro/services/config.py`

- [ ] **#10 — `TurboFileEngine.pause()` raises `NotImplementedError`**  
  `cerebro/engines/turbo_file_engine.py` advertises pause/resume via `BaseEngine` but raises `NotImplementedError` at runtime. If the UI exposes a pause button for this engine, it will crash.  
  **Fix:** Either implement pause (use `threading.Event`) or document/disable the pause button for this engine mode.  
  **File:** `cerebro/engines/turbo_file_engine.py`

- [ ] **#11 — `runtime_deps.py` restart loop has no iteration guard**  
  After pip install succeeds, the process is restarted. If a package installs successfully but is still not importable (e.g., wrong platform wheel, corrupted install), `_missing_pip_names()` will return it again on the next run, triggering another pip call and restart — infinitely.  
  **Fix:** Set an environment variable (e.g., `CEREBRO_RESTART_ATTEMPT=1`) before restarting and abort with a clear error if that variable is already set.  
  **File:** `cerebro/runtime_deps.py:126-137`

- [ ] **#12 — No performance regression tests**  
  `test_turbo_discovery_speed.py` exists but uses `use_multiprocessing=False` for all benchmarks. There is no CI assertion that scanning N files completes within a time budget. A slow PR could regress scan speed silently.  
  **Fix:** Add a pytest benchmark with `pytest-benchmark` or a simple `time.perf_counter()` assertion for a known file corpus.  
  **File:** `tests/test_turbo_discovery_speed.py`

---

## RESOLVED

- [x] **#3 — `freeze_support()` added to `main.py`** — `multiprocessing.freeze_support()` added before `main()` call. Required for Windows PyInstaller frozen builds with multiprocessing.

- [x] **#6 — Logger hierarchy fixed** — Renamed logger root from `"CEREBRO"` → `"cerebro"`. Module loggers using `getLogger(__name__)` now propagate naturally. Verified with `tests/test_logger_hierarchy.py` (4 tests, all green). Root cause also documented: `cerebro/services/__init__.py` shadows the `logger` submodule name — use `importlib.import_module("cerebro.services.logger")` in tests.

- [x] **#1 — CEREBRO.spec collect_all failures now fatal** — Silent `except Exception: pass` replaced with stderr message + `raise SystemExit(1)`. Build now fails explicitly if flet or PIL cannot be collected.

- [x] **#4 — Audit log O(n²) rewrite eliminated** — `history/store.py:record_deletion` now uses `open(audit_file, "a")` + `fsync`. True O(1) append. Stress tested: 10,000 appends verified well under 100ms average, all records readable (`tests/test_history_store_stress.py`).

- [x] **#5 — Structured logging added** — `structlog>=24.0.0` added to `requirements.txt` and `pyproject.toml`. `get_structured_logger(name)` added to `logger.py` for new code wanting key=value context. JSON output enabled via `CEREBRO_LOG_JSON=1`. Existing code unchanged.

- [x] **Memory profiling in CI** — `pytest-memray` added to CI install step. `tests/test_memory_bounds.py` added with 50MB ceiling tests for import footprint, history store, hash cache. `@pytest.mark.limit_memory` registered in `pyproject.toml` to suppress local warnings.

- [x] **Startup time monitoring in CI** — CI step added: imports `cerebro` and fails build if elapsed time exceeds 3000ms.

- [x] **`logging.conf` added** — `cerebro/services/logging.conf` documents the full logger hierarchy and provides an INI-format config for runtime log-level changes via `CEREBRO_LOG_CONF`.

---

## CLEAN (no action needed)

- `if __name__ == "__main__"` guard — present and correct
- `shell=True` — zero occurrences, all subprocess calls safe
- `eval()` / `exec()` — zero occurrences
- `pip check` — no dependency conflicts
- `pip-audit` — no CVEs
- Bare `except:` — zero occurrences
- Debug `print()` in business logic — zero occurrences
- `asyncio.sleep()` vs `time.sleep()` crossover — none found
- Unbounded `while True:` loops — none found
- File handle leaks — all I/O uses `with` context managers
- `pkg_resources` / deprecated patterns — not used; `importlib.util` used correctly
