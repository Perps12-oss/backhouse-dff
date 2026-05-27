# Cerebro Scan Path Audit

*Canonical copy:* `dev/docs/architecture/scan_paths.md` (relocated from
`cerebro/core/SCAN_PATHS.md` in Phase 8.3).

*Last revised: post-v1 audit — Cuts 1–3 ("single entrance") + Phase 8
DIAG cleanup.*

## One Entrance, One File-Scan Core

Every file scan in the shipped app enters through **one function** and
lands in **one scan core**:

```
UI  (scan_page / app_shell / audit.py)
      │
      ▼
ScanOrchestrator.start_scan(mode, folders, …)   ← the only entrance
      │
      ├─ mode="files"          → TurboFileEngine   → TurboScanner.scan()   ← THE file-scan core
      ├─ mode="photos"         → ImageDedupEngine                            (separate concern: perceptual)
      ├─ mode="videos"         → VideoDedupEngine                            (separate concern)
      ├─ mode="music"          → MusicDedupEngine                            (separate concern)
      ├─ mode="empty_folders"  → EmptyFolderEngine                           (separate concern)
      └─ mode="large_files"    → LargeFileEngine                             (separate concern)
```

- **`ScanOrchestrator.start_scan()`** — `cerebro/engines/orchestrator.py`, the
  single UI-facing entry function.
- **`TurboScanner.scan()`** — `cerebro/core/scanners/turbo_scanner.py`, the
  single file-duplicate scan core. Reached via the thin `TurboFileEngine`
  adapter.

At scale (50k+ files), discovery streams rows into `CheckpointDB` and grouping
uses `iter_files_by_size` instead of a full in-memory catalogue. See
`dev/docs/architecture/scan_scale.md`.

`mode="files_classic"` no longer exists. `FileDedupEngine` (the old
independent classic pipeline, ~600 LOC) was removed in Cut 3.

## Historical Paths — all removed

| Path | Was | Removed in | Reason |
|------|-----|------------|--------|
| A | `FastScanWorker` (turbo tier) → `OptimizedScannerAdapter` → `TurboScanner` | Cut 2 | PyQt QThread wrapper with no runtime caller in the v2 Tk/CTk app |
| B | `FastScanWorker` (other tier) → `FastPipeline` | Cut 2 | legacy pre-turbo core, no caller |
| C | `TurboFileEngine` → `TurboScanner` | — | **kept, renamed as THE file-scan path** |
| D | `FileDedupEngine` (own 4-stage pipeline) | Cut 3 | independent classic duplicate of Path C |
| E | `ScanWorker` (BaseWorker) → `CerebroPipeline.run()` | Cut 2 | dead since before Phase 1 (CerebroPipeline has no run method) |
| grouping.py | `SizeGrouping.group_by_size()` | Cut 2 | confirmed dead in Phase 1 audit |

## Cut 3 details — what was removed and why it was safe

**Deleted:** `cerebro/engines/file_dedup_engine.py` (~600 LOC, ~27 KB).

**Safety argument:** the Phase 2c regression guard
(`_assert_no_self_duplicates` in `cerebro/core/group_invariants.py`) was
already live on both independent cores — `TurboScanner` and
`FileDedupEngine`. Since any behavioural divergence that would promote a
self-duplicate to emission would trip that same guard on both paths, and
since both paths already consume the same `dedupe_roots()` layer above
them, collapsing files_classic → files carries no invariant-level risk.
Functional parity was not separately benchmarked; the user accepted this
risk explicitly ("C" in the one-entrance decision gate).

**Side edits:**
- `cerebro/engines/orchestrator.py` — dropped `FileDedupEngine` import and
  the `self._engines["files_classic"]` registration.
- `cerebro/engines/__init__.py` — dropped `FileDedupEngine` re-export.
- `cerebro/engines/turbo_file_engine.py` — docstring now notes it is the
  sole file-dedup core.
- `cerebro/core/group_invariants.py` — docstring no longer lists
  file_dedup_engine among its callers.
- `dev/tests/test_turbo_engine_regressions.py` — `files_classic in
  get_available_modes()` flipped to `not in`, documenting the invariant.

## TurboScanner logging (Phase 8.1 — post-audit cleanup)

Temporary `[DIAG:*]` INFO markers (`DISCOVERY`, `REDUCE`, `PAIR`, `EMIT`,
`SUMMARY`) and the `_diagnose_pair()` sampling loop were **removed** from
`TurboScanner.scan()` to reduce log noise and per-scan CPU overhead. What
remains:

- **`[ROOT_DEDUP]`** at **INFO** — root overlap collapse (`dedupe_roots()`).
- **`[Turbo] summary:`** at **INFO** — single end-of-scan line (discovered,
  size-group candidates, final hash groups, emitted count, elapsed, cache
  stats).
- **`[DIAG:GUARD]`** at **DEBUG only** — `_assert_no_self_duplicates` counters
  (`groups_checked`, `total_files_checked`, `regressions`). Enable DEBUG on
  `CEREBRO.cerebro.core.scanners.turbo_scanner` to audit guard health.

## Phase 1 waivers — historical (pre–Phase 8.1)

These applied while `[DIAG:*]` instrumentation was live at INFO:

- **Waiver 1A** — `[DIAG:SUMMARY]` lacked `groups_dropped_self_dup` and
  `scan_type` fields; superseded at the time by `[DIAG:GUARD]`. **Obsolete**
  after `[DIAG:SUMMARY]` removal; retained here for audit trail.
- **Waiver 1B** — `_diagnose_pair()` capped at 8 invocations per scan.
  **Obsolete** — function removed with Phase 8.1.
- **Waiver 1C** — Phase 1 sample log used the `jhjl` test tree; production
  evidence is documented in `dev/docs/bug-investigations/bug1-canonical-path-dedup.md`.
  **Still accurate.**

## Bug 1 canonical-path dedup — status

Fixed in Phase 2a via `cerebro/core/root_dedup.py::dedupe_roots()` at the root
layer, plus the `_assert_no_self_duplicates` guard in
`cerebro/core/group_invariants.py` at the group layer. Both guards remain live
on `TurboScanner`, which is now the only file-dedup core. Full evidence in
`dev/docs/bug-investigations/bug1-canonical-path-dedup.md`.
