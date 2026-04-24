"""
Path validation utilities for CEREBRO.

Provides helpers for validating local, network (UNC), and mapped-drive paths
before they are used as scan roots.  All functions are safe to call even when
the target path is offline or unreachable.
"""

from __future__ import annotations

from pathlib import Path


def validate_scan_path(path_str: str) -> tuple[bool, str]:
    """Validate a candidate scan path (local, UNC, or mapped drive).

    Returns ``(True, "")`` when the path exists and is a directory.
    Returns ``(False, reason)`` when unreachable or not a directory —
    the caller may still allow adding it to the scan list for offline shares.
    """
    p = Path(path_str)
    try:
        if not p.exists():
            return False, f"Path does not exist: {path_str}"
        if not p.is_dir():
            return False, f"Not a directory: {path_str}"
        return True, ""
    except (OSError, PermissionError, TimeoutError) as exc:
        return False, f"Cannot reach path: {exc}"
