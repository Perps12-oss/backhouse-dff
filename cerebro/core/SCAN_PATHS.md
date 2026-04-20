# Cerebro Scan Path Audit
*Last revised: post-v1 audit, Cuts 1–3 landed ("single entrance" complete)*

## One Entrance, One File-Scan Core

Every file scan in the shipped app enters through **one function** and
lands in **one scan core**:

```
UI  (scan_page / main_window_controllers / audit.py)
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
- `tests/test_turbo_engine_regressions.py` — `files_classic in
  get_available_modes()` flipped to `not in`, documenting the invariant.

## Phase 1 instrumentation — still in effect on the sole live path

DIAG log markers remain at INFO level on TurboScanner:

- `[DIAG:DISCOVERY]` — file count actually passed downstream, root(s), filters
- `[DIAG:REDUCE]`    — count-in / count-out at each reduction step
- `[DIAG:PAIR]`      — per-pair canonical-path / inode collision detection (capped at 8/scan)
- `[DIAG:SUMMARY]`   — final totals
- `[DIAG:GUARD]`     — `_assert_no_self_duplicates` regression guard output
- `[DIAG:EMIT]`      — singleton-group filter at the emit step
- `[ROOT_DEDUP]`     — root-overlap collapse (Phase 2a fix)

## Phase 1 waivers — still in force

- **Waiver 1A** — `[DIAG:SUMMARY]` lacks `groups_dropped_self_dup` and `scan_type`
  fields. Superseded by `[DIAG:GUARD]`. Accepted.
- **Waiver 1B** — `_diagnose_pair()` capped at 8 invocations per scan to prevent
  log flooding. Accepted.
- **Waiver 1C** — Phase 1 sample log used the `jhjl` test tree; production
  evidence is documented in `docs/bug-investigations/bug1-canonical-path-dedup.md`.

## Bug 1 canonical-path dedup — status

Fixed in Phase 2a via `cerebro/core/root_dedup.py::dedupe_roots()` at the root
layer, plus the `_assert_no_self_duplicates` guard in
`cerebro/core/group_invariants.py` at the group layer. Both guards remain live
on `TurboScanner`, which is now the only file-dedup core. Full evidence in
`docs/bug-investigations/bug1-canonical-path-dedup.md`.
