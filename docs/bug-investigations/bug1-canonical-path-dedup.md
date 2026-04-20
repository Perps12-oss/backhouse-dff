# Bug 1 — Canonical-Path Dedup: Investigation Report

**Status:** CLOSED  
**Branch:** fix/post-v1-audit  
**Primary fix SHA:** b0e94d6  
**Defense SHAs:** 835bc68, 434fa7f, 0f72da7  
**Date closed:** 2026-04-20  

---

## 1. Datasets

### jhjl (test tree)

- **Path:** `C:\Users\S8633\Downloads\jhjl`
- **Files:** 1,072
- **Size groups:** 23
- **Final duplicate pairs:** 1
- **Emitted:** 2 files
- **Used for:** Phase 1 instrumentation verification; Phase 2 quick-iteration
  hypothesis testing. Single root — root-overlap cannot manifest here.

### Production (5-root overlap set)

- **User-specified roots (5):**
  - `C:\Users\S8633\OneDrive\Desktop`
  - `C:\Users\S8633\Downloads`
  - `C:\Users\S8633\OneDrive\Desktop\DCIM\PHOTO` ← descendant of root 1
  - `C:\Users\S8633\Downloads\jhjl` ← descendant of root 2
  - `C:\Users\S8633\.dedup\trash`
- **Pre-fix discovered:** 16,803 files (5 roots, overlap counted twice)
- **Effective roots post-fix:** 3 (2 descendants collapsed by `dedupe_roots()`)
- **Post-fix discovered:** ~15,338–15,341 files
- **Emitted post-fix:** 4,560 files in 1,232 groups
- **Delta from fix:** ~1,462–1,465 files (the double-enumerated `DCIM\PHOTO`
  and `jhjl` trees)

---

## 2. Timeline of Hypotheses

### H4 — File-level canonical collision (original plan's assumption)

**Date:** 2026-04-20 (initial assumption before diagnostic runs)

**Hypothesis:** Different path strings on Windows (case variants, 8.3 aliases,
junction/symlink traversal) can resolve to the same physical file and hash
identically, producing false-duplicate groups.

**Evidence that prompted investigation:**
Wide production scan with 5 roots emitted 7,476 files across 2,677 groups — far
more than expected from a corpus of ~15K unique files.

**Status:** REJECTED — see §4 Falsifications.

---

### H2 — Cache serving pre-fix stale entries

**Date:** 2026-04-20 (during 4-run diagnostic matrix)

**Hypothesis:** The `HashCache` SQLite store had cached hashes from an
earlier pre-fix scan state. Hot-cache runs re-served those stale entries,
inflating counts even after a partial fix.

**Evidence used to test:**
Ran identical corpus with `use_cache=True` (hot) and `use_cache=False` (cold):

```
phase2_parents_only_hot.log  04:34:41  roots=3  use_cache=True   emitted=4560  groups=1232
phase2_parents_only_cold.log 04:35:03  roots=3  use_cache=False  emitted=4560  groups=1232
phase2a_5roots_hot.log       04:44:13  roots=5  use_cache=True   emitted=4560  groups=1232
phase2a_5roots_cold.log      04:46:39  roots=5  use_cache=False  emitted=4560  groups=1232
```

Hot and cold produce identical emitted counts. Cache is not a factor.
`CACHE_SCHEMA_VERSION` was not bumped.

**Status:** REJECTED.

---

### H3 — Zero-filtering at emit (singleton groups leaking)

**Date:** 2026-04-20 (during Phase 2b instrumentation)

**Hypothesis:** Size groups containing exactly one file after hash reduction
were not being filtered before emit, leaking singleton groups into results and
inflating counts.

**Evidence:**

```
phase2b_jhjl.log      04:51:03  [DIAG:EMIT] total_groups=1 dupe_groups=1 singleton_groups=0 files_in_dupe_groups=2
phase2b_5roots_hot.log 04:50:32  [DIAG:EMIT] total_groups=1232 dupe_groups=1232 singleton_groups=0 files_in_dupe_groups=4560
phase2b_parents_hot.log 04:51:22  [DIAG:EMIT] total_groups=1232 dupe_groups=1232 singleton_groups=0 files_in_dupe_groups=4560
```

