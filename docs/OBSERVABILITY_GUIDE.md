# CEREBRO — Observability & Diagnostics Guide

How to get more meaningful logs, measure performance, and surface the *silent*
errors that only appear under load (large libraries, slow/external drives,
permission edge cases). Written against the current code; file:line refs included.

---

## 1. Switches you already have (no code change)

Set these as environment variables before launching (`set VAR=1` on Windows cmd,
`$env:VAR=1` in PowerShell):

| Env var | Effect | When to use |
|---------|--------|-------------|
| `CEREBRO_DEBUG=1` | Root log level → DEBUG | Reproducing a bug; see the `_log.debug(...)` lines that are normally hidden |
| `CEREBRO_LOG_JSON=1` | One JSON object per log line (`logger.py:108`) | Feeding logs to a parser / aggregator; reliable field extraction |
| `CEREBRO_REDACT_PATHS=1` | Replaces home dir with `~` (`logger.py:76`) | Sharing logs without leaking paths |
| `CEREBRO_SENTRY_DSN=…` | Sends exceptions to Sentry (`sentry_init.py`) | Catching crashes on machines you can't see |
| `CEREBRO_TURBO_TIERA_WORKERS=N` | Override Tier-A read concurrency | Tuning the slow filter phase on external/unknown drives |
| `CEREBRO_TURBO_HASH_WORKERS=N` | Override hash worker count | Tuning hashing throughput |

**Logs live in** `~/.cerebro/logs/`:
- `cerebro.log` — rotating, 10 MB × 5 backups, UTF-8 (`logger.py:273`)
- `cerebro_<timestamp>.log` — one per session (`logger.py:289`)
- Old session logs auto-pruned after 7 days (`logger.py:212`)

> **Console encoding fix (2026-05):** stdout is now forced to UTF-8 so non-ASCII
> paths no longer render as mojibake (`¼áÞ¿¡á…`) on Windows consoles. The file logs
> were always UTF-8; if you still see garbled paths, your *viewer* is using cp1252 —
> open the log as UTF-8.

---

## 2. Reading a scan run (what "good" looks like)

The Turbo summary block is your primary perf instrument (`turbo_scanner.py`):

```
[Turbo] Phase timings: discovery=21.70s grouping=71.19s tier_a=424.52s
        quick_hash=0.95s full_hash=0.00s yield=0.03s total=518.40s
[Turbo] Tier-A filter: candidates_in=414057 survivors=234 rejected=413823 (99.9%)
        in 424.52s (975 cand/s, workers=8)      <-- NEW: throughput + worker count
```

Rules of thumb:
- **`tier_a` should not dominate.** If it's >50% of `total`, you're seek-bound —
  the drive, not the CPU, is the limit. The `cand/s` and `workers=N` fields tell
  you whether raising workers helps (see §3).
- **`discovery` slow?** Network/USB latency or antivirus scanning every file.
- **High `rejected %` with huge `candidates_in`** means lots of same-size files
  that aren't actually duplicates — Tier-A is doing real work to prove that.
- **`Process RSS after scan`** is your memory ceiling. Watch it grow with the
  *number of duplicate rows emitted*, not total files scanned.

The **cache stat is per-phase, not whole-scan.** `Cache hits: 234 / 100%` only
covers the full-hash phase; the 414k Tier-A reads are **not** counted. Don't read
"100% hit rate" as "the scan was cached."

---

## 3. The Tier-A tuning loop (slow-drive performance)

When storage detection logs `type=unknown` or `type=removable_unknown`, the worker
cap is deliberately conservative (8 Tier-A threads) to avoid thrashing a single
spinning HDD. For a fast external **SSD** that's far too few. To find the sweet spot:

1. Run a baseline scan, note `cand/s` and `workers=N` in the Tier-A line.
2. `set CEREBRO_TURBO_TIERA_WORKERS=24` and re-scan the same folder.
3. Compare `cand/s`:
   - **Goes up** → it's an SSD/low-seek device; keep the higher value.
   - **Flat or down** → it's a real HDD; seeks are thrashing — lower it (try 4–8).
4. Persist the winning value in your launch script / shortcut.

Bounds: overrides are clamped to 1–64 (`turbo_file_engine.py`). The override also
forces phase-worker policy on so it actually takes effect.

> **Known limitation (not yet fixed):** `_probe_windows_storage` picks the *first*
> physical disk, not the drive being scanned (`turbo_file_engine.py`). On a
> multi-disk machine it can mislabel an external drive. Until that's fixed, the env
> override is the reliable lever. Fixing it needs a drive→partition→disk PowerShell
> query, validated on your Windows version.

> **Bigger win than worker tuning (follow-up):** 414k candidates → 234 survivors is
> a 99.9% rejection rate — Tier-A does 414k seeks to discard almost all of them. A
> cheaper pre-filter (e.g. special-casing the pathological "25,177 files all 747 bytes"
> bucket, or rejecting obvious system-install copies before Tier-A) could be a 5–10×
> scan win that dwarfs concurrency tuning.

---

## 4. Finding *silent* errors

The app is defensively coded — many failures are caught and swallowed so a scan or
delete never aborts. That resilience hides problems. Where they hide and how to see them:

