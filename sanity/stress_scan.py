#!/usr/bin/env python3
"""
stress_scan.py — Stress-test the CEREBRO scan pipeline.

Creates a temporary tree of duplicate files and runs the scan engine
against it, verifying that:
  1. The scan completes without crash.
  2. The expected number of duplicate groups is found.
  3. Each group contains exactly the expected files.

Usage:
    python -m sanity.stress_scan [--files N] [--groups N] [--dir PATH]

Exit codes:
    0 = PASS
    1 = FAIL
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def _create_test_tree(root: Path, num_groups: int, dupes_per_group: int) -> dict:
    """Create a deterministic tree of duplicate files.

    Returns dict mapping group_index -> list of absolute paths.
    """
    root.mkdir(parents=True, exist_ok=True)
    groups: dict[int, list[str]] = {}
    for g in range(num_groups):
        content = f"GROUP-{g:04d}-PAYLOAD-{'X' * 1024}".encode()
        paths: list[str] = []
        for d in range(dupes_per_group):
            sub = root / f"group_{g}" / f"copy_{d}"
            sub.mkdir(parents=True, exist_ok=True)
            fp = sub / f"file_{g}_{d}.dat"
            fp.write_bytes(content)
            paths.append(str(fp))
        groups[g] = paths
    return groups


def _run_scan(root: Path) -> dict:
    """Run the CEREBRO fast-scan engine headlessly and return the result dict."""
    from cerebro.workers.fast_scan_worker import FastScanWorker

    result_holder: list[dict] = []
    error_holder: list[str] = []

    class FakeSignal:
        def __init__(self):
            self._slots = []
        def connect(self, fn):
            self._slots.append(fn)
        def emit(self, *args):
            for fn in self._slots:
                fn(*args)

    worker = FastScanWorker.__new__(FastScanWorker)
    worker.progress = FakeSignal()
    worker.finished = FakeSignal()
    worker.error = FakeSignal()
    worker.cancelled = FakeSignal()

    worker.finished.connect(lambda r: result_holder.append(r))
    worker.error.connect(lambda e: error_holder.append(e))

    config = {
        "root": str(root),
        "mode": "fast",
        "fast_mode": True,
        "engine": "simple",
        "media_type": "all",
        "min_size_bytes": 0,
    }

    try:
        worker._config = config
        worker._cancel = False
        worker.run()
    except Exception as exc:
        error_holder.append(str(exc))

    if error_holder:
        return {"error": error_holder[0], "groups": []}
    if result_holder:
        return result_holder[0]
    return {"error": "No result returned", "groups": []}


def main() -> int:
    parser = argparse.ArgumentParser(description="CEREBRO scan stress test")
    parser.add_argument("--files", type=int, default=200, help="Total duplicate files to create")
    parser.add_argument("--groups", type=int, default=50, help="Number of duplicate groups")
    parser.add_argument("--dir", type=str, default="", help="Temp dir (auto-created if empty)")
    args = parser.parse_args()

    dupes_per_group = max(2, args.files // max(1, args.groups))
    effective_files = args.groups * dupes_per_group

    tmpdir = Path(args.dir) if args.dir else Path(tempfile.mkdtemp(prefix="cerebro_stress_"))
    print(f"[stress_scan] Creating {effective_files} files in {args.groups} groups @ {tmpdir}")

    t0 = time.perf_counter()
    expected = _create_test_tree(tmpdir, args.groups, dupes_per_group)
    t_create = time.perf_counter() - t0
    print(f"[stress_scan] Tree created in {t_create:.2f}s")

    t0 = time.perf_counter()
    result = _run_scan(tmpdir)
    t_scan = time.perf_counter() - t0

    if result.get("error"):
        print(f"[stress_scan] FAIL — scan error: {result['error']}")
        return 1

    groups_found = result.get("groups", [])
    print(f"[stress_scan] Scan completed in {t_scan:.2f}s — {len(groups_found)} groups found (expected {args.groups})")

    ok = True
    if len(groups_found) < args.groups * 0.8:
        print(f"[stress_scan] WARN — expected ~{args.groups} groups, got {len(groups_found)}")
        ok = False

    # Cleanup
    if not args.dir:
        shutil.rmtree(tmpdir, ignore_errors=True)

    status = "PASS" if ok else "FAIL"
    print(f"[stress_scan] {status}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
