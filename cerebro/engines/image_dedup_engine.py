"""
Image Deduplication Engine

Detects similar images using perceptual hashing (pHash, dHash).
Implements BaseEngine interface with multi-stage pipeline:
1. Filter by image extensions
2. Load and resize images
3. Compute pHash (perceptual hash)
4. Compute dHash (difference hash)
5. Group by hash similarity threshold
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, List, Optional

try:
    from PIL import Image
    from imagehash import phash, dhash
    HAS_PIL = True
except ImportError:
    HAS_PIL = False
    Image = None
    phash = None
    dhash = None

from cerebro.engines.base_engine import (
    BaseEngine,
    ScanProgress,
    ScanState,
    DuplicateGroup,
    DuplicateFile,
    EngineOption
)
from cerebro.engines.hash_cache import HashCache

logger = logging.getLogger(__name__)


# Supported image extensions
IMAGE_EXTENSIONS = {
    '.jpg', '.jpeg', '.jpe',
    '.png', '.gif', '.bmp', '.tiff', '.tif', '.webp',
    '.heic', '.heif', '.cr2', '.cr3', '.nef',
    '.arw', '.dng', '.orf', '.rw2', '.pef', '.raf', '.sr2'
}

# Hash sizes for perceptual hashing
PHASH_SIZE = 8  # 8x8 grid for pHash
DHASH_SIZE = 8  # 8x8 grid for dHash


class ImageDedupEngine(BaseEngine):
    """
    Image deduplication engine using perceptual hashing.

    Uses:
    - pHash (perceptual hash) for detecting visually similar images
    - dHash (difference hash) for detecting exact or near-duplicates

    Pipeline:
    1. Filter by image extensions
    2. Load image and extract basic info
    3. Compute pHash (perceptual hash)
    4. Compute dHash (difference hash)
    5. Group by hash similarity
    """

    def __init__(self, cache_path: Optional[Path] = None):
        """
        Initialize image dedup engine.

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
            "phash_threshold": 5,
            "dhash_threshold": 3,
            "min_resolution": 0,
            "min_width": 0,
            "min_height": 0,
            "max_resolution": 0,
            "include_hidden": False,
        }

    def get_name(self) -> str:
        """Return engine name."""
        return "Image Deduplication"

    def get_mode_options(self) -> List[EngineOption]:
        """Return configurable options for UI."""
        return [
            EngineOption(
                name="phash_threshold",
                display_name="pHash Threshold",
                type="int",
                default=5,
                min_value=0,
                max_value=64,
                tooltip="Lower = more sensitive. Images with pHash difference <= this are grouped."
            ),
            EngineOption(
                name="dhash_threshold",
                display_name="dHash Threshold",
                type="int",
                default=3,
                min_value=0,
                max_value=64,
                tooltip="Lower = more sensitive. Images with dHash difference <= this are grouped."
            ),
            EngineOption(
                name="min_resolution",
                display_name="Minimum Resolution",
                type="int",
                default=0,
                min_value=0,
                max_value=999999,
                tooltip="Minimum total pixels (width * height). 0 = no minimum."
            ),
            EngineOption(
                name="min_width",
                display_name="Minimum Width",
                type="int",
                default=0,
                min_value=0,
                max_value=999999,
                tooltip="Minimum image width in pixels. 0 = no minimum."
            ),
            EngineOption(
                name="min_height",
                display_name="Minimum Height",
                type="int",
                default=0,
                min_value=0,
                max_value=999999,
                tooltip="Minimum image height in pixels. 0 = no minimum."
            ),
            EngineOption(
                name="max_resolution",
                display_name="Maximum Resolution",
                type="int",
                default=0,
                min_value=0,
                max_value=999999,
                tooltip="Maximum total pixels (width * height). 0 = no maximum."
            ),
            EngineOption(
                name="include_hidden",
                display_name="Include Hidden Files",
                type="bool",
                default=False,
                tooltip="Include hidden images in scan."
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
        if not HAS_PIL:
            error_msg = "PIL (Pillow) and imagehash packages are required.\n"
            error_msg += "Install with: pip install Pillow imagehash"
            self._progress = ScanProgress(state=ScanState.ERROR, current_file=error_msg)
            progress_callback(self._progress)
            return

        self._cancel_event.clear()
        self._pause_event.clear()
        self._progress = ScanProgress(state=ScanState.SCANNING)
        self._results = []
        self._start_time = time.time()

        # Create worker pool
        max_workers = min(32, (os.cpu_count() or 4) * 2)
        self._worker_pool = ThreadPoolExecutor(max_workers=max_workers)

        # Start scan thread
        self._scan_thread = threading.Thread(
            target=self._run_scan,
            daemon=True,
            name=f"ScanThread-photos"
        )
        self._scan_thread.start()

    def _run_scan(self) -> None:
        """Run scan in a background thread."""
        try:
            def wrapper_callback(progress: ScanProgress) -> None:
                """Thread-safe wrapper for progress callback."""
                if self._progress_callback:
                    self._progress_callback(progress)

            self._active_engine.start(wrapper_callback)
        except Exception as e:
            # Report error via progress callback
            if self._progress_callback:
                error_progress = ScanProgress(
                    state=ScanState.ERROR,
                    current_file=f"Error: {str(e)}"
                )
                self._progress_callback(error_progress)

    def _get_image_files(self) -> List[Path]:
        """Get all image files from scan folders, excluding protected."""
        image_files = []
        image_ext_lower = {ext.lower() for ext in IMAGE_EXTENSIONS}

        for folder in self._folders:
            try:
                for item in folder.rglob("*"):
                    if self._cancel_event.is_set():
                        return

                    if item.is_file():
                        path = Path(item)

                        # Skip protected folders
                        if self._protected:
                            if any(p in path.parents for p in self._protected):
                                continue

                        # Check extension
                        if path.suffix.lower() in image_ext_lower:
                            # Check resolution filter
                            width, height = self._get_image_resolution(path)
                            if self._passes_resolution_filter(width, height):
                                image_files.append(path)

            except PermissionError as e:
                logger.warning(f"Permission denied: {e}")

        return image_files

    def _get_image_resolution(self, path: Path) -> Optional[tuple]:
        """Get image resolution without loading full image."""
        try:
            with Image.open(path) as img:
                return img.size
        except Exception:
            return None

    def _passes_resolution_filter(
        self, width: Optional[int], height: Optional[int]
    ) -> bool:
        """Check if image passes resolution filter from options."""
        min_res = self._options.get("min_resolution", 0)
        max_res = self._options.get("max_resolution", 0)

        if width is None or height is None:
            return True

        resolution = width * height

        if min_res > 0 and resolution < min_res:
            return False

        if max_res > 0 and resolution > max_res:
            return False

        return True

    def _compute_hashes(self, image_path: Path) -> Optional[tuple]:
        """
        Compute pHash and dHash for an image.

        Args:
            image_path: Path to image file.

        Returns:
            Tuple of (phash_hex, dhash_hex) or None if failed.
        """
        try:
            with Image.open(image_path) as img:
                # Compute pHash (perceptual hash)
                phash_val = phash(img, hash_size=PHASH_SIZE)

                # Compute dHash (difference hash)
                dhash_val = dhash(img, hash_size=DHASH_SIZE)

                return (phash_val.hexdigest(), dhash_val.hexdigest())

        except Exception as e:
            logger.warning(f"Failed to compute hashes for {image_path}: {e}")
            return None

    def _group_images(self, image_files: List[Path]) -> List[DuplicateGroup]:
        """
        Group images by perceptual hash similarity.

        Args:
            image_files: List of image file paths.

        Returns:
            List of DuplicateGroup objects.
        """
        # Map: hash -> list of image paths
        hash_map: dict[str, List[Path]] = {}

        # Cache for hash lookups
        cache_hits = 0
        cache_misses = 0

        total_files = len(image_files)
        processed = 0

        for image_path in image_files:
            if self._cancel_event.is_set():
                return

            processed += 1

            # Check cache first
            mtime = image_path.stat().st_mtime
            size = image_path.stat().st_size

            cached_phash = self._cache.get(image_path, mtime, size, "phash")
            if cached_phash:
                hash_map[cached_phash] = hash_map.get(cached_phash, []) + [image_path]
                cache_hits += 1
                continue

            cache_misses += 1

            # Compute hashes
            hashes = self._compute_hashes(image_path)
            if not hashes:
                continue

            phash_hex, dhash_hex = hashes

            # Check for matching group
            # First try exact pHash match
            if phash_hex in hash_map:
                hash_map[phash_hex].append(image_path)
            # Then try near match (threshold)
            else:
                threshold = self._options.get("phash_threshold", 5)
                # Simple Hamming distance check
                for existing_hash, group_files in list(hash_map.items()):
                    if self._hamming_distance(phash_hex, existing_hash) <= threshold:
                        hash_map[existing_hash].append(image_path)
                        break

            # Update progress
            self._progress.files_scanned = processed
            self._progress.duplicates_found = sum(len(files) - 1 for files in hash_map.values() if len(files) > 1)
            self._progress.groups_found = len(hash_map)
            self._progress.current_file = str(image_path)

            if processed % 100 == 0:
                self._progress.percent = (processed / total_files) * 100
                if self._progress_callback:
                    self._progress_callback(self._progress.clone())

        # Create duplicate groups
        groups = []
        group_id = 0

        for hash_value, group_files in hash_map.items():
            if len(group_files) > 1:
                # Calculate reclaimable space
                total_size = sum(f.stat().st_size for f in group_files)
                max_size = max(f.stat().st_size for f in group_files)
                reclaimable = total_size - max_size

                # Create file objects
                files_list = []
                for f in group_files:
                    # Mark largest as keeper
                    is_keeper = (f.stat().st_size == max_size)

                    files_list.append(DuplicateFile(
                        path=f,
                        size=f.stat().st_size,
                        modified=f.stat().st_mtime,
                        extension=f.suffix.lower(),
                        is_keeper=is_keeper,
                        similarity=1.0,  # Will be refined later
                        metadata={}
                    ))

                group = DuplicateGroup(
                    group_id=group_id,
                    files=files_list,
                    total_size=total_size,
                    reclaimable=reclaimable,
                    similarity_type="perceptual"
                )
                groups.append(group)
                group_id += 1

        return groups

    def _hamming_distance(self, hash1: str, hash2: str) -> int:
        """
        Calculate Hamming distance between two hex hashes.

        Args:
            hash1: First hex hash.
            hash2: Second hex hash.

        Returns:
            Number of differing bits.
        """
        if len(hash1) != len(hash2):
            return 64  # Maximum possible distance

        # XOR each corresponding byte
        distance = 0
        for c1, c2 in zip(hash1, hash2):
            if c1 != c2:
                distance += 1

        return distance

    def pause(self) -> None:
        """Pause the current scan."""
        if self._scan_thread and self._scan_thread.is_alive():
            self._pause_event.set()
            self._state = ScanState.PAUSED

    def resume(self) -> None:
        """Resume a paused scan."""
        if self._scan_thread and self._scan_thread.is_alive():
            self._pause_event.clear()
            self._state = ScanState.SCANNING

    def cancel(self) -> None:
        """Cancel the current scan."""
        self._cancel_event.set()
        self._pause_event.clear()
        if self._worker_pool:
            self._worker_pool.shutdown(wait=False, cancel_futures=True)

    def get_results(self) -> List[DuplicateGroup]:
        """
        Return scan results.

        Returns:
            List of DuplicateGroup objects with scan results.
        """
        return self._results

    def get_progress(self) -> ScanProgress:
        """
        Return current progress snapshot.

        Returns:
            ScanProgress object with current scan state.
        """
        return self._progress
