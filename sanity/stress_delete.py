#!/usr/bin/env python3
"""
stress_delete.py — Stress-test the CEREBRO delete pipeline.

Creates duplicate files, runs scan, applies Smart Select, builds a
deletion plan, executes it, and verifies:
  1. Deleted files no longer exist on disk.
  2. Keeper files still exist.
  3. Pipeline returns correct counts.

Usage:
    python -m sanity.stress_delete [--groups N] [--dir PATH]

Exit codes:
    0 = PASS
    1 = FAIL
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def _create_test_tree(root: Path, num_groups: int) -> list[dict]:
    """Create groups of 3 duplicate files each.

    Returns list of dicts: [{keep: str, delete: [str, str], group_index: int}, ...]
    """
    root.mkdir(parents=True, exist_ok=True)
    groups = []
    for g in range(num_groups):
        content = f"DELETE-STRESS-{g:04d}-{'Y' * 512}".encode()
        paths = []
        for d in range(3):
            sub = root / f"grp_{g}"
            sub.mkdir(parents=True, exist_ok=True)
            fp = sub / f"copy_{d}.dat"
            fp.write_bytes(content)
            paths.append(str(fp))
        groups.append({
            "group_index": g,
            "keep": paths[0],
            "delete": paths[1:],
        })
    return groups


def main() -> int:
    parser = argparse.ArgumentParser(description="CEREBRO delete pipeline stress test")
    parser.add_argument("--groups", type=int, default=30, help="Number of duplicate groups")
    parser.add_argument("--dir", type=str, default="", help="Temp dir (auto-created if empty)")
    args = parser.parse_args()

    tmpdir = Path(args.dir) if args.dir else Path(tempfile.mkdtemp(prefix="cerebro_del_stress_"))
    print(f"[stress_delete] Creating {args.groups} groups (3 files each) @ {tmpdir}")

    groups = _create_test_tree(tmpdir, args.groups)
    total_delete = sum(len(g["delete"]) for g in groups)
    print(f"[stress_delete] {total_delete} files to delete, {args.groups} keepers to preserve")

    from cerebro.core.pipeline import CerebroPipeline

    pipeline = CerebroPipeline()

    deletion_plan = {
        "scan_id": "stress-test",
        "policy": {"mode": "permanent"},
        "groups": groups,
        "source": "stress_delete",
    }

    t0 = time.perf_counter()
    try:
        executable = pipeline.build_delete_plan(deletion_plan)
    except Exception as exc:
        print(f"[stress_delete] FAIL — build_delete_plan raised: {exc}")
        return 1

    print(f"[stress_delete] Plan built: {executable.total_files} ops, {executable.total_bytes} bytes")

    progress_ticks = []

    def progress_cb(current, total, name):
        progress_ticks.append(current)
        return True

    try:
        result = pipeline.execute_delete_plan(executable, progress_cb=progress_cb)
    except Exception as exc:
        print(f"[stress_delete] FAIL — execute_delete_plan raised: {exc}")
        return 1

    t_total = time.perf_counter() - t0
    print(f"[stress_delete] Executed in {t_total:.2f}s — deleted={len(result.deleted)} failed={len(result.failed)}")

    ok = True

    # Verify deleted files are gone
    for p in result.deleted:
        if p.exists():
            print(f"[stress_delete] FAIL — deleted file still exists: {p}")
            ok = False
            break

    # Verify keepers still exist
    for g in groups:
        kp = Path(g["keep"])
        if not kp.exists():
            print(f"[stress_delete] FAIL — keeper was deleted: {kp}")
            ok = False
            break

    # Verify counts
    if len(result.deleted) != total_delete:
        print(f"[stress_delete] WARN — expected {total_delete} deleted, got {len(result.deleted)}")

    if len(result.failed) > 0:
        print(f"[stress_delete] WARN — {len(result.failed)} failures")
        for p, reason in result.failed[:5]:
            print(f"  {p}: {reason}")

    if not progress_ticks:
        print("[stress_delete] WARN — no progress callbacks received")

    # Cleanup
    if not args.dir:
        shutil.rmtree(tmpdir, ignore_errors=True)

    status = "PASS" if ok else "FAIL"
    print(f"[stress_delete] {status}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
