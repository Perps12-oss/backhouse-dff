# path: cerebro/core/reporting/script_report.py
"""
cerebro/core/reporting/script_report.py — Cleanup script exporter

Emits:
- cleanup.sh  (bash)        safe default = echo, with EXECUTE flag
- cleanup.ps1 (PowerShell)  safe default = Write-Host, with EXECUTE flag
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, List, Tuple


def _iter_paths_from_plan(plan: Any) -> List[str]:
    if not plan:
        return []
    items = getattr(plan, "items", None) or []
    out: List[str] = []
    for it in items:
        p = getattr(it, "path", it)
        out.append(str(p))
    return out


def write_cleanup_scripts(out_dir: Path, *, delete_plan: Any, scan_id: str = "") -> Tuple[Path, Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    paths = _iter_paths_from_plan(delete_plan)

    sh_path = out_dir / "cleanup.sh"
    ps_path = out_dir / "cleanup.ps1"

    sh_path.write_text(_bash_script(paths, scan_id=scan_id), encoding="utf-8")
    ps_path.write_text(_powershell_script(paths, scan_id=scan_id), encoding="utf-8")
    return sh_path, ps_path


def _bash_script(paths: List[str], *, scan_id: str) -> str:
    lines: List[str] = []
    lines.append("#!/usr/bin/env bash")
    lines.append("set -euo pipefail")
    lines.append("")
    lines.append(f"# CEREBRO cleanup script (scan_id={scan_id})")
    lines.append("# Safe default: DRY RUN (echo). To execute, run: EXECUTE=1 ./cleanup.sh")
    lines.append('EXECUTE="${EXECUTE:-0}"')
    lines.append("")
    lines.append("rm_file() {")
    lines.append('  local p="$1"')
    lines.append('  if [[ "${EXECUTE}" == "1" ]]; then')
    lines.append('    rm -f -- "$p"')
    lines.append("  else")
    lines.append('    echo "[DRY] rm -f -- $p"')
    lines.append("  fi")
    lines.append("}")
    lines.append("")
    for p in paths:
        qp = p.replace("'", "'\"'\"'")
        lines.append(f"rm_file '{qp}'")
    lines.append("")
    return "\n".join(lines) + "\n"


def _powershell_script(paths: List[str], *, scan_id: str) -> str:
    lines: List[str] = []
    lines.append("# CEREBRO cleanup script")
    lines.append(f"# scan_id: {scan_id}")
    lines.append("# Safe default: DRY RUN (Write-Host). To execute: $env:EXECUTE=1; .\\cleanup.ps1")
    lines.append("$Execute = $env:EXECUTE")
    lines.append("if (-not $Execute) { $Execute = '0' }")
    lines.append("")
    lines.append("function Remove-FileSafe($p) {")
    lines.append("  if ($Execute -eq '1') {")
    lines.append("    Remove-Item -LiteralPath $p -Force -ErrorAction Continue")
    lines.append("  } else {")
    lines.append('    Write-Host "[DRY] Remove-Item -LiteralPath $p -Force"')
    lines.append("  }")
    lines.append("}")
    lines.append("")
    for p in paths:
        qp = p.replace("'", "''")
        lines.append(f"Remove-FileSafe '{qp}'")
    lines.append("")
    return "\n".join(lines) + "\n"
