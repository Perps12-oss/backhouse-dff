# Review flow / Browse performance notes

This document captures how to measure UI flush cost for large duplicate sets and how to avoid regressions after `feat/perceived-performance`.

## Chunked list profiling (`ChunkedViewBuilder`)

1. Set environment variable `CEREBRO_PROFILE_CHUNKED=1` (or `true` / `yes`).
2. Run the Flet app, complete a real scan so the Review tab has duplicate groups, open **Review** (v2 flow) → **Browse**, and scroll through the list. For synthetic large lists in automated or scratch tests, build `DuplicateGroup` lists (see `tests/review_flow_fixtures.duplicate_groups_for_tests`) and call `ReviewFlowHost.load_results` from a small script.
3. Watch logs for lines like `[CHUNK_PERF] async_tick safe_update XX.XX ms` emitted from `cerebro/v2/ui/flet_app/components/common/chunked_view.py`.

**Interpretation**

- Values **well under ~16 ms** per `safe_update` call mean the UI thread is staying light for that flush.
- **30 ms+** usually indicates control creation or image work on the main thread; pair with Python profiling if needed.

## Bounded async builds

`ChunkedViewBuilder` caps how many new row controls are appended before yielding a frame (`max_builds_per_tick`, default **20** for review groups). This trades slightly longer wall time for smoother scrolling.

## Thumbnail pipeline

- Browse rows load a **32×32** tiny JPEG first (when the file is a supported image), then crossfade to the normal grid thumbnail.
- Inspect compare slots load a **128×128** tiny preview before the full compare JPEG.
- All tiers share the same LRU in `ThumbnailCache` with distinct key prefixes.

## Optional local stress counts

Generating **50k / 100k / 500k** synthetic groups is intentionally **not** part of CI (too slow / too much memory). For local experiments, generate a large list with `duplicate_groups_for_tests` in `tests/review_flow_fixtures.py`, pass it to `load_results` from a scratch script, then use `CEREBRO_PROFILE_CHUNKED` as above.

## Future work (not yet implemented)

- True **virtualized** lists (only mount visible rows) for guaranteed smooth scrolling beyond a few thousand controls.
- **Incremental row reuse** in Browse (skip rebuilding a row when only a thumbnail bitmap changed).
