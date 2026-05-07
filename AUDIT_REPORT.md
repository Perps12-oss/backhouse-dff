# CEREBRO Security & Quality Audit Report

> Date: 2026-05-07  
> Tools used: vulture, radon, custom grep sweeps, git log -S, pip-audit  
> Status legend: CLEAN · LOW · MEDIUM · HIGH · CRITICAL

---

## 1. SECURITY

### 1.1 Secrets Scanning
**Result: CLEAN**

- Zero hardcoded API keys, passwords, or tokens in source.
- `secrets.token_urlsafe(16)` and `secrets.compare_digest()` used correctly in `deletion_gate.py` and `session.py`.
- Git history scanned with `git log -S "password|api_key|secret_key|token="` — no credential commits found.
- One commit message `fix(security): harden delete tokens and safety boundaries` confirms prior deliberate hardening.

### 1.2 Path Traversal
**Result: LOW**

All file paths come from one of three sources:
1. **Flet FilePicker** (OS native dialog) — user picks a folder/file via GUI; raw path strings are never typed in a text field.
2. **Scan results** — paths discovered by the scanner, never constructed from user text.
3. **History store** — paths reconstructed from previously stored scan results.

**No text-input-to-filesystem path construction exists.** However, two low-severity observations:

- `os.startfile(str(path))` in `cerebro/core/preview.py:26` executes the file. On Windows, `startfile` on a path with a `.exe`, `.bat`, `.lnk`, or `.msi` extension will launch it. If an attacker can insert a malicious file into a scan root and the user clicks "Preview" on it, Windows will execute it. This is not a traversal bug — it's a feature (preview), but the risk profile should be documented.
- **Recommendation:** Before calling `startfile`, validate that the path extension is in a safe allow-list (image, video, audio, document types only). Reject `.exe`, `.bat`, `.com`, `.msi`, `.lnk`, `.ps1`, etc.

**File:** `cerebro/core/preview.py:23-32`

### 1.3 Pickle Deserialization
**Result: CLEAN**

Zero `pickle.load()`, `pickle.loads()`, or `pickle.Unpickler()` calls in the entire codebase.

### 1.4 Command Injection
**Result: CLEAN**

All `subprocess` calls verified:

| File | Call | Args source | shell= |
|------|------|-------------|--------|
| `runtime_deps.py` | `subprocess.call(cmd)` | `[sys.executable, "-m", "pip", ...]` — hardcoded | False (implicit) |
| `runtime_deps.py` | `subprocess.run([sys.executable, *sys.argv], env=new_env)` | `sys.argv` — OS-controlled | False |
| `core/preview.py` | `subprocess.run(["open", str(path)])` | Scanner-discovered path | False |
| `v2/shell_open.py` | `Popen(["explorer", "shell:RecycleBinFolder"])` | Hardcoded | False |
| `v2/shell_open.py` | `Popen(["open"/​"xdg-open", str(t)])` | Scanner path | False |
| `v2/ui/.../review_page.py:1583` | `Popen(["explorer", "/select,", str(path)])` | Scanner path | False |
| `engines/video_dedup_engine.py` | `subprocess.run(["ffprobe"/"ffmpeg", ..., str(video_path)])` | Scanner path | False |

`shell=False` everywhere. No string concatenation into shell commands. No user-typed text enters any subprocess argument.

**Note:** `sys.argv` forwarding in the restart path (`runtime_deps.py:143`) means a malicious `sys.argv[0]` could theoretically inject. In practice, `sys.argv[0]` is the Python script path set by the OS loader. Accepted.

---

## 2. DATA INTEGRITY

### 2.1 SQL Injection
**Result: CLEAN**

Every SQLite query uses parameterized `?` placeholders. Full sweep found zero f-string or `%`-formatted SQL. Examples confirmed:
- `hash_cache.py` — `WHERE size=? AND mtime_ns=?`
- `deletion_history_db.py` — `INSERT INTO deletion_history ... VALUES (?, ?, ?, ?, ?)`
- `scan_history_db.py`, `engine_errors_db.py`, `scheduler.py` — all parameterized.

