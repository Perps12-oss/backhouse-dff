"""
File Deduplication Engine

Detects exact duplicate files using byte-level hashing (SHA256/Blake3/MD5).
Implements the BaseEngine interface with multi-stage pipeline:
1. Size pre-filter (same size required for dupes)
2. Partial hash (first N + last N bytes)
3. Full hash (authoritative)
"""

from __future__ import annotations

import hashlib
import os
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, List, Optional

from cerebro.engines.base_engine import (
    BaseEngine,
    ScanProgress,
    ScanState,
    DuplicateGroup,
    DuplicateFile,
    EngineOption
)
from cerebro.engines.hash_cache import HashCache


# Hash algorithm support
SUPPORTED_ALGORITHMS = ["sha256", "blake3", "md5", "sha1"]

# Partial hash configuration
PARTIAL_HASH_HEAD = 64 * 1024  # First 64KB
PARTIAL_HASH_TAIL = 64 * 1024  # Last 64KB


class FileDedupEngine(BaseEngine):
    """
    Exact file duplicate detection engine.

    Uses a multi-stage hashing pipeline for optimal performance:
    1. Group files by size (instant elimination of unique sizes)
    2. Compute partial hashes (first + last 64KB) for size groups
    3. Compute full hashes only for partial hash matches
    4. Return duplicate groups with keeper selection
    """

    def __init__(self, cache_path: Optional[Path] = None):
        """
        Initialize the file dedup engine.

        Args:
            cache_path: Path to hash cache database.
        """
        super().__init__()
        self._cache = HashCache(cache_path) if cache_path else None
        self._results: List[DuplicateGroup] = []
        self._progress = ScanProgress(state=ScanState.IDLE)
        self._cancel_event = threading.Event()
        self._pause_event = threading.Event()
        self._scan_thread: Optional[threading.Thread] = None
        self._start_time: float = 0
        self._worker_pool: Optional[ThreadPoolExecutor] = None

        # Default options
        self._default_options = {
            "hash_algorithm": "sha256",
            "min_size_bytes": 0,
            "max_size_bytes": 0,
            "skip_extensions": [".sys", ".dll", ".tmp", ".exe", ".msi"],
            "include_hidden": False,
            "follow_symlinks": False,
        }

    def get_name(self) -> str:
        """Return engine name."""
        return "File Deduplication"

    def get_mode_options(self) -> List[EngineOption]:
        """Return configurable options for the UI."""
        return [
            EngineOption(
                name="hash_algorithm",
                display_name="Hash Algorithm",
                type="choice",
                default="sha256",
                choices=["sha256", "blake3", "md5", "sha1"],
                tooltip="Algorithm used for file hashing. SHA256 is most secure."
            ),
            EngineOption(
                name="min_size_bytes",
                display_name="Minimum File Size",
                type="int",
                default=0,
                min_value=0,
                max_value=10 * 1024 * 1024 * 1024,  # 10GB
                tooltip="Skip files smaller than this size (bytes). 0 = no minimum."
            ),
            EngineOption(
                name="max_size_bytes",
                display_name="Maximum File Size",
                type="int",
                default=0,
                min_value=0,
                max_value=100 * 1024 * 1024 * 1024,  # 100GB
                tooltip="Skip files larger than this size (bytes). 0 = no maximum."
            ),
            EngineOption(
                name="include_hidden",
                display_name="Include Hidden Files",
                type="bool",
                default=False,
                tooltip="Include hidden files and directories in scan."
            ),
            EngineOption(
                name="follow_symlinks",
                display_name="Follow Symbolic Links",
                type="bool",
                default=False,
                tooltip="Follow symbolic links instead of treating them as files."
            ),
        ]

    def configure(self, folders: List[Path], protected: List[Path],
                 options: dict) -> None:
        """Configure scan parameters."""
        self._folders = [Path(f) for f in folders]
        self._protected = [Path(p) for p in protected]
        # Merge with defaults
        merged = self._default_options.copy()
        merged.update(options)
        self._options = merged

    def start(self, progress_callback: Callable[[ScanProgress], None]) -> None:
        """Start scanning in a background thread."""
        self._cancel_event.clear()
        self._pause_event.clear()
        self._progress = ScanProgress(state=ScanState.SCANNING)
        self._results = []
        self._start_time = time.time()

        # Create worker pool
        max_workers = min(32, (os.cpu_count() or 4) * 4)
        self._worker_pool = ThreadPoolExecutor(max_workers=max_workers)

        # Start scan thread
        self._scan_thread = threading.Thread(
            target=self._run_scan,
            args=(progress_callback,),
            daemon=True
        )
        self._scan_thread.start()

    def pause(self) -> None:
        """Pause the scan."""
        if self._state == ScanState.SCANNING:
            self._pause_event.set()
            self._state = ScanState.PAUSED
            logger.info("Scan paused")

    def resume(self) -> None:
        """Resume the scan."""
        if self._state == ScanState.PAUSED:
            self._pause_event.clear()
            self._state = ScanState.SCANNING
            logger.info("Scan resumed")

    def cancel(self) -> None:
        """Cancel the scan."""
        self._cancel_event.set()
        self._pause_event.clear()  # Unpause if paused
        self._state = ScanState.CANCELLED

    def get_results(self) -> List[DuplicateGroup]:
        """Return scan results."""
        return self._results

    def get_progress(self) -> ScanProgress:
        """Return current progress."""
        return self._progress

    # ========================================================================
    # SCAN PIPELINE
    # ========================================================================

    def _run_scan(self, progress_callback: Callable[[ScanProgress], None]) -> None:
        """Main scan execution in background thread."""
        try:
            # Stage 1: Discover files
            self._update_progress(progress_callback, "Discovering files...")
            files = self._discover_files()

            if self._cancel_event.is_set():
                self._state = ScanState.CANCELLED
                return

            if not files:
                self._progress = ScanProgress(
                    state=ScanState.COMPLETED,
                    files_scanned=0,
                    elapsed_seconds=time.time() - self._start_time
                )
                progress_callback(self._progress)
                return

            # Stage 2: Group by size
            self._update_progress(progress_callback, "Grouping by size...")
            size_groups = self._group_by_size(files)

            if self._cancel_event.is_set():
                self._state = ScanState.CANCELLED
                return

            # Stage 3: Partial hash for size groups
            self._update_progress(progress_callback, "Computing partial hashes...")
            partial_groups = self._compute_partial_hashes(size_groups, progress_callback)

            if self._cancel_event.is_set():
                self._state = ScanState.CANCELLED
                return

            # Stage 4: Full hash for matches
            self._update_progress(progress_callback, "Computing full hashes...")
            hash_groups = self._compute_full_hashes(partial_groups, progress_callback)

            if self._cancel_event.is_set():
                self._state = ScanState.CANCELLED
                return

            # Stage 5: Build result groups
            self._update_progress(progress_callback, "Building results...")
            self._build_results(hash_groups)

            # Final update
            elapsed = time.time() - self._start_time
            self._progress = ScanProgress(
                state=ScanState.COMPLETED,
                files_scanned=len(files),
                duplicates_found=sum(len(g.files) for g in self._results),
                groups_found=len(self._results),
                bytes_reclaimable=sum(g.reclaimable for g in self._results),
                elapsed_seconds=elapsed
            )
            self._state = ScanState.COMPLETED
            progress_callback(self._progress)

        except Exception as e:
            import traceback
            traceback.print_exc()
            self._progress = ScanProgress(
                state=ScanState.ERROR,
                current_file=f"Error: {str(e)}"
            )
            self._state = ScanState.ERROR
            progress_callback(self._progress)
        finally:
            # Cleanup
            if self._worker_pool:
                self._worker_pool.shutdown(wait=False)

    def _update_progress(self, callback: Callable[[ScanProgress], None],
                       current_file: str = "") -> None:
        """Send progress update to callback."""
        if callback:
            self._progress.current_file = current_file
            self._progress.elapsed_seconds = time.time() - self._start_time
            callback(self._progress)

    def _check_pause(self) -> None:
        """Check if paused and wait if so."""
        while self._pause_event.is_set() and not self._cancel_event.is_set():
            time.sleep(0.1)

    def _is_cancelled(self) -> bool:
        """Check if scan was cancelled."""
        return self._cancel_event.is_set()

    # ========================================================================
    # STAGE 1: FILE DISCOVERY
    # ========================================================================

    def _discover_files(self) -> List[Path]:
        """Discover all files in the specified folders."""
        files = []
        min_size = self._options.get("min_size_bytes", 0)
        max_size = self._options.get("max_size_bytes", 0)
        include_hidden = self._options.get("include_hidden", False)
        follow_symlinks = self._options.get("follow_symlinks", False)

        for folder in self._folders:
            if not folder.exists():
                continue

            for root, dirs, filenames in os.walk(
                folder,
                topdown=True,
                followlinks=follow_symlinks
            ):
                # Check protected folders
                root_path = Path(root)
                if any(root_path.is_relative_to(p) for p in self._protected):
                    dirs[:] = []  # Don't descend into protected folders
                    continue

                # Filter hidden directories
                if not include_hidden:
                    dirs[:] = [d for d in dirs if not d.startswith(".")]

                for filename in filenames:
                    if self._is_cancelled():
                        return files

                    # Filter hidden files
                    if not include_hidden and filename.startswith("."):
                        continue

                    filepath = root_path / filename

                    try:
                        stat = filepath.stat(follow_symlinks=follow_symlinks)
                        size = stat.st_size

                        # Size filter
                        if min_size and size < min_size:
                            continue
                        if max_size and size > max_size:
                            continue

                        files.append(filepath)

                    except (OSError, PermissionError):
                        # Skip unreadable files
                        continue

        return files

    # ========================================================================
    # STAGE 2: GROUP BY SIZE
    # ========================================================================

    def _group_by_size(self, files: List[Path]) -> dict[int, List[Path]]:
        """Group files by size. Files with unique sizes cannot be duplicates."""
        size_groups: dict[int, List[Path]] = {}

        for file in files:
            if self._is_cancelled():
                break

            self._check_pause()

            try:
                size = file.stat().st_size
                if size not in size_groups:
                    size_groups[size] = []
                size_groups[size].append(file)
            except OSError:
                continue

        # Filter to only groups with 2+ files
        return {s: files for s, files in size_groups.items() if len(files) >= 2}

    # ========================================================================
    # STAGE 3: PARTIAL HASH
    # ========================================================================

    def _compute_partial_hashes(
        self,
        size_groups: dict[int, List[Path]],
        progress_callback: Callable[[ScanProgress], None]
    ) -> dict[str, List[Path]]:
        """Compute partial hashes (head + tail) for size groups."""
        hash_groups: dict[str, List[Path]] = {}
        total_files = sum(len(files) for files in size_groups.values())
        processed = 0

        # Flatten files to hash
        files_to_hash = []
        for files in size_groups.values():
            files_to_hash.extend(files)

        # Submit hashing tasks
        futures = {}
        for file in files_to_hash:
            self._check_pause()
            if self._is_cancelled():
                break

            future = self._worker_pool.submit(
                self._compute_partial_hash,
                file
            )
            futures[future] = file

        # Collect results
        for future in as_completed(futures):
            if self._is_cancelled():
                break

            self._check_pause()

            try:
                file, partial_hash = future.result(timeout=10)
                if partial_hash:
                    if partial_hash not in hash_groups:
                        hash_groups[partial_hash] = []
                    hash_groups[partial_hash].append(file)

                processed += 1
                if processed % 50 == 0:
                    self._progress.files_scanned = processed
                    self._progress.files_total = total_files
                    self._update_progress(progress_callback, str(file))

            except Exception:
                processed += 1
                continue

        # Filter to groups with 2+ files
        return {h: files for h, files in hash_groups.items() if len(files) >= 2}

    def _compute_partial_hash(self, file: Path) -> tuple[Path, Optional[str]]:
        """Compute partial hash (head + tail) for a single file."""
        try:
            # Check cache first
            if self._cache:
                mtime = file.stat().st_mtime
                size = file.stat().st_size
                cached = self._cache.get(file, mtime, size, "partial")
                if cached:
                    return file, cached

            # Compute partial hash
            hasher = hashlib.sha256()
            size = 0

            with open(file, 'rb') as f:
                # Read head
                head_data = f.read(PARTIAL_HASH_HEAD)
                hasher.update(head_data)
                size = len(head_data)

                # Read tail if file is large enough
                if file.stat().st_size > PARTIAL_HASH_HEAD + PARTIAL_HASH_TAIL:
                    f.seek(-PARTIAL_HASH_TAIL, 2)
                    tail_data = f.read(PARTIAL_HASH_TAIL)
                    hasher.update(tail_data)
                    size += len(tail_data)

            hash_value = hasher.hexdigest()

            # Cache result
            if self._cache:
                mtime = file.stat().st_mtime
                file_size = file.stat().st_size
                self._cache.set(file, mtime, file_size, "partial", hash_value)

            return file, hash_value

        except Exception:
            return file, None

    # ========================================================================
    # STAGE 4: FULL HASH
    # ========================================================================

    def _compute_full_hashes(
        self,
        partial_groups: dict[str, List[Path]],
        progress_callback: Callable[[ScanProgress], None]
    ) -> dict[str, List[Path]]:
        """Compute full hashes for partial hash matches."""
        hash_groups: dict[str, List[Path]] = {}
        total_files = sum(len(files) for files in partial_groups.values())
        processed = 0

        # Flatten files to hash
        files_to_hash = []
        for files in partial_groups.values():
            files_to_hash.extend(files)

        algorithm = self._options.get("hash_algorithm", "sha256")

        # Submit hashing tasks
        futures = {}
        for file in files_to_hash:
            self._check_pause()
            if self._is_cancelled():
                break

            future = self._worker_pool.submit(
                self._compute_full_hash,
                file,
                algorithm
            )
            futures[future] = file

        # Collect results
        for future in as_completed(futures):
            if self._is_cancelled():
                break

            self._check_pause()

            try:
                file, full_hash = future.result(timeout=60)
                if full_hash:
                    if full_hash not in hash_groups:
                        hash_groups[full_hash] = []
                    hash_groups[full_hash].append(file)

                processed += 1
                if processed % 10 == 0:
                    self._progress.files_scanned = processed
                    self._progress.files_total = total_files
                    self._update_progress(progress_callback, str(file))

            except Exception:
                processed += 1
                continue

        # Filter to groups with 2+ files
        return {h: files for h, files in hash_groups.items() if len(files) >= 2}

    def _compute_full_hash(self, file: Path, algorithm: str) -> tuple[Path, Optional[str]]:
        """Compute full hash for a single file."""
        try:
            # Check cache first
            if self._cache:
                mtime = file.stat().st_mtime
                size = file.stat().st_size
                cached = self._cache.get(file, mtime, size, algorithm)
                if cached:
                    return file, cached

            # Compute full hash
            if algorithm == "blake3":
                try:
                    import blake3
                    hasher = blake3.blake3()
                    with open(file, 'rb') as f:
                        for chunk in iter(lambda: f.read(65536), b""):
                            hasher.update(chunk)
                    hash_value = hasher.hexdigest()
                except ImportError:
                    # Fallback to sha256 if blake3 not available
                    hasher = hashlib.sha256()
                    with open(file, 'rb') as f:
                        for chunk in iter(lambda: f.read(65536), b""):
                            hasher.update(chunk)
                    hash_value = hasher.hexdigest()
            else:
                hasher = hashlib.new(algorithm)
                with open(file, 'rb') as f:
                    for chunk in iter(lambda: f.read(65536), b""):
                        hasher.update(chunk)
                hash_value = hasher.hexdigest()

            # Cache result
            if self._cache:
                mtime = file.stat().st_mtime
                file_size = file.stat().st_size
                self._cache.set(file, mtime, file_size, algorithm, hash_value)

            return file, hash_value

        except Exception:
            return file, None

    # ========================================================================
    # STAGE 5: BUILD RESULTS
    # ========================================================================

    def _build_results(self, hash_groups: dict[str, List[Path]]) -> None:
        """Build DuplicateGroup results from hash groups."""
        self._results = []

        for group_id, files in enumerate(hash_groups.values(), 1):
            if self._is_cancelled():
                break

            # Build DuplicateFile objects
            dup_files = []
            for file in files:
                try:
                    stat = file.stat()
                    ext = file.suffix.lower()

                    # Check if file is in protected folder
                    is_protected = any(
                        file.is_relative_to(p) for p in self._protected
                    )

                    dup_files.append(DuplicateFile(
                        path=file,
                        size=stat.st_size,
                        modified=stat.st_mtime,
                        extension=ext,
                        is_keeper=False,  # Will be set by keeper selection
                        similarity=1.0,  # Exact match
                        metadata={"is_protected": is_protected}
                    ))
                except OSError:
                    continue

            if len(dup_files) < 2:
                continue

            # Keeper selection: largest file is keeper
            largest_size = max(f.size for f in dup_files)
            for f in dup_files:
                if f.size == largest_size:
                    f.is_keeper = True
                    break

            # Create group
            self._results.append(DuplicateGroup(
                group_id=group_id,
                files=dup_files,
                similarity_type="exact"
            ))


# Simple logger fallback
logger = __import__('logging').getLogger(__name__)
