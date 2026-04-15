# cerebro/services/device_identity.py
"""
Device identity for v6.1 scale foundation (Phase 7C).
Stable device ID and type (internal/removable/network) for a root path.
Phase 7A uses path-based fallback; this module allows platform-specific overrides.
"""

from __future__ import annotations

import hashlib
import os
import sys
from typing import Tuple


def get_device_id(root_path: str) -> str:
    """Return stable device ID for root. Uses platform APIs when available; else path hash."""
    if not root_path:
        return ""
    canonical = os.path.normpath(os.path.abspath(root_path))
    if sys.platform == "win32":
        try:
            return _windows_volume_guid(canonical)
        except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
            pass
    if sys.platform == "darwin":
        try:
            return _macos_device_id(canonical)
        except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
            pass
    if sys.platform.startswith("linux"):
        try:
            return _linux_device_id(canonical)
        except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
            pass
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def get_device_type(root_path: str) -> str:
    """Return 'internal' | 'removable' | 'network'."""
    if not root_path:
        return "internal"
    if sys.platform == "win32":
        try:
            return _windows_drive_type(root_path)
        except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
            pass
    return "internal"


def _windows_volume_guid(path: str) -> str:
    """Windows: try Volume GUID via ctypes."""
    import ctypes
    from ctypes import wintypes
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    volume = path[:3] if len(path) >= 3 and path[1:3] in (":\\", ":/") else path
    if not volume.endswith("\\"):
        volume = volume + "\\"
    buf = ctypes.create_unicode_buffer(50)
    if kernel32.GetVolumeNameForVolumeMountPointW(volume, buf):
        guid = buf.value.strip("\\").split("}")[0].split("{")[-1]
        if guid:
            return hashlib.sha256(guid.encode()).hexdigest()[:16]
    raise RuntimeError("GetVolumeNameForVolumeMountPointW failed")


def _windows_drive_type(path: str) -> str:
    """Windows: DRIVE_REMOVABLE=2, DRIVE_FIXED=3, DRIVE_REMOTE=4."""
    import ctypes
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    drive = path[:3] if len(path) >= 3 and path[1:3] in (":\\", ":/") else path
    if not drive.endswith("\\"):
        drive = drive + "\\"
    kind = kernel32.GetDriveTypeW(drive)
    if kind == 2:
        return "removable"
    if kind == 4:
        return "network"
    return "internal"


def _macos_device_id(path: str) -> str:
    """macOS: use st_dev + path for a stable id (volume id)."""
    try:
        st = os.stat(path)
        dev = getattr(st, "st_dev", 0)
        return hashlib.sha256(f"{dev}:{path}".encode()).hexdigest()[:16]
    except OSError:
        raise


def _linux_device_id(path: str) -> str:
    """Linux: try /dev/disk/by-uuid for the mount; else st_dev hash."""
    try:
        real = os.path.realpath(path)
        if "/by-uuid/" in real:
            uuid = real.split("/by-uuid/")[-1].split("/")[0]
            if uuid:
                return hashlib.sha256(uuid.encode()).hexdigest()[:16]
        st = os.stat(path)
        dev = getattr(st, "st_dev", 0)
        return hashlib.sha256(f"{dev}:{path}".encode()).hexdigest()[:16]
    except OSError:
        raise
