# Post-V1 Audit Plan — Working Contract

**Status:** Active
**Owner:** Steve
**Reviewer:** [senior advisor]
**Branch:** fix/post-v1-audit
**Target tag:** v1.1.0-post-audit
**Last updated:** 2026-04-22

---

## Purpose

This document is the single source of truth for the post-v1 audit
work on Cerebro. It supersedes the original phased plan, all
intermediate amendments in chat history, and any ad-hoc
instructions given in individual sessions.

Any commit landed on `fix/post-v1-audit` is graded against this
file. If a task is not in this file, it is not authorized. If a
deviation from this file is needed, the deviation must be
documented in an amendment commit to this file BEFORE the
implementation commit lands.

---

## Protocol (binding on every phase)

1. **Readback first.** Before any code change, Claude Code
   produces a readback of the phase spec. Readback must include
   the signal phrase `canonical chokepoint understood` as the
   final line. Absence of the phrase = soft reject.

2. **One phase per response.** No combining phases.

3. **Commit + push after each phase.** No batching multiple
   phases into one push.

4. **Verify checklist must pass** before the next phase starts.
   Failed verify = stop and report. Do not patch forward.

5. **No sub-phase splits** (e.g. 2a/2b/2c) without explicit
   approval recorded in this document's amendment log.

6. **No silent waivers.** Every deviation from an original verify
   bullet requires a written waiver with evidence quoted inline
   in the relevant bug investigation doc.

7. **Stop conditions** are binding. If any are hit during
   execution, halt and report. Do not attempt to patch around
   them.

---

## Phase Status

| Phase | Status                       | SHAs                                   |
|-------|------------------------------|----------------------------------------|
| 1     | CLOSURE COMPLETE             | 65ce5d1, a8bb998 (+ plan closure commit) |
| 1.5   | MERGED INTO PHASE 1          | —                                      |
| 2     | CLOSURE PENDING (Steps 2–5)  | b0e94d6, 835bc68, 434fa7f, + 2d/2e/doc |
| 3     | NOT STARTED                  | —                                      |
| 4     | NOT STARTED                  | —                                      |
| 5     | NOT STARTED                  | —                                      |
| 6     | NOT STARTED                  | —                                      |
| 7     | NOT STARTED                  | —                                      |
| 8     | NOT STARTED                  | —                                      |

---

# PHASE 1 — Instrument All Scan Paths (CLOSURE PENDING)

## Status

**CLOSURE COMPLETE (2026-04-22).** Implementation commits landed earlier
(65ce5d1, a8bb998). On-branch verification confirms: no tracked files
under `diagnostics/` (local logs only), `.gitignore` lists `diagnostics/`,
`scripts/dev/phase1_scan_runner.py` is the canonical runner, and
`cerebro/core/SCAN_PATHS.md` carries Waivers 1A–1C (see §Phase 1 waivers).

## Closure Commit — `chore(phase1-closure): reconcile Phase 1 artifacts`

One commit on `fix/post-v1-audit`. Scope:

1. **Add `diagnostics/` to `.gitignore`.** Currently tracked
   despite being treated as local-only. Fix.

2. **`git rm` the two tracked diagnostic files:**
   - `diagnostics/_run_phase1_scan.py`
   - `diagnostics/phase1_scan_20260420_015801.log`

3. **Relocate the Phase 1 scan runner.** Move to
   `scripts/dev/phase1_scan_runner.py` for re-run capability.
   Same retention policy will apply to `_phase2_cache_experiment.py`
   at Phase 8 — retained until final cleanup, then evaluated for
   deletion.

4. **Append three waivers to `SCAN_PATHS.md`** (current location;
   moves to `docs/architecture/scan_paths.md` in Phase 8):

   - **Waiver 1A:** `[DIAG:SUMMARY]` does not include
     `groups_dropped_self_dup` or `scan_type` fields as originally
     specified. Reason: instrumentation scope creep — these fields
     would have required tracking across phase boundaries for no
     diagnostic value post-Phase-2. Existing `[DIAG:SUMMARY]` fields
     (groups_created, emitted, cache_hits, cache_misses, elapsed)
     are sufficient.

   - **Waiver 1B:** `_diagnose_pair()` fires at most 8 times per
     scan. Reason: prevents log flooding on corpora with many
     potential collisions; 8 samples are sufficient to characterize
     a pattern.

   - **Waiver 1C:** Sample reproduction used `jhjl` (1,072 files,
     23 size groups, 1 final pair). This is the test tree, not the
     production dataset. Production reproduction was performed
     against the 5-root overlap set (16,965 files) documented in
     `docs/bug-investigations/bug1-canonical-path-dedup.md`.

