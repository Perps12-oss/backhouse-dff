# Cerebro v2 — Performance Audit & Fix Prompt

> Paste everything below as a single message to Claude. It contains all context Claude needs to investigate without re-asking.

---

## ROLE

You are a senior Flet/Python performance engineer doing a deep-dive bottleneck audit on a desktop app. You will identify *every* cause of slowness in the UI layer, rank them by severity, and produce concrete fixes. You are methodical, evidence-driven, and you do not guess — you measure first, then fix.

## PROJECT CONTEXT

- **App:** Cerebro Duplicate File Finder v2
- **Repo:** `github.com/Perps12-oss/silver-octo-pancake`
- **UI stack:** Flet 0.84.0, Python
- **Project structure:**
  - `cerebro/v2/ui/flet_app/` — Flet app root
  - `cerebro/v2/ui/flet_app/theme.py` — token-style theme objects, `theme_for_mode`
  - `cerebro/v2/ui/flet_app/palette_themes.py` — 35 preset palettes
  - `cerebro/v2/ui/flet_app/services/state_bridge.py` — `apply_preset_theme`, `set_on_theme_change`, dispatches `ThemeChanged`
  - Page modules each implement `apply_theme(mode)` for repaint
  - Engine: `TurboFileEngine` — **off-limits, do not touch**
  - Engine boundary: anything that hashes, traverses, persists, or compares files. Treat as a black box.
- **Architecture:** Phases 0–5 of a UI modernization shipped recently. Dark-themed, Material 3, multiple pages: Home, Results, Review, History, Settings.

## OBSERVED SYMPTOMS

Confirmed by the user:

1. **Results page takes "minutes" to load** even on small scans (e.g. 6 groups, 13 files, 185 KB).
2. **Review page (image grid) takes "minutes" to load** and feels laggy on scroll.
3. **General UI feels sluggish** — clicks have perceptible delay, theme changes are slow to propagate, scrolling stutters.
4. **No visible hang or crash** — the app responds, just slowly.
5. **Engine itself is fast** — scans complete quickly per user reports; the slowness is purely in rendering and interaction.

## SCOPE CONTRACT — STRICT

✅ **In scope:**
- Anything under `cerebro/v2/ui/flet_app/`
- Theme system, state bridge, page rendering, control trees
- How scan results are passed from engine → UI
- Image/thumbnail loading, caching
- Animation, update batching, layout cost
- Startup time of the Flet app shell

❌ **Out of scope (do not modify):**
- `TurboFileEngine`
- File traversal, hashing, comparison logic
- Database schema, scan persistence
- File deletion, trash logic
- Thread pool / concurrency model on the engine side

If a fix would require an engine change, **flag it as a separate proposal** with justification — do not implement it.

## INVESTIGATION METHODOLOGY — FOLLOW THIS ORDER

### Phase A: Map the surface (don't fix anything yet)

1. **Catalog every page entry point.** For each page (Home, Results, Review, History, Settings), find:
   - The `build()` / page construction function
   - All controls created on initial render
   - All `page.update()` calls
   - All event handlers and what they trigger
2. **Trace the data path** from `TurboFileEngine` results → state bridge → page render. Document every transformation, copy, and signal hop.
3. **Identify hot loops** — anywhere code iterates over scan results to build controls.
4. **List every async or threaded boundary** between engine and UI.

Output of Phase A: a written **architectural map** of where time *could* be spent, before measuring where it *is* spent. Save this — you'll need it later.

### Phase B: Measure (the most important phase)

Do not fix based on intuition. Instrument first.

1. **Add timing instrumentation** to every suspect path. Use `time.perf_counter()`. Log at function entry/exit with elapsed ms. Specifically wrap:
   - Page build functions (Results, Review)
   - Each per-row / per-card builder function
   - `page.update()` calls — log how many controls are in the tree at the time of each call
   - Theme propagation (`apply_theme` on each page)
   - State bridge dispatches
   - Image/thumbnail loading

2. **Run with a representative dataset.** Use a scan with 100+ result groups if available. Capture a clean log.

3. **Count `page.update()` invocations** during a single Results page load. **Print the count.** This is often the smoking gun in Flet apps.

4. **Profile import time.** Run `python -X importtime -m cerebro.v2.ui.flet_app.main 2>importtime.log` and analyze. Heavy imports at startup show up here.

5. **Capture memory growth** with `tracemalloc` snapshots before/after Results page load.

Output of Phase B: a **measurement report** with concrete numbers — "Results page build: 47.3s, of which 41.1s is in `_build_group_row` called 381 times averaging 108ms each. `page.update()` called 384 times during build."

### Phase C: Diagnose

For every measurable hotspot, identify the root cause from this checklist of common Flet-specific anti-patterns:

#### Update thrash
- [ ] Is `page.update()` called inside a loop instead of once after?
- [ ] Is `control.update()` being called when the control isn't yet in the tree?
- [ ] Are state bridge dispatches triggering full-page rebuilds when partial would suffice?

#### Control tree weight
- [ ] Are list rows nested `Container > Row > Column > Container > ...` 5+ levels deep when `ListTile` would do?
- [ ] Are decorative effects (`shadow`, `gradient`, `BackdropFilter`-style) applied per-row instead of per-section?
- [ ] Are SVGs being rendered as `Image(src=...)` (re-parsed every frame) instead of cached?
- [ ] Are `ft.Container` instances created with `bgcolor` set to a function call (e.g. `theme.color()`) that runs every build?

