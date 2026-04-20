# Cerebro Scan Path Audit
*Generated: Phase 1 post-v1 audit*

## Active Scan Paths

### Path A — PRIMARY (default production path)
- **Entry**: `cerebro/workers/fast_scan_worker.py` `FastScanWorker._run_optimized_scan()`
- **Via**: `cerebro/core/scanner_adapter.py` `OptimizedScannerAdapter.scan()`
- **Core**: `cerebro/core/scanners/turbo_scanner.py` `TurboScanner.scan()`
- **Trigger**: `scanner_tier` in `{"turbo", "ultra", "quantum"}` (default: `"turbo"`)
- **Canonical dedup**: NONE
- **Cache-backed**: YES (`HashCache` SQLite at `~/.cerebro/cache/hash_cache.sqlite`)
- **Logger**: `get_logger(__name__)` via `cerebro.services.logger` — CEREBRO handler ✓

### Path B — LEGACY FALLBACK
- **Entry**: `cerebro/workers/fast_scan_worker.py` `FastScanWorker.run()`
- **Core**: `cerebro/core/fast_pipeline.py` `FastPipeline.run_fast_scan()`
- **Trigger**: `scanner_tier` is any value NOT in `{"turbo", "ultra", "quantum"}`
- **Canonical dedup**: NONE
- **Cache-backed**: YES (conditional on `cache_path` being set)
- **Logger**: none in original — added `get_logger(__name__)` in Phase 1

### Path C — ENGINE MODE
- **Entry**: `cerebro/engines/turbo_file_engine.py` `TurboFileEngine._do_scan()`
- **Core**: `cerebro/core/scanners/turbo_scanner.py` `TurboScanner.scan()` (direct)
- **Trigger**: `ScanOrchestrator.start_scan()` with `mode="files"` (registered default)
- **Canonical dedup**: NONE
- **Cache-backed**: YES (same `HashCache` as Path A)
- **Logger**: `logging.getLogger(__name__)` — bypasses CEREBRO file handler

### Path D — CLASSIC ENGINE
- **Entry**: `cerebro/engines/file_dedup_engine.py` `FileDedupEngine._run_scan()`
- **Trigger**: `ScanOrchestrator.start_scan()` with `mode="files_classic"`
- **Canonical dedup**: NONE
- **Cache-backed**: YES (own `HashCache` from `cerebro.engines.hash_cache`)
- **Logger**: `logging.getLogger(__name__)` at module bottom — bypasses CEREBRO file handler

### Convenience Wrappers
- `cerebro/core/scanners/turbo_scanner.py` `quick_scan()` → TurboScanner.scan() — Path A core
- `cerebro/core/scanners/turbo_scanner.py` `incremental_scan()` → TurboScanner.scan() — Path A core

---

## Dead Paths

### grouping.py — DEAD (instrumented)
- **File**: `cerebro/core/grouping.py` `SizeGrouping.group_by_size()`
- **Caller**: designed for the Path E `ScanWorker` → `CerebroPipeline` pipeline
- **Status**: DEAD — `SizeGrouping` is never imported anywhere in the live app
- **Instrumented**: YES — DIAG:DISCOVERY / DIAG:REDUCE / DIAG:PAIR / DIAG:SUMMARY added
  for completeness; logs will not appear in normal operation

---

### Path E — DEAD
- **Entry**: `cerebro/workers/scan_worker.py` `ScanWorker.execute()`
- **Calls**: `CerebroPipeline().run(request, ...)` — `CerebroPipeline` in `cerebro/core/pipeline.py`
  has no `.run()` method (it is a **delete pipeline**, not a scan pipeline)
- **Never instantiated**: No UI or controller code creates `ScanWorker`
- **Status**: DEAD — would raise `AttributeError` if ever called

---

## Bug 1 Surface: Canonical-Path False Positives

All four active paths group files by size before hashing. None apply canonical-path
deduplication. On Windows, paths to the same physical file can appear as distinct strings
via: NTFS hardlinks, directory junctions, 8.3 short-name aliases, or Unicode
normalization variants. When two such paths fall in the same size group, they hash
identically and are incorrectly reported as duplicates.

**Fix target (Phase 2)**: apply canonical dedup at the size-grouping chokepoint in
each active path using `os.path.normcase(os.path.realpath(p))` +
`unicodedata.normalize("NFC", ...)`.

---

## Phase 1 Instrumentation Added

DIAG log markers added to all active paths at INFO level:
- `[DIAG:DISCOVERY]` — file count actually passed downstream, root(s), filters
- `[DIAG:REDUCE]`    — count-in / count-out at each size/hash reduction step (no path dumps)
- `[DIAG:PAIR]`      — fires per-pair when `_diagnose_pair()` detects a canonical-path or
                       inode collision within a size group
- `[DIAG:SUMMARY]`   — final totals: discovered, candidates, groups, elapsed, cache hit%

### DIAG:SUMMARY cache_hit% coverage

| Path | cache_hit% in SUMMARY | Notes |
|------|-----------------------|-------|
| A / C  turbo_scanner.py   | YES | HashCache tracks hits/misses via stats dict |
| B      fast_pipeline.py   | YES | Counter added in cache-lookup loop |
| D      file_dedup_engine.py | WAIVER | Cache accessed inside worker threads; adding a thread-safe hit counter requires non-trivial shared state. cache_hit% omitted from DIAG:SUMMARY for this path. |
| grouping.py (dead)         | N/A | No hash cache; omitted |

---

## Phase 1 Closure Waivers

### Waiver 1A — `[DIAG:SUMMARY]` missing `groups_dropped_self_dup` and `scan_type` fields

**Original spec:** `[DIAG:SUMMARY]` to include `groups_dropped_self_dup` and `scan_type`
fields (fresh|rescan|resume).

**Actual:** These fields are absent. Existing `[DIAG:SUMMARY]` fields
(groups_created, emitted, cache_hits, cache_misses, elapsed) are present.

**Reason:** Instrumentation scope creep — tracking these fields would have required
state propagation across phase boundaries for no diagnostic value post-Phase-2.
The `groups_dropped_self_dup` metric is superseded by the `[DIAG:GUARD]` regression
guard landed in Phase 2c (434fa7f). The `scan_type` field is not needed for any
downstream phase decision.

**Status:** ACCEPTED. No corrective action required.

---

### Waiver 1B — `_diagnose_pair()` fires at most 8 times per scan

**Original spec:** `_diagnose_pair()` exhaustive coverage (implied: fires on every
collision pair encountered).

**Actual:** Capped at 8 invocations per scan.

**Reason:** Prevents log flooding on corpora with many potential collisions. 8 samples
are sufficient to characterize a collision pattern; exhaustive logging on a 16,965-file
scan would produce hundreds of entries with no additional diagnostic value.

**Status:** ACCEPTED. No corrective action required.

---

### Waiver 1C — Sample reproduction used `jhjl` test tree, not production dataset

**Original spec:** Reproduction against production dataset.

**Actual:** Phase 1 sample log (`phase1_scan_20260420_015801.log`) was captured against
the `jhjl` test tree (1,072 files, 23 size groups, 1 final pair).

**Reason:** Production reproduction was performed during Phase 2 investigation, not
Phase 1. The 5-root overlap set (16,965 files, 5 user-specified roots, 2 descendants
collapsed to 3 effective roots, 4,560 emitted post-fix) is documented with full inline
log evidence in `docs/bug-investigations/bug1-canonical-path-dedup.md`.

**Status:** ACCEPTED. Production evidence exists in the Phase 2 investigation doc.