`singleton_groups=0` across all three run variants. No singleton leakage.

**Status:** REJECTED.

---

### H1 — Root-overlap double-enumeration (winning hypothesis)

**Date:** 2026-04-20 (confirmed by `[DIAG:PAIR]` evidence in pre-fix run)

**Hypothesis:** When a user specifies both a parent root and a descendant root
(e.g., `Desktop` AND `Desktop\DCIM\PHOTO`), the scanner walks `DCIM\PHOTO`
twice — once as part of the `Desktop` traversal, and again as an explicit root.
Files under the descendant are discovered twice, hash identically (same file),
and are reported as duplicates of themselves.

**Evidence from pre-fix run (`phase2_prod_hot.log`, 2026-04-20 04:32:43):**

Pre-fix summary:
```
[DIAG:DISCOVERY] roots=5 discovered=16803 skip_hidden=True min_size=1024
[DIAG:SUMMARY] scan=turbo discovered=16803 size_candidates=7702 final_groups=2677 emitted=7476 elapsed=12.02s
```

DIAG:PAIR entries (1,342 total — capped at 8 per Phase 1 run but uncapped here):
```
[DIAG:PAIR] canonical-path-collision size=41472 path_a=C:\Users\S8633\OneDrive\Desktop\DCIM\PHOTO\PHO00000.JPG path_b=C:\Users\S8633\OneDrive\Desktop\DCIM\PHOTO\PHO00000.JPG
[DIAG:PAIR] canonical-path-collision size=41472 path_a=C:\Users\S8633\OneDrive\Desktop\DCIM\PHOTO\PHO00065.JPG path_b=C:\Users\S8633\OneDrive\Desktop\DCIM\PHOTO\PHO00065.JPG
[DIAG:PAIR] canonical-path-collision size=41472 path_a=C:\Users\S8633\OneDrive\Desktop\DCIM\PHOTO\PHO00069.JPG path_b=C:\Users\S8633\OneDrive\Desktop\DCIM\PHOTO\PHO00069.JPG
[DIAG:PAIR] canonical-path-collision size=24576 path_a=C:\Users\S8633\OneDrive\Desktop\DCIM\PHOTO\PHO00001.JPG path_b=C:\Users\S8633\OneDrive\Desktop\DCIM\PHOTO\PHO00001.JPG
```

Critically: `path_a == path_b` in every entry. This is not two different paths
resolving to the same inode — it is the **exact same path string** appearing in
two different size groups because the file was enumerated twice during discovery.

Post-fix confirmation (`phase2a_5roots_hot.log`, 2026-04-20 04:44:13):
```
[ROOT_DEDUP] collapsing C:\Users\S8633\Downloads\jhjl into parent root (already covered)
[ROOT_DEDUP] collapsing C:\Users\S8633\OneDrive\Desktop\DCIM\PHOTO into parent root (already covered)
[ROOT_DEDUP] 5 roots → 3 after dedup
[ROOT_DEDUP] user_roots=5 deduped_roots=3 collapsed=['C:\\Users\\S8633\\OneDrive\\Desktop\\DCIM\\PHOTO', 'C:\\Users\\S8633\\Downloads\\jhjl']
[DIAG:DISCOVERY] roots=5 discovered=15338 skip_hidden=True min_size=1024
[DIAG:SUMMARY] scan=turbo discovered=15338 size_candidates=5224 final_groups=1232 emitted=4560 elapsed=6.40s
```

Discovered count drops from 16,803 → 15,338 (delta: 1,465 — the
double-enumerated files). Emitted drops from 7,476 → 4,560. Matches
parents-only baseline exactly.

**Status:** ACCEPTED. Primary fix: `dedupe_roots()` in `cerebro/core/root_dedup.py` (b0e94d6).

