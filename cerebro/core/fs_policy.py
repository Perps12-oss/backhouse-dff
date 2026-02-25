# path: cerebro/core/fs_policy.py
"""
cerebro/core/fs_policy.py — Filesystem policy helpers

Purpose
- Centralizes rules for symlinks and hardlinks (safe deletion semantics).
- Provides cheap stat helpers used by discovery and deletion stages.

This module does NOT perform deletion; it only answers policy questions.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple


@dataclass(frozen=True, slots=True)
class SymlinkPolicy:
    """
    follow_symlinks:
      - False (default): do not traverse symlink targets when discovering files.
      - True: treat symlink targets as normal paths (risk: cycles, duplicates).
    """
    follow_symlinks: bool = False


@dataclass(frozen=True, slots=True)
class HardlinkPolicy:
    """
    allow_hardlink_deletes:
      - False (default): protect files with st_nlink > 1 from deletion.
      - True: allow deleting a hardlinked path (may not free space).
    """
    allow_hardlink_deletes: bool = False


@dataclass(frozen=True, slots=True)
class FileIdentity:
    """Stable identity fields for hardlink detection."""
    dev: int
    inode: int
    nlink: int

    @staticmethod
    def from_path(path: Path, *, follow_symlinks: bool = False) -> "FileIdentity":
        st = path.stat() if follow_symlinks else path.lstat()
        return FileIdentity(
            dev=int(getattr(st, "st_dev", 0) or 0),
            inode=int(getattr(st, "st_ino", 0) or 0),
            nlink=int(getattr(st, "st_nlink", 1) or 1),
        )

    def is_hardlinked(self) -> bool:
        return self.nlink > 1


def is_symlink(path: Path) -> bool:
    try:
        return path.is_symlink()
    except Exception:
        return False


def should_skip_for_discovery(path: Path, *, symlink_policy: SymlinkPolicy) -> bool:
    """
    Conservative: if follow_symlinks is False and this is a symlink, discovery should skip.
    """
    if not symlink_policy.follow_symlinks and is_symlink(path):
        return True
    return False


def should_block_delete(
    path: Path,
    *,
    hardlink_policy: HardlinkPolicy,
    follow_symlinks: bool = False,
) -> Optional[str]:
    """
    Returns a reason string if deletion should be blocked, else None.
    """
    try:
        if path.is_dir():
            return "is_directory"
        if not path.exists():
            return "missing"
        ident = FileIdentity.from_path(path, follow_symlinks=follow_symlinks)
        if ident.is_hardlinked() and not hardlink_policy.allow_hardlink_deletes:
            return f"hardlink_protected (st_nlink={ident.nlink})"
    except Exception as e:
        return f"stat_failed: {e}"
    return None


def derive_policies_from_request(request: object) -> Tuple[SymlinkPolicy, HardlinkPolicy]:
    """
    Reads optional fields from PipelineRequest without hard dependency on its exact schema.
    """
    follow_symlinks = bool(getattr(request, "follow_symlinks", False))
    allow_hardlinks = bool(getattr(request, "allow_hardlinks", False)) or bool(
        getattr(request, "include_hardlinks", False)
    ) or bool(getattr(request, "treat_hardlinks_as_duplicates", False))
    return SymlinkPolicy(follow_symlinks=follow_symlinks), HardlinkPolicy(allow_hardlink_deletes=allow_hardlinks)
