"""
Similar Folder Detection Engine

Finds near-duplicate folder trees by comparing the set of file signatures
(filename+size by default, or partial SHA256 when use_content_hash is True)
within each folder and grouping folders whose Jaccard similarity exceeds a
configurable threshold.
"""

from __future__ import annotations

import hashlib
import os
import threading
import time
from pathlib import Path
from typing import Callable, Dict, List, Set

from cerebro.engines.base_engine import (
    BaseEngine,
    DuplicateFile,
    DuplicateGroup,
    EngineOption,
    ScanProgress,
    ScanState,
)
from cerebro.engines.image_formats import UnionFind


# ---------------------------------------------------------------------------
# Partial SHA256 helper
# ---------------------------------------------------------------------------

_PARTIAL_READ_BYTES = 65536  # 64 KB


def _partial_sha256(path: Path) -> str:
    """Read up to 64 KB from a file and return a hex digest."""
    try:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            h.update(fh.read(_PARTIAL_READ_BYTES))
        return h.hexdigest()
    except OSError:
        return ""


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class SimilarFolderEngine(BaseEngine):
    """
    Detects near-duplicate folder trees by comparing file-signature sets.

    For each folder: build a set of file signatures, then group folders
    whose pairwise Jaccard similarity >= similarity_threshold using
    Union-Find.
    """

    def __init__(self):
        super().__init__()
        self._results: List[DuplicateGroup] = []
        self._progress = ScanProgress(state=ScanState.IDLE)
        self._cancel_event = threading.Event()
        self._pause_event = threading.Event()

        self._default_options = {
            "similarity_threshold": 0.7,
            "min_files": 3,
            "use_content_hash": False,
            "include_hidden": False,
            "max_depth": 0,
        }

    # ------------------------------------------------------------------
    # BaseEngine interface
    # ------------------------------------------------------------------

    def get_name(self) -> str:
        return "Similar Folders"

    def get_mode_options(self) -> List[EngineOption]:
        return [
            EngineOption(
                name="similarity_threshold",
                display_name="Similarity Threshold",
                type="float",
                default=0.7,
                min_value=0.3,
                max_value=1.0,
                tooltip="Minimum Jaccard similarity (0.3–1.0) for two folders to be grouped.",
            ),
            EngineOption(
                name="min_files",
                display_name="Minimum Files per Folder",
                type="int",
                default=3,
                min_value=1,
                max_value=10000,
                tooltip="Folders with fewer files than this are ignored.",
            ),
            EngineOption(
                name="use_content_hash",
                display_name="Use Content Hash",
                type="bool",
                default=False,
                tooltip="Use partial SHA256 instead of filename+size for file signatures.",
            ),
            EngineOption(
                name="include_hidden",
                display_name="Include Hidden Files/Folders",
                type="bool",
                default=False,
                tooltip="Include hidden files and folders (names starting with '.').",
            ),
            EngineOption(
                name="max_depth",
                display_name="Maximum Depth",
                type="int",
                default=0,
                min_value=0,
                max_value=100,
                tooltip="Limit recursion depth. 0 = unlimited.",
            ),
        ]

    def configure(self, folders: List[Path], protected: List[Path],
                  options: dict) -> None:
        self._folders = [Path(f) for f in folders]
        self._protected = [Path(p) for p in protected]
        merged = self._default_options.copy()
        merged.update(options)
        self._options = merged

    def start(self, progress_callback: Callable[[ScanProgress], None]) -> None:
        self._cancel_event.clear()
        self._pause_event.clear()
        self._results = []
        self._state = ScanState.SCANNING
        self._progress = ScanProgress(state=ScanState.SCANNING)
        self._run_scan(progress_callback)

    def pause(self) -> None:
        self._pause_event.set()
        self._state = ScanState.PAUSED

    def resume(self) -> None:
        self._pause_event.clear()
        self._state = ScanState.SCANNING

    def cancel(self) -> None:
        self._cancel_event.set()
        self._pause_event.clear()
        self._state = ScanState.CANCELLED

    def get_results(self) -> List[DuplicateGroup]:
        return self._results

    def get_progress(self) -> ScanProgress:
        return self._progress

    # ------------------------------------------------------------------
    # Internal scan logic
    # ------------------------------------------------------------------

    def _run_scan(self, cb: Callable[[ScanProgress], None]) -> None:
        threshold = float(self._options.get("similarity_threshold", 0.7))
        min_files = int(self._options.get("min_files", 3))
        use_content_hash = bool(self._options.get("use_content_hash", False))
        include_hidden = bool(self._options.get("include_hidden", False))
        max_depth = int(self._options.get("max_depth", 0))

        protected_set: Set[Path] = set(self._protected)

        cb(ScanProgress(
            state=ScanState.SCANNING,
            stage="discovering",
            current_file="Walking folder tree…",
        ))

        # Step 1: build folder → set-of-signatures map
        folder_sigs: Dict[Path, Set[str]] = {}
        folder_sizes: Dict[Path, int] = {}  # total bytes in each folder
        folders_processed = 0

        for base in self._folders:
            if self._cancel_event.is_set():
                break
            self._walk_folder(
                base, base, max_depth, include_hidden, protected_set,
                use_content_hash, folder_sigs, folder_sizes,
            )

        if self._cancel_event.is_set():
            self._state = ScanState.CANCELLED
            cb(ScanProgress(state=ScanState.CANCELLED))
            return

        # Step 2: filter by min_files
        eligible: List[Path] = [
            p for p, sigs in folder_sigs.items() if len(sigs) >= min_files
        ]

        total_folders = len(eligible)
        cb(ScanProgress(
            state=ScanState.SCANNING,
            stage="comparing",
            files_total=total_folders,
            current_file=f"Comparing {total_folders} folders…",
        ))

        if total_folders == 0:
            self._state = ScanState.COMPLETED
            cb(ScanProgress(state=ScanState.COMPLETED, files_total=0, groups_found=0))
            return

        # Step 3: pairwise Jaccard + Union-Find grouping
        uf = UnionFind()
        for p in eligible:
            uf.add(p)

        for i in range(total_folders):
            if self._cancel_event.is_set():
                break

            while self._pause_event.is_set():
                time.sleep(0.05)

            folders_processed += 1
            if folders_processed % 25 == 0:
                self._progress = ScanProgress(
                    state=ScanState.SCANNING,
                    stage="comparing",
                    files_scanned=folders_processed,
                    files_total=total_folders,
                    current_file=str(eligible[i]),
                )
                cb(self._progress)

            sigs_a = folder_sigs[eligible[i]]
            for j in range(i + 1, total_folders):
                sigs_b = folder_sigs[eligible[j]]
                jaccard = self._jaccard(sigs_a, sigs_b)
                if jaccard >= threshold:
                    uf.union(eligible[i], eligible[j])

        if self._cancel_event.is_set():
            self._state = ScanState.CANCELLED
            cb(ScanProgress(state=ScanState.CANCELLED))
            return

        # Step 4: build DuplicateGroup results
        groups: List[DuplicateGroup] = []
        for gid, group_paths in enumerate(uf.get_groups()):
            files_list: List[DuplicateFile] = []
            for p in group_paths:
                folder_size = folder_sizes.get(p, 0)
                file_count = len(folder_sigs.get(p, set()))
                try:
                    stat = p.stat()
                    modified = stat.st_mtime
                except OSError:
                    modified = 0.0

                # Compute similarity relative to the largest folder in the group
                sigs_p = folder_sigs.get(p, set())
                # (similarity is set below after we know the reference)
                files_list.append(DuplicateFile(
                    path=p,
                    size=folder_size,
                    modified=modified,
                    extension="<dir>",
                    similarity=1.0,  # placeholder; updated below
                    metadata={
                        "file_count": file_count,
                        "similarity_pct": "100%",  # placeholder
                    },
                ))

            if len(files_list) < 2:
                continue

            # Compute pairwise similarity relative to the largest folder
            ref_idx = max(range(len(files_list)), key=lambda i: files_list[i].size)
            ref_path = group_paths[ref_idx]
            ref_sigs = folder_sigs.get(ref_path, set())

            for k, df in enumerate(files_list):
                p = group_paths[k]
                sigs_k = folder_sigs.get(p, set())
                j_val = self._jaccard(ref_sigs, sigs_k) if ref_sigs or sigs_k else 1.0
                df.similarity = j_val
                df.metadata["similarity_pct"] = f"{j_val * 100:.0f}%"
                df.is_keeper = (k == ref_idx)

            total_size = sum(df.size for df in files_list)
            keeper_size = files_list[ref_idx].size
            reclaimable = total_size - keeper_size

            dg = DuplicateGroup(
                group_id=gid,
                files=files_list,
                total_size=total_size,
                reclaimable=reclaimable,
                similarity_type="similar_folder",
            )
            groups.append(dg)

        self._results = groups
        self._state = ScanState.COMPLETED
        total_reclaimable = sum(g.reclaimable for g in groups)
        cb(ScanProgress(
            state=ScanState.COMPLETED,
            files_scanned=total_folders,
            files_total=total_folders,
            groups_found=len(groups),
            duplicates_found=sum(len(g.files) - 1 for g in groups),
            bytes_reclaimable=total_reclaimable,
        ))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _walk_folder(
        self,
        base: Path,
        current: Path,
        max_depth: int,
        include_hidden: bool,
        protected: Set[Path],
        use_content_hash: bool,
        folder_sigs: Dict[Path, Set[str]],
        folder_sizes: Dict[Path, int],
    ) -> None:
        """Recursively walk current, populating folder_sigs and folder_sizes."""
        if not current.is_dir():
            return

        # Depth check
        if max_depth > 0:
            try:
                depth = len(current.relative_to(base).parts)
            except ValueError:
                depth = 0
            if depth > max_depth:
                return

        # Hidden check
        if not include_hidden and current != base:
            if current.name.startswith("."):
                return

        # Protected check
        if any(current == p or str(current).startswith(str(p) + os.sep)
               for p in protected):
            return

        sigs: Set[str] = set()
        total_size = 0

        try:
            entries = list(current.iterdir())
        except PermissionError:
            return

        for entry in entries:
            if self._cancel_event.is_set():
                return
            try:
                if entry.is_file(follow_symlinks=False):
                    if not include_hidden and entry.name.startswith("."):
                        continue
                    stat = entry.stat()
                    size = stat.st_size
                    total_size += size
                    if use_content_hash:
                        digest = _partial_sha256(entry)
                        sig = digest if digest else f"{entry.name.lower()}:{size}"
                    else:
                        sig = f"{entry.name.lower()}:{size}"
                    sigs.add(sig)

                elif entry.is_dir(follow_symlinks=False):
                    self._walk_folder(
                        base, entry, max_depth, include_hidden, protected,
                        use_content_hash, folder_sigs, folder_sizes,
                    )
            except OSError:
                continue

        # Register this folder (even if empty — filtered later by min_files)
        folder_sigs[current] = sigs
        folder_sizes[current] = total_size

    @staticmethod
    def _jaccard(a: Set[str], b: Set[str]) -> float:
        """Compute Jaccard similarity between two sets."""
        if not a and not b:
            return 1.0
        intersection = len(a & b)
        union = len(a | b)
        return intersection / union if union > 0 else 0.0