---

## 3. Winning Hypothesis

**H1 — Root-overlap double-enumeration.**

When the user specifies both a parent root and a descendant root, the
`TurboScanner` (and all active scan paths) walk the descendant subtree twice.
Files in the descendant hash identically on both passes and are reported as
duplicates of themselves.

**Primary fix:** `dedupe_roots()` in `cerebro/core/root_dedup.py`, called at
the scan dispatcher before any root is walked. Collapses any root that is a
path-prefix descendant of another root in the same set.

**Fix SHA:** b0e94d6

**Regression indicators:**
- `[ROOT_DEDUP]` log line absent from a scan with multiple roots
- Non-monotonic Phase 1 → Phase 2 discovered count relationship (Phase 2
  should be ≤ Phase 1; if Phase 2 > Phase 1, overlap has been re-introduced)
- `[DIAG:GUARD] regressions > 0` at any scan (self-duplicate reached emit)

---

## 4. Falsifications

### H3 falsified — no singleton groups at emit

All three run variants after Phase 2b instrumentation show `singleton_groups=0`:

```
phase2b_jhjl.log       [DIAG:EMIT] total_groups=1 dupe_groups=1 singleton_groups=0 files_in_dupe_groups=2
phase2b_5roots_hot.log [DIAG:EMIT] total_groups=1232 dupe_groups=1232 singleton_groups=0 files_in_dupe_groups=4560
phase2b_parents_hot.log [DIAG:EMIT] total_groups=1232 dupe_groups=1232 singleton_groups=0 files_in_dupe_groups=4560
```

Candidates always equal emitted. No singleton leakage was occurring. The
singleton filter landed in 835bc68 is defense-in-depth, not a causal fix.

### H2 falsified — cache parity across hot/cold runs

4-run matrix (all post Phase 2a fix, 2026-04-20):

| Run | Roots | Cache | Discovered | Emitted | Groups |
|-----|-------|-------|-----------|---------|--------|
| phase2_parents_only_hot  | 3 (no overlap) | hot  | 15,334 | 4,560 | 1,232 |
| phase2_parents_only_cold | 3 (no overlap) | cold | 15,335 | 4,560 | 1,232 |
| phase2a_5roots_hot       | 5 → 3 (deduped) | hot  | 15,338 | 4,560 | 1,232 |
| phase2a_5roots_cold      | 5 → 3 (deduped) | cold | 15,339 | 4,560 | 1,232 |

Hot and cold produce identical emitted counts in all four variants. The cache
is not serving stale data. `CACHE_SCHEMA_VERSION` was not bumped because
cache invalidation was not required — the fix operates before any file reaches
the hash cache.

### H4 falsified — not file-level canonical collision

The `[DIAG:PAIR]` entries in the pre-fix run show `path_a == path_b` (same
path string, not two different paths to the same inode). H4 assumed paths like
`C:\FOLDER\file.txt` and `c:\folder\file.txt` (case variant) or
`C:\SHORT~1\file.txt` (8.3 alias) hashing to the same result. The actual
pattern is simpler and more systematic: the file at `DCIM\PHOTO\PHO00000.JPG`
appears in the discovery list twice with the exact same path, because two roots
(`Desktop` and `Desktop\DCIM\PHOTO`) both traverse it.

The `normcase(realpath)` canonicalization originally planned for
`engine/canonical.py` is retained in `_assert_no_self_duplicates` as
defense-in-depth against genuine canonical-collision variants (hardlinks,
junctions) that `dedupe_roots()` does not cover — but it is not the primary fix.

---

## 5. Defense-in-Depth

### Singleton filter — SHA 835bc68

Adds an explicit `if len(group) < 2: continue` filter at the emit loop in
Paths A/C (`turbo_scanner.py`). Ensures no single-file group reaches
`ScanResultStore`, even if an upstream reduction step fails to filter.

Ported to Paths B (`fast_pipeline.py`) and D (`file_dedup_engine.py`) at
SHA 0f72da7.

