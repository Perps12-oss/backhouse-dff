# Engine Borrow Scavenge Notes

## Purpose
Provide a practical scavenging checklist for borrowing high-value dedupe-engine ideas from the old project while preventing framework leakage and regressions.

## Non-negotiable guardrails
- No PySide6 imports or assumptions in current core engine code.
- Keep core modules UI-agnostic:
  - `cerebro/core/scanners`
  - `cerebro/engines`
  - `cerebro/services`
  - `cerebro/v2/core`
- Preserve no-regression constraints:
  - duplicate correctness,
  - progress monotonicity,
  - terminal-state monotonicity,
  - pause/cancel responsiveness.

## Old-code scavenging map
- Source to inspect:
  - [dedup/engine folder](https://github.com/Perps12-oss/dedup/tree/main/dedup/engine)
  - [pipeline.py](https://raw.githubusercontent.com/Perps12-oss/dedup/main/dedup/engine/pipeline.py)
  - [grouping.py](https://raw.githubusercontent.com/Perps12-oss/dedup/main/dedup/engine/grouping.py)
  - [hashing.py](https://raw.githubusercontent.com/Perps12-oss/dedup/main/dedup/engine/hashing.py)

## Priority borrow targets
1. Adaptive candidate reduction
- Borrow idea: refine very large candidate groups with stronger partial strategy before full hash.
- Apply to current hotspot: Tier-A in `turbo_scanner.py`.
- Expected benefit: reduce oversized-group waste and lower Tier-A elapsed time.

2. Durable phase artifacts for resume
- Borrow idea: persist size/partial/full phase outputs with versioned metadata.
- Apply to current checkpoint pipeline in `checkpoint_db.py` and scanner resume logic.
- Expected benefit: avoid recomputing already-safe reductions after interruption.

3. Canonical-path pre-dedup placement
- Borrow idea: canonical path dedup before expensive hash phases.
- Apply to current discovery-to-grouping handoff in `turbo_scanner.py`.
- Expected benefit: remove alias duplicates early, reduce candidate cardinality.

4. Hash strategy metadata discipline
- Borrow idea: persist algorithm + strategy version as first-class metadata.
- Apply to cache/checkpoint records to prevent stale reuse.
- Expected benefit: safer upgrades and cleaner compatibility gates.

## Things to reject during scavenging
- Any framework-bound UI lifecycle logic.
- Legacy callback semantics that force scanner behavior based on UI loop specifics.
- Broad architectural rewrites that risk current Flet bridge behavior in `turbo_file_engine.py`.

## Scavenge execution checklist
- Read old module.
- Extract pattern as a small isolated utility/flow in current engine.
- Add tests before enabling by default.
- Validate correctness parity against golden datasets.
- Validate progress/terminal-state invariants.
- Run performance A/B and keep only net-positive changes.

## Done criteria
- Measurable Tier-A and end-to-end improvement on representative scans.
- Zero PySide6 references in core engine paths.
- Resume behavior improved with no stale-artifact regressions.
- All no-regression tests pass.
