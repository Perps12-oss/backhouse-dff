"""
Empty Folder Engine

Detects empty directories and nested empty trees using stdlib only.

An "empty folder" is a directory that:
  - Contains no files (directly), AND
  - All its subdirectories are themselves empty (recursively)

Results are returned as DuplicateGroup objects with one file each
(path = the top-level empty dir). The "duplicate" concept maps to
"redundant empty container" — all empty dirs are deletable.
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Callable, List, Set

from cerebro.engines.base_engine import (
    BaseEngine,
    DuplicateFile,
    DuplicateGroup,
    EngineOption,
    ScanProgress,
    ScanState,
)


def _is_empty_tree(path: Path) -> bool:
    """Return True if path is a directory with no files anywhere beneath it."""
    try:
        for root, dirs, files in os.walk(path):
            if files:
                return False
        return True
    except PermissionError:
        return False


def _collect_empty_roots(base: Path, protected: Set[Path]) -> List[Path]:
    """
    Walk base bottom-up; collect dirs that are empty trees and are not
    covered by a parent already collected.
    """
    empty_roots: List[Path] = []
    covered: Set[Path] = set()

    try:
        for root, dirs, files in os.walk(base, topdown=False):
            p = Path(root)
            # Skip protected paths and children already covered
            if any(str(p).startswith(str(pr)) for pr in protected):
                continue
            if p in covered:
                continue
            # Skip the scan root itself
            if p == base:
                continue
            if _is_empty_tree(p):
                empty_roots.append(p)
                # Mark all children as covered
                for sub_root, _, _ in os.walk(p):
                    covered.add(Path(sub_root))
    except PermissionError:
        pass

    return empty_roots


class EmptyFolderEngine(BaseEngine):
    """
    Empty directory detection engine.

    Results are single-file groups where each "file" is an empty directory.
    The delete action removes the directory tree.
    """

    def __init__(self):
        super().__init__()
        self._results: List[DuplicateGroup] = []
        self._progress = ScanProgress(state=ScanState.IDLE)
        self._cancel_event = threading.Event()
        self._pause_event = threading.Event()

    def get_name(self) -> str:
        return "Empty Folder Finder"

    def get_mode_options(self) -> List[EngineOption]:
        return [
            EngineOption(
                name="include_hidden",
                display_name="Include Hidden Folders",
                type="bool", default=False,
                tooltip="Also look for hidden directories (starting with .)",
            ),
            EngineOption(
                name="min_depth",
                display_name="Minimum Folder Depth",
                type="int", default=1, min_value=1, max_value=20,
                tooltip="Ignore empty folders shallower than this depth",
            ),
        ]

    def configure(self, folders, protected, options) -> None:
        self._folders = folders
        self._protected = protected
        self._options = options

    def start(self, progress_callback: Callable[[ScanProgress], None]) -> None:
        self._cancel_event.clear()
        self._pause_event.clear()
        self._results = []
        self._state = ScanState.SCANNING
        self._run_scan(progress_callback)

    def _run_scan(self, cb: Callable[[ScanProgress], None]) -> None:
        include_hidden = self._options.get("include_hidden", False)
        min_depth      = self._options.get("min_depth", 1)
        protected_set: Set[Path] = set(self._protected)

        cb(ScanProgress(state=ScanState.SCANNING, files_total=0, current_file="Scanning for empty folders…"))

        all_empty: List[Path] = []
        scanned = 0

        for base in self._folders:
            if self._cancel_event.is_set():
                break
            while self._pause_event.is_set():
                time.sleep(0.1)

            roots = _collect_empty_roots(Path(base), protected_set)

            for ep in roots:
                if self._cancel_event.is_set():
                    break
                if not include_hidden:
                    # Skip if any component is hidden
                    if any(part.startswith(".") for part in ep.parts):
                        continue
                # Depth check relative to base
                try:
                    depth = len(ep.relative_to(base).parts)
                    if depth < min_depth:
                        continue
                except ValueError:
                    continue

                all_empty.append(ep)
                scanned += 1
                cb(ScanProgress(
                    state=ScanState.SCANNING,
                    files_scanned=scanned,
                    current_file=str(ep),
                ))

        if self._cancel_event.is_set():
            self._state = ScanState.CANCELLED
            cb(ScanProgress(state=ScanState.CANCELLED))
            return

        # Each empty folder becomes a 1-file group (it IS the duplicate/redundant item)
        for gid, ep in enumerate(all_empty):
            try:
                stat = ep.stat()
                df = DuplicateFile(
                    path=ep, size=0, modified=stat.st_mtime,
                    extension="<dir>", similarity=1.0,
                    metadata={"type": "empty_folder"},
                )
                df.is_keeper = False
                dg = DuplicateGroup(group_id=gid, files=[df])
                dg.reclaimable = 0  # empty dirs free no disk space
                self._results.append(dg)
            except OSError:
                pass

        self._state = ScanState.COMPLETED
        cb(ScanProgress(
            state=ScanState.COMPLETED,
            files_scanned=scanned,
            files_total=scanned,
            groups_found=len(self._results),
            duplicates_found=len(self._results),
            bytes_reclaimable=0,
        ))

    def pause(self) -> None:
        self._pause_event.set()
        self._state = ScanState.PAUSED

    def resume(self) -> None:
        self._pause_event.clear()
        self._state = ScanState.SCANNING

    def cancel(self) -> None:
        self._cancel_event.set()
        self._state = ScanState.CANCELLED

    def get_results(self) -> List[DuplicateGroup]:
        return self._results

    def get_progress(self) -> ScanProgress:
        return self._progress
