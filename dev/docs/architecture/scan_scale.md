# TurboScanner scale (500k–1M files)

## Goals

| Scenario | Target (NVMe, user tree, warm hash cache) |
|----------|-------------------------------------------|
| Index 1M paths | Under ~20 minutes |
| First dedup (~10% same-size candidates) | Under ~90 minutes |
| Re-scan same scope | Under ~15 minutes |

## Pipeline

1. **Discovery** — parallel `os.scandir` walk; optional **streaming** into `CheckpointDB` (no 1M-row Python list).
2. **Grouping** — in-memory below `STREAMING_THRESHOLD` (50k); otherwise SQL `ORDER BY file_size`.
3. **Tier-A** — 4 KiB prefix filter with progress stage `tier_a_prefilter`; adaptive mode on large scans.
4. **Quick hash** — 64 KiB window; **full hash** only when `verify_duplicates=True`.

## Settings

- **Settings → General → Skip system folders** — skips `Windows`, `Program Files`, `node_modules`, etc.
- **Home → Advanced → Index only** — catalogue + size groups; resume later to hash.
- **Home → Advanced → Deep verify** — enables full-file hash pass (slower).
- **Settings → Performance** — thread cap and hash cache.

## Flags (engine / dev)

- `force_scale_mode` — enables tier-A adaptive + phase worker policy.
- `skip_system_folders` — passed into `TurboScanConfig.skip_system`.
- Checkpoint scope includes `skip_system_folders`, `verify_duplicates`, `index_only`.

## Windows pitfalls

- Scanning `C:\` or `D:\` includes hundreds of thousands of system files.
- Same-size buckets (0-byte, small logs) can be huge — `MAX_BUCKET_FILES` (10k) triggers chunked Tier-A.
- Exclude `%WINDIR%` or enable skip system folders.

## Benchmarks

Run scale tests locally:

```bash
pytest dev/tests/test_scan_scale.py -q
pytest dev/tests/test_scan_scale.py -m slow -q
```

Phase timings appear in logs as `[Turbo] Phase timings: discovery=… grouping=… tier_a=…`.
