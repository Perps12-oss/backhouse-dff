# CEREBRO Stress Test Guide

## Overview

Two headless stress harnesses exercise the scan and delete pipelines without launching the GUI.

## Scripts

### `sanity/stress_scan.py`
Creates a temporary tree of deterministic duplicate files and runs the FastScanWorker headlessly.

```bash
python -m sanity.stress_scan --groups 50 --files 200
```

**Pass criteria:**
- Exit code 0
- No exceptions during scan
- At least 80% of expected groups detected (engine may merge or split)

**Output format:**
```
[stress_scan] Creating 200 files in 50 groups @ /tmp/cerebro_stress_xxx
[stress_scan] Tree created in 0.12s
[stress_scan] Scan completed in 1.45s — 50 groups found (expected 50)
[stress_scan] PASS
```

### `sanity/stress_delete.py`
Creates groups of 3 duplicate files, builds a DeletionPlan, executes via CerebroPipeline, and verifies disk state.

```bash
python -m sanity.stress_delete --groups 30
```

**Pass criteria:**
- Exit code 0
- All deleted files removed from disk
- All keeper files remain on disk
- `result.deleted` count matches expected total
- At least one progress callback fired

**Output format:**
```
[stress_delete] Creating 30 groups (3 files each) @ /tmp/cerebro_del_stress_xxx
[stress_delete] 60 files to delete, 30 keepers to preserve
[stress_delete] Plan built: 60 ops, 31200 bytes
[stress_delete] Executed in 0.23s — deleted=60 failed=0
[stress_delete] PASS
```

## Running Both

```bash
python -m sanity.stress_scan --groups 100 --files 400
python -m sanity.stress_delete --groups 50
```

Both should print `PASS` and exit 0.

## Arguments

| Script | Flag | Default | Description |
|--------|------|---------|-------------|
| stress_scan | `--files` | 200 | Total files to create |
| stress_scan | `--groups` | 50 | Number of duplicate groups |
| stress_scan | `--dir` | (auto) | Custom temp directory |
| stress_delete | `--groups` | 30 | Number of groups |
| stress_delete | `--dir` | (auto) | Custom temp directory |