#### List virtualization
- [ ] Is `ListView` virtualized (default) or is the page using `Column` with hundreds of children (no virtualization)?
- [ ] Is `GridView` configured with reasonable `runs_count` / `max_extent` so off-screen rows are recycled?
- [ ] Are scroll containers nested inside other scroll containers (kills virtualization)?

#### Image loading
- [ ] Are image thumbnails loaded synchronously during row construction?
- [ ] Are full-resolution images being decoded when small thumbnails would suffice?
- [ ] Is there any thumbnail cache, or is every visible card re-decoding from disk?
- [ ] Are images being read on the UI thread instead of a background thread/executor?

#### Theme propagation
- [ ] Does `apply_theme` walk every control on every page, or only the active one?
- [ ] Are inactive pages still subscribed to `ThemeChanged` and rebuilding off-screen?
- [ ] Does `theme_for_mode` rebuild the entire `ft.Theme` object on every call, or is it cached per palette?

#### State bridge
- [ ] Are state events fired synchronously on the UI thread?
- [ ] Is `set_on_theme_change` registering duplicate listeners over time (memory leak + N× work per dispatch)?
- [ ] Are subscribers retained after their pages are disposed?

#### Engine → UI handoff
- [ ] Is the entire result set marshaled to UI state in one go, or streamed?
- [ ] Are result objects being re-copied/serialized when one reference would do?
- [ ] Is the Results page waiting on the engine's *complete* signal before showing anything, when progressive rendering would feel instant?

#### Startup
- [ ] Is the entire palette set (35 themes) being loaded eagerly at import time?
- [ ] Are page modules imported eagerly even when not visited?
- [ ] Are font / icon assets being decoded on first paint?

### Phase D: Rank

Build a table:

| # | Hotspot | Measured cost | Root cause | Severity | Fix complexity |
|---|---------|---------------|------------|----------|----------------|
| 1 | ... | ... | ... | 🔴/🟠/🟡 | Low/Med/High |

Severity rule:
- 🔴 Critical — accounts for >20% of perceived slowness or causes >5s delay
- 🟠 High — accounts for 5–20% or causes 1–5s delay
- 🟡 Medium — measurable but <1s impact

### Phase E: Fix

For every 🔴 and 🟠 item, produce a concrete patch. For each fix:

1. **Show the before code** (exact file path + line range).
2. **Show the after code.**
3. **Explain why this fixes the measured cost** — reference the Phase B numbers.
4. **State the expected improvement** as a measurable claim ("expect Results page build to drop from 47s to <2s").
5. **Note any risk** (visual regression, behavior change, edge cases).

Apply fixes incrementally — one hotspot at a time. After each fix, **re-measure** to confirm the improvement. If the numbers don't move as expected, stop and re-diagnose.

🟡 medium items: list them as "deferred" with notes; don't fix unless trivial.

### Phase F: Verify

After all fixes:

1. Re-run the full Phase B instrumentation.
2. Produce a **before/after table** — original timing vs. new timing for every measured hotspot.
3. Confirm **no engine changes** were made (`git diff` against the engine module path should be empty).
4. Confirm **no visual regressions** by checking the UI still matches the Phase 5 redesign intent.
5. Document any remaining slowness that's outside UI scope (e.g. "result load takes 800ms which is engine-side; UI rendering is now <100ms").

## DELIVERABLES

At the end, produce a single document `CEREBRO_PERF_AUDIT_REPORT.md` with these sections:

1. **Executive summary** — 3-5 bullets: what was slow, why, what changed, measurable result.
2. **Architectural map** (from Phase A).
3. **Measurement report** (from Phase B) — raw numbers, before any fixes.
4. **Diagnosed root causes** (from Phase C) — checklist results with evidence.
5. **Ranked hotspot table** (from Phase D).
6. **Applied fixes** (from Phase E) — one subsection per fix, with diffs.
7. **Verification report** (from Phase F) — before/after numbers, screenshots if relevant.
8. **Deferred items** — anything not fixed, with rationale.
9. **Engine-side proposals** — anything that would need engine changes, presented as separate proposals for the user to approve.

## RULES

- **Measure before you fix.** Every claim of slowness needs a number attached.
- **Fix one thing at a time.** Don't combine three optimizations into one PR — you won't know which one helped.
- **Do not modify the engine.** If a fix requires it, write a proposal instead.
- **Preserve the visual design.** No visual regressions — the Phase 0–5 redesign stays.
- **Preserve all functionality.** No behavior changes, only speed changes.
- **Show your work.** Every claim needs a measurement, every fix needs a before/after.
- **If you can't reproduce a slowness symptom, say so explicitly** rather than guessing at fixes.
- **Bias toward simplicity.** A fix that removes 100 lines and makes things faster is better than one that adds 200 lines of caching infrastructure.

## ANTI-PATTERNS TO REJECT

If you find yourself doing any of these, stop:

- ❌ Adding `async`/threading without first proving the bottleneck is CPU-bound
- ❌ Adding caches without first proving the underlying call is expensive
- ❌ "Optimizing" code that the profiler shows takes <10ms
- ❌ Refactoring for cleanliness while claiming it's a performance fix
- ❌ Touching engine code under the guise of "necessary for UI perf"
- ❌ Disabling features (animations, themes, effects) instead of making them efficient

## STARTING INSTRUCTIONS

Begin with Phase A. Do not write any fixes until Phase B measurements are in hand. When Phase B is done, present the measurement report to me and wait for confirmation before proceeding to Phase C and beyond.

If anything in this brief is unclear or the codebase doesn't match the structure described, ask before proceeding.
