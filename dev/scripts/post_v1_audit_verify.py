#!/usr/bin/env python3
"""Aggregate post–v1 audit verification (Phase 8.5 automated subset).

Runs:
  * pytest on audit + core regression tests
  * headless smoke scripts (engine deps, virtual grid, thumb grid)

Writes ``docs/releases/v1.1.0/final_verification.log`` (overwritten each run).

Usage (from repo root)::

    python scripts/post_v1_audit_verify.py

Exit code 0 only if every subprocess succeeds.

Manual / operator-owned (not run here):
  * Full 5-root overlap regression scan and log forensics
  * Squash-merge to ``main`` and advisor sign-off (Phase 8.7)
"""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / "docs" / "releases" / "v1.1.0"
LOG_PATH = LOG_DIR / "final_verification.log"


def _run(cmd: list[str], log: list[str], env: dict[str, str]) -> int:
    log.append(f"$ {' '.join(cmd)}")
    p = subprocess.run(
        cmd,
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if p.stdout:
        log.append("--- stdout ---")
        log.append(p.stdout.rstrip())
    if p.stderr:
        log.append("--- stderr ---")
        log.append(p.stderr.rstrip())
    log.append(f"exit_code={p.returncode}")
    log.append("")
    return int(p.returncode)


def main() -> int:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines: list[str] = [
        f"CEREBRO post-v1 audit — automated verification ({stamp})",
        f"repo_root={ROOT}",
        "",
        "== Preconditions ==",
        "- Phase 1–2 closure: recorded in docs/plans/post-v1-audit-plan.md",
        "- Phase 8.1 DIAG:* removal: enforced by tests/test_post_v1_audit_verification.py",
        "",
        "== pytest (audit + turbo + DB smoke) ==",
    ]

    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT)

    rc = _run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "tests/test_post_v1_audit_verification.py",
            "tests/test_group_invariants.py",
            "tests/test_turbo_engine_regressions.py",
            "tests/test_scan_history_db.py",
            "tests/test_deletion_history_db.py",
        ],
        lines,
        env,
    )
    if rc != 0:
        lines.append("FAIL: pytest")
        LOG_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return rc

    lines.append("== smoke_engine_deps.py ==")
    rc = _run([sys.executable, "scripts/smoke_engine_deps.py"], lines, env)
    if rc != 0:
        lines.append("FAIL: smoke_engine_deps")
        LOG_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return rc

    lines.append("== smoke_virtual_grid.py ==")
    rc = _run([sys.executable, "scripts/smoke_virtual_grid.py"], lines, env)
    if rc != 0:
        lines.append("FAIL: smoke_virtual_grid")
        LOG_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return rc

    lines.append("== smoke_thumb_grid.py ==")
    rc = _run([sys.executable, "scripts/smoke_thumb_grid.py"], lines, env)
    if rc != 0:
        lines.append("FAIL: smoke_thumb_grid")
        LOG_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return rc

    lines.extend(
        [
            "== Operator-pending (manual Phase 8.5 bars) ==",
            "- Full 5-root overlap scan + count inversion / emit baseline checks",
            "- Paste run excerpt into this log or companion file if desired",
            "- Phase 8.7: squash-merge fix/post-v1-audit → main after advisor sign-off",
            "",
            "ALL AUTOMATED CHECKS PASSED",
        ]
    )
    LOG_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    rel = LOG_PATH.relative_to(ROOT)
    print(f"OK — wrote {rel} ({LOG_PATH.stat().st_size} bytes)", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
