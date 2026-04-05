"""
Large File Engine

Finds the largest files on disk — informational tool, not a dedup engine.
Results are sorted by size descending and presented as single-file groups.

No delete by default — the "Move To" action from the toolbar applies.
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Callable, List

from cerebro.engines.base_engine import (
    BaseEngine,
    DuplicateFile,
    DuplicateGroup,
    EngineOption,
    ScanProgress,
    ScanState,
)

# Extensions to always skip (system files)
_SKIP_EXTENSIONS = {".sys", ".dll", ".drv", ".lnk"}


class LargeFileEngine(BaseEngine):
    """
    Large file finder.

    Collects all files above a size threshold, sorts by size descending,
    returns top-N as single-file DuplicateGroup objects so the standard
    treeview can display them.
    """

    def __init__(self):
        super().__init__()
        self._results: List[DuplicateGroup] = []
        self._progress = ScanProgress(state=ScanState.IDLE)
        self._cancel_event = threading.Event()
        self._pause_event = threading.Event()

    def get_name(self) -> str:
        return "Large File Finder"

    def get_mode_options(self) -> List[EngineOption]:
        return [
            EngineOption(
                name="min_size_mb",
                display_name="Minimum Size (MB)",
                type="int", default=100, min_value=1, max_value=100_000,
                tooltip="Only list files larger than this size",
            ),
            EngineOption(
                name="top_n",
                display_name="Show Top N Files",
                type="int", default=500, min_value=10, max_value=10_000,
                tooltip="Maximum number of files to show",
            ),
            EngineOption(
                name="skip_system",
                display_name="Skip System Files",
                type="bool", default=True,
                tooltip="Skip .sys, .dll, .drv files",
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
        min_bytes  = self._options.get("min_size_mb", 100) * 1024 * 1024
        top_n      = self._options.get("top_n", 500)
        skip_sys   = self._options.get("skip_system", True)

        cb(ScanProgress(state=ScanState.SCANNING, current_file="Collecting file sizes…"))

        candidates: List[DuplicateFile] = []
        scanned = 0

        for folder in self._folders:
            for root, _, files in os.walk(folder):
                if self._cancel_event.is_set():
                    break
                while self._pause_event.is_set():
                    time.sleep(0.1)

                for fname in files:
                    p = Path(root) / fname
                    if skip_sys and p.suffix.lower() in _SKIP_EXTENSIONS:
                        continue
                    try:
                        stat = p.stat()
                        if stat.st_size >= min_bytes:
                            candidates.append(DuplicateFile(
                                path=p,
                                size=stat.st_size,
                                modified=stat.st_mtime,
                                extension=p.suffix.lower(),
                                similarity=1.0,
                                is_keeper=False,
                            ))
                        scanned += 1
                        if scanned % 500 == 0:
                            cb(ScanProgress(
                                state=ScanState.SCANNING,
                                files_scanned=scanned,
                                current_file=str(p),
                            ))
                    except OSError:
                        pass

        if self._cancel_event.is_set():
            self._state = ScanState.CANCELLED
            cb(ScanProgress(state=ScanState.CANCELLED))
            return

        # Sort by size descending, take top N
        candidates.sort(key=lambda f: f.size, reverse=True)
        top_files = candidates[:top_n]

        # Wrap each file in its own group (informational — not actually duplicates)
        for gid, df in enumerate(top_files):
            dg = DuplicateGroup(group_id=gid, files=[df])
            dg.reclaimable = df.size  # user can reclaim by moving/deleting
            self._results.append(dg)

        self._state = ScanState.COMPLETED
        cb(ScanProgress(
            state=ScanState.COMPLETED,
            files_scanned=scanned,
            files_total=scanned,
            groups_found=len(self._results),
            duplicates_found=len(self._results),
            bytes_reclaimable=sum(g.reclaimable for g in self._results),
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
