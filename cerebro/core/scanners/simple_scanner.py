"""
SimpleScanner — Quick, minimal scanner for duplicate detection (Option B)
=========================================================================

This is a lightweight scanner used by the duplicate ScanWorker in "quick"
mode. It is deliberately much simpler than the advanced FileScanner:

- No multi-threading
- No system/venv/cache directory exclusion heuristics
- No complex strategies

It just:
  os.walk → apply basic filters → produce FileMetadata list.

This avoids the aggressive filters of the advanced scanner that were
skipping user folders (Desktop, Downloads, Documents, etc.).
"""

from __future__ import annotations

import os
import fnmatch
from pathlib import Path
from typing import List, Dict, Any

from cerebro.core.models import FileMetadata

from cerebro.core.utils import is_system_file  # reuse your existing helper


class SimpleScanner:
    """
    Minimal, synchronous scanner for duplicate detection.

    Contract:
        scan_directory(directory: Path, options: Dict[str, Any]) -> List[FileMetadata]

    The options dict is expected to contain (all optional):

        - min_file_size: int (bytes, 0 = no minimum)
        - max_file_size: int (bytes, 0 = no limit)
        - skip_hidden: bool
        - skip_system: bool
        - include_empty: bool
        - follow_symlinks: bool
        - include_patterns: List[str] (e.g. ["*.jpg", "*.png"])
        - exclude_patterns: List[str]
    """

    def __init__(self) -> None:
        # Very small stats used only for debugging / introspection.
        self.stats = {
            "files_found": 0,
            "total_size": 0,
        }

    # ------------------------------------------------------------------
    # NOTE: This is the ONLY entry-point ScanWorker uses.
    # ------------------------------------------------------------------
    def scan_directory(self, directory: Path, options: Dict[str, Any], *, cancel_event: Any = None) -> List[FileMetadata]:
        directory = Path(directory)
        results: List[FileMetadata] = []

        # -----------------------------
        # 1. Sanitize numeric filters
        # -----------------------------
        raw_min = options.get("min_file_size", 0)
        min_size = self._to_int_or_default(raw_min, 0)

        raw_max = options.get("max_file_size", 0)
        max_size = self._to_int_or_default(raw_max, 0)
        if max_size < 0:
            max_size = 0  # treat negative as "no limit"

        # -----------------------------
        # 2. Behaviour flags
        # -----------------------------
        skip_hidden = bool(options.get("skip_hidden", False))
        skip_system = bool(options.get("skip_system", False))
        include_empty = bool(options.get("include_empty", False))
        follow_symlinks = bool(options.get("follow_symlinks", False))

        include_patterns = options.get("include_patterns") or []
        exclude_patterns = options.get("exclude_patterns") or []
        allowed_extensions = options.get("allowed_extensions") or options.get("file_types") or []

        # Media-type / extension filter: build include patterns from extensions
        if allowed_extensions:
            ext_patterns = []
            for e in allowed_extensions:
                e = (e if e.startswith(".") else f".{e}").lower()
                ext_patterns.append(f"*{e}")
            if ext_patterns:
                include_patterns = ext_patterns
        # If no include patterns given, accept everything
        elif not include_patterns:
            include_patterns = ["*"]

        # -----------------------------
        # 3. Walk the tree
        # -----------------------------
        for root, dirs, files in os.walk(directory, followlinks=follow_symlinks):
            root_path = Path(root)

            for name in files:
                if cancel_event is not None:
                    try:
                        if bool(getattr(cancel_event, 'is_set')()):
                            break
                    except Exception:
                        pass
                file_path = root_path / name
                file_name_lower = name.lower()

                # Hidden files (very simple rule: dot-prefixed)
                if skip_hidden and file_name_lower.startswith("."):
                    continue

                # System files via your helper
                if skip_system and is_system_file(file_path):
                    continue

                # Include / exclude patterns
                if include_patterns:
                    if not any(fnmatch.fnmatch(name, pat) for pat in include_patterns):
                        continue

                if exclude_patterns:
                    if any(fnmatch.fnmatch(name, pat) for pat in exclude_patterns):
                        continue

                # Now try to read basic metadata
                meta = FileMetadata.from_path(file_path)
                if not meta:
                    continue

                # Empty-file handling
                if not include_empty and meta.size == 0:
                    continue

                # Size filters
                if meta.size < min_size:
                    continue
                if max_size > 0 and meta.size > max_size:
                    continue

                results.append(meta)

        # -----------------------------
        # 4. Stats update
        # -----------------------------
        self.stats["files_found"] = len(results)
        self.stats["total_size"] = sum(f.size for f in results)

        return results


def scan_request(self, request: "PipelineRequest", *, cancel_event: Any = None) -> List[FileMetadata]:
    """Convenience: scan the first root in request using request-like options."""
    roots = getattr(request, "roots", None) or []
    if not roots:
        root = getattr(request, "scan_root", None)
        roots = [root] if root else []
    if not roots:
        return []

    options = {
        "min_file_size": int(getattr(request, "min_size_bytes", 0) or 0),
        "max_file_size": 0,
        "skip_hidden": not bool(getattr(request, "include_hidden", False)),
        "skip_system": True,
        "include_empty": False,
        "follow_symlinks": bool(getattr(request, "follow_symlinks", False)),
    }
    return self.scan_directory(Path(roots[0]), options, cancel_event=cancel_event)
    # ------------------------------------------------------------------
    # INTERNAL HELPERS
    # ------------------------------------------------------------------
    def _to_int_or_default(self, value: Any, default: int) -> int:
        """Convert to int safely, falling back to default on error."""
        if isinstance(value, (int, float)):
            return int(value)
        if isinstance(value, str):
            value = value.strip()
            if not value:
                return default
            try:
                return int(value)
            except ValueError:
                return default
        return default
