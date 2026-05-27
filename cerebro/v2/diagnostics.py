"""Export a redacted diagnostic bundle for support."""

from __future__ import annotations

import json
import platform
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from cerebro.core.paths import cerebro_user_root


def export_diagnostic_bundle(dest_zip: Optional[Path] = None) -> Path:
    """Zip logs, version info, and summary metadata (no full scan groups)."""
    root = cerebro_user_root()
    logs = root / "logs"
    out = dest_zip or (root / f"diagnostic_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.zip")
    try:
        from importlib.metadata import version as _pkg_version

        pkg_ver = _pkg_version("cerebro")
    except Exception:
        pkg_ver = "unknown"
    meta = {
        "cerebro_version": pkg_ver,
        "platform": platform.platform(),
        "python": platform.python_version(),
    }
    summary = root / "scan_snapshots" / "last_summary.json"
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("meta.json", json.dumps(meta, indent=2))
        if summary.is_file():
            zf.write(summary, arcname="last_summary.json")
        if logs.is_dir():
            for log_file in logs.glob("*.log*"):
                if log_file.is_file() and log_file.stat().st_size < 20 * 1024 * 1024:
                    zf.write(log_file, arcname=f"logs/{log_file.name}")
    return out