### 2.2 Race Conditions in File Writes
**Result: LOW (one gap)**

| Component | Write pattern | Thread-safe? |
|-----------|--------------|--------------|
| `config.py` | `mkstemp` → `fsync` → `os.replace` (atomic) | Yes — single writer |
| `history/store.py` | `open("a")` + `fsync` | Yes for single process; multi-process append could interleave bytes (see 2.3) |
| `logger.py` | `_config_lock` guards handler setup | Yes |
| `hash_cache.py` | `_write_lock` + `_conn_lock` | Yes |
| `deletion_history_db.py` | `threading.RLock()` | Yes |

**Gap:** The global config singletons (`_config_instance`, `_config_manager` in `config.py`) are updated without a lock:

```python
# config.py — no lock around these
def load_config(config_dir=None):
    global _config_instance, _config_manager
    if _config_instance is None:               # TOCTOU race
        _config_manager = ConfigManager(...)
        _config_instance = _config_manager.load_config()
    return _config_instance
```

Two threads calling `load_config()` simultaneously could both pass the `is None` check and create two `ConfigManager` instances. The second one's result overwrites the first. Worst case: redundant disk reads, not data corruption. Fix with a module-level `threading.Lock`.

**File:** `cerebro/services/config.py` — `load_config()`, `save_config()`, `reload_config()`

### 2.3 File Locking on Windows
**Result: ACCEPTABLE with documented limitations**

- **Config writes:** `tempfile.mkstemp` + `os.replace` — Windows `MoveFileEx` is atomic within the same volume. Two processes writing the same config file will serialize through the OS; the last writer wins. Acceptable (one user session).
- **Audit log appends:** `open("a", encoding="utf-8")` + `fsync`. On Windows, concurrent multi-process appends to the same file can interleave bytes at the write boundary. Because JSONL is line-delimited and the reader already skips corrupt lines, a partial line from a crashed write is safe. However, two concurrent processes appending simultaneously could silently corrupt two records into one partial line each. **Production risk only if two CEREBRO instances run simultaneously with the same `~/.cerebro` dir.**
- **Log rotation:** `_WindowsSafeRotatingFileHandler` catches `PermissionError` on rollover — documented and tested.
- **SQLite databases:** All use `timeout=10.0` and WAL mode (hash cache) or `RLock`. Safe.

**Recommendation:** Document the single-instance assumption in README. Optionally add a `lockfile` (`filelock` package) on `~/.cerebro/.lock` to enforce it.

---

## 3. PERFORMANCE SCALING

### 3.1 UI Thread Blocking
**Result: CLEAN**

All long-running work dispatched via `page.run_task(async_fn)`. Verified across all 5 UI pages:
- `dashboard_page.py` — scan start, folder browse, recent-path refresh all via `run_task`
- `review_page.py` — grid build, thumbnail load, compare load all async
- `results_page.py` — list build, thumbnail load, inspector dims all async
- `settings_page.py` — save is synchronous but fast (JSON write only)
- `state_bridge.py` — `page.update()` calls are lightweight Flet render flushes

No blocking I/O or `time.sleep()` in Flet event handlers.

### 3.2 Unbounded LRU Cache
**Result: CLEAN**

Zero `@lru_cache()` (unbounded), `@lru_cache(maxsize=None)`, or `@cache` decorators found. Thumbnail cache in `thumbnail_cache.py` has manual LRU eviction.

### 3.3 Database Indexing
**Result: CLEAN**

All five SQLite databases have explicit indexes:

| DB | Index |
|----|-------|
| `hash_cache.db` | `idx_sig ON file_hashes(size, mtime_ns, dev, inode)` |
| `deletion_history.db` | `idx_deletion_date ON deletion_history(deletion_date DESC)` |
| `scan_history.db` | `idx_scan_history_ts ON scan_history(timestamp DESC)` |
| `engine_errors.db` | `idx_engine_errors_ts`, `idx_engine_errors_key_ts` |
| `turbo directory_cache` | `idx_checksum ON directory_cache(checksum)` |

**Gap:** No `EXPLAIN QUERY PLAN` tests in the test suite. A schema refactor could drop an index silently. Add index-coverage tests.