### Canonical regression guard — SHA 434fa7f, ported 0f72da7

`_assert_no_self_duplicates()` in `cerebro/core/group_invariants.py` (extracted
from inline definition in `turbo_scanner.py`). Runs on every emit-ready group
across all four active scan paths. Canonicalizes each path via
`normcase(realpath)` and rejects any second entry that resolves to the same
canonical form.

- **Paths A/C** (turbo_scanner.py): 434fa7f
- **Paths B/D** (fast_pipeline.py, file_dedup_engine.py): 0f72da7

Strict mode: `CEREBRO_STRICT=1` → raises `AssertionError` (for CI/dev use).  
Default (unset): logs `[GUARD]` warning and drops the offending entry.

---

## 6. Waivers

### Waiver 1 — "Candidates > Emitted"

**Original verify bullet:** After fix, `DIAG:SUMMARY` should show
`candidates > emitted` (some candidates filtered out).

**Actual:** Candidates == Emitted in all post-fix runs.

**ACCEPTED.** Evidence from Phase 2b runs showing `singleton_groups=0`:

```
phase2b_jhjl.log       [DIAG:EMIT] total_groups=1 dupe_groups=1 singleton_groups=0 files_in_dupe_groups=2
phase2b_5roots_hot.log [DIAG:EMIT] total_groups=1232 dupe_groups=1232 singleton_groups=0 files_in_dupe_groups=4560
```

All groups reaching emit are genuine duplicate groups (2+ files). No singletons
exist to be filtered. The pre-fix inflation came from double-enumeration (groups
with 2 copies of the same file), not from singleton leakage. The fix removes
the double-enumerated entries at the root level before grouping, so the
remaining candidates are all legitimate.

Dataset context: jhjl (1,072 files, 2026-04-20 04:51:03, SHA 835bc68);
5-roots hot (15,341 files, 2026-04-20 04:50:32, SHA 835bc68).

---

### Waiver 2 — "Cache invalidated on first post-fix run"

**Original verify bullet:** First post-fix run should show cache misses,
proving stale pre-fix cache entries were not served.

**ACCEPTED.** Evidence: the 4-run matrix above shows identical emitted counts
(4,560) across all hot/cold combinations. Hot runs (cache_hits=9,784,
cache_hit_pct=100%) and cold runs (cache_hits=0) produce the same results.

Reasoning: `dedupe_roots()` fires before any file reaches the hash cache.
Double-enumerated paths are removed from the root list before walk, so they
never enter the cache lookup path. Cache invalidation was not required and
`CACHE_SCHEMA_VERSION` was not bumped.

---

### Waiver 3 — "DB canonical_path query returns zero rows"

**DEFERRED — not yet waived.**

The original verify query:
```sql
SELECT canonical_path, COUNT(*) FROM files GROUP BY canonical_path HAVING COUNT(*) > 1 LIMIT 20;
```

Cannot be run as specified: no `files` table with a `canonical_path` column
exists in any live Cerebro database. The original plan assumed a
`canonical.py`-based schema that was superseded by the `root_dedup.py`
approach (Waiver 4). The equivalent query runs against `scan_results.db ::
group_files.path`, scoped to the latest `scan_id`.

The two scans in `scan_results.db` at time of writing are dated 2026-03-24 and
2026-03-07 — both pre-fix. The adapted invariant query against the most recent
pre-fix scan returned non-zero rows (expected: pre-fix data, Bug 1 pattern).

**This waiver will be RESOLVED (not waived) after the first post-fix scan run:**
the adapted query should return zero rows against post-fix data. Raw SQL output
will be appended here at that time.

---

### Waiver 4 — "canonical.py as primary mechanism"

**Original Phase 2 spec:** Primary fix in `engine/canonical.py` via
`_canonicalize_and_dedupe(files)` applying `normcase(realpath) + NFC + strip`
at a shared chokepoint.

**Actual:** Primary fix in `cerebro/core/root_dedup.py` via `dedupe_roots()`.

