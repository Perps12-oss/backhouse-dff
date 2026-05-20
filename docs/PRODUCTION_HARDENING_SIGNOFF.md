# Production Hardening Signoff

Checklist from production readiness plan (monolith extraction **skipped** per request).

| Item | Status |
|------|--------|
| UI marshal (`run_on_ui_thread`); no `run_thread` for controls | Done |
| Engine lifecycle: blocking `start`, `wait_until_done`, pause contract | Done |
| Orchestrator cancel: 30s join + `shutdown_workers()` | Done |
| ResultsStore + snapshot caps + `busy_timeout` on history DB | Done |
| Coordinator scan_* wired from `BackendService` | Done |
| Shutdown: bridge unsubscribe, TimeKeeper, thumbnail cache | Done |
| Trash via `build_explicit_paths_plan` | Done |
| Session schema validation on resume | Done |
| Preview size cap (`CEREBRO_PREVIEW_MAX_BYTES`) | Done |
| Archives scan option disabled (coming soon) | Done |
| MP pause disabled when multiple folders | Done |
| `SECURITY.md` | Done |
| Diagnostic bundle export (Settings → About) | Done |
| Log path redaction (`CEREBRO_REDACT_PATHS`) | Done |
| Sentry opt-in (`CEREBRO_SENTRY_DSN`) | Done (optional `sentry-sdk`) |
| CI: pip-audit, secret scan, coverage slice, Windows smoke | Done |
| `requirements.lock` (pinned subset) | Done |
| Monolith split (`dashboard_page`, `scan_hud`, `host`) | **Skipped** |
| Full `glass` → `cards` rename | **Skipped** (shim only) |
| Signed release / SBOM | Pending — packaging |

## Tests added (fast CI)

- `test_ui_marshal.py`, `test_coordinator_scan_wiring.py`
- `test_orchestrator_engine_lifecycle.py`, `test_engine_pause_contract.py`
- `test_results_store_roundtrip.py`, `test_snapshot_size_cap.py`
- `test_session_schema_validation.py`, `test_trash_pipeline_validation.py`
- `test_preview_size_limits.py`, `test_flet_headless_smoke.py`

## Re-score (estimate)

| Area | Before audit | After hardening |
|------|--------------|-----------------|
| Concurrency / UI safety | Weak | Strong |
| Engine lifecycle | Fragile | Solid |
| Scale / memory | Risky | Bounded |
| Security / deletes | Gaps | Gated |
| CI / observability | Minimal | Expanded |
| Maintainability (LOC) | Poor | Unchanged (skipped) |

**Estimated readiness: ~88–92 / 100** (90–95% target met on runtime/CI; LOC debt remains by design).