---

## 4. DEPLOYMENT

### 4.1 Windows Registry Access
**Result: CLEAN — no admin required**

`winreg` read at `cerebro/v2/ui/flet_app/main.py:60-65`:
```python
winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Control Panel\Accessibility")
```
`HKEY_CURRENT_USER` reads require **no elevation**. No UAC prompt. Wrapped in `except Exception: return False` so failure is safe. CLEAN.

### 4.2 Temp File Cleanup
**Result: CLEAN**

- `config.py`: `mkstemp` in `config_dir`, cleaned in `finally:` block. ✓
- `history/store.py`: `mkstemp` for resume payload, cleaned in `finally:`. ✓
- `video_dedup_engine.py`: uses `with tempfile.TemporaryDirectory() as tmp:` — auto-cleaned on context exit. ✓
- No `tempfile.gettempdir()` accumulation found.

### 4.3 Uninstaller / Config Residue
**Result: LOW — by design, worth documenting**

No uninstaller script. On removal the following persist:
- `~/.cerebro/` — config, logs, cache, history databases, hash cache
- `~/.cerebro/logs/` — up to 50MB of rolling logs + per-session logs (unbounded session count)

**Session logs accumulate:** `_configure_root()` creates `cerebro_<TIMESTAMP>.log` on every launch. With daily use, this creates 365 files/year. The rotating `cerebro.log` is bounded (10MB × 5), but session logs are never pruned.

**Recommendation:**
1. Add a `cleanup` CLI subcommand: `cerebro cleanup --older-than 30d`
2. Or prune session logs older than 7 days on startup (one-liner in logger.py)
3. Add uninstall instructions to README

**File:** `cerebro/services/logger.py:248-251` (session log creation)

---

## 5. CODE QUALITY

### 5.1 MyPy Strict Mode
**Result: NOT RUN (mypy not installed in current environment)**

CI runs `mypy --follow-imports=skip --ignore-missing-imports main.py` (single file, non-strict).

**Action:** Install mypy in CI environment and run `--strict` on core safety paths:
```yaml
python -m mypy cerebro/core/safety/ cerebro/engines/base_engine.py \
               cerebro/v2/state/ --strict --ignore-missing-imports
```

### 5.2 Cyclomatic Complexity (McCabe Score)
**Result: 5 functions above grade D — two at F (score 44)**

Critical refactor candidates:

| Grade | Score | Location | Risk |
|-------|-------|----------|------|
| **F** | 44 | `ImageDedupEngine._group_images` (`image_dedup_engine.py:475`) | Hard to test all branches; perceptual hash clustering logic |
| **F** | 44 | `reduce()` (`v2/state/reducer.py:65`) | Every action type is a branch; impossible to unit-test individual cases in isolation |
| **F** | 42 | `ResultsPage._refresh` (`results_page.py:1233`) | UI rendering logic with 42 branch paths — rendering bugs will be invisible |
| **E** | 32 | `BurstDetectionEngine._do_scan` (`burst_detection_engine.py:184`) | Burst grouping heuristics all in one method |
| **E** | 31 | `TurboScanner.scan` (`turbo_scanner.py:511`) | Core scan pipeline — a regression here affects all file scans |
| D | 25 | `CerebroPipeline.build_delete_plan` | Deletion logic — safety-critical |
| D | 22 | `CerebroPipeline.execute_delete_plan` | Deletion execution — safety-critical |
| D | 21 | `_extract_text` (`document_dedup_engine.py:78`) | 20+ format branches |
| C | 19 | `_cmd_scan` (`cli.py:52`) | CLI argument handling |
| C | 19 | `_delete_duplicates` (`cli.py:172`) | CLI deletion handling |

**Immediate actions:**
1. `reduce()` — split into sub-reducers by domain: `_reduce_scan`, `_reduce_history`, `_reduce_ui`. This is the Redux pattern already started; finish it.
2. `_group_images` — extract clustering into a pure function `_cluster_by_hamming(hashes, threshold)` and format detection into `_classify_image(path)`.
3. `ResultsPage._refresh` — extract filter logic, sort logic, and rendering logic into separate private methods.