## Verify (all must be true after closure commit)

- [x] `git ls-files diagnostics/` returns nothing
- [x] `.gitignore` contains `diagnostics/`
- [x] `scripts/dev/phase1_scan_runner.py` exists (`python scripts/dev/phase1_scan_runner.py`)
- [x] `cerebro/core/SCAN_PATHS.md` contains the three waivers above
- [x] Running `python scripts/dev/phase1_scan_runner.py <path>` completes
      a turbo scan without error (log file under gitignored `diagnostics/`)

## Original Verify Bullets (status)

| Bullet                                                  | Status       |
|---------------------------------------------------------|--------------|
| All 5 scan paths documented                             | CLOSED       |
| DIAG:DISCOVERY on all active paths                      | CLOSED       |
| DIAG:REDUCE at every chokepoint                         | CLOSED       |
| DIAG:PAIR triggers on canonical collision not basename  | CLOSED       |
| DIAG:SUMMARY on all active paths                        | CLOSED w/1A  |
| `diagnostics/` gitignored + sample log saved            | CLOSED       |
| `_diagnose_pair` exhaustive coverage                    | CLOSED w/1B  |
| Reproduction against production dataset                 | CLOSED w/1C  |

---

# PHASE 2 — Fix Bug 1 (CLOSURE PENDING)

## Status

Primary fix landed (b0e94d6, root overlap). Two defense-in-depth
commits landed (835bc68 singleton filter, 434fa7f canonical
regression guard). Three closure steps remain: coverage gap, build
mode correction, and investigation doc.

## Scope Change (Waiver 4) — Formally Recorded

**Original Phase 2 primary mechanism:** `engine/canonical.py` with
`_canonicalize_and_dedupe(files)` applying `normcase(realpath) +
NFC + strip` at a shared chokepoint covering all scan paths.

**Actual primary mechanism:** `cerebro/core/root_dedup.py` with
`dedupe_roots()` applied at the scan dispatcher.

**Reason:** The 4-run diagnostic matrix (jhjl × {hot, cold} ×
{5-root, parents-only}) falsified the hypothesis that Bug 1 was
file-level canonical collision. The winning hypothesis is
root-overlap double-enumeration: when a user specifies both a
parent root and a descendant root, files under the descendant are
enumerated twice.

**Retention:** `normcase(realpath)` canonicalization IS retained,
but in the defense-in-depth guard `_assert_no_self_duplicates`
(434fa7f), not as the primary fix. Evidence: see
`docs/bug-investigations/bug1-canonical-path-dedup.md` §Falsifications.

## Sub-Phase Ledger (Post-Hoc Documented — Advisor Waiver Granted)

Sub-phase split (2a/2b/2c) was a protocol breach — not pre-approved.
Recorded here for audit trail. No further sub-phase splits
permitted without explicit approval.

| Sub-phase | SHA       | Landed     | Scope                                  |
|-----------|-----------|------------|----------------------------------------|
| 2a        | b0e94d6   | [date]     | `dedupe_roots()` + `[ROOT_DEDUP]` log   |
| 2b        | 835bc68   | [date]     | Singleton emit filter + `[DIAG:EMIT]`  |
| 2c        | 434fa7f   | [date]     | `_assert_no_self_duplicates` + `[DIAG:GUARD]` |
| 2d        | PENDING   | Step 3     | Port 2b+2c to Paths B and D            |
| 2e        | PENDING   | Step 4     | `__debug__` posture correction         |
| doc       | PENDING   | Step 5     | `bug1-canonical-path-dedup.md`         |

## Step 2 — DB Canonical-Path Invariant (Waiver 3 Resolution)

**NOT WAIVABLE.** Original Phase 2 verify bullet. Run the query,
paste raw output.

```sql
SELECT canonical_path, COUNT(*) 
FROM files 
GROUP BY canonical_path 
HAVING COUNT(*) > 1 
LIMIT 20;
```

**Outcome gates:**

- Zero rows → Waiver 3 resolved positive. Proceed to Step 3.
- Non-zero rows with identifiable cause (test fixtures, etc.) →
  Stop, report to advisor with rows, do not proceed.
- Non-zero rows unexpected → Phase 2 re-opens. Stop all downstream
  work. Bug 1 is not closed.

## Step 3 — `fix(phase2d)`: Port Guard + Filter to Paths B and D

### Context

Advisor review §D identified coverage gap in Phase 2b/2c. Current
state:

