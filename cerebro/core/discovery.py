# path: cerebro/core/discovery.py
"""
cerebro/core/discovery.py — CEREBRO File Discovery Engine (PySide6-safe, UI-agnostic)

Responsibilities
- Fast filesystem traversal (os.scandir)
- Early pruning: hidden, extensions, excluded dirs, min size
- Cancellation-aware
- Deterministic ordering in validation mode
- No exceptions leak upward (skips unreadable entries)
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, List, Optional, Protocol


class CancelToken(Protocol):
    def is_cancelled(self) -> bool: ...


@dataclass(frozen=True, slots=True)
class DiscoveredFile:
    path: Path
    size: int
    mtime_ns: int


class FileDiscovery:
    def __init__(self, logger: Any = None):
        self._logger = logger

    def discover_files(self, request: Any, cancel: CancelToken) -> List[DiscoveredFile]:
        roots = list(getattr(request, "roots", []) or [])
        if not roots:
            root = getattr(request, "root", None) or getattr(request, "scan_root", None)
            if root:
                roots = [Path(root)]

        include_hidden = bool(getattr(request, "include_hidden", False))
        follow_symlinks = bool(getattr(request, "follow_symlinks", False))
        min_size = int(getattr(request, "min_size_bytes", 0) or 0)
        validation_mode = bool(getattr(request, "validation_mode", False))

        allowed_exts = getattr(request, "allowed_extensions", None)
        if allowed_exts is None:
            allowed_exts = (getattr(request, "options", {}) or {}).get("allowed_extensions")
        allowed_exts = [e.lower() for e in (allowed_exts or [])] or None

        exclude_dirs = getattr(request, "exclude_dirs", None)
        if exclude_dirs is None:
            exclude_dirs = (getattr(request, "options", {}) or {}).get("exclude_dirs")
        exclude_dirs = set(exclude_dirs or [])

        out: List[DiscoveredFile] = []
        for root in roots:
            out.extend(
                self._scan_root(
                    Path(root),
                    cancel=cancel,
                    include_hidden=include_hidden,
                    follow_symlinks=follow_symlinks,
                    allowed_exts=allowed_exts,
                    exclude_dirs=exclude_dirs,
                    min_size=min_size,
                    validation_mode=validation_mode,
                )
            )

        # Deterministic ordering if requested
        if validation_mode:
            out.sort(key=lambda f: str(f.path).lower())

        return out

    def _scan_root(
        self,
        root: Path,
        *,
        cancel: CancelToken,
        include_hidden: bool,
        follow_symlinks: bool,
        allowed_exts: Optional[List[str]],
        exclude_dirs: set[str],
        min_size: int,
        validation_mode: bool,
    ) -> List[DiscoveredFile]:
        stack: List[Path] = [root]
        discovered: List[DiscoveredFile] = []

        while stack:
            if cancel.is_cancelled():
                break

            cur = stack.pop()
            try:
                with os.scandir(cur) as it:
                    entries = list(it)
            except Exception:
                continue

            # Deterministic directory traversal if validation_mode
            if validation_mode:
                entries.sort(key=lambda e: e.name.lower())

            for entry in entries:
                if cancel.is_cancelled():
                    break

                name = entry.name

                # hidden
                if not include_hidden and name.startswith("."):
                    continue

                try:
                    if entry.is_dir(follow_symlinks=follow_symlinks):
                        if name in exclude_dirs:
                            continue
                        stack.append(Path(entry.path))
                        continue

                    if not entry.is_file(follow_symlinks=follow_symlinks):
                        continue

                    ext = os.path.splitext(name)[1].lower()
                    if allowed_exts and ext not in allowed_exts:
                        continue

                    st = entry.stat(follow_symlinks=follow_symlinks)
                    size = int(getattr(st, "st_size", 0))
                    if size < min_size:
                        continue

                    mtime_ns = int(
                        getattr(st, "st_mtime_ns", int(float(getattr(st, "st_mtime", 0.0)) * 1_000_000_000))
                    )

                    discovered.append(DiscoveredFile(path=Path(entry.path), size=size, mtime_ns=mtime_ns))
                except Exception:
                    # unreadable entry (permissions, broken symlink, etc.)
                    continue

        return discovered