### 5.3 Dead Code Detection (vulture)
**Result: 2 unused variables — extremely clean**

```
exclude_list_page.py:200  unused variable 'ev' (100%)
exclude_list_page.py:210  unused variable 'ev' (100%)
```

These are Flet event handler parameters that must be present in the signature but are not used. The fix is cosmetic: rename to `_ev` or `_` to signal intentional non-use and silence linters.

**File:** `cerebro/v2/ui/flet_app/pages/exclude_list_page.py:200,210`

---

## 6. ADDITIONAL FINDINGS

### 6.1 `startfile` Extension Allow-List (Security — LOW/MEDIUM)
`cerebro/core/preview.py:26` calls `os.startfile(str(path))` on Windows with no extension guard. If a `.exe` or `.bat` file lands in a scanned folder and the user clicks Preview, Windows executes it.

**Fix (5 lines):**
```python
_SAFE_PREVIEW_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff", ".heic",
    ".mp4", ".mov", ".avi", ".mkv", ".mp3", ".flac", ".wav", ".aac",
    ".pdf", ".txt", ".md", ".docx", ".xlsx",
}

def preview_file(self, path: Path) -> bool:
    if path.suffix.lower() not in _SAFE_PREVIEW_EXTENSIONS:
        logger.warning("Preview blocked for unsafe extension: %s", path.suffix)
        return False
    ...
```

### 6.2 Session Log Accumulation (Deployment — LOW)
Every app launch creates an unbounded timestamped log. After 1 year of daily use: ~365 × (log size) files in `~/.cerebro/logs/`.

**Fix (3 lines in `logger.py:_safe_logs_dir` call site):**
```python
# Prune session logs older than 7 days
for old in logs_dir.glob("cerebro_*.log"):
    if old.stat().st_mtime < time.time() - 7 * 86400:
        old.unlink(missing_ok=True)
```

### 6.3 Config Singleton Race (Data Integrity — LOW)
`load_config()` / `save_config()` module-level functions are not thread-safe at the singleton guard.

**Fix:** Add a `threading.Lock` guarding the `_config_instance is None` check in `config.py`.

### 6.4 `ev` Variables in Flet Handlers (Code Quality — TRIVIAL)
`exclude_list_page.py:200,210` — rename `ev` → `_ev` to signal intentional unused parameter.

---

## SUMMARY TABLE

| Area | Finding | Severity | File |
|------|---------|----------|------|
| Security | `startfile` opens any extension including `.exe` | LOW/MED | `core/preview.py:26` |
| Security | All other checks | **CLEAN** | — |
| Data integrity | Config singleton load race (redundant reads, no corruption) | LOW | `services/config.py` |
| Data integrity | Multi-instance audit log append interleaving | LOW | `history/store.py` |
| Data integrity | SQL injection / pickle / race conditions | **CLEAN** | — |
| Performance | No unbounded caches, all UI ops async | **CLEAN** | — |
| Performance | No EXPLAIN QUERY PLAN tests | LOW | tests/ |
| Deployment | Registry read (HKCU, no UAC) | **CLEAN** | `flet_app/main.py` |
| Deployment | Temp file cleanup | **CLEAN** | — |
| Deployment | Session logs accumulate unboundedly | LOW | `services/logger.py` |
| Deployment | No uninstaller / residue docs | LOW | — |
| Code quality | 2 functions at complexity F(44) — reducer, image grouping | MEDIUM | `reducer.py`, `image_dedup_engine.py` |
| Code quality | ResultsPage._refresh at F(42) | MEDIUM | `results_page.py` |
| Code quality | 2 safety-critical D-grade pipelines | MEDIUM | `core/pipeline.py` |
| Code quality | Dead code: 2 unused `ev` vars | TRIVIAL | `exclude_list_page.py` |
| Code quality | mypy strict not in CI | LOW | `ci.yml` |

**No CRITICAL or HIGH severity findings.** The codebase is production-safe.
The three MEDIUM items (complexity) should be addressed before significant feature expansion.