| Path | Route               | dedupe_roots | DIAG:EMIT + filter | _assert_no_self_duplicates |
|------|---------------------|:------------:|:------------------:|:--------------------------:|
| A    | Turbo (primary)     | YES          | YES                | YES                        |
| B    | fast_pipeline       | n/a          | NO                 | NO                         |
| C    | Turbo (engine mode) | YES          | YES                | YES                        |
| D    | file_dedup_engine   | YES          | NO                 | NO                         |

Paths B and D lack the emit filter and the canonical guard.

### Decision

**Port, not waive.** Guard + filter is ~20 lines each per path.
Waiver is the weaker move and creates permanent asymmetry between
scan paths.

### Tasks

1. **Extract the canonical guard into a shared module.** Currently
   defined inline in `turbo_scanner.py`. Move to
   `cerebro/core/group_invariants.py` (or similar) so all scan
   paths can import it. Same behavior, same signature.

2. **Port to `fast_pipeline.py` (Path B):**
   - Add `[DIAG:EMIT]` summary log before emit loop
   - Add singleton filter (`if len(group) < 2: continue`)
   - Call `_assert_no_self_duplicates(group)` BEFORE the singleton
     filter (preserves Phase 2c ordering decision)

3. **Port to `file_dedup_engine.py` (Path D):**
   - Same three additions as Path B

4. **Verify each ported path:**
   - Run harness against Path B if it can be invoked directly
   - Run harness against Path D if it can be invoked directly
   - `[DIAG:GUARD]` must show `regressions=0` on every path that
     CAN be invoked

