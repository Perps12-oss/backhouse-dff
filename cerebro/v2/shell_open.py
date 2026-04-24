"""
OS shell helpers (Recycle Bin / Trash) — no UI imports.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def open_system_recycle_bin() -> bool:
    """Open the OS recycle location so the user can restore deleted files (Blueprint §4, §7)."""
    if sys.platform == "win32":
        try:
            os.startfile("shell:RecycleBinFolder")  # type: ignore[attr-defined]
            return True
        except (OSError, AttributeError):
            try:
                subprocess.Popen(
                    ["explorer", "shell:RecycleBinFolder"],
                    shell=False,
                )
                return True
            except OSError:
                return False
    if sys.platform == "darwin":
        p = Path("~/.Trash").expanduser()
        try:
            subprocess.Popen(["open", str(p)])
            return True
        except OSError:
            return False
    # Linux: FreeDesktop trash
    t = Path("~/.local/share/Trash").expanduser()
    try:
        t.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(["xdg-open", str(t)])
        return True
    except OSError:
        return False
