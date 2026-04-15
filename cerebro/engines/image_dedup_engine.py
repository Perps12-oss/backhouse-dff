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

import dataclasses
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
from cerebro.engines.image_formats import UnionFind, hamming_distance, similarity_from_hamming

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


@dataclasses.dataclass
class ImageMetadata:
    """Metadata captured for an image candidate."""

    path: Path
    size: int
    modified: float
    extension: str
    width: int = 0
    height: int = 0

    @property
    def resolution_str(self) -> str:
        if self.width <= 0 or self.height <= 0:
            return "-"
        return f"{self.width} × {self.height}"

    @property
    def key(self) -> tuple[int, str]:
        return (self.size, self.extension.lower())


@dataclasses.dataclass
class ImageHashResult:
    """Hash computation result including the source metadata."""

    metadata: ImageMetadata
    phash_hex: str
    dhash_hex: str
    phash_int: int
    dhash_int: int


def compute_perceptual_hashes(
    path: str,
    width: int,
    height: int,
    size: int,
    modified: float,
    extension: str,
) -> ImageHashResult:
    """
    Compute pHash+dHash pair for a single image path.

    This helper is used by tests and mirrors the same hash generation path as the engine.
    """
    image_path = Path(path)
    if HAS_PIL and image_path.exists():
        with Image.open(image_path) as img:
            ph = phash(img, hash_size=PHASH_SIZE)
            dh = dhash(img, hash_size=DHASH_SIZE)
        ph_hex = str(ph)
        dh_hex = str(dh)
    else:
        # Deterministic fallback keeps tests and non-photo environments functional.
        digest = hashlib.sha256(
            f"{path}|{width}|{height}|{size}|{modified}|{extension}".encode("utf-8")
        ).hexdigest()
        ph_hex = digest[:16]
        dh_hex = digest[16:32]
    return ImageHashResult(
        metadata=ImageMetadata(
            path=image_path,
            size=size,
            modified=modified,
            extension=extension,
            width=width,
            height=height,
        ),
        phash_hex=ph_hex,
        dhash_hex=dh_hex,
        phash_int=int(ph_hex, 16),
        dhash_int=int(dh_hex, 16),
    )


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
            "phash_threshold": 8,
            "dhash_threshold": 10,
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
                default=8,
                min_value=0,
                max_value=64,
                tooltip="Lower = more sensitive. Images with pHash difference <= this are grouped."
            ),
            EngineOption(
                name="dhash_threshold",
                display_name="dHash Threshold",
                type="int",
                default=10,
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

        self._callback = progress_callback

        # Start scan thread
        self._scan_thread = threading.Thread(
            target=self._run_scan,
            args=(progress_callback,),
            daemon=True,
            name=f"ScanThread-photos"
        )
        self._scan_thread.start()

    def _run_scan(self, cb: Callable[[ScanProgress], None]) -> None:
        """Run scan in a background thread."""
        try:
            image_files = self._get_image_files()
            cb(ScanProgress(state=ScanState.SCANNING, files_total=len(image_files)))
            groups = self._group_images(image_files)
            self._results = groups if groups else []
            self._state = ScanState.COMPLETED
            cb(ScanProgress(
                state=ScanState.COMPLETED,
                files_scanned=len(image_files),
                files_total=len(image_files),
                groups_found=len(self._results),
                duplicates_found=sum(len(g.files) - 1 for g in self._results),
                bytes_reclaimable=sum(g.reclaimable for g in self._results),
            ))
        except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError) as e:
            cb(ScanProgress(
                state=ScanState.ERROR,
                current_file=f"Error: {str(e)}"
            ))

    def _get_image_files(self) -> List[Path]:
        """Get all image files from scan folders, excluding protected."""
        image_files = []
        image_ext_lower = {ext.lower() for ext in IMAGE_EXTENSIONS}

        for folder in self._folders:
            try:
                for item in folder.rglob("*"):
                    if self._cancel_event.is_set():
                        return []

                    if item.is_file():
                        path = Path(item)

                        # Skip protected folders
                        if self._protected:
                            if any(p in path.parents for p in self._protected):
                                continue

                        # Check extension
                        if path.suffix.lower() in image_ext_lower:
                            # Check resolution filter
                            result = self._get_image_resolution(path)
                            if result is None:
                                continue
                            width, height = result
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
        except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
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

    def _compute_hashes(self, image_path: Path) -> Optional[tuple[str, str, int, int]]:
        """
        Compute pHash and dHash for an image.

        Args:
            image_path: Path to image file.

        Returns:
            Tuple of (phash_hex, dhash_hex) or None if failed.
        """
        try:
            if HAS_PIL:
                with Image.open(image_path) as img:
                    # Compute pHash (perceptual hash)
                    phash_val = phash(img, hash_size=PHASH_SIZE)
                    # Compute dHash (difference hash)
                    dhash_val = dhash(img, hash_size=DHASH_SIZE)
                    # imagehash objects serialize to hexadecimal using str(...)
                    phash_hex = str(phash_val)
                    dhash_hex = str(dhash_val)
                    return (phash_hex, dhash_hex, int(phash_hex, 16), int(dhash_hex, 16))

            raw = image_path.read_bytes()
            digest = hashlib.sha256(raw).hexdigest()
            phash_hex = digest[:16]
            dhash_hex = digest[16:32]
            return (phash_hex, dhash_hex, int(phash_hex, 16), int(dhash_hex, 16))
        except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError) as e:
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
        if not image_files:
            return []

        # Per-file records used for clustering and final group conversion
        records: list[dict] = []
        uf = UnionFind()

        total_files = len(image_files)
        processed = 0

        for idx, image_path in enumerate(image_files):
            if self._cancel_event.is_set():
                return []

            processed += 1
            uf.add(idx)

            # Check cache first
            stat = image_path.stat()
            mtime = stat.st_mtime
            size = stat.st_size

            phash_hex: Optional[str] = None
            dhash_hex: Optional[str] = None
            phash_int: Optional[int] = None
            dhash_int: Optional[int] = None

            if self._cache is not None:
                cached_phash = self._cache.get(image_path, mtime, size, "phash")
                cached_dhash = self._cache.get(image_path, mtime, size, "dhash")
                if cached_phash and cached_dhash:
                    phash_hex = cached_phash
                    dhash_hex = cached_dhash
                    phash_int = int(cached_phash, 16)
                    dhash_int = int(cached_dhash, 16)

            # Compute hashes
            if phash_hex is None or dhash_hex is None:
                hashes = self._compute_hashes(image_path)
                if not hashes:
                    continue
                phash_hex, dhash_hex, phash_int, dhash_int = hashes
                if self._cache is not None:
                    self._cache.set(image_path, mtime, size, "phash", phash_hex)
                    self._cache.set(image_path, mtime, size, "dhash", dhash_hex)

            record = {
                "path": image_path,
                "size": size,
                "modified": mtime,
                "phash_hex": phash_hex,
                "dhash_hex": dhash_hex,
                "phash_int": phash_int,
                "dhash_int": dhash_int,
            }
            records.append(record)

            # Update progress
            self._progress.files_scanned = processed
            self._progress.current_file = str(image_path)

            if processed % 100 == 0:
                if self._callback:
                    self._callback(dataclasses.replace(self._progress))

        # Connectivity rule: both pHash and dHash distances must satisfy thresholds.
        phash_threshold = int(self._options.get("phash_threshold", 8))
        dhash_threshold = int(self._options.get("dhash_threshold", 10))
        for i in range(len(records)):
            for j in range(i + 1, len(records)):
                a = records[i]
                b = records[j]
                ph_dist = hamming_distance(a["phash_int"], b["phash_int"])
                dh_dist = hamming_distance(a["dhash_int"], b["dhash_int"])
                if ph_dist <= phash_threshold and dh_dist <= dhash_threshold:
                    uf.union(i, j)

        # Create duplicate groups
        groups: List[DuplicateGroup] = []
        group_id = 0
        for group_indices in uf.get_groups():
            if len(group_indices) <= 1:
                continue

            group_records = [records[i] for i in group_indices]
            total_size = sum(r["size"] for r in group_records)
            keeper_record = max(
                group_records,
                key=lambda r: (
                    self._resolution_score(r["path"]),
                    r["size"],
                ),
            )
            reclaimable = total_size - keeper_record["size"]
            ref = keeper_record
            files_list = []
            for rec in group_records:
                ph_dist = hamming_distance(rec["phash_int"], ref["phash_int"])
                dh_dist = hamming_distance(rec["dhash_int"], ref["dhash_int"])
                similarity = (
                    similarity_from_hamming(ph_dist, PHASH_SIZE * PHASH_SIZE)
                    + similarity_from_hamming(dh_dist, DHASH_SIZE * DHASH_SIZE)
                ) / 2.0
                files_list.append(
                    DuplicateFile(
                        path=rec["path"],
                        size=rec["size"],
                        modified=rec["modified"],
                        extension=rec["path"].suffix.lower(),
                        is_keeper=(rec["path"] == keeper_record["path"]),
                        similarity=similarity,
                        metadata={},
                    )
                )

            groups.append(
                DuplicateGroup(
                    group_id=group_id,
                    files=files_list,
                    total_size=total_size,
                    reclaimable=reclaimable,
                    similarity_type="perceptual",
                )
            )
            group_id += 1

        return groups

    def _resolution_score(self, path: Path) -> int:
        """Return pixel count for keeper ranking (falls back to 0 on errors)."""
        res = self._get_image_resolution(path)
        if res is None:
            return 0
        width, height = res
        return width * height

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

        # Convert hex strings to integers and XOR to find differing bits
        try:
            int1 = int(hash1, 16)
            int2 = int(hash2, 16)
            xor_result = int1 ^ int2

            # Count the number of set bits in the XOR result
            distance = bin(xor_result).count('1')
            return distance
        except ValueError:
            # Fallback for malformed hashes
            return 64

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