5. **Untestable-path handling:** If a path cannot be invoked
   standalone (Path B is "single-root dispatcher, no production
   usage observed" — may require GUI driving), document in the
   commit message with explicit language:
   
   > "Path [B/D] instrumented but not exercised in verification
   > run; relies on code-path static review for correctness."

### Verify

- [ ] `cerebro/core/group_invariants.py` exists; old inline
      definition removed
- [ ] `fast_pipeline.py` contains `[DIAG:EMIT]` log, singleton
      filter, and guard call (in correct order)
- [ ] `file_dedup_engine.py` same
- [ ] `[DIAG:GUARD] regressions=0` on every path that can be
      invoked in verification
- [ ] Untestable paths documented in commit message

## Step 4 — `fix(phase2e)`: `__debug__` Posture Correction

### Context

Advisor review §E identified that `_assert_no_self_duplicates`
uses `if __debug__: raise AssertionError`. Python runs with
`__debug__ == True` unless `-O` is passed. If Cerebro ships
without `-O`, every regression crashes the scan in production
instead of the "log warning and drop" release behavior the plan
promised.

### Pre-task investigation

Verify: does any Cerebro launch path use `python -O`?
Check:
- Entry-point scripts (`cerebro`, `cerebro.exe`, `main.py`)
- PyInstaller build flags if applicable
- Packaging/installer configuration
- CI launch commands

**Expected finding:** no `-O`. Therefore `__debug__` is True at
runtime and the guard's release behavior is unreachable.

**Unexpected finding:** `-O` is used. STOP. Report to advisor
before changing the logic.

### Fix

Replace `if __debug__:` gating with environment-variable gating:

```python
import os

_STRICT = os.environ.get("CEREBRO_STRICT", "").lower() in ("1", "true", "yes")

# ... inside _assert_no_self_duplicates:
if _STRICT:
    raise AssertionError(msg)
log.warning(msg)
continue
```

Docstring must explain:
- `CEREBRO_STRICT=1` enables hard-fail mode (tests, CI, developer runs)
- Unset or empty = log-and-drop release behavior
- Default production posture = unset

### Commit strategy

- Fold into Step 3's `fix(phase2d)` commit if diff stays small
- Otherwise land as separate `fix(phase2e)` commit

### Verify

- [ ] Build mode confirmed (with or without `-O`)
- [ ] `_STRICT` flag implemented with correct env-var parsing
- [ ] Docstring documents the three states (strict, default,
      unexpected -O)
- [ ] Test with `CEREBRO_STRICT=1`: synthetic self-dup raises
- [ ] Test with `CEREBRO_STRICT` unset: synthetic self-dup logs
      warning and continues
- [ ] Phase 8 verification adds a bar for this behavior

## Step 5 — `docs(phase2): bug 1 investigation report`

### Location

`docs/bug-investigations/bug1-canonical-path-dedup.md`

### Mandatory Sections

All seven sections required. Evidence must be quoted inline — log
lines pasted verbatim, not referenced by file path alone.

1. **Datasets**
   - jhjl: 1,072 files, 23 size groups, 1 final pair (test tree)
   - Production: 16,965 files, 5 user-specified roots, 2
     descendants collapsed to 3 effective roots, 4,560 emitted
     post-fix

2. **Timeline of Hypotheses**
   Each hypothesis gets: date, evidence line from logs (quoted
   inline), rejected or accepted status.
   - H1: Root-overlap double-enumeration
   - H2: Cache serving pre-fix stale entries
   - H3: Zero-filtering at emit (singleton groups leaking)
   - H4: File-level canonical collision (original plan's assumption)

3. **Winning Hypothesis**
   - Root-overlap double-enumeration (H1)
   - Fix SHA: b0e94d6
   - Regression indicator: `[ROOT_DEDUP] N roots → M` log line
     AND Phase 1 → Phase 2 monotonic count relationship

4. **Falsifications**
   - Singleton hypothesis (H3): Phase 2b evidence,
     `singleton_groups=0` across all runs (inline log lines)
   - Cache hypothesis (H2): 4-run matrix table reproduced inline
   - Canonical-collision hypothesis (H4): matrix showed cache
     parity, ruling out pre-fix canonicalization issues

5. **Defense-in-Depth**
   - Singleton filter (835bc68) — scope: Paths A/C initially,
     ported to B/D at [fix(phase2d) SHA]
   - Canonical guard (434fa7f) — scope: Paths A/C initially,
     ported to B/D at [fix(phase2d) SHA]

6. **Waivers (each with inline evidence)**
   - **Waiver 1 — "Candidates > Emitted":** ACCEPTED. Evidence:
     `[DIAG:EMIT]` log lines from jhjl, 5-roots hot,
     parents-only runs showing `singleton_groups=0`. Dataset
     context, SHAs, timestamps included.
   - **Waiver 2 — "Cache invalidated on first post-fix run":**
     ACCEPTED. Evidence: 4-run matrix table (hot × cold × 5-roots
     × parents-only). Reasoning that cache parity exonerated H2.
     Statement that `CACHE_SCHEMA_VERSION` was not bumped.
   - **Waiver 3 — "DB canonical_path query returns zero rows":**
     RESOLVED (not waived). Evidence: raw SQL output from Step 2.
   - **Waiver 4 — "canonical.py as primary mechanism":** ACCEPTED.
     Evidence: falsified hypothesis description, redirect to
     `root_dedup.py` + `_assert_no_self_duplicates` as retained
     canonical logic.
   - **Waiver 5 — "Shared chokepoint covers all paths":**
     RESOLVED via port (not waived). Evidence: `fix(phase2d)` SHA
     with verification results.

7. **Forward Guard (Maintenance Runbook)**
   - Which log line would indicate a Bug 1 regression?
     (`[ROOT_DEDUP]` missing, or non-monotonic phase counts, or
     `[DIAG:GUARD] regressions > 0`)
   - Which DB query would surface a regression?
     (The canonical-path COUNT(*)>1 query from Step 2)
   - Under what filesystem conditions might a NEW Bug 1 variant
     appear that current fixes don't catch?
     (Hardlinks/junctions from non-overlapping user-specified
     roots; guard catches these, but worth noting.)

## Verify (full Phase 2 closure)

- [ ] Step 2 SQL output pasted in the investigation doc,
      confirmed zero rows
- [ ] Step 3 port commit landed, `[DIAG:GUARD] regressions=0`
      on testable paths
- [ ] Step 4 `__debug__` correction landed, strict/default
      behaviors verified
- [ ] Step 5 investigation doc complete with all 7 sections and
      inline evidence
- [ ] All 5 waivers either resolved or formally accepted with
      evidence
- [ ] `docs/bug-investigations/bug1-canonical-path-dedup.md`
      committed

---

# PHASE 3 — Scan Counter (with mandatory Phase 3.0)

## Phase 3.0 — Guard/INSERT Order Investigation (binding)

Before any Phase 3 fix is written:

### Tasks

1. Add temporary DEBUG log at TWO points:
   - Controller-level guard entry
     (`main_window_controllers.py :: start_scan` or equivalent)
   - `INSERT INTO scans` call site (wherever scan history
     persistence lives)

2. Run scenario: two rapid back-to-back Scan button clicks in the
   GUI.

3. Capture the full log.

4. Decide on evidence:
   - **Guard fires BEFORE INSERT** → no orphan rows. Proceed with
     Phase 3 as originally specified.
   - **Guard fires AFTER INSERT** → orphan rows exist. Phase 3
     fix must ALSO move the INSERT below the guard OR remove
     existing orphan rows, in the same commit, with a
     `[DIAG:GUARD_ORDER]` one-shot runtime assertion line proving
     the fix is live.

5. Commit the investigation log (sanitized) to
   `docs/bug-investigations/phase3_guard_order.log`. No verbal
   wave-through.

## Phase 3 — Main (conditional on 3.0 finding)

### Tasks

1. Locate the insert:
   ```
   grep -rn "scan_history\|INSERT.*scan" --include="*.py"
   ```

2. Apply the appropriate fix based on 3.0 finding:
   - If guard-before-insert confirmed: just fix the root cause of
     the counter not incrementing (likely `INSERT OR REPLACE` with
     fixed key, missing commit, or UI caching stale count).
   - If guard-after-insert confirmed: fix the persistence logic
     AND add the `[DIAG:GUARD_ORDER]` assertion AND purge existing
     orphan rows.

3. Ensure Welcome page and Diagnostics re-query on
   `on_show()` / tab activation, not only at app-init.

### Verify

- [ ] 3.0 investigation log committed
- [ ] Run 3 scans back-to-back (respecting the concurrency guard,
      i.e. each after previous completes)
- [ ] Welcome "SCANS RUN" increments by 3
- [ ] Diagnostics "Scan history DB records" increments by 3
- [ ] `SELECT COUNT(*) FROM scans` confirms 3 new rows
- [ ] No orphan rows
- [ ] If Phase 3.0 revealed guard-after-insert:
      `[DIAG:GUARD_ORDER]` runtime assertion fires on startup

### Commit

```
fix(phase3): scan counter increments per completed scan

Root cause: [one sentence based on 3.0 finding]

- [specific persistence fix]
- [if applicable: guard/insert reorder + orphan purge]
- Welcome + Diagnostics re-query on tab activation
- [DIAG:GUARD_ORDER] runtime assertion [if applicable]

Fixes: scan count stuck at 49
Refs: docs/bug-investigations/phase3_guard_order.log
```

---

# PHASE 4 — File-Type Counts on Results Filter Tabs

## Tasks

1. Add or reuse `classify_file(path) -> str` helper. Buckets:
   pictures, music, videos, documents, archives, other.

2. After groups load on Results page, compute `type_counts` dict.

3. Render tabs with counts:
   ```
   All (4,803) · Pictures (3,412) · Music (0) · 
   Videos (2) · Documents (8) · Archives (0) · Other (1,381)
   ```

4. Zero-count tabs: muted text color, disabled click handler.

5. Recompute counts after any filter/delete operation that
   mutates the result set.

## Verify

- [ ] Tabs show counts matching total groups
- [ ] Zero-count tabs visually muted and not clickable
- [ ] Counts update after a delete operation

## Commit

```
feat(phase4): file-type counts on Results filter tabs

- classify_file() buckets by extension
- Live counts on each tab, zero-count tabs disabled
- Counts refresh on filter/delete mutations
```

---

# PHASE 5 — Virtualize Results (with mandatory Phase 5.0)

## Phase 5.0 — Benchmark (binding, pre-declared verdict rule)

Before any Phase 5 fix is written:

### Tasks

1. With current post-Phase-2 code, run a scan that populates
   Results with ≥4,000 rows (production 5-root overlap set).

2. Perform three measured actions, capturing timings:
   - **A:** Scrollbar-drag to bottom; measure time to first
     render complete
   - **B:** Arrow-key from row 0 to row N-1; measure per-event
     response time
   - **C:** Sort by any column; measure completion time

3. Pre-declared verdict rule:

   ```
   IF   drag-A < 1000ms
   AND  arrow-B < 200ms per event
   AND  sort-C < 2000ms on ≥4,000 rows
   THEN Phase 5 DEFERRED to v1.2
        Document at docs/backlog/phase5-results-virtualization.md
        with raw numbers
   ELSE Phase 5 proceeds as written
        Measured numbers become the "before" baseline
   ```

4. Measurement log committed as
   `docs/bug-investigations/phase5_pre_measure.md`:
   - Raw numbers per measurement
   - Hardware: CPU, RAM, disk type
   - Dataset: discovered count, emitted count, group count
   - Code SHA at measurement time

## Phase 5 — Main (conditional on 5.0 verdict)

### Tasks (only if 5.0 verdict says "proceed")

1. Evaluate `tksheet` as the replacement. Criteria:
   virtualization, themeable via `design_tokens.py`, column sort,
   multi-select, row selection events, keyboard nav.

2. If `tksheet` fits, integrate behind existing Results page
   interface so callers are unaffected.

3. If not, implement canvas-based virtualization: fixed widget
   pool (~40 rows), recycle on scroll, render visible range only.

4. Preserve: column sorting, multi-select (Ctrl+click,
   Shift+click), double-click-to-Review, keyboard navigation.

5. Post-fix targets (to beat 5.0 baseline):
   drag < 200ms, arrow < 50ms/event, sort < 1s.

### Verify

- [ ] 5.0 measurement log committed
- [ ] If DEFERRED: backlog doc landed with raw numbers
- [ ] If PROCEEDING: all five original Phase 5 bullets met
      (smooth scroll, row 4,800 reachable in <1s, sort <2s,
      double-click preserved, multi-select preserved)

## Commit (if proceeding)

```
perf(phase5): virtualize Results table for large result sets

Pre-fix baseline: docs/bug-investigations/phase5_pre_measure.md
- drag-A: [Nms]
- arrow-B: [Nms/event]  
- sort-C: [Nms]

Post-fix:
- [tksheet integration OR canvas virtualization]
- drag: [Nms] · arrow: [Nms/event] · sort: [Nms]
- Preserves sort, multi-select, keyboard nav, double-click

Fixes: scroll deadlock on 4000+ row scans
```

---

# PHASE 6 — Review Empty State + Grid View

## Tasks

1. **Review empty state.** When Review is opened from top nav
   without a group selected, render:
   ```
   [icon]
   No group selected
   Pick a group on the Results page to review its duplicates.
   [Go to Results]
   ```

2. **Results grid view.** Add List/Grid toggle in Results
   toolbar. Grid view requirements:
   - Thumbnails at 140px square
   - Duplicate-count badge overlay (top-right)
   - File-type icon fallback for non-images
   - Click selects, double-click opens Review
   - Virtualized — never render all thumbnails at once
   - Async thumbnail loading with placeholder

3. Persist view mode across sessions (user preferences).

## Verify

- [ ] Review via top nav without selection → empty state renders
- [ ] Results view toggle switches list/grid
- [ ] Grid with ≥4,000 items scrolls smoothly (virtualized)
- [ ] View mode persists after app restart

## Commit

```
feat(phase6): Review empty state + Results grid view

- Review page shows empty state with CTA when no group selected
- Results List/Grid toggle, grid uses virtualized thumbnail rendering
- View mode persists across sessions
```

---

# PHASE 7 — Engine Status Diagnostics Overhaul

## Tasks

1. **Capture actual exception details.** Catch
   `ModuleNotFoundError` specifically, store `e.name`. Catch
   generic `ImportError` separately.

2. **Engine state machine.** Each engine has exactly one of:
   - `available` — loaded and working
   - `missing_deps` — optional packages not installed
   - `import_failed` — packages present but import crashed
   - `disabled` — user turned off in settings
   - `planned` — not yet implemented in this build

3. **`ENGINE_DEPS` registry.** Hardcode per-engine metadata:
   ```python
   ENGINE_DEPS = {
       "audio_fingerprint": {
           "packages": ["pyacoustid", "chromaprint"],
           "install_hint": "pip install pyacoustid chromaprint",
           "docs_url": "...",
       },
       "documents_content": {
           "packages": ["python-docx", "pypdf", "openpyxl"],
           "install_hint": "pip install python-docx pypdf openpyxl",
           "docs_url": "...",
       },
   }
   ```

4. **Actionable status rows.** Example:
   ```
   ● Audio (sound match)    Missing: chromaprint
                            [pip install pyacoustid chromaprint] [Copy]
                            [Retry after install]
   ```
   Retry re-imports and refreshes status without app restart.

5. **Plain-language UI names** (keep technical names in logs):
   ```
   ● Files                  available
   ● Images (visual match)  available
   ● Audio (sound match)    missing deps
   ● Video (scene match)    available
   ● Documents (text match) missing deps
   ```

6. **Pre-scan warning on Scan page.** If relevant engines offline:
   ```
   ⚠ Audio engine unavailable. MP3/FLAC matched by byte identity only.
   [Install now] [Continue anyway] [Cancel]
   ```

7. **Persist engine load errors.** New table
   `engine_load_errors`: timestamp, engine_name, exception_type,
   exception_message, traceback. Last 10 surfaced in Diagnostics.

## Verify

- [ ] Diagnostics shows specific missing package names
- [ ] Install command copy-to-clipboard works
- [ ] Retry re-imports without app restart
- [ ] Scan page pre-scan warning when relevant engines offline
- [ ] `engine_load_errors` table populated
- [ ] UI uses plain-language names; logs retain technical names

## Commit

```
feat(phase7): actionable engine status with dep detection

- Capture ModuleNotFoundError.name, distinguish from ImportError
- State machine: available / missing_deps / import_failed / disabled / planned
- ENGINE_DEPS registry with install hints
- Diagnostics: specific missing package, copy install command, retry
- Plain-language engine names in UI
- Scan page pre-scan warning
- engine_load_errors table

Fixes: opaque ModuleNotFoundError in Engine Status
```

---

# PHASE 8 — Merge to Main (Expanded Cleanup)

## Preconditions (ALL must be true before Phase 8 starts)

- All Phases 1–7 verify checklists pass
- All Phase 1 and Phase 2 closure steps complete
- All advisor waivers either accepted with evidence or resolved

## Cleanup Tasks

### 8.1 — DIAG:* Removal

Single commit. Commit body MUST include grep proof of per-tag
removal. Example:

```
rg '\[DIAG:(DISCOVERY|REDUCE|PAIR|SUMMARY|EMIT|TURBO:)' --stats

BEFORE:
  DIAG:DISCOVERY: N occurrences
  DIAG:REDUCE:    N occurrences
  ...

AFTER:
  DIAG:DISCOVERY: 0
  DIAG:REDUCE:    0
  ...

(Retained: DIAG:GUARD = M occurrences (demoted to DEBUG))
```

**Remove:**
- `[DIAG:DISCOVERY]`
- `[DIAG:REDUCE]`
- `[DIAG:PAIR]`
- `[DIAG:SUMMARY]`
- `[DIAG:EMIT]` (Phase 2b — not load-bearing per falsification)
- `[DIAG:TURBO:*]`

**Retain:**
- `[ROOT_DEDUP]` at **INFO** — user-facing useful info from
  Phase 2a. Current location: [verify before removal].
- `[DIAG:GUARD]` demoted to **DEBUG** — this IS the "keep
  regression guard from Phase 2" item from the original plan.
  Current location: [verify before removal].

### 8.2 — Harness Cleanup

- Delete `diagnostics/_phase2_cache_experiment.py` outright
  (git has history; `scripts/dev/` retention rejected).
- Delete `scripts/dev/phase1_scan_runner.py` IF no longer needed
  (keep if there's an argument for re-runnability).
- Delete `diagnostics/*.log` files (gitignored; remove on-disk
  clutter).

### 8.3 — Documentation Relocation

- Move `SCAN_PATHS.md` → `docs/architecture/scan_paths.md`
- Confirm `docs/bug-investigations/` contains:
  - `bug1-canonical-path-dedup.md`
  - `phase3_guard_order.log`
  - `phase5_pre_measure.md`
- Confirm `docs/backlog/phase5-results-virtualization.md` exists
  IFF Phase 5 was deferred.

### 8.4 — Code Comments Above Defensive Structures

Each comment MUST include: bug SHA(s), test/log line that would
regress, phase + date context.

- **`main_window_controllers.py`** — Bug X concurrency guard:
  > Guard preventing concurrent scan launches (fix: a40055c,
  > 2026-04-15, Phase 1 Bug X investigation).
  > Regression indicator: multiple "Starting scan in files mode"
  > lines within <1s in logs.
  > If you add another scan entry point that bypasses start_search(),
  > replicate this guard at the new entry point OR move the guard
  > down into the scanner/orchestrator layer.

- **`dedupe_roots()` in `cerebro/core/root_dedup.py`** — Bug 1
  root-overlap fix:
  > Collapses descendant roots (fix: b0e94d6, Phase 2a,
  > 2026-04-20, post-v1 audit).
  > Regression indicator: missing [ROOT_DEDUP] log line, OR
  > non-monotonic Phase 1 → Phase 2 → Phase 3 counts.
  > Investigation: docs/bug-investigations/bug1-canonical-path-dedup.md

- **`_assert_no_self_duplicates` in
  `cerebro/core/group_invariants.py`** — defense-in-depth guard:
  > Catches any self-duplicate regression not caught by dedupe_roots
  > (fix: 434fa7f, Phase 2c, 2026-04-20; ported to all paths in
  > [fix(phase2d) SHA]).
  > Regression indicator: [DIAG:GUARD] regressions > 0 at any scan.
  > Strict mode via CEREBRO_STRICT=1 raises instead of logging.

### 8.5 — Final Verification (ALL must pass before tag)

Run full regression scan against production 5-root overlap set.
Capture verification log to
`docs/releases/v1.1.0/final_verification.log` (tracked path; no
`git add -f`).

- [ ] No Phase 1→2 count inversion
- [ ] Emitted count matches parents-only baseline (±1% tolerance)
- [ ] `[ROOT_DEDUP]` log present in verification run
- [ ] `[DIAG:GUARD]` regressions=0 on all exercisable paths
- [ ] `_assert_no_self_duplicates` did not fire, OR if it did,
      benign case is documented
- [ ] DB invariant SQL returns zero rows:
      ```sql
      SELECT canonical_path, COUNT(*) FROM files 
      GROUP BY canonical_path HAVING COUNT(*) > 1;
      ```
- [ ] `CEREBRO_STRICT=1` causes synthetic self-dup to raise
      (test run)
- [ ] `CEREBRO_STRICT` unset: synthetic self-dup logs and continues
      (test run)
- [ ] All Phase 3–7 verify checklists confirmed passing

### 8.6 — Tag

`v1.1.0-post-audit`

Tag message:
```
v1.1.0-post-audit — post-v1 audit release

Bug fixes:
- Bug 1: scan root overlap causing Phase 1→2 count inversion
  (Phase 2a: b0e94d6)
- Bug 1 defense: singleton filter at emit (Phase 2b: 835bc68)
- Bug 1 defense: canonical-path regression guard
  (Phase 2c: 434fa7f; ported Phase 2d: [SHA])
- CEREBRO_STRICT flag for strict-mode guard behavior
  (Phase 2e: [SHA])
- Scan counter increments per completed scan (Phase 3: [SHA])

UX improvements:
- File-type counts on Results filter tabs (Phase 4: [SHA])
- [Results virtualization OR deferred-to-v1.2] (Phase 5: [SHA or backlog ref])
- Review empty state + Results grid view (Phase 6: [SHA])
- Actionable engine status with dep detection (Phase 7: [SHA])

Documentation:
- docs/plans/post-v1-audit-plan.md — working contract
- docs/bug-investigations/bug1-canonical-path-dedup.md
- docs/architecture/scan_paths.md
- docs/releases/v1.1.0/final_verification.log
```

### 8.7 — Squash-Merge to Main

Only after tag is pushed and advisor sign-off received.

---

# Appendix A — Commit Ledger

(Updated on every commit. Claude Code appends; advisor audits
against `git log`.)

| SHA      | Date       | Phase | Summary                                    |
|----------|------------|-------|--------------------------------------------|
| 65ce5d1  | 2026-04-?? | 1     | [verify and fill]                          |
| a8bb998  | 2026-04-?? | 1     | [verify and fill]                          |
| b0e94d6  | 2026-04-?? | 2a    | dedupe_roots + [ROOT_DEDUP]                |
| 835bc68  | 2026-04-?? | 2b    | singleton filter + [DIAG:EMIT]             |
| 434fa7f  | 2026-04-?? | 2c    | _assert_no_self_duplicates + [DIAG:GUARD]  |
| (see git log) | 2026-04-22 | 1-closure | Phase 1 verify recorded in plan   |
| PENDING  | —          | 2d    | Port guard + filter to Paths B and D       |
| PENDING  | —          | 2e    | __debug__ posture → CEREBRO_STRICT         |
| PENDING  | —          | 2-doc | bug1-canonical-path-dedup.md               |
| ...      |            |       |                                            |

---

# Appendix B — Amendment Log of This Document

Every edit to this file requires a line here.

- **2026-04-20** — Initial version, merged advisor review
  decisions (§0–§H). Supersedes the original plan and all chat-
  history spec. Working contract for all remaining work.
- **2026-04-22** — Phase 1 closure verified in-tree (no tracked
  `diagnostics/` paths; runner at `scripts/dev/phase1_scan_runner.py`;
  waivers recorded in `SCAN_PATHS.md`). Document-only reconciliation
  commit; no code delta required beyond this plan update.

---

# Appendix C — Stop Conditions (Consolidated)

Any of these halt work immediately and require advisor consultation:

1. Step 2 SQL returns non-zero rows with unexpected data
2. Phase 3.0 log shows guard-after-insert + orphans too numerous
   to safely purge
3. Phase 5.0 benchmark numbers are inconsistent or unreproducible
4. Build mode investigation reveals `-O` in use (unexpected)
5. Any Phase 3–7 verify checklist fails
6. Phase 8 final verification fails any bar
7. Any commit lands without readback signal
   "canonical chokepoint understood"

---

*End of working contract.*
