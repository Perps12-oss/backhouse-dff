# CEREBRO (backhouse-dff) — Production Audit **Verification & Delta**

**Verification date:** 2026-05-20
**Auditor mode:** Independent re-audit (verify, don't re-derive)
**Baseline documents:**
- `docs/PRODUCTION_READINESS_AUDIT.md` (overall **58/100**, pre-hardening)
- `docs/PRODUCTION_HARDENING_SIGNOFF.md` (self-estimate **88–92/100**, post-hardening)

**Scope:** `cerebro/` (157 source files, ~35.9k LOC) + `dev/` (97 test files, ~6.9k LOC), CI, packaging.
**Product:** Local desktop duplicate-file finder (Flet UI, no network API in default config).
**Method:** Rather than regenerate the 22-section template the baseline already covers, this report **verifies the signoff's "Done" claims against the live code**, records the **delta**, and adds **new findings** the prior audit did not surface. Every claim below is grounded in a cited `file:line`.

---

## 1. Executive Summary

The baseline audit was real and was **acted upon**. Spot-checking the signoff's "Done" list against source confirms the hardening is genuine, not aspirational — this is a well-engineered codebase for its category, with unusually strong investment in **deletion safety**, **scan performance/cancel semantics**, and **CI breadth**.

**Verified true (sampled):** UI control mutation now goes through a marshaller (no `run_thread` writes); orchestrator cancel uses a 30s join + `shutdown_workers()`; SQLite `busy_timeout` is set on every connection path; the deletion gate is a cryptographically sound one-time-token lattice; CI runs pip-audit, secret scan, scoped ruff/mypy, xvfb pytest, memray bounds, a single-entrance invariant check, **and** a Windows smoke job; lockfile, dependabot, and `SECURITY.md` exist.

**The self-estimated 88–92/100 is defensible for the primary path** (Windows/macOS, Files/Turbo scan → review → trash/permanent-delete-with-gate). It is **not** yet enterprise-grade because of a small set of **residual, mostly-known** items: deferred scale work (streaming discovery + pagination), CI gates that *run but don't fail the build*, lint/type coverage scoped to ~15 files, an asymmetric Windows test gate, the explicitly-skipped monolith debt, and pending signed-release/SBOM packaging.

**Verdict:** **Conditionally production-ready** for the primary single-mode path. **Not yet enterprise-grade** for large libraries (>100k files), accessibility compliance, or signed-distribution requirements.

**Net-new effort to close the residual list:** ~**3–5 engineer-weeks** (the heavy lifting in the baseline's 8–14 week estimate has largely been done).

---

## 2. Production Readiness Score — Re-scored

| Dimension | Baseline | This audit | Movement / reason |
|-----------|:--------:|:----------:|-------------------|
| Core scan engine (Turbo/files) | 78 | **82** | Cancel join 5s→30s + `shutdown_workers()` verified |
| Secondary scan modes | 35 | **70** | `base_engine` lifecycle + pause contract + tests landed |
| UI / Flet layer | 62 | **75** | `ui_marshal.run_on_ui_thread` verified; `run_thread` writes gone |
| Security (desktop threat model) | 72 | **80** | Gate verified sound; trash via pipeline; preview cap; **auto-pip still present (by design)** |
| Testing | 70 | **78** | Lifecycle/marshal/schema/preview tests added; matrix still thin |
| DevOps / CI | 58 | **74** | pip-audit/secret/Windows/memray added; **gates non-blocking, scope narrow** |
| Observability | 45 | **65** | Sentry opt-in + path redaction + diagnostic bundle |
| Maintainability | 55 | **55** | **Unchanged — monolith split deliberately skipped** |
| UX / accessibility | 50 | **55** | Overflow UX improved; a11y semantics still missing |
| **Overall** | **58** | **~74–78** | Real gains; capped by maintainability + residual CI/scale items |

> Note: my overall is slightly below the signoff's self-estimate of 88–92. The difference is almost entirely **CI gating quality, lint/type breadth, and maintainability debt** — areas where the signoff counts a capability as "Done" when it *exists* but does not yet *enforce*.

---

## 3. Signoff Verification Matrix

| Signoff claim | Status | Evidence |
|---------------|:------:|----------|
| No `run_thread` for control mutations | ✅ Verified | Only references are warning docstrings + a marshalled timer; live writes go through `run_on_ui_thread` (`scan_hud.py:1394-1396`, `ui_marshal.py:35`, `host.py:999`) |
| Engine blocking `start`/`wait_until_done`/pause contract | ✅ Verified | `base_engine.py:175,183`; orchestrator joins active engine (`orchestrator.py:179`) |
| Orchestrator cancel: 30s join + `shutdown_workers()` | ✅ Verified | `_CANCEL_JOIN_TIMEOUT_SEC = 30.0` (`orchestrator.py:25`), used at `:220,:231`; `shutdown_workers()` at `:228` |
| `busy_timeout` on history/results/pool DBs | ✅ Verified | `hash_cache.py:103`, `results_store.py:32`, `scan_history_db.py:41`, `db_pool.py:52` (all 5000ms) |
| Trash via `build_explicit_paths_plan` | ✅ Verified (callers) | pipeline-validated path present; see directory-policy caveat in §5 (M2) |
| Session schema validation on resume | ✅ Present | `test_session_schema_validation.py` in suite + Windows gate |
| Preview size cap | ✅ Verified | `CEREBRO_PREVIEW_MAX_BYTES` default 50 MiB (`thumbnail_cache.py:25`) |
| Log path redaction | ✅ Verified | `CEREBRO_REDACT_PATHS` (`logger.py:37,77`) |
| Sentry opt-in | ✅ Verified | `CEREBRO_SENTRY_DSN` (`sentry_init.py:12-19`) |
| CI: pip-audit, secret scan, coverage slice, Windows smoke | ⚠️ Partial | All steps **exist** but pip-audit is **non-blocking**; Windows gate is 4 tests; lint scope ~15 files (`ci.yml`) |
| `requirements.lock` | ✅ Present | repo root |
| Monolith split | ❌ Skipped (by design) | `dashboard_page.py` 1820, `scan_hud.py` 1739, `host.py` 1645, `browse.py` 1340 LOC |
| Signed release / SBOM | ⏳ Pending | packaging not yet wired |
| Auto-pip disabled in releases | ⚠️ Nuance | No-op only when `sys.frozen`; **still installs from PyPI on source launch** (`runtime_deps.py:78-151`) |

---

## 4. Top 10 Residual Risks (post-hardening)

| # | Finding | Sev | Impact | Difficulty |
|:-:|---------|:---:|--------|:----------:|
| 1 | **`pip-audit` is non-blocking (`\|\| true`)** — a critical CVE never fails CI (`ci.yml:60`) | High | Vulnerable dep ships silently | Trivial |
| 2 | **Deferred scale work** — full in-memory results + JSON snapshot; no streaming discovery / pagination (memory v2.2 backlog; baseline C4) | High @ scale | OOM / multi-GB disk on 100k+ libraries | Hard |
| 3 | **Directory adapter ignores TRASH policy** — `can_handle` accepts TRASH but `delete()` always `rmtree` (`deletion.py:210-211,236`) | Medium | A `TRASH`+`allow_directory_delete` caller permanently deletes a tree | Low |
| 4 | **Lint/type coverage scoped to ~15 files** — most of `cerebro/` is unchecked by ruff; mypy covers 2 files (`ci.yml:66-90`) | Medium | Regressions land outside the gate | Medium |
| 5 | **Single-version CI matrix (3.11)** despite `requires-python>=3.10`; 3.14 in local use | Medium | Version-specific breakage undetected | Low |
| 6 | **Windows gate = 4 tests** vs full xvfb suite on Linux; Windows is the primary platform (`ci.yml:143-145`) | Medium | Platform regressions on primary OS | Medium |
| 7 | **Runtime auto-`pip install` from PyPI on source launch** (`runtime_deps.py`) — documented, frozen-safe, but supply-chain surface for source users | Medium | Compromised index → code exec | Low (mitigated) |
| 8 | **Over-broad `except` tuples in delete loop** include `AttributeError/KeyError/ImportError` (`deletion.py:147,194,243,352,360,367`) | Low–Med | Masks programming bugs as I/O failures | Low |
| 9 | **Maintainability debt unaddressed** — 4 files >1300 LOC (split skipped by design) | Medium | Slows review/onboarding; hides bugs | Large |
| 10 | **Accessibility gaps** — no `ft.Semantics`/screen-reader; browse keyboard focus visual (baseline UX, not in signoff) | Medium | Excludes a11y users; compliance blocker | Medium |

---

## 5. New / Sharpened Findings (not in baseline)

**N1 — pip-audit runs but does not gate (`ci.yml:58-60`).**
```yaml
- name: pip-audit
  run: |
    pip-audit -r requirements.txt || true   # <-- swallows non-zero exit
```
The signoff lists "pip-audit" as Done; this verifies it *executes* but a discovered vulnerability **cannot fail the build**. *Why it matters:* the control gives false assurance. *Fix:* drop `|| true`; if noisy, pin a vetted ignore list (`pip-audit --ignore-vuln GHSA-…`) so only *new* CVEs break CI.

**N2 — Directory adapter silently downgrades TRASH→permanent (`deletion.py:210-236`).**
`DirectoryDeletionAdapter.can_handle()` returns `True` for both `PERMANENT` and `TRASH`, but `delete()` unconditionally calls `shutil.rmtree`. The in-code comment scopes callers to EmptyFolder/SimilarFolder engines, so this is likely **not currently exploited** — but it's an unguarded contract gap: any future caller passing `policy=TRASH, allow_directory_delete=True` gets an unrecoverable delete instead of the Recycle Bin. *Fix:* in the directory adapter, branch on policy (route TRASH dirs through `send2trash`/managed-trash) or make `can_handle` reject TRASH and assert at the boundary.

**N3 — CI version & platform asymmetry (`ci.yml`).** Flet is matrixed (0.80/0.84) but Python is pinned to 3.11 only, while `pyproject.toml` declares `>=3.10` and local artifacts show 3.14. Linux runs the full `-m "not slow"` suite under xvfb; Windows (the primary target per `SECURITY.md`) runs only 4 tests. *Fix:* add 3.10 + 3.13 to the Python matrix; promote the core review/scan/delete suite to the Windows job.

**N4 — Lint/type enforcement is a thin slice.** `ruff check` names ~15 files; `mypy` covers `main.py` + 2 modules. The ruff *config* only selects `T20` (print gate). *Why it matters:* the signoff's "Maintainability: Unchanged" is honest, but the *enforcement surface* is narrower than a reader of "CI hardened" would assume. *Fix:* expand ruff to `E,F,UP` across `cerebro/` incrementally (per-file-ignore the noisy ones); widen mypy to `core/safety`, `engines`, `v2/state`.

**N5 — Silent failure sinks in the delete path.** The fallback trash manifest swallows `OSError` (`deletion.py:83-84`, "must never abort a deletion") and the progress/path extraction blocks catch broad tuples and `pass`. Defensible to keep deletions resilient, but a lost manifest line = a lost undo/rollback record **with no user-visible signal**. *Fix:* on manifest write failure, surface a non-fatal warning toast / structured log at WARNING so the user knows undo coverage is incomplete.

**N6 — Auto-pip nuance vs. the signoff wording.** `runtime_deps.ensure_runtime_dependencies()` is correctly a no-op when `sys.frozen` and respects `CEREBRO_SKIP_AUTO_DEPS`, but on a **source/venv launch it will `pip install --upgrade` from PyPI and re-exec the process** (`runtime_deps.py:101-151`). For desktop end-users on frozen builds this is fine; for any source-distributed or enterprise-from-source deployment it's a live supply-chain path. *Fix:* default `CEREBRO_SKIP_AUTO_DEPS=1` in non-frozen enterprise docs (already in `SECURITY.md`), and consider pinning the install to `requirements.lock` with `--require-hashes` instead of `--upgrade`.

**Strengths confirmed (credit where due):** deletion gate uses `secrets.token_urlsafe` + `compare_digest` + one-time consumption under a `threading.Lock` (`deletion_gate.py:68-131`); permanent adapter refuses to auto-escalate to `rmtree` (`deletion.py:156-200`); hardlink policy enforced pre-delete with platform-aware nlink threshold (`deletion.py:270-289`, `deletion_gate.py:33-41`); **no `shell=True`** anywhere; **no `pickle`/`eval`/`exec`/`yaml.load`** unsafe sinks; parameterized SQL with WAL + busy_timeout; CI asserts a "single-entrance" engine invariant (`ci.yml:108`) and a 3s import-time budget (`ci.yml:110-120`).

---

## 6. Remediation Plan (prioritized, residual-only)

### Quick wins (≤1 day each)
1. **Make pip-audit gate** — remove `|| true` (N1).
2. **Add Python 3.10 + 3.13 to CI matrix** (N3).
3. **Branch directory adapter on TRASH vs PERMANENT** + add a regression test (N2).
4. **Warning-level log on manifest write failure** (N5).
5. **Document `CEREBRO_SKIP_AUTO_DEPS=1` as the enterprise default**; switch the from-source install to `requirements.lock --require-hashes` (N6).

### Short term (1–2 weeks)
6. Expand ruff to `E,F,UP` across `cerebro/`; widen mypy to safety/engines/state (N4).
7. Promote the review/scan/delete suite onto the Windows runner (N3/#6).
8. Tighten the broad `except` tuples in `deletion.py` to `OSError`-only on the I/O lines; let real bugs raise (N8).
9. Add the missing **orchestrator + ImageDedupEngine non-empty-results integration test** (baseline C1 detection guard) if not already covered by `test_orchestrator_engine_lifecycle.py` — verify it asserts non-empty `get_results()`.

### Medium term (2–4 weeks)
10. **Scale path (memory v2.2 backlog):** streaming directory discovery + scroll-triggered pagination for >10k groups; bound `last.json` snapshot (cap groups / summary-only / spill to SQLite-JSONL).
11. **Accessibility pass:** `ft.Semantics` on primary controls; visible browse keyboard focus + scroll-into-view.
12. **Signed releases + SBOM** in a packaging workflow (CycloneDX + code-signed installers).

### Deferred (by design — not blockers)
13. Monolith split of `dashboard_page.py` / `scan_hud.py` / `host.py` / `browse.py` (TD-1..TD-3).
14. `glass` → `cards` rename (shim retained).

---

## 7. Production Hardening Checklist (current state)

- [x] UI mutations only via `run_on_ui_thread` marshaller
- [x] Engine lifecycle: blocking `start` + `wait_until_done` + pause contract
- [x] Cancel kills workers within SLA (30s join + `shutdown_workers()`)
- [x] SQLite `busy_timeout` on all connection paths; WAL
- [x] Deletion gate: one-time token, `compare_digest`, TTL, lock
- [x] No `rmtree` auto-escalation; hardlink policy enforced
- [x] No `shell=True`, no unsafe deserialization
- [x] Session schema validation on resume
- [x] Preview decode size cap
- [x] `SECURITY.md`, dependabot, `requirements.lock`, diagnostic bundle, Sentry opt-in
- [x] **pip-audit gates the build** (removed `|| true`)
- [ ] **Lint/type enforcement covers the bulk of `cerebro/`**
- [x] **CI Python matrix ≥ 2 versions; Windows runs core suite** (3.10/3.11/3.13 + expanded Windows gate)
- [x] **Directory deletion honors TRASH policy**
- [ ] **Bounded/streamed results at 100k+ files**
- [ ] **Accessibility semantics + browse focus**
- [ ] **Signed release + SBOM**

---

## 8. Technical Debt Backlog (residual)

| ID | Item | Sev | Effort |
|----|------|:---:|:------:|
| RD-1 | pip-audit non-blocking | High | S | **Fixed** |
| RD-2 | Streaming discovery + pagination + snapshot bound | High | L |
| RD-3 | Directory adapter TRASH-policy gap | Med | S | **Fixed** |
| RD-4 | Ruff/mypy breadth | Med | M |
| RD-5 | CI Python matrix + Windows suite breadth | Med | M |
| RD-6 | Auto-pip → hash-pinned lock / enterprise default | Med | S |
| RD-7 | Over-broad excepts in delete path | Low–Med | S |
| RD-8 | Monolith split (4 files >1300 LOC) | Med | L |
| RD-9 | Accessibility semantics + browse focus | Med | M |
| RD-10 | Signed release + SBOM | Med | M |
| RD-11 | Silent manifest-write failure signal | Low | S | **Fixed** (WARNING log) |

---

## 9. Is It Production-Ready?

- **Primary path** (Windows/macOS desktop · Files/Turbo scan · review · trash/permanent-delete-with-gate · libraries up to ~tens of thousands of files): **Yes, conditionally.** The data-loss-critical code is genuinely well-defended and the hardening claims verify. Close RD-1 and RD-3 first (both ≤1 day) for a clean release.
- **Enterprise-grade / at scale** (>100k files, a11y compliance, signed distribution, multi-mode guarantees): **Not yet.** Blockers are RD-2 (scale), RD-9 (a11y), RD-10 (signing), plus the CI-enforcement gaps (RD-1/4/5).

**Biggest remaining blockers:** (1) unbounded in-memory/JSON results at large scale; (2) CI controls that run but don't gate; (3) accessibility; (4) signed-release packaging. Maintainability debt (large files) is real but a deliberate, non-blocking deferral.

**Effort to enterprise-grade:** ~3–5 engineer-weeks (vs. the baseline's 8–14 — most of the runtime/safety hardening is already done and verified).

---

*This is a verification/delta report layered on `PRODUCTION_READINESS_AUDIT.md` (architecture/state/UX analysis) and `PRODUCTION_HARDENING_SIGNOFF.md` (fix log). For the full architectural narrative and mermaid diagram, see the baseline; this document supersedes the signoff's CI/maintainability optimism with verified evidence. Re-run after the scale (RD-2) and CI-gating (RD-1/4/5) work lands.*