**ACCEPTED.** The 4-run diagnostic matrix falsified the file-level canonical
collision hypothesis (H4). The winning hypothesis (H1) required a root-level
fix, not a file-level one. `normcase(realpath)` canonicalization is retained in
`_assert_no_self_duplicates` as defense-in-depth (SHA 434fa7f, ported 0f72da7)
but is not the primary fix.

Evidence: `[DIAG:PAIR]` entries show `path_a == path_b` (root-overlap pattern),
not two different paths to the same file. See §4 Falsifications.

---

### Waiver 5 — "Shared chokepoint covers all paths"

**Original verify bullet:** The fix must apply to every scan entry point
identified in Phase 1.

**RESOLVED via port — not waived.** 

Phase 2a/b/c landed the fix and defense on Paths A/C only. Phase 2d (SHA
0f72da7) ported `[DIAG:EMIT]` + singleton filter + `_assert_no_self_duplicates`
to Paths B (`fast_pipeline.py`) and D (`file_dedup_engine.py`).

`dedupe_roots()` was already present on Paths A, C, and D at b0e94d6.
Path B (`fast_pipeline.py`) dispatches single-root jobs only (no overlap
possible) — `dedupe_roots()` is not required there.

All active scan paths now have full defense-in-depth coverage.

---

## 7. Forward Guard — Maintenance Runbook

### Which log lines indicate a Bug 1 regression?

1. **`[ROOT_DEDUP]` absent** from a multi-root scan log — means `dedupe_roots()`
   did not run. Check if the scan dispatcher still calls `dedupe_roots()` before
   walking.

2. **Non-monotonic Phase 1 → Phase 2 count:** if `discovered` in a Phase 2
   run is significantly higher than in a parents-only baseline for the same
   corpus, double-enumeration has been re-introduced.

3. **`[DIAG:GUARD] regressions > 0`** — a self-duplicate reached the emit loop.
   Either `dedupe_roots()` was bypassed, or a new overlap mechanism (hardlink,
   junction, cross-drive alias) is active that `dedupe_roots()` does not cover.

4. **`[DIAG:PAIR] canonical-path-collision` with `path_a == path_b`** — same
   path discovered twice. Root-overlap pattern.

### Which DB query surfaces a regression?

Run against `scan_results.db` after any scan:

```sql
SELECT path, COUNT(*) AS cnt
FROM group_files
WHERE scan_id = (SELECT scan_id FROM scans ORDER BY created_at DESC LIMIT 1)
GROUP BY path
HAVING COUNT(*) > 1
LIMIT 20;
```

Zero rows = invariant holds. Non-zero rows = a file path appears in multiple
duplicate groups within the same scan — Bug 1 pattern.

### Under what filesystem conditions might a NEW Bug 1 variant appear?

`dedupe_roots()` detects overlap via path-prefix matching
(`os.path.normcase(os.path.realpath(root))`). The following scenarios could
bypass it:

1. **NTFS hardlinks from non-overlapping roots:** two roots that are not
   ancestor/descendant of each other, but contain hardlinks pointing to the
   same inode. `dedupe_roots()` would not collapse them (no path-prefix
   relationship), but `_assert_no_self_duplicates` would catch the resulting
   group at emit via `normcase(realpath)` comparison.

2. **Directory junctions / symlinks:** a junction inside root A that points
   into root B. If root B is also specified, files under the junction are
   walked from both A (via junction) and B (directly). `dedupe_roots()` may
   not detect this if the junction resolves to a path outside A's prefix.
   `_assert_no_self_duplicates` catches this case too.

3. **New scan entry point bypassing `dedupe_roots()`:** any future code that
   invokes `TurboScanner.scan()` or `FileDedupEngine._run_scan()` without
   passing roots through `dedupe_roots()` first. The guard catches the
   symptom but the root cause would need a separate fix. See the comment block
   at `dedupe_roots()` in `cerebro/core/root_dedup.py` (to be added in Phase
   8.4) for the regression indicator.