### a. Broad `except` blocks that `pass`
Search for them:
```
rg -n "except.*:\s*$" --type py -A1 cerebro | rg -B1 "pass|continue"
```
The risky pattern is `except (OSError, ValueError, RuntimeError, AttributeError,
TypeError, KeyError, ImportError)` (e.g. `deletion.py:147,194,243`). It catches
*programming* errors (`AttributeError`/`KeyError`) as if they were I/O errors. Under
stress these mask real bugs. **Tighten to `OSError` on the I/O lines** so logic bugs
raise instead of vanishing.

### b. Make swallowed exceptions countable
When you must swallow, count it so it shows up in summaries instead of disappearing:
```python
# module-level
_swallowed = collections.Counter()

try:
    risky()
except OSError as exc:
    _swallowed[type(exc).__name__] += 1
    _log.debug("swallowed during scan: %s", exc, exc_info=True)

# at end of operation
if _swallowed:
    _log.warning("scan finished with %d swallowed errors: %s", sum(_swallowed.values()), dict(_swallowed))
```
A scan that "succeeds" but logs `847 swallowed errors: {'PermissionError': 847}`
tells you antivirus or ACLs blocked nearly everything — invisible today.

### c. Failures that already surface (use them)
- **Deletes:** every failure is recorded in the audit trail
  (`history.store: Recorded deletion audit ... failed=N`). After a batch, check
  `failed` — non-zero means files couldn't be trashed (read-only, locked, permissions).
- **Trash manifest write failures** now log at WARNING (`deletion.py:83`) — they mean
  your undo coverage is incomplete.
- **Log rotation failures** on Windows print to stderr once (`logger.py:163`).

### d. Promote DEBUG breadcrumbs at the boundary
The checkpoint/cancel/pause paths log at DEBUG. When chasing a "scan hung / returned
empty" report, run with `CEREBRO_DEBUG=1` and grep the session log for the phase
transitions (`scan phase transition`) — a missing transition pinpoints the stuck phase.

---

## 5. Logging under stress (load, large libraries)

Things that only break at scale, and how to instrument them:

| Symptom under load | Add this signal |
|--------------------|-----------------|
| Memory creeps up on huge result sets | Periodic RSS sampler (below) during the scan, not just at the end |
| UI freezes during big batches | Log marshaller queue depth / time spent on the UI thread |
| Slow ops you can't see | A `@timed` decorator that warns past a threshold |
| Thread leaks after cancel | Log `threading.active_count()` before/after scan |

**Periodic resource sampler** (drop in a worker thread during long scans):
```python
import psutil, threading, time
def _resource_sampler(stop: threading.Event, every=5.0):
    p = psutil.Process()
    while not stop.wait(every):
        _log.info("resource sample: rss_mb=%.1f threads=%d open_files=%d",
                  p.memory_info().rss/1e6, p.num_threads(), len(p.open_files()))
```
This turns "it got slow somewhere" into a time series you can correlate with phases.

**Slow-op timing decorator:**
```python
import functools, time
def timed(threshold_s=1.0):
    def deco(fn):
        @functools.wraps(fn)
        def wrap(*a, **k):
            t = time.perf_counter(); r = fn(*a, **k); dt = time.perf_counter()-t
            if dt >= threshold_s:
                _log.warning("slow: %s took %.2fs", fn.__qualname__, dt)
            return r
        return wrap
    return deco
```

---

## 6. Adopt structured logging for new metrics

The codebase already ships `structlog` and a helper (`logger.py:403`,
`get_structured_logger`). For *new* perf/metric logging, prefer key=value over
free-text — it survives parsing and aggregation:

```python
from cerebro.services.logger import get_structured_logger
_slog = get_structured_logger(__name__)
_slog.info("scan_complete", files=591197, dup_groups=80, tier_a_s=424.5,
           cand_per_s=975, rss_mb=490.6, drive_type="removable_unknown")
```
Combine with `CEREBRO_LOG_JSON=1` and you can `jq` your scans:
`jq 'select(.event=="scan_complete") | {files, tier_a_s, cand_per_s}' cerebro_*.log`.

Do **not** mass-migrate existing `getLogger(__name__)` calls — add structured logs
only where you're adding new metrics.

---

## 7. Stress-test logging checklist

Before shipping a perf or reliability change, run a scan on a *large, real* folder
with these on, and check the session log:

- [ ] `CEREBRO_DEBUG=1` — phase transitions present and in order?
- [ ] Tier-A `cand/s` and `workers=N` recorded — is the phase split sane?
- [ ] `Process RSS after scan` within budget for the dup-row count?
- [ ] Delete a batch including a **read-only** and a **locked** file — both reported in `failed=`, none silently lost?
- [ ] Cancel mid-scan — does `threading.active_count()` return to baseline within the 30s join?
- [ ] Any `swallowed errors` warning? Investigate the counter breakdown.
- [ ] On an external/USB drive: is it labeled `removable_unknown`, and does the tuning hint appear?

---

*Companion to `docs/PRODUCTION_AUDIT_VERIFICATION.md`. The §3 pre-filter idea and the
drive-specific storage probe are tracked there as performance follow-ups.*
