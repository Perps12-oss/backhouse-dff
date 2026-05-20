"""
Turbo Scanner - Ultra-Fast File Scanning Engine
================================================

Optimizations:
1. Integrated hash caching (SQLite + memory)
2. Parallel directory traversal with multiprocessing
3. Incremental scanning (directory-level change detection)
4. Memory-mapped I/O for large files
5. Batch processing and chunked operations
6. Smart file comparison (size -> partial hash -> full hash)
7. Directory signature caching
8. Lockless data structures where possible

Performance target: 250K files in < 3 minutes (from 30 minutes)

Logging (Phase 8.1, post-v1 audit): temporary ``[DIAG:*]`` INFO markers and
``_diagnose_pair()`` sampling were removed from ``scan()``; end-of-run totals
use ``[Turbo] summary:`` at INFO and ``[DIAG:GUARD]`` at DEBUG only. See
``dev/docs/architecture/scan_paths.md``.
"""

from __future__ import annotations

import os
import time
import hashlib
import json
import threading
from concurrent.futures import (
    ThreadPoolExecutor,
    ProcessPoolExecutor,
    as_completed,
    wait,
    FIRST_COMPLETED,
)
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, Callable, Any, Generator
from collections import defaultdict
import sqlite3
import mmap
from cerebro.core.models import FileMetadata
from cerebro.core.paths import default_cerebro_cache_dir
from cerebro.services.hash_cache import HashCache, StatSignature, TierAPrefixCache
from cerebro.services.logger import get_logger
from cerebro.core.root_dedup import dedupe_roots
from cerebro.core.group_invariants import _assert_no_self_duplicates
from cerebro.core.utils import DEFAULT_SKIP_DIRS, should_skip_directory
from cerebro.engines.scan_stage import ScanStage

logger = get_logger(__name__)
_LAST_PROCESS_RSS_MB: Optional[float] = None

try:
    import xxhash  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    xxhash = None

try:
    import blake3  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    blake3 = None


# ============================================================================
# CONSTANTS
# ============================================================================

# Optimal chunk sizes based on typical SSD/NVMe performance
HASH_CHUNK_SIZE = 8 * 1024 * 1024  # 8MB chunks for better I/O
MMAP_THRESHOLD = 50 * 1024 * 1024  # Use mmap for files > 50MB
QUICK_HASH_SIZE = 64 * 1024  # 64KB for quick hash (first + last 32KB)
TIER_A_SIZE = 4 * 1024       # 4 KiB prefix read — cheap pre-filter before quick-hash

# Parallelism settings
DEFAULT_DIR_WORKERS = min(32, (os.cpu_count() or 4) * 4)  # Aggressive parallelism
DEFAULT_HASH_WORKERS = min(64, (os.cpu_count() or 4) * 8)
BATCH_SIZE = 1000  # Process files in batches

# Cache settings
DIRECTORY_CACHE_SIZE = 10000  # Keep 10K directory signatures in memory
FILE_CACHE_SIZE = 50000  # Keep 50K file hashes in memory

# Archive file extensions treated as opaque blobs by default.
# When scan_archives=False these files are included in duplicate detection
# but never extracted; their whole-file hash identifies them.
ARCHIVE_EXTENSIONS: frozenset[str] = frozenset({
    ".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".lz4",
    ".zst", ".lzma", ".cab", ".iso", ".dmg", ".pkg", ".deb", ".rpm",
    ".jar", ".war", ".ear", ".apk", ".ipa", ".crx",
})

# Scale targets: switch to checkpoint streaming / DB grouping above this catalogue size.
STREAMING_THRESHOLD: int = 50_000
# Pathological same-size buckets (e.g. zero-byte files under Windows) are processed in chunks.
MAX_BUCKET_FILES: int = 10_000
_TIER_A_SKIP_CANDIDATE_RATIO: float = 0.02


# ============================================================================
# DATA STRUCTURES
# ============================================================================

@dataclass
class DirectorySignature:
    """Lightweight signature for directory change detection."""
    path: str
    file_count: int
    total_size: int
    last_modified: float
    checksum: str  # Hash of (file_count, total_size, last_modified)
    
    @classmethod
    def from_directory(cls, path: Path) -> Optional['DirectorySignature']:
        """Create signature from directory (recursive mtime walk)."""
        try:
            if not path.is_dir():
                return None

            stat = path.stat()
            entries = list(path.iterdir())
            file_count = sum(1 for e in entries if e.is_file())

            # Quick total size estimate (just immediate children)
            total_size = 0
            for entry in entries:
                try:
                    if entry.is_file():
                        total_size += entry.stat().st_size
                except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
                    pass

            last_modified = stat.st_mtime

            # Fold in mtime of every subdirectory so that adding/removing files
            # anywhere in the tree is detected without reading file contents.
            max_sub_mtime: float = 0.0
            try:
                for dirpath, _dirs, _files in os.walk(str(path)):
                    try:
                        sub_mtime = Path(dirpath).stat().st_mtime
                        if sub_mtime > max_sub_mtime:
                            max_sub_mtime = sub_mtime
                    except OSError:
                        pass
            except OSError:
                pass

            # Create checksum
            sig_data = f"{file_count}:{total_size}:{last_modified}:{max_sub_mtime}".encode()
            checksum = hashlib.md5(sig_data).hexdigest()

            return cls(
                path=str(path),
                file_count=file_count,
                total_size=total_size,
                last_modified=last_modified,
                checksum=checksum
            )
        except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
            return None


@dataclass
class ScanBatch:
    """Batch of files to process together."""
    files: List[Tuple[Path, int, float]]  # (path, size, mtime)
    batch_id: int
    

@dataclass
class TurboScanConfig:
    """Configuration for turbo scanner."""
    # Parallelism
    dir_workers: int = DEFAULT_DIR_WORKERS
    hash_workers: int = DEFAULT_HASH_WORKERS
    # True only helps on multi-disk setups; threads are faster for typical single-disk
    use_multiprocessing: bool = False
    
    # Caching
    use_cache: bool = True
    cache_dir: Optional[Path] = None
    incremental: bool = True  # Enable incremental scanning
    
    # Filtering
    min_size: int = 1024
    max_size: int = 0  # 0 = unlimited
    skip_hidden: bool = True
    skip_system: bool = True
    exclude_dirs: Set[str] = field(default_factory=set)
    exclude_paths: Set[str] = field(default_factory=set)
    recursive: bool = True
    
    # Hashing
    use_quick_hash: bool = True
    use_full_hash: bool = False
    hash_algorithm: str = "auto"
    
    # Performance
    use_mmap: bool = True  # Use memory-mapped I/O
    batch_processing: bool = True
    prefetch_enabled: bool = True  # Prefetch file metadata
    
    # Progress
    progress_callback: Optional[Callable] = None

    # Pause control
    # When set (default), the scanner runs at full speed. Engines that want
    # mid-scan pause/resume pass in a threading.Event and call .clear() to
    # pause and .set() to resume. The event is checked at every phase boundary
    # and (most importantly) before each file hash so wall-time-dominant
    # hashing phases respond promptly to pause requests. Cross-process
    # pause is intentionally not supported; ``use_multiprocessing=True``
    # bypasses these checks because threading.Event does not span processes.
    pause_event: Optional[threading.Event] = None

    # Cancel control — when set, hash workers exit after the current file.
    # Checked per-file in _compute_hashes_parallel; also checked at phase
    # boundaries via the engine's scan loop.
    cancel_event: Optional[threading.Event] = None

    # When False, archives are hashed as opaque blobs. When True, member-file
    # extraction will be attempted (not yet implemented beyond this flag).
    scan_archives: bool = False

    # Checkpoint integration — set by TurboFileEngine when resume_from_checkpoint=True.
    # If provided and resume_from_checkpoint is True, Phase 1 (os.walk) is skipped;
    # pending files are loaded from the DB instead, saving 30-90 s on 1 M-file trees.
    checkpoint_db: Optional[object] = None   # CheckpointDB instance
    scan_id: Optional[str] = None
    resume_from_checkpoint: bool = False

    # --- Staged enhancement flags (all default False = legacy path) ---
    # Canonical path dedup guard before hash phases (Phase 2).
    # Suppresses alias/symlink/hardlink/case-variant self-duplicates.
    enable_prehash_canonical_dedup: bool = False
    # Adaptive Tier-A per-group bounded submission with escalation (Phase 1).
    enable_tier_a_adaptive: bool = False
    # Phase-aware separate worker caps for Tier-A / quick / full hash (Phase 3).
    enable_phase_worker_policy: bool = False
    # Durable size/partial phase artifacts for resume (Phase 4).
    enable_resume_artifacts: bool = False

    # Stop after discovery + grouping (checkpoint seeded); hashing on resume only.
    index_only: bool = False

    # Per-phase worker overrides — 0 means fall back to hash_workers (Phase 3).
    tier_a_workers: int = 0
    quick_hash_workers: int = 0
    full_hash_workers: int = 0


def effective_exclude_dirs(config: TurboScanConfig) -> Set[str]:
    """User exclude_dirs union DEFAULT_SKIP_DIRS when skip_system is enabled."""
    dirs: Set[str] = set(config.exclude_dirs or set())
    if config.skip_system:
        dirs |= set(DEFAULT_SKIP_DIRS)
    return dirs


def _process_rss_mb() -> Optional[float]:
    try:
        import psutil

        return psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024)
    except (OSError, ValueError, RuntimeError, AttributeError, ImportError, TypeError):
        return None


# ============================================================================
# DIRECTORY CACHE
# ============================================================================

class DirectoryCache:
    """Fast directory-level cache for incremental scanning."""
    
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = None
        self._memory_cache: Dict[str, DirectorySignature] = {}
        self._init_db()
        
    def _init_db(self):
        """Initialize cache database."""
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS directory_cache (
                path TEXT PRIMARY KEY,
                file_count INTEGER,
                total_size INTEGER,
                last_modified REAL,
                checksum TEXT,
                cached_at REAL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_checksum ON directory_cache(checksum)")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS file_cache (
                dir_path TEXT PRIMARY KEY,
                files_json TEXT,
                cached_at REAL
            )
        """)
        conn.commit()
        conn.close()
        
    def get(self, path: Path) -> Optional[DirectorySignature]:
        """Get cached directory signature."""
        path_str = str(path)
        
        # Check memory cache
        if path_str in self._memory_cache:
            return self._memory_cache[path_str]
        
        # Check database
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.execute(
            "SELECT file_count, total_size, last_modified, checksum FROM directory_cache WHERE path = ?",
            (path_str,)
        )
        row = cursor.fetchone()
        conn.close()
        
        if row:
            sig = DirectorySignature(
                path=path_str,
                file_count=row[0],
                total_size=row[1],
                last_modified=row[2],
                checksum=row[3]
            )
            self._memory_cache[path_str] = sig
            return sig
        
        return None
    
    def put(self, sig: DirectorySignature):
        """Store directory signature."""
        self._memory_cache[sig.path] = sig
        
        conn = sqlite3.connect(str(self.db_path))
        conn.execute(
            """INSERT OR REPLACE INTO directory_cache 
               (path, file_count, total_size, last_modified, checksum, cached_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (sig.path, sig.file_count, sig.total_size, sig.last_modified, 
             sig.checksum, time.time())
        )
        conn.commit()
        conn.close()
        
    def has_changed(self, path: Path) -> bool:
        """Check if directory has changed since last scan."""
        cached_sig = self.get(path)
        if not cached_sig:
            return True  # No cache = assume changed

        current_sig = DirectorySignature.from_directory(path)
        if not current_sig:
            return True

        return cached_sig.checksum != current_sig.checksum

    def get_files(self, path: Path) -> Optional[List[Tuple[Path, int, float]]]:
        """Return cached file list for *path*, or None if not cached."""
        import json
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.execute(
            "SELECT files_json FROM file_cache WHERE dir_path = ?",
            (str(path),),
        )
        row = cursor.fetchone()
        conn.close()
        if not row:
            return None
        try:
            data = json.loads(row[0])
            return [(Path(item[0]), int(item[1]), float(item[2])) for item in data]
        except (ValueError, TypeError, KeyError):
            return None

    def set_files(self, path: Path, files: List[Tuple[Path, int, float]]) -> None:
        """Persist the file list for *path* so it can be restored on the next scan."""
        import json
        files_data = [[str(p), sz, mt] for p, sz, mt in files]
        conn = sqlite3.connect(str(self.db_path))
        conn.execute(
            "INSERT OR REPLACE INTO file_cache (dir_path, files_json, cached_at) VALUES (?, ?, ?)",
            (str(path), json.dumps(files_data), time.time()),
        )
        conn.commit()

    def clear_all(self) -> None:
        """Delete all directory signatures and cached file lists."""
        self._memory_cache.clear()
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("DELETE FROM directory_cache")
        conn.execute("DELETE FROM file_cache")
        conn.commit()
        conn.close()
        conn.close()


# ============================================================================
# OPTIMIZED HASH FUNCTIONS
# ============================================================================

def _new_hasher(algorithm: str):
    algo = str(algorithm or "sha256").lower()
    if algo == "xxhash" and xxhash is not None:
        return xxhash.xxh64()
    if algo == "blake3" and blake3 is not None:
        return blake3.blake3()
    return hashlib.new(algo)


def _available_hash_algorithms() -> List[str]:
    algos: List[str] = []
    if xxhash is not None:
        algos.append("xxhash")
    if blake3 is not None:
        algos.append("blake3")
    algos.extend(["sha256", "md5"])
    seen: set[str] = set()
    out: List[str] = []
    for a in algos:
        if a not in seen:
            seen.add(a)
            out.append(a)
    return out


def _algorithms_for_auto_pick() -> List[str]:
    """Candidates when ``hash_algorithm`` is ``auto``: fast, strong enough for full-file dedup.

    MD5 is excluded from auto-selection (legacy / weaker); it remains available if chosen explicitly.
    """
    out: List[str] = []
    if xxhash is not None:
        out.append("xxhash")
    if blake3 is not None:
        out.append("blake3")
    out.append("sha256")
    return out


def compute_quick_hash_fast(path: Path, algorithm: str = "md5") -> Optional[str]:
    """
    Compute quick hash using first 32KB + last 32KB.
    This is much faster than full file hash for large files.
    """
    try:
        size = path.stat().st_size
        if size == 0:
            return None
        
        hasher = _new_hasher(algorithm)
        
        with open(path, 'rb') as f:
            # Read first 32KB
            chunk_size = min(32 * 1024, size)
            hasher.update(f.read(chunk_size))
            
            # Read last 32KB if file is large enough
            if size > 64 * 1024:
                f.seek(-32 * 1024, 2)  # Seek to 32KB before end
                hasher.update(f.read(32 * 1024))
        
        return hasher.hexdigest()
    except (sqlite3.Error, OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
        return None


def _phase_artifact_version_hash(cfg: "TurboScanConfig") -> str:
    """Compute a fingerprint for phase artifact compatibility gating.

    Encodes scan-affecting config fields so that artifacts from a prior run
    with a different algorithm, filter set, or engine version are rejected.
    """
    import hashlib as _hashlib

    _ENGINE_VERSION = "1"  # bump when artifact format changes
    parts = "|".join([
        _ENGINE_VERSION,
        str(cfg.hash_algorithm or "auto"),
        str(cfg.min_size),
        str(cfg.max_size),
        str(cfg.skip_hidden),
        str(cfg.recursive),
        str(sorted(cfg.exclude_paths or [])),
        str(sorted(cfg.exclude_dirs or [])),
        str(cfg.skip_system),
        str(cfg.use_quick_hash),
        str(cfg.use_full_hash),
    ])
    return _hashlib.sha256(parts.encode()).hexdigest()[:16]


def compute_tier_a_hash(path: Path, algorithm: str = "xxhash") -> Optional[str]:
    """Hash the first 4 KiB of a file (tier-A pre-filter).

    Used to reject non-duplicate candidates cheaply before the more expensive
    quick-hash (64 KiB) phase.  Can only reject — never used to confirm duplicates.
    Files smaller than TIER_A_SIZE read the whole file (correct behaviour).
    """
    try:
        with open(path, "rb") as f:
            data = f.read(TIER_A_SIZE)
        if not data:
            return None
        h = _new_hasher(algorithm)
        h.update(data)
        return h.hexdigest()
    except OSError:
        return None


def compute_partial_hash(path: Path, algorithm: str, nbytes: int) -> Optional[str]:
    """Hash the first ``nbytes`` of a file (adaptive Tier-A pre-filter).

    Same semantics as compute_tier_a_hash but with a caller-specified byte
    count for adaptive escalation on oversized candidate groups.
    Can only reject — never used to confirm duplicates.
    """
    try:
        with open(path, "rb") as f:
            data = f.read(nbytes)
        if not data:
            return None
        h = _new_hasher(algorithm)
        h.update(data)
        return h.hexdigest()
    except OSError:
        return None


def compute_full_hash_mmap(path: Path, algorithm: str = "md5") -> Optional[str]:
    """
    Compute full hash using memory-mapped I/O for better performance.
    Falls back to regular I/O for small files or if mmap fails.
    """
    try:
        size = path.stat().st_size
        if size == 0:
            return None
        
        hasher = _new_hasher(algorithm)
        
        # Use mmap for large files
        if size > MMAP_THRESHOLD:
            try:
                with open(path, 'rb') as f:
                    with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
                        # Process in chunks
                        for i in range(0, len(mm), HASH_CHUNK_SIZE):
                            hasher.update(mm[i:i + HASH_CHUNK_SIZE])
                return hasher.hexdigest()
            except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
                pass  # Fall through to regular I/O
        
        # Regular I/O for smaller files
        with open(path, 'rb') as f:
            while chunk := f.read(HASH_CHUNK_SIZE):
                hasher.update(chunk)
        
        return hasher.hexdigest()
    except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
        return None


def compute_hash_cached(
    path: Path,
    cache: HashCache,
    algorithm: str = "md5",
    quick: bool = True
) -> Optional[str]:
    """
    Compute hash with caching.
    
    Returns cached hash if file hasn't changed, otherwise computes new hash.
    """
    try:
        sig = StatSignature.from_path(path)
        
        # Try cache first
        if quick:
            cached = cache.get_quick(str(path), sig, expected_algo=algorithm)
            if cached:
                return cached
            
            # Compute and cache
            hash_val = compute_quick_hash_fast(path, algorithm)
            if hash_val:
                cache.set_quick(path, sig, hash_val, algo=algorithm, quick_bytes=QUICK_HASH_SIZE)
            return hash_val
        else:
            cached = cache.get_full(str(path), sig, expected_algo=algorithm)
            if cached:
                return cached
            
            # Compute and cache
            hash_val = compute_full_hash_mmap(path, algorithm)
            if hash_val:
                cache.set_full(path, sig, hash_val, algo=algorithm)
            return hash_val
    except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
        return None


# ============================================================================
# PARALLEL DIRECTORY WALKER
# ============================================================================

def walk_directory_worker(args: Tuple[Any, ...]) -> List[Tuple[Path, int, float]]:
    """Worker function for parallel directory traversal.

    Uses os.scandir to avoid redundant stat() calls — DirEntry.stat()
    reuses the data returned by the underlying directory enumeration
    syscall, which is materially faster on Windows (FindFirstFile)
    and on SMB/network mounts.

    Returns list of (path, size, mtime) tuples.

    ``args`` ends with optional ``skip_system`` and ``cancel_event`` (threads only).
    Legacy 8-tuples omit ``skip_system`` (treated as False).
    Multiprocessing discovery passes 9 fields (ends with ``skip_system`` bool, no cancel).
    Legacy 9-tuples with only ``cancel_event`` (no ``skip_system``) are still accepted.
    """
    skip_system = False
    cancel_event = None
    if len(args) >= 10:
        (
            directory,
            skip_hidden,
            exclude_dirs,
            exclude_paths,
            recursive,
            min_size,
            max_size,
            scan_archives,
            skip_system,
            cancel_event,
        ) = args[:10]
    elif len(args) == 9 and hasattr(args[8], "is_set"):
        (
            directory,
            skip_hidden,
            exclude_dirs,
            exclude_paths,
            recursive,
            min_size,
            max_size,
            scan_archives,
            cancel_event,
        ) = args[:9]
    elif len(args) >= 9:
        (
            directory,
            skip_hidden,
            exclude_dirs,
            exclude_paths,
            recursive,
            min_size,
            max_size,
            scan_archives,
            skip_system,
        ) = args[:9]
    else:
        (
            directory,
            skip_hidden,
            exclude_dirs,
            exclude_paths,
            recursive,
            min_size,
            max_size,
            scan_archives,
        ) = args[:8]
    results: List[Tuple[Path, int, float]] = []
    listed_since_cancel_check = 0

    # Iterative DFS with an explicit stack. Avoids recursion-depth limits
    # on pathological trees and gives us tight control over symlink/junction
    # behaviour.
    stack: List[str] = [str(directory)]
    root_dir_s = str(directory)
    exclude_prefixes = []
    for p in (exclude_paths or set()):
        raw = str(p).replace("/", "\\").rstrip("\\")
        if raw:
            exclude_prefixes.append(raw.casefold())

    def _norm_path(p: str) -> str:
        return str(p).replace("/", "\\").rstrip("\\").casefold()

    def _is_excluded_path(p: str) -> bool:
        np = _norm_path(p)
        for ep in exclude_prefixes:
            if np == ep or np.startswith(ep + "\\"):
                return True
        return False

    def _want_cancel() -> bool:
        return cancel_event is not None and cancel_event.is_set()

    while stack:
        if _want_cancel():
            return results
        current = stack.pop()
        if _is_excluded_path(current):
            continue
        try:
            with os.scandir(current) as it:
                for entry in it:
                    listed_since_cancel_check += 1
                    if listed_since_cancel_check >= 128:
                        listed_since_cancel_check = 0
                        if _want_cancel():
                            return results
                    name = entry.name
                    try:
                        if _is_excluded_path(entry.path):
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            if not recursive:
                                continue
                            if skip_hidden and name.startswith('.'):
                                continue
                            if name in exclude_dirs:
                                continue
                            if skip_system and should_skip_directory(
                                Path(entry.path),
                                include_hidden=not skip_hidden,
                                include_system=False,
                            ):
                                continue
                            # Skip descending into dirs whose names look like
                            # archive bundles (mounted/extracted trees) unless
                            # scan_archives is enabled.
                            # Known edge case: a *real* directory literally named
                            # "backup.zip" will also be skipped here because the
                            # name matches ARCHIVE_EXTENSIONS. This is intentional —
                            # such names are vanishingly rare and almost always indicate
                            # an extracted/mounted archive tree. If this becomes a problem,
                            # add an explicit opt-out via exclude_dirs.
                            if not scan_archives:
                                suf = Path(name).suffix.lower()
                                if suf in ARCHIVE_EXTENSIONS:
                                    continue
                            stack.append(entry.path)
                            continue

                        if not entry.is_file(follow_symlinks=False):
                            continue
                        if skip_hidden and name.startswith('.'):
                            continue

                        # Archive files are included as opaque blobs.
                        # When scan_archives is True (opt-in) the engine layer
                        # may add extraction later; the walker surfaces the path.

                        st = entry.stat(follow_symlinks=False)
                        size = st.st_size
                        if size < min_size:
                            continue
                        if max_size > 0 and size > max_size:
                            continue

                        results.append((Path(entry.path), size, st.st_mtime))
                    except OSError:
                        # Permission denied, dangling symlink, etc.
                        # Skip the individual entry and keep going.
                        continue
        except OSError as exc:
            # Directory unreadable as a whole — skip and continue.
            if str(current) == root_dir_s:
                raise OSError(f"Network path unreachable: {root_dir_s}") from exc
            continue

    return results


# ============================================================================
# TURBO SCANNER
# ============================================================================

class TurboScanner:
    """
    Ultra-fast file scanner with aggressive optimizations.
    
    Features:
    - Parallel directory traversal (multiprocessing)
    - Integrated hash caching (SQLite + memory)
    - Incremental scanning (directory-level change detection)
    - Memory-mapped I/O for large files
    - Batch processing
    - Smart comparison (size -> quick hash -> full hash)
    """
    
    def __init__(self, config: Optional[TurboScanConfig] = None):
        self.config = config or TurboScanConfig()
        
        # Initialize caches
        cache_dir = self.config.cache_dir or default_cerebro_cache_dir()
        cache_dir.mkdir(parents=True, exist_ok=True)
        self._cache_dir = cache_dir
        self._scope_fingerprint_path = self._cache_dir / "scan_scope_fingerprint.json"
        
        self.hash_cache = None
        self.dir_cache = None
        self.tier_a_cache = None

        if self.config.use_cache:
            self.hash_cache = HashCache(cache_dir / "hash_cache.sqlite")
            self.hash_cache.open()

            # Isolated Tier-A prefix cache: lets repeat scans skip the per-file
            # prefix reads that dominate seek-bound scans. Separate DB so it can
            # never corrupt the full-hash cache that drives dedup/deletes.
            try:
                self.tier_a_cache = TierAPrefixCache(cache_dir / "tier_a_cache.sqlite")
                self.tier_a_cache.open()
            except sqlite3.Error:
                self.tier_a_cache = None

            if self.config.incremental:
                self.dir_cache = DirectoryCache(cache_dir / "dir_cache.sqlite")
        
        # Groups from last scan (for Review page; worker reads this)
        self.last_groups = []
        
        # Statistics
        self.stats = {
            'files_scanned': 0,
            'files_skipped_cache': 0,
            'files_skipped_unchanged': 0,
            'directories_skipped': 0,
            'hash_cache_hits': 0,
            'hash_cache_misses': 0,
            'tier_a_cache_hits': 0,
            'tier_a_cache_misses': 0,
            'total_bytes': 0,
            'elapsed_time': 0,
        }
        self._tier_a_groups_escalated = 0

    def _scan_scope_fingerprint(self) -> Dict[str, Any]:
        def _norm_paths(values: Set[str] | List[str]) -> List[str]:
            out: List[str] = []
            for raw in values or []:
                text = str(raw).strip().replace("/", "\\").rstrip("\\")
                if text:
                    out.append(text.casefold())
            return sorted(set(out))

        return {
            "min_size": int(self.config.min_size or 0),
            "max_size": int(self.config.max_size or 0),
            "exclude_paths": _norm_paths(list(self.config.exclude_paths or set())),
            "exclude_dirs": _norm_paths(list(self.config.exclude_dirs or set())),
            "scan_archives": bool(self.config.scan_archives),
            "skip_hidden": bool(self.config.skip_hidden),
            "recursive": bool(self.config.recursive),
            "skip_system": bool(self.config.skip_system),
        }

    # Threshold for adaptive escalation: groups whose total bytes exceed this
    # get a stronger prefix read (up to 64 KiB) before the full quick-hash phase.
    _TIER_A_ADAPTIVE_THRESHOLD = 50 * 1024 * 1024  # 50 MB
    _TIER_A_ESCALATED_BYTES = 64 * 1024             # max escalated prefix (=quick-hash size)

    def _apply_tier_a_filter(
        self,
        size_groups: Dict[Any, List[Tuple[Path, float]]],
        algorithm: str,
        cancel_event: Optional[threading.Event],
        *,
        discovered_count: int = 0,
        emit: Optional[Callable[..., None]] = None,
        scope_total: int = 0,
    ) -> tuple[Dict[Any, List[Tuple[Path, float]]], int, int]:
        """Apply a prefix-hash pre-filter before the quick-hash phase.

        Returns (filtered_size_groups, candidates_in, candidates_out).
        Correctness guarantee: Tier-A can only *reject* non-matches — files that
        share the prefix hash still go through quick-hash + full-hash before being
        confirmed as duplicates.

        Two modes controlled by config.enable_tier_a_adaptive:
        • False (default): legacy flat task flooding — all groups submitted at once
          with a fixed 4 KiB prefix read (unchanged behaviour).
        • True: per-group bounded submission with adaptive escalation. Groups whose
          total bytes exceed _TIER_A_ADAPTIVE_THRESHOLD use a stronger prefix
          (up to _TIER_A_ESCALATED_BYTES) to get a better rejection rate.
          self._tier_a_groups_escalated is incremented for observability.

        The filter is skipped (returns size_groups unchanged) when:
        • there are no candidates, or
        • hash_workers < 2 (not worth the overhead).
        """
        from collections import defaultdict as _dd

        self._tier_a_groups_escalated = 0

        candidates_in = sum(len(v) for v in size_groups.values())
        if not size_groups or candidates_in < 2:
            return size_groups, candidates_in, candidates_in

        if not self.config.use_quick_hash:
            return size_groups, candidates_in, candidates_in
        if (
            discovered_count > 0
            and (candidates_in / float(discovered_count)) < _TIER_A_SKIP_CANDIDATE_RATIO
        ):
            logger.info(
                "[Turbo] Tier-A skipped: candidates=%d discovered=%d (ratio below %.2f)",
                candidates_in,
                discovered_count,
                _TIER_A_SKIP_CANDIDATE_RATIO,
            )
            return size_groups, candidates_in, candidates_in

        for sz, paths in size_groups.items():
            if len(paths) > MAX_BUCKET_FILES:
                logger.warning(
                    "[Turbo] Large size bucket: size=%s files=%d (processing in chunks of %d)",
                    sz,
                    len(paths),
                    MAX_BUCKET_FILES,
                )

        # Use the configured hash algorithm for tier-A so the hasher is already warm.
        tier_algo = algorithm if algorithm not in ("auto", "") else "sha256"
        if xxhash is not None:
            tier_algo = "xxhash"

        hash_workers = self.config.hash_workers
        # Per-phase cap (Phase 3): use tier_a_workers if set and policy is enabled.
        if self.config.enable_phase_worker_policy and self.config.tier_a_workers > 0:
            effective_workers = max(2, min(self.config.tier_a_workers, 32))
        else:
            effective_workers = max(2, min(hash_workers, 16))

        # Do not use ``with ThreadPoolExecutor`` here: on cancel, __exit__ would call
        # shutdown(wait=True) and block until every submitted Tier-A read finishes
        # (often hundreds of thousands of tasks), making cancel slower than scanning.
        pool = ThreadPoolExecutor(max_workers=effective_workers)
        abrupt_exit = False

        def _tier_a_emit_progress(processed_jobs: int, total_jobs: int, path_hint: str) -> None:
            if emit is None or total_jobs <= 0:
                return
            _now = time.monotonic()
            if not hasattr(self, "_tier_a_last_emit_ts"):
                self._tier_a_last_emit_ts = 0.0
            if (
                processed_jobs <= 1
                or processed_jobs % 512 == 0
                or processed_jobs >= total_jobs
                or (_now - self._tier_a_last_emit_ts) >= 0.3
            ):
                self._tier_a_last_emit_ts = _now
                try:
                    emit(
                        ScanStage.TIER_A_PREFILTER,
                        processed_jobs,
                        total_jobs,
                        path_hint,
                        metrics={
                            "total_files_in_scope": scope_total or discovered_count,
                            "files_processed": processed_jobs,
                            "candidates_found": candidates_in,
                        },
                    )
                except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
                    pass

        # Tier-A prefix cache: on a repeat scan, files unchanged since last time
        # serve their prefix hash from disk instead of re-reading 4 KiB each — the
        # dominant cost on seek-bound drives. Only the base-prefix read is cached;
        # adaptive escalated reads (larger prefix) bypass it.
        from collections import deque as _deque

        _ta_cache = (
            self.tier_a_cache
            if (self.config.use_cache and self.tier_a_cache is not None)
            else None
        )
        _ta_prefetch: Dict[str, str] = {}
        if _ta_cache is not None:
            _keys = [
                (str(path), int(size_key), TierAPrefixCache.mtime_to_ns(mtime), TIER_A_SIZE, tier_algo)
                for size_key, paths in size_groups.items()
                for path, mtime in paths
            ]
            try:
                _ta_prefetch = _ta_cache.get_many(_keys)
            except sqlite3.Error:
                _ta_prefetch = {}
        _ta_writeback: "deque" = _deque()

        def _ta_compute(path: Path, mtime: float, size_key: Any, nbytes: int) -> Optional[str]:
            """Cache-aware Tier-A read (base prefix only; escalated reads bypass cache)."""
            if _ta_cache is not None and nbytes == TIER_A_SIZE:
                hit = _ta_prefetch.get(str(path))
                if hit is not None:
                    return hit
                h = compute_partial_hash(path, tier_algo, nbytes)
                if h is not None:
                    _ta_writeback.append(
                        (str(path), int(size_key), TierAPrefixCache.mtime_to_ns(mtime),
                         nbytes, tier_algo, h)
                    )
                return h
            return compute_partial_hash(path, tier_algo, nbytes)

        def _ta_flush() -> None:
            if _ta_cache is not None:
                if _ta_writeback:
                    try:
                        _ta_cache.set_many(list(_ta_writeback))
                    except sqlite3.Error:
                        pass
                self.stats['tier_a_cache_hits'] += len(_ta_prefetch)
                self.stats['tier_a_cache_misses'] += max(0, candidates_in - len(_ta_prefetch))
                _ta_writeback.clear()

        if not self.config.enable_tier_a_adaptive:
            # Chunked flat path — bounded queue depth at scale (1M+ candidates).
            all_jobs: List[Tuple[Any, Path, float]] = []
            for size_key, paths in size_groups.items():
                for path, mtime in paths:
                    all_jobs.append((size_key, path, mtime))
            keyed: Dict[tuple, list] = _dd(list)
            total_jobs = max(1, len(all_jobs))
            processed_jobs = 0
            next_pct_log = 10
            _submit_chunk = 4096
            try:
                for chunk_off in range(0, len(all_jobs), _submit_chunk):
                    if cancel_event is not None and cancel_event.is_set():
                        abrupt_exit = True
                        return size_groups, candidates_in, candidates_in
                    chunk = all_jobs[chunk_off : chunk_off + _submit_chunk]
                    futures_map: Dict = {}
                    for size_key, path, mtime in chunk:
                        fut = pool.submit(_ta_compute, path, mtime, size_key, TIER_A_SIZE)
                        futures_map[fut] = (size_key, path, mtime)
                    for fut in as_completed(list(futures_map.keys())):
                        size_key, path, mtime = futures_map[fut]
                        if cancel_event is not None and cancel_event.is_set():
                            abrupt_exit = True
                            return size_groups, candidates_in, candidates_in
                        try:
                            ta_hash = fut.result()
                        except Exception:
                            ta_hash = None
                        if ta_hash is None:
                            keyed[(size_key, "__error__")].append((path, mtime))
                        else:
                            keyed[(size_key, ta_hash)].append((path, mtime))
                        processed_jobs += 1
                        pct = int((processed_jobs / total_jobs) * 100)
                        if pct >= next_pct_log:
                            logger.info(
                                "[Turbo] Tier-A progress: %d%% (%d/%d)",
                                pct,
                                processed_jobs,
                                total_jobs,
                            )
                            next_pct_log += 10
                        _tier_a_emit_progress(processed_jobs, total_jobs, str(path))

                survivors: Dict[Any, List[Tuple[Path, float]]] = {}
                for (size_key, _), grp_paths in keyed.items():
                    if len(grp_paths) < 2:
                        continue
                    existing = survivors.setdefault(size_key, [])
                    existing.extend(grp_paths)

                candidates_out = sum(len(v) for v in survivors.values())
                _ta_flush()
                return survivors, candidates_in, candidates_out
            finally:
                try:
                    pool.shutdown(wait=not abrupt_exit, cancel_futures=abrupt_exit)
                except TypeError:
                    pool.shutdown(wait=False if abrupt_exit else True)

        else:
            # ── Adaptive per-group path ───────────────────────────────────────
            # Process one size-group at a time so:
            #  • Oversized groups get a stronger prefix read (adaptive escalation).
            #  • Queue depth stays bounded (effective_workers tasks in flight per group).
            #  • Cancel checks happen at group boundaries, not just per-file.
            survivors_adaptive: Dict[Any, List[Tuple[Path, float]]] = {}
            try:
                for size_key, paths in size_groups.items():
                    if cancel_event is not None and cancel_event.is_set():
                        abrupt_exit = True
                        return size_groups, candidates_in, candidates_in

                    # Decide prefix size for this group.
                    group_total_bytes = len(paths) * int(size_key)
                    if (
                        group_total_bytes > self._TIER_A_ADAPTIVE_THRESHOLD
                        and int(size_key) > TIER_A_SIZE
                    ):
                        prefix_bytes = min(int(size_key), self._TIER_A_ESCALATED_BYTES)
                        self._tier_a_groups_escalated += 1
                        logger.debug(
                            "[Turbo] Tier-A adaptive: escalating group size_key=%d "
                            "n=%d total_bytes=%d → prefix=%d",
                            size_key, len(paths), group_total_bytes, prefix_bytes,
                        )
                    else:
                        prefix_bytes = TIER_A_SIZE

                    # Submit this group's tasks.
                    grp_futures: Dict = {}
                    for path, mtime in paths:
                        if cancel_event is not None and cancel_event.is_set():
                            abrupt_exit = True
                            return size_groups, candidates_in, candidates_in
                        fut = pool.submit(_ta_compute, path, mtime, size_key, prefix_bytes)
                        grp_futures[fut] = (path, mtime)

                    # Collect results for this group.
                    keyed_grp: Dict[str, list] = _dd(list)
                    for fut in as_completed(list(grp_futures.keys())):
                        path, mtime = grp_futures[fut]
                        if cancel_event is not None and cancel_event.is_set():
                            abrupt_exit = True
                            return size_groups, candidates_in, candidates_in
                        try:
                            ta_hash = fut.result()
                        except Exception:
                            ta_hash = None
                        bucket = ta_hash if ta_hash is not None else "__error__"
                        keyed_grp[bucket].append((path, mtime))

                    # Merge survivors back into size_key bucket.
                    for bucket_paths in keyed_grp.values():
                        if len(bucket_paths) >= 2:
                            existing = survivors_adaptive.setdefault(size_key, [])
                            existing.extend(bucket_paths)

                candidates_out = sum(len(v) for v in survivors_adaptive.values())
                if self._tier_a_groups_escalated:
                    logger.info(
                        "[Turbo] Tier-A adaptive: %d groups escalated to stronger prefix",
                        self._tier_a_groups_escalated,
                    )
                _ta_flush()
                return survivors_adaptive, candidates_in, candidates_out
            finally:
                try:
                    pool.shutdown(wait=not abrupt_exit, cancel_futures=abrupt_exit)
                except TypeError:
                    pool.shutdown(wait=False if abrupt_exit else True)

    def _invalidate_caches_if_scope_changed(self) -> None:
        if not self.config.use_cache:
            return
        current = self._scan_scope_fingerprint()
        previous: Optional[Dict[str, Any]] = None
        try:
            if self._scope_fingerprint_path.exists():
                previous = json.loads(self._scope_fingerprint_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, RuntimeError, TypeError, json.JSONDecodeError):
            previous = None

        changed = not isinstance(previous, dict) or previous != current
        if changed:
            logger.info("[Turbo] Scan scope changed; clearing hash/directory cache")
            try:
                if self.hash_cache:
                    self.hash_cache.clear_all()
                if self.dir_cache:
                    self.dir_cache.clear_all()
                if self.tier_a_cache:
                    self.tier_a_cache.clear_all()
            except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError, sqlite3.Error):
                logger.exception("[Turbo] Failed clearing cache on scope change")
        try:
            self._scope_fingerprint_path.write_text(json.dumps(current, sort_keys=True), encoding="utf-8")
        except (OSError, ValueError, RuntimeError, TypeError):
            logger.exception("[Turbo] Failed writing scope fingerprint")
        
    def scan(self, roots: List[Path]) -> Generator[FileMetadata, None, None]:
        """
        Scan directories and yield file metadata.
        
        Uses aggressive parallelization and caching for maximum speed.
        """
        start_time = time.time()
        _t_scan_start = time.perf_counter()
        _t_discovery_end = _t_scan_start
        _t_grouping_end = _t_scan_start
        _t_tier_a_end = _t_scan_start
        _t_quick_hash_end = _t_scan_start
        _t_full_hash_end = _t_scan_start
        _t_yield_end = _t_scan_start
        self.stats.update(
            {
                "files_scanned": 0,
                "files_skipped_cache": 0,
                "files_skipped_unchanged": 0,
                "directories_skipped": 0,
                "hash_cache_hits": 0,
                "hash_cache_misses": 0,
                "total_bytes": 0,
                "elapsed_time": 0,
            }
        )

        self._turbo_completed_normally = False
        self._scan_last_emit_p = 0
        self._scan_last_emit_t = 0
        self._last_stage_emitted = ""
        self._invalidate_caches_if_scope_changed()

        ckpt = self.config.checkpoint_db
        scan_id = self.config.scan_id
        resume_mode = bool(self.config.resume_from_checkpoint and ckpt and scan_id)
        _ckpt_total: int = 0
        _ckpt_completed_at_start: int = 0

        if resume_mode:
            _ckpt_total, _ckpt_pending = ckpt.get_counts(scan_id)
            _ckpt_completed_at_start = _ckpt_total - _ckpt_pending
            logger.info(
                "[Turbo] checkpoint resume state: scan_id=%s total=%d pending=%d completed=%d",
                scan_id,
                _ckpt_total,
                _ckpt_pending,
                _ckpt_completed_at_start,
            )
        elif ckpt and scan_id:
            ckpt.mark_stale_as_crashed()
            ckpt.purge_old_scans()

        # Heartbeat thread keeps the session alive every 10 s while scanning.
        _hb_stop = threading.Event()
        def _heartbeat_loop():
            while not _hb_stop.wait(10):
                try:
                    ckpt.beat(scan_id)
                except Exception:
                    pass
        _hb_thread = None
        if ckpt and scan_id:
            _hb_thread = threading.Thread(target=_heartbeat_loop, daemon=True, name="ckpt-hb")
            _hb_thread.start()

        def _emit(
            stage: str,
            processed: int,
            total: int,
            current_file: str = "",
            metrics: Optional[Dict[str, Any]] = None,
        ) -> None:
            self._scan_last_emit_p = processed
            self._scan_last_emit_t = max(self._scan_last_emit_t, total, processed)
            cb = self.config.progress_callback
            if cb is None:
                return
            try:
                cb(stage, processed, total, current_file, metrics or {})
                self._last_stage_emitted = stage
            except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
                # Never allow UI callback errors to break scanning.
                pass

        def _pause_gate() -> None:
            """Block here while the engine has cleared the pause event.

            Called at phase boundaries and inside the inner hash worker so
            long-running phases respond to pause() within ~1 file.
            """
            ev = self.config.pause_event
            if ev is not None and not ev.is_set():
                ev.wait()

        # Phase 1: Discovery — skip os.walk when resuming from checkpoint DB.
        _pause_gate()
        user_roots = list(roots)
        scan_roots = dedupe_roots(user_roots)
        if len(scan_roots) != len(user_roots):
            collapsed = [str(r) for r in user_roots if Path(r).resolve() not in {Path(s).resolve() for s in scan_roots}]
            logger.debug(
                "[ROOT_DEDUP] user_roots=%d deduped_roots=%d collapsed=%s",
                len(user_roots), len(scan_roots), collapsed,
            )
        else:
            logger.debug("[ROOT_DEDUP] user_roots=%d deduped_roots=%d (no overlap)", len(user_roots), len(scan_roots))

        _stream_discovery_flag = False
        if resume_mode:
            # Load pending files first, then also load completed files from checkpoint
            # so size-grouping can detect cross-pairs across both sets.
            logger.info("[Turbo] Resume mode: loading pending files from checkpoint (skipping os.walk)")
            # Row cursor counts checkpoint rows validated during reload (not os.walk).
            # Start at 0 so UI can climb monotonically; hashing still uses engine-side
            # checkpoint_completed_offset from TurboFileEngine.
            _emit(
                ScanStage.DISCOVERING,
                0,
                _ckpt_total,
                "Resuming: reading checkpoint (no disk walk yet)…",
                metrics={
                    "total_files_in_scope": _ckpt_total,
                    "files_processed": 0,
                    "candidates_found": 0,
                    "checkpoint_resume": True,
                    "checkpoint_completed_offset": _ckpt_completed_at_start,
                },
            )
            discovered_files: List[Tuple[Path, int, float]] = []
            _resume_ce = self.config.cancel_event
            _resume_checked = 0
            _resume_emit_every = 2048
            _t_last_resume_emit = time.perf_counter()

            def _emit_resume_row_progress() -> None:
                nonlocal _t_last_resume_emit
                now = time.perf_counter()
                if _resume_checked > 1:
                    if (
                        _resume_checked % _resume_emit_every != 0
                        and (now - _t_last_resume_emit) < 0.35
                    ):
                        return
                _t_last_resume_emit = now
                row_n = min(_ckpt_total, _resume_checked)
                _emit(
                    ScanStage.DISCOVERING,
                    row_n,
                    _ckpt_total,
                    f"Resuming: validating paths from checkpoint ({row_n:,} / {_ckpt_total:,})…",
                    metrics={
                        "total_files_in_scope": _ckpt_total,
                        "files_processed": row_n,
                        "candidates_found": 0,
                        "checkpoint_resume": True,
                        "checkpoint_completed_offset": _ckpt_completed_at_start,
                    },
                )

            for batch in ckpt.iter_pending_files(scan_id):
                if _resume_ce is not None and _resume_ce.is_set():
                    logger.info(
                        "[Turbo] Cancel observed during checkpoint pending load: loaded=%d",
                        len(discovered_files),
                    )
                    return
                for path_str, size, mtime in batch:
                    _resume_checked += 1
                    if (_resume_checked % 128) == 0 and _resume_ce is not None and _resume_ce.is_set():
                        logger.info(
                            "[Turbo] Cancel observed during checkpoint pending iteration: checked=%d loaded=%d",
                            _resume_checked,
                            len(discovered_files),
                        )
                        return
                    _emit_resume_row_progress()
                    p = Path(path_str)
                    try:
                        st = p.stat()
                    except OSError:
                        ckpt.enqueue_hash_result(scan_id, path_str, None, None, "error")
                        continue
                    discovered_files.append((p, size, float(st.st_mtime)))
            _pending_count = len(discovered_files)
            # Load completed files so size-grouping catches cross-pairs between
            # already-hashed and pending files (hash_cache will serve them instantly).
            for batch in ckpt.iter_completed_hashes(scan_id):
                if _resume_ce is not None and _resume_ce.is_set():
                    logger.info(
                        "[Turbo] Cancel observed during checkpoint completed load: pending_loaded=%d total_loaded=%d",
                        _pending_count,
                        len(discovered_files),
                    )
                    return
                for path_str, size, mtime, _hash in batch:
                    _resume_checked += 1
                    if (_resume_checked % 128) == 0 and _resume_ce is not None and _resume_ce.is_set():
                        logger.info(
                            "[Turbo] Cancel observed during checkpoint completed iteration: checked=%d total_loaded=%d",
                            _resume_checked,
                            len(discovered_files),
                        )
                        return
                    _emit_resume_row_progress()
                    p = Path(path_str)
                    try:
                        st = p.stat()
                    except OSError:
                        continue
                    discovered_files.append((p, int(size), float(st.st_mtime)))
            row_final = min(_ckpt_total, _resume_checked)
            _emit(
                ScanStage.DISCOVERING,
                row_final,
                _ckpt_total,
                f"Resuming: checkpoint reload done ({row_final:,} / {_ckpt_total:,} rows)…",
                metrics={
                    "total_files_in_scope": _ckpt_total,
                    "files_processed": row_final,
                    "candidates_found": 0,
                    "checkpoint_resume": True,
                    "checkpoint_completed_offset": _ckpt_completed_at_start,
                },
            )
            logger.info("[Turbo] Resume: %d pending + %d completed = %d total files",
                        _pending_count, len(discovered_files) - _pending_count, len(discovered_files))
        else:
            _stream_discovery_flag = False
            logger.info("[Turbo] Phase 1: Discovering files...")
            _emit(
                ScanStage.DISCOVERING,
                0,
                0,
                metrics={"total_files_in_scope": 0, "files_processed": 0, "candidates_found": 0},
            )
            _stream_discovery = bool(ckpt and scan_id and not resume_mode)
            _stream_discovery_flag = _stream_discovery
            discovered_files = self._discover_files_parallel(
                scan_roots,
                emit=_emit,
                stream_to_checkpoint=_stream_discovery,
                scan_id=scan_id if _stream_discovery else None,
                checkpoint_db=ckpt if _stream_discovery else None,
            )
            if _stream_discovery and ckpt and scan_id:
                _ckpt_total = ckpt.count_files(scan_id)
                try:
                    if hasattr(ckpt, "verify_consistency"):
                        ckpt.verify_consistency(scan_id)
                except Exception:
                    logger.debug("[Turbo] checkpoint verify after stream failed", exc_info=True)
            else:
                _ckpt_total = len(discovered_files)
                if ckpt and scan_id and discovered_files:
                    try:
                        ckpt.insert_pending_files(
                            scan_id,
                            [(str(p), sz, mt) for p, sz, mt in discovered_files],
                        )
                        if hasattr(ckpt, "verify_consistency"):
                            ckpt.verify_consistency(scan_id)
                    except Exception:
                        logger.debug(
                            "[Turbo] checkpoint insert_pending_files failed (non-fatal)",
                            exc_info=True,
                        )
            _emit(
                ScanStage.DISCOVERING,
                _ckpt_total,
                _ckpt_total,
                str(discovered_files[-1][0]) if discovered_files else "",
                metrics={
                    "total_files_in_scope": _ckpt_total,
                    "files_processed": _ckpt_total,
                    "candidates_found": 0,
                },
            )
            logger.info(
                "[Turbo] Discovered %d files in %.2fs (streamed=%s)",
                _ckpt_total,
                time.time() - start_time,
                _stream_discovery,
            )
        # True scope for UI metrics: full checkpoint total on resume, discovered count on new scan.
        _scope_total = _ckpt_total if (_ckpt_total > 0) else len(discovered_files)
        _t_discovery_end = time.perf_counter()
        # Phase 2: Group by size (instant duplicate detection)
        _pause_gate()
        _emit(
            ScanStage.GROUPING_BY_SIZE,
            0,
            _scope_total,
            str(discovered_files[0][0]) if discovered_files else "",
            metrics={
                "total_files_in_scope": _scope_total,
                "files_processed": 0,
                "candidates_found": 0,
            },
        )
        _use_db_grouping = bool(ckpt and scan_id) and (
            _stream_discovery_flag or (_scope_total >= STREAMING_THRESHOLD and not resume_mode)
        )
        size_groups = self._group_files_by_size(
            discovered_files=discovered_files,
            ckpt=ckpt,
            scan_id=scan_id,
            use_db_grouping=_use_db_grouping,
            scope_total=_scope_total,
            emit=_emit,
            cancel_event=self.config.cancel_event,
        )
        if not size_groups and self.config.cancel_event is not None and self.config.cancel_event.is_set():
            return
        if not _use_db_grouping:
            logger.info("[Turbo] Found %d size groups with potential duplicates", len(size_groups))
        _rss = _process_rss_mb()
        if _rss is not None:
            logger.info(
                "[Turbo] Post-grouping: scope=%d size_groups=%d rss_mb=%.1f",
                _scope_total,
                len(size_groups),
                _rss,
            )

        # Canonical-path dedup guard: suppress alias/symlink/hardlink/case variants
        # before any hash I/O.  Only activated when enable_prehash_canonical_dedup=True
        # (default False = legacy path unchanged).
        _canonical_dedup_removed = 0
        if self.config.enable_prehash_canonical_dedup and size_groups:
            cleaned: Dict[int, List] = {}
            for sz, entries in size_groups.items():
                seen_canonical: Dict[str, int] = {}  # canonical_key -> first index kept
                kept = []
                for entry in entries:
                    path_obj = entry[0] if isinstance(entry, (tuple, list)) else entry
                    try:
                        canonical_key = os.path.normcase(
                            str(Path(str(path_obj)).resolve())
                        )
                    except (OSError, ValueError):
                        canonical_key = os.path.normcase(str(path_obj))
                    if canonical_key not in seen_canonical:
                        seen_canonical[canonical_key] = 1
                        kept.append(entry)
                    else:
                        _canonical_dedup_removed += 1
                if len(kept) >= 2:
                    cleaned[sz] = kept
            size_groups = cleaned
            if _canonical_dedup_removed:
                logger.info(
                    "[Turbo] Canonical dedup guard: removed %d alias paths, %d size groups remain",
                    _canonical_dedup_removed,
                    len(size_groups),
                )

        _diag_size_candidates = sum(len(v) for v in size_groups.values())
        _t_grouping_end = time.perf_counter()

        if self.config.index_only:
            logger.info(
                "[Turbo] index_only: catalogue complete (%d files, %d size groups) — skipping hash phases",
                _scope_total,
                len(size_groups),
            )
            _emit(
                ScanStage.COMPLETE,
                _scope_total,
                _scope_total,
                "",
                metrics={
                    "total_files_in_scope": _scope_total,
                    "files_processed": _scope_total,
                    "candidates_found": _diag_size_candidates,
                    "index_only": True,
                },
            )
            self._turbo_completed_normally = True
            if _hb_thread is not None:
                _hb_stop.set()
            if ckpt and scan_id:
                try:
                    ckpt.flush_sync()
                    ckpt.update_manifest_status(scan_id, "indexed")
                except Exception:
                    pass
            return

        # Persist size-group artifact for resume (Phase 4).
        if self.config.enable_resume_artifacts and ckpt and scan_id and size_groups:
            try:
                _art_ver = _phase_artifact_version_hash(self.config)
                _art_data = {
                    "size_groups": {
                        str(k): [[str(p), mt] for p, mt in v]
                        for k, v in size_groups.items()
                    }
                }
                ckpt.save_phase_artifact(scan_id, "size_groups", _art_data, _art_ver)
            except Exception:
                pass

        # Tier-A pre-filter (4 KiB prefix hash) — cheaply rejects non-matches before
        # the more expensive 64 KiB quick-hash phase.  Runs only when quick-hash is
        # enabled (the tier-A read is a strict prefix of what quick-hash reads anyway).
        _t_tier_a_start = time.perf_counter()
        _tier_a_rejected = 0
        _tier_a_in = 0
        self._tier_a_groups_escalated = 0  # reset before each scan; updated inside _apply_tier_a_filter
        if self.config.use_quick_hash and size_groups:
            _pause_gate()
            logger.info(
                "[Turbo] Grouping finished -> Tier-A started: size_groups=%d candidates=%d",
                len(size_groups),
                _diag_size_candidates,
            )
            _effective_algo_for_tier_a = str(self.config.hash_algorithm or "auto").lower()
            if _effective_algo_for_tier_a == "auto":
                _effective_algo_for_tier_a = "xxhash" if xxhash is not None else "sha256"
            size_groups, _tier_a_in, _tier_a_out = self._apply_tier_a_filter(
                size_groups,
                _effective_algo_for_tier_a,
                self.config.cancel_event,
                discovered_count=_scope_total,
                emit=_emit,
                scope_total=_scope_total,
            )
            _tier_a_rejected = max(0, _tier_a_in - _tier_a_out)
            _tier_a_elapsed = time.perf_counter() - _t_tier_a_start
            _tier_a_workers_used = (
                self.config.tier_a_workers
                if (self.config.enable_phase_worker_policy and self.config.tier_a_workers > 0)
                else max(2, min(self.config.hash_workers, 16))
            )
            logger.info(
                "[Turbo] Tier-A filter: candidates_in=%d survivors=%d rejected=%d (%.1f%%) "
                "in %.2fs (%.0f cand/s, workers=%d)",
                _tier_a_in,
                _tier_a_out,
                _tier_a_rejected,
                100.0 * _tier_a_rejected / max(1, _tier_a_in),
                _tier_a_elapsed,
                _tier_a_in / max(1e-6, _tier_a_elapsed),
                _tier_a_workers_used,
            )
            _ta_ch = self.stats.get('tier_a_cache_hits', 0)
            _ta_cm = self.stats.get('tier_a_cache_misses', 0)
            if _ta_ch or _ta_cm:
                logger.info(
                    "[Turbo] Tier-A prefix cache: hits=%d misses=%d (%.1f%% reads avoided)",
                    _ta_ch,
                    _ta_cm,
                    100.0 * _ta_ch / max(1, _ta_ch + _ta_cm),
                )
            # Persist Tier-A survivors for resume (Phase 4).
            if self.config.enable_resume_artifacts and ckpt and scan_id and size_groups:
                try:
                    _art_ver = _phase_artifact_version_hash(self.config)
                    _art_data = {
                        "size_groups": {
                            str(k): [[str(p), mt] for p, mt in v]
                            for k, v in size_groups.items()
                        }
                    }
                    ckpt.save_phase_artifact(scan_id, "tier_a_survivors", _art_data, _art_ver)
                except Exception:
                    pass
        _t_tier_a_end = time.perf_counter()

        # Phase 3: Quick hash for size groups (parallel with caching)
        _pause_gate()
        candidates_found = sum(len(v) for v in size_groups.values()) if size_groups else 0
        _grp_sample = ""
        if size_groups:
            _v0 = next(iter(size_groups.values()))
            if _v0:
                _grp_sample = str(_v0[0][0])
        _emit(
            ScanStage.GROUPING_BY_SIZE,
            _scope_total,
            _scope_total,
            _grp_sample,
            metrics={
                "total_files_in_scope": _scope_total,
                "files_processed": _scope_total,
                "candidates_found": candidates_found,
            },
        )
        if self.config.use_quick_hash and size_groups:
            logger.info("[Turbo] Phase 2: Computing quick hashes...")
            quick_hash_groups = self._compute_hashes_parallel(
                size_groups, 
                quick=True,
                emit=_emit,
                stage_name=ScanStage.HASHING_PARTIAL,
            )
            logger.info("[Turbo] Found %d quick-hash groups", len(quick_hash_groups))
        else:
            quick_hash_groups = size_groups
        _t_quick_hash_end = time.perf_counter()

        # Phase 4: Full hash if needed (parallel with caching)
        _pause_gate()
        if self.config.use_full_hash and quick_hash_groups:
            logger.info("[Turbo] Phase 3: Computing full hashes...")
            final_groups = self._compute_hashes_parallel(
                quick_hash_groups,
                quick=False,
                emit=_emit,
                stage_name=ScanStage.HASHING_FULL,
            )
            logger.info("[Turbo] Found %d duplicate groups", len(final_groups))
        else:
            final_groups = quick_hash_groups
        _t_full_hash_end = time.perf_counter()

        # Expose groups for Review page (worker reads scanner.last_groups)
        def _group_recoverable(paths_list):
            total = 0
            for p, _ in paths_list:
                try:
                    total += Path(str(p)).stat().st_size
                except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
                    pass
            return total

        self.last_groups = [
            {
                "paths": [str(p) for p, _ in paths],
                "hash": str(h),
                "count": len(paths),
                "recoverable_bytes": _group_recoverable(paths),
            }
            for h, paths in (final_groups.items() if final_groups else [])
            if len(paths) >= 2
        ]

        # Phase 5: Yield results
        _ce = self.config.cancel_event
        discovered_count = _scope_total
        candidate_count = sum(len(v) for v in final_groups.values()) if final_groups else 0
        emitted_count = 0
        meta_errors = 0
        _guard_regressions = 0
        _guard_checked = 0
        _guard_files_checked = 0

        for yi, (h, group_paths) in enumerate(final_groups.items()):
            if yi % 48 == 0 and _ce is not None and _ce.is_set():
                return
            group_paths, _r = _assert_no_self_duplicates(group_paths, group_key=h)
            _guard_regressions += _r
            _guard_checked += 1
            _guard_files_checked += len(group_paths)
            if len(group_paths) < 2:
                continue
            for path, _ in group_paths:
                try:
                    # Be robust: FileMetadata may expect a string path
                    meta = FileMetadata.from_path(str(path))
                    if meta is not None:
                        yield meta
                        emitted_count += 1
                except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
                    meta_errors += 1
                    continue

        # Update statistics
        elapsed = time.time() - start_time
        self.stats['elapsed_time'] = elapsed
        # 'files_scanned' should reflect what we actually scanned/discovered
        self.stats['files_scanned'] = discovered_count
        self.stats['files_discovered'] = discovered_count
        self.stats['files_in_candidate_groups'] = candidate_count
        self.stats['files_emitted'] = emitted_count
        self.stats['metadata_errors'] = meta_errors

        logger.info("[Turbo] Scan complete")
        logger.debug(
            "[DIAG:GUARD] groups_checked=%d total_files_checked=%d regressions=%d",
            _guard_checked, _guard_files_checked, _guard_regressions,
        )
        logger.info("Discovered: %d", discovered_count)
        logger.info(
            "Files in final duplicate groups (path rows before metadata): %d",
            candidate_count,
        )
        logger.info(
            "File records yielded to engine (successful metadata, incl. all copies): %d",
            emitted_count,
        )
        if meta_errors:
            logger.warning("File metadata failures while emitting: %d", meta_errors)
        logger.info("Time: %.2fs", elapsed)
        if elapsed > 0:
            logger.info("Speed: %.0f files/sec", discovered_count / elapsed)
        else:
            logger.info("Speed: n/a (instant phase)")
        logger.info("Cache hits: %d", self.stats["hash_cache_hits"])
        logger.info("Cache misses: %d", self.stats["hash_cache_misses"])
        if self.stats['hash_cache_hits'] + self.stats['hash_cache_misses'] > 0:
            hit_rate = self.stats['hash_cache_hits'] / (self.stats['hash_cache_hits'] + self.stats['hash_cache_misses']) * 100
            logger.info("Hit rate: %.1f%%", hit_rate)
        _t_yield_end = time.perf_counter()
        _total_cache = self.stats["hash_cache_hits"] + self.stats["hash_cache_misses"]
        _hit_pct = (self.stats["hash_cache_hits"] / _total_cache * 100) if _total_cache else 0.0
        _final_ngroups = len(final_groups) if final_groups else 0
        logger.info(
            "[Turbo] Phase timings: discovery=%.2fs grouping=%.2fs tier_a=%.2fs "
            "quick_hash=%.2fs full_hash=%.2fs yield=%.2fs total=%.2fs",
            _t_discovery_end - _t_scan_start,
            _t_grouping_end - _t_discovery_end,
            _t_tier_a_end - _t_grouping_end,
            _t_quick_hash_end - _t_tier_a_end,
            _t_full_hash_end - _t_quick_hash_end,
            _t_yield_end - _t_full_hash_end,
            _t_yield_end - _t_scan_start,
        )
        _tier_a_groups_escalated = getattr(self, "_tier_a_groups_escalated", 0)
        logger.info(
            "[Turbo] summary: discovered=%d canonical_dedup_removed=%d "
            "tier_a_groups_escalated=%d files_in_size_candidate_groups=%d "
            "final_duplicate_groups=%d file_rows_emitted=%d elapsed=%.2fs "
            "cache_hits=%d cache_misses=%d cache_hit_pct=%.1f%%",
            discovered_count,
            _canonical_dedup_removed,
            _tier_a_groups_escalated,
            _diag_size_candidates,
            _final_ngroups,
            emitted_count,
            elapsed,
            self.stats["hash_cache_hits"],
            self.stats["hash_cache_misses"],
            _hit_pct,
        )
        try:
            import psutil

            global _LAST_PROCESS_RSS_MB
            rss_mb = psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024)
            if _LAST_PROCESS_RSS_MB is None:
                logger.info("Process RSS after scan: %.1f MiB", rss_mb)
            else:
                logger.info(
                    "Process RSS after scan: %.1f MiB (delta %+.1f MiB vs previous scan)",
                    rss_mb,
                    rss_mb - _LAST_PROCESS_RSS_MB,
                )
            _LAST_PROCESS_RSS_MB = rss_mb
        except (OSError, ValueError, RuntimeError, AttributeError, ImportError, TypeError):
            pass
        ce = self.config.cancel_event
        _was_cancelled = ce is not None and ce.is_set()

        # Stop heartbeat and flush remaining checkpoint writes.
        if _hb_thread is not None:
            _hb_stop.set()
        if ckpt and scan_id:
            try:
                ckpt.flush_sync()
                new_status = "active" if _was_cancelled else "completed"
                ckpt.update_manifest_status(scan_id, new_status)
                if hasattr(ckpt, "verify_consistency"):
                    ckpt.verify_consistency(scan_id)
                _final_total, _final_pending = ckpt.get_counts(scan_id)
                logger.info(
                    "[Turbo] checkpoint terminal: scan_id=%s status=%s total=%d pending=%d completed=%d",
                    scan_id,
                    new_status,
                    _final_total,
                    _final_pending,
                    max(0, _final_total - _final_pending),
                )
            except Exception:
                pass

        if not _was_cancelled:
            self._turbo_completed_normally = True
            _emit(
                ScanStage.COMPLETE,
                discovered_count,
                discovered_count,
                metrics={
                    "total_files_in_scope": discovered_count,
                    "files_processed": discovered_count,
                    "candidates_found": candidates_found,
                    "canonical_dedup_removed": _canonical_dedup_removed,
                    "tier_a_groups_escalated": _tier_a_groups_escalated,
                },
            )

    def force_emit_cancel_terminal_if_needed(self) -> None:
        """Emit CANCELLED if cancel is set but COMPLETE never ran (consumer broke early).

        Called from TurboFileEngine when the generator loop ends so UI never hangs
        waiting for a terminal stage.
        """
        if getattr(self, "_turbo_completed_normally", False):
            return
        if getattr(self, "_last_stage_emitted", "") == ScanStage.CANCELLED:
            return
        evt = self.config.cancel_event
        cb = self.config.progress_callback
        if cb is None or evt is None or not evt.is_set():
            return
        lp = int(getattr(self, "_scan_last_emit_p", 0) or 0)
        lt = max(int(getattr(self, "_scan_last_emit_t", 0) or 0), lp)
        try:
            cb(ScanStage.CANCELLED, lp, lt, "")
            self._last_stage_emitted = ScanStage.CANCELLED
        except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
            pass

    def _group_files_by_size(
        self,
        *,
        discovered_files: List[Tuple[Path, int, float]],
        ckpt: Optional[object],
        scan_id: Optional[str],
        use_db_grouping: bool,
        scope_total: int,
        emit: Callable[..., None],
        cancel_event: Optional[threading.Event],
    ) -> Dict[Any, List[Tuple[Path, float]]]:
        """Build size_groups with len>=2. DB path uses O(bucket) memory."""
        size_groups: Dict[Any, List[Tuple[Path, float]]] = {}
        _ce = cancel_event
        _group_total = max(1, scope_total)
        _next_group_pct_log = 10
        _last_group_emit = 0
        _cancel_log_grouping_emitted = False
        processed = 0

        def _flush_bucket(size_key: int, bucket: List[Tuple[Path, float]]) -> None:
            if len(bucket) >= 2:
                size_groups[size_key] = bucket

        if use_db_grouping and ckpt is not None and scan_id:
            current_size: Optional[int] = None
            bucket: List[Tuple[Path, float]] = []
            for path_str, size, mtime in ckpt.iter_files_by_size(scan_id, statuses=("pending",)):
                if processed % 128 == 0 and _ce is not None and _ce.is_set():
                    if not _cancel_log_grouping_emitted:
                        logger.info(
                            "[Turbo] Cancel during DB grouping at %d/%d",
                            processed,
                            _group_total,
                        )
                        _cancel_log_grouping_emitted = True
                    return {}
                if current_size is not None and size != current_size:
                    _flush_bucket(current_size, bucket)
                    bucket = []
                current_size = size
                bucket.append((Path(path_str), mtime))
                processed += 1
                if processed - _last_group_emit >= 512 or processed == _group_total:
                    _last_group_emit = processed
                    emit(
                        ScanStage.GROUPING_BY_SIZE,
                        processed,
                        _group_total,
                        path_str,
                        metrics={
                            "total_files_in_scope": _group_total,
                            "files_processed": processed,
                            "candidates_found": 0,
                        },
                    )
            if current_size is not None:
                _flush_bucket(current_size, bucket)
        else:
            for gi, (path, size, mtime) in enumerate(discovered_files):
                if gi % 128 == 0 and _ce is not None and _ce.is_set():
                    if not _cancel_log_grouping_emitted:
                        logger.info(
                            "[Turbo] Cancel observed during grouping_by_size: processed=%d/%d",
                            gi,
                            _group_total,
                        )
                        _cancel_log_grouping_emitted = True
                    return {}
                if size not in size_groups:
                    size_groups[size] = []
                size_groups[size].append((path, mtime))
                processed = gi + 1
                pct = int((processed / _group_total) * 100)
                if pct >= _next_group_pct_log:
                    logger.info(
                        "[Turbo] Grouping progress: %d%% (%d/%d)",
                        pct,
                        processed,
                        _group_total,
                    )
                    _next_group_pct_log += 10
                if processed - _last_group_emit >= 512 or processed == _group_total:
                    _last_group_emit = processed
                    emit(
                        ScanStage.GROUPING_BY_SIZE,
                        processed,
                        _group_total,
                        str(path),
                        metrics={
                            "total_files_in_scope": _group_total,
                            "files_processed": processed,
                            "candidates_found": 0,
                        },
                    )
            size_groups = {k: v for k, v in size_groups.items() if len(v) >= 2}
            return size_groups

        logger.info("[Turbo] Found %d size groups with potential duplicates (DB path)", len(size_groups))
        return size_groups

    def _discover_files_parallel(
        self,
        roots: List[Path],
        emit: Optional[Callable[..., None]] = None,
        *,
        stream_to_checkpoint: bool = False,
        scan_id: Optional[str] = None,
        checkpoint_db: Optional[object] = None,
    ) -> List[Tuple[Path, int, float]]:
        """
        Discover all files using parallel directory traversal.
        
        Uses multiprocessing to scan multiple directories simultaneously.
        """
        all_files: List[Tuple[Path, int, float]] = []
        discovered_so_far = 0

        dirs_to_scan: List[Path] = []
        for root in roots:
            if not root.exists():
                continue

            if root.is_file():
                try:
                    stat = root.stat()
                    row = (root, stat.st_size, stat.st_mtime)
                    if stream_to_checkpoint and checkpoint_db is not None and scan_id:
                        checkpoint_db.insert_pending_files_batch(
                            scan_id,
                            [(str(root), stat.st_size, stat.st_mtime)],
                            update_total=True,
                        )
                        discovered_so_far += 1
                    else:
                        all_files.append(row)
                except OSError:
                    pass
                continue

            if self.config.incremental and self.dir_cache:
                if not self.dir_cache.has_changed(root):
                    cached_files = self.dir_cache.get_files(root)
                    if cached_files is not None:
                        self.stats['directories_skipped'] += 1
                        if stream_to_checkpoint and checkpoint_db is not None and scan_id:
                            checkpoint_db.insert_pending_files_batch(
                                scan_id,
                                [(str(p), sz, mt) for p, sz, mt in cached_files],
                                update_total=True,
                            )
                            discovered_so_far += len(cached_files)
                        else:
                            all_files.extend(cached_files)
                        continue
                    # Signature unchanged but no file cache yet — fall through to scan.

            dirs_to_scan.append(root)

        if not dirs_to_scan and not stream_to_checkpoint:
            return all_files

        ex_dirs = effective_exclude_dirs(self.config)
        worker_tpl = (
            self.config.skip_hidden,
            ex_dirs,
            self.config.exclude_paths,
            self.config.recursive,
            self.config.min_size,
            self.config.max_size,
            self.config.scan_archives,
            self.config.skip_system,
        )
        use_mp = bool(self.config.use_multiprocessing and len(dirs_to_scan) > 1)
        worker_args = []
        for d in dirs_to_scan:
            tup: Tuple[Any, ...] = (d,) + worker_tpl
            if not use_mp:
                tup = tup + (self.config.cancel_event,)
            worker_args.append(tup)

        def _ingest_worker_results(results: List[Tuple[Path, int, float]], root_dir: Path) -> None:
            nonlocal discovered_so_far
            if stream_to_checkpoint and checkpoint_db is not None and scan_id:
                rows = [(str(p), int(sz), float(mt)) for p, sz, mt in results]
                if rows:
                    checkpoint_db.insert_pending_files_batch(
                        scan_id, rows, update_total=True
                    )
                discovered_so_far += len(results)
            else:
                all_files.extend(results)
                discovered_so_far += len(results)
            if emit and discovered_so_far % 100 <= max(1, len(results)):
                emit(ScanStage.DISCOVERING, discovered_so_far, 0, str(root_dir))
            if self.dir_cache and results and not stream_to_checkpoint:
                sig = DirectorySignature.from_directory(root_dir)
                if sig:
                    self.dir_cache.put(sig)
                    self.dir_cache.set_files(root_dir, results)

        def _shutdown_exec(ex: Optional[Any]) -> None:
            if ex is None:
                return
            try:
                ex.shutdown(wait=False, cancel_futures=True)
            except TypeError:
                ex.shutdown(wait=False)

        def _collect(
            future_to_root: Dict[Any, Any],
            executor: Optional[Any],
            warn_prefix: str,
        ) -> None:
            """Drain futures; poll cancel continuously while waiting for workers."""
            nonlocal discovered_so_far
            pending = set(future_to_root.keys())
            while pending:
                if self.config.cancel_event is not None and self.config.cancel_event.is_set():
                    logger.info(
                        "[Turbo] Cancel observed during discovery collect: completed=%d pending=%d",
                        len(future_to_root) - len(pending),
                        len(pending),
                    )
                    _shutdown_exec(executor)
                    return
                done, pending = wait(
                    pending,
                    timeout=0.25,
                    return_when=FIRST_COMPLETED,
                )
                if not done:
                    continue
                for future in done:
                    if self.config.cancel_event is not None and self.config.cancel_event.is_set():
                        logger.info(
                            "[Turbo] Cancel observed while handling discovery result: completed=%d pending=%d",
                            len(future_to_root) - len(pending) - 1,
                            len(pending),
                        )
                        _shutdown_exec(executor)
                        return
                root_dir = future_to_root[future]
                try:
                    results = future.result()
                    _ingest_worker_results(results, root_dir)
                except OSError as e:
                    logger.warning("%s: %s", warn_prefix, e)
                    if emit:
                        emit("network_error", discovered_so_far, 0, f"Network path unreachable: {root_dir}")
                except Exception as e:
                    logger.warning("%s: %s", warn_prefix, e)
                    if emit:
                        emit("network_error", discovered_so_far, 0, f"Network path unreachable: {root_dir}")

        if self.config.use_multiprocessing and len(dirs_to_scan) > 1:
            workers = min(self.config.dir_workers, len(dirs_to_scan))
            mp_exec = ProcessPoolExecutor(max_workers=workers)
            try:
                future_to_root_mp = {
                    mp_exec.submit(walk_directory_worker, args): d
                    for args, d in zip(worker_args, dirs_to_scan)
                }
                _collect(future_to_root_mp, mp_exec, "[Turbo] Worker error")
            finally:
                _shutdown_exec(mp_exec)
        else:
            # Threads share cancel_event end-to-end; avoid ``with ThreadPoolExecutor``
            # alone so cancelled scans don't block on executor __exit__(wait=True).
            workers = min(self.config.dir_workers, max(1, len(dirs_to_scan)))
            th_exec = ThreadPoolExecutor(max_workers=workers)
            try:
                future_to_root_th = {
                    th_exec.submit(walk_directory_worker, args): d
                    for args, d in zip(worker_args, dirs_to_scan)
                }
                _collect(
                    future_to_root_th,
                    th_exec,
                    "[Turbo] Worker error walking directory",
                )
            finally:
                _shutdown_exec(th_exec)

        return all_files
    
    def _compute_hashes_parallel(
        self, 
        groups: Dict[Any, List[Tuple[Path, float]]],
        quick: bool = True,
        emit: Optional[Callable[..., None]] = None,
        stage_name: str = ScanStage.HASHING_PARTIAL,
    ) -> Dict[str, List[Tuple[Path, float]]]:
        """
        Compute hashes in parallel with caching.
        
        Returns: Dictionary mapping hash -> list of (path, mtime)
        """
        hash_groups = defaultdict(list)
        
        # Flatten groups into list of files to hash
        files_to_hash = []
        for paths in groups.values():
            files_to_hash.extend(paths)
        
        if not files_to_hash:
            return {}

        effective_algorithm = str(self.config.hash_algorithm or "xxhash").lower()
        if effective_algorithm == "auto":
            sample_paths = [p for p, _ in files_to_hash[:24]]
            effective_algorithm = self._auto_pick_hash_algorithm(sample_paths, quick=quick)
            logger.info(
                "[Turbo] auto hash selection: phase=%s picked=%s sample=%d",
                stage_name,
                effective_algorithm,
                len(sample_paths),
            )

        total = len(files_to_hash)
        # With hash cache: count stat/prep + hash as two halves so the progress bar
        # never jumps backwards when the thread pool starts (prep reached N, then
        # hash counted from 1 again).
        work_total = total * 2 if self.hash_cache else total
        prep_done = total if self.hash_cache else 0

        pause_event = self.config.pause_event
        cancel_event = self.config.cancel_event
        _cancel_log_prefetch_emitted = False
        _cancel_log_hash_emit_emitted = False
        _cancel_log_post_pool_emitted = False

        if emit and total > 0:
            try:
                emit(
                    stage_name,
                    0,
                    work_total,
                    "",
                    {
                        "total_files_in_scope": total,
                        "files_processed": 0,
                        "candidates_found": total,
                        "active_hash_algorithm": effective_algorithm,
                    },
                )
            except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
                pass

        # Pre-fetch all cache entries in batch to avoid one SQLite query per file.
        # StatSignature.from_path() does a stat() per file but that is still far
        # cheaper than N individual "SELECT ... WHERE path=?" round-trips at scale.
        # Emit progress here: this loop can take minutes on huge candidate sets and
        # previously produced zero UI updates until the first hash completed.
        _batch_cache: Dict[str, Optional[str]] = {}
        if self.hash_cache:
            _batch_paths = [str(p) for p, _ in files_to_hash]
            _batch_sigs: Dict[str, Any] = {}
            _prep_emit = time.monotonic()
            for idx, (p, _) in enumerate(files_to_hash):
                if cancel_event is not None and cancel_event.is_set():
                    if not _cancel_log_prefetch_emitted:
                        logger.info(
                            "[Turbo] Cancel observed during %s prefetch: prepared=%d/%d",
                            stage_name,
                            idx,
                            total,
                        )
                        _cancel_log_prefetch_emitted = True
                    return {}
                try:
                    _batch_sigs[str(p)] = StatSignature.from_path(p)
                except OSError:
                    pass
                _now = time.monotonic()
                if emit and (
                    idx == 0
                    or idx % 200 == 0
                    or idx == len(files_to_hash) - 1
                    or (_now - _prep_emit) >= 0.3
                ):
                    _prep_emit = _now
                    try:
                        emit(
                            stage_name,
                            min(idx + 1, total),
                            work_total,
                            str(p),
                            {
                                "total_files_in_scope": total,
                                "files_processed": min(idx + 1, total),
                                "candidates_found": total,
                                "active_hash_algorithm": effective_algorithm,
                            },
                        )
                    except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
                        pass
            if cancel_event is not None and cancel_event.is_set():
                if not _cancel_log_prefetch_emitted:
                    logger.info(
                        "[Turbo] Cancel observed during %s prefetch finalization: prepared=%d/%d",
                        stage_name,
                        len(_batch_sigs),
                        total,
                    )
                    _cancel_log_prefetch_emitted = True
                return {}
            # Page SQLite cache reads (cancel checked immediately before each query).
            # Adaptive chunk sizing keeps cold / network disks responsive.
            n_paths = len(_batch_paths)
            chunk_sz = 2000
            min_chunk = 400
            slow_slice_s = 0.55
            page_off = 0
            max_pages = max(512, (n_paths // max(1, min_chunk)) + 64)
            page_iter = 0

            while page_off < n_paths:
                if cancel_event is not None and cancel_event.is_set():
                    if not _cancel_log_prefetch_emitted:
                        logger.info(
                            "[Turbo] Cancel observed during %s cache-page scan: page_off=%d/%d",
                            stage_name,
                            page_off,
                            n_paths,
                        )
                        _cancel_log_prefetch_emitted = True
                    return {}

                slice_paths = _batch_paths[page_off : page_off + chunk_sz]
                if not slice_paths:
                    break
                slice_sigs = {p: _batch_sigs[p] for p in slice_paths if p in _batch_sigs}

                if cancel_event is not None and cancel_event.is_set():
                    if not _cancel_log_prefetch_emitted:
                        logger.info(
                            "[Turbo] Cancel observed before %s cache lookup: page_off=%d/%d",
                            stage_name,
                            page_off,
                            n_paths,
                        )
                        _cancel_log_prefetch_emitted = True
                    return {}

                dt_sql = 0.0
                if slice_sigs:
                    t0_sql = time.monotonic()
                    if quick:
                        part = self.hash_cache.get_many_quick(
                            slice_paths,
                            slice_sigs,
                            expected_algo=effective_algorithm,
                        )
                    else:
                        part = self.hash_cache.get_many_full(
                            slice_paths,
                            slice_sigs,
                            expected_algo=effective_algorithm,
                        )
                    dt_sql = time.monotonic() - t0_sql
                    _batch_cache.update(part)

                adv = len(slice_paths)
                page_off += adv
                page_iter += 1
                if page_iter > max_pages:
                    logger.warning(
                        "[Turbo] hash-cache prefetch exceeded page budget (%s); stopping prefetch",
                        max_pages,
                    )
                    break

                if slice_sigs and dt_sql > slow_slice_s and chunk_sz > min_chunk:
                    chunk_sz = max(min_chunk, chunk_sz // 2)

                if emit:
                    done = min(page_off, n_paths)
                    tail = slice_paths[-1] if slice_paths else ""
                    hint = f"Retrieving cached signatures ({done:,} / {n_paths:,})"
                    msg = f"{hint} — {tail}" if tail else hint
                    try:
                        emit(
                            stage_name,
                            total,
                            work_total,
                            msg,
                            {
                                "total_files_in_scope": total,
                                "files_processed": total,
                                "candidates_found": total,
                                "active_hash_algorithm": effective_algorithm,
                            },
                        )
                    except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
                        pass

        # Use thread pool (not process pool) for hashing to share cache.
        # When phase_worker_policy is enabled, use a phase-specific cap; otherwise
        # fall back to hash_workers (legacy behaviour preserved exactly).
        if self.config.enable_phase_worker_policy:
            if stage_name in (ScanStage.HASHING_PARTIAL,):
                _phase_cap = self.config.quick_hash_workers or self.config.hash_workers
            else:
                # ScanStage.HASHING_FULL or any other stage → full-hash cap
                _phase_cap = self.config.full_hash_workers or self.config.hash_workers
        else:
            _phase_cap = self.config.hash_workers
        workers = max(1, min(_phase_cap, len(files_to_hash)))
        _ckpt = self.config.checkpoint_db
        _sid = self.config.scan_id

        # For full-hash phase with cache: workers compute but do NOT write to cache.
        # The as_completed loop collects results and batch-writes via set_many_full().
        # For quick-hash phase and no-cache path: original per-file write behaviour.
        _batch_write_full = (not quick) and (self.hash_cache is not None)

        def hash_worker(path_mtime: Tuple[Path, float]) -> Tuple[Path, float, Optional[str]]:
            path, mtime = path_mtime
            # Per-file pause gate. Blocks the worker (not the executor) so
            # paused workers free up no CPU but also do no I/O. The check is
            # before any read so an interrupted file is never half-processed.
            if pause_event is not None and not pause_event.is_set():
                pause_event.wait()
            if cancel_event is not None and cancel_event.is_set():
                return path, mtime, None
            path_str = str(path)
            # Fast path: batch pre-fetch already validated the sig.
            if path_str in _batch_cache:
                cached = _batch_cache[path_str]
                if cached:
                    self.stats['hash_cache_hits'] += 1
                    return path, mtime, cached
            if self.hash_cache:
                if _batch_write_full:
                    # Full-hash batch path: _batch_cache already contains every
                    # prefetched hit; any path that reaches here is a confirmed
                    # miss — compute without an extra DB round-trip.
                    hash_val = compute_full_hash_mmap(path, effective_algorithm)
                    self.stats['hash_cache_misses'] += 1
                else:
                    hash_val = compute_hash_cached(
                        path,
                        self.hash_cache,
                        effective_algorithm,
                        quick=quick,
                    )
                    if hash_val:
                        self.stats['hash_cache_hits'] += 1
                    else:
                        self.stats['hash_cache_misses'] += 1
            else:
                if quick:
                    hash_val = compute_quick_hash_fast(path, effective_algorithm)
                else:
                    hash_val = compute_full_hash_mmap(path, effective_algorithm)

            # Checkpoint only on final hash phase to avoid double-counting.
            if not quick and _ckpt and _sid:
                try:
                    status = "complete" if hash_val else "error"
                    _ckpt.enqueue_hash_result(_sid, path_str, hash_val, None, status)
                except Exception:
                    pass

            return path, mtime, hash_val

        executor = ThreadPoolExecutor(max_workers=workers)
        cancel_aborted = False
        try:
            # Chunked submit so cancel is honored before every task is queued (huge
            # candidate sets otherwise spend seconds only in list-comprehension submit).
            futures = []
            _submit_chunk = 4096
            for i in range(0, len(files_to_hash), _submit_chunk):
                if cancel_event is not None and cancel_event.is_set():
                    if not _cancel_log_hash_emit_emitted:
                        logger.info(
                            "[Turbo] Cancel observed before %s worker submit: queued=%d/%d",
                            stage_name,
                            len(futures),
                            total,
                        )
                        _cancel_log_hash_emit_emitted = True
                    cancel_aborted = True
                    break
                for pm in files_to_hash[i : i + _submit_chunk]:
                    futures.append(executor.submit(hash_worker, pm))
            processed = 0
            _last_emit_time = time.monotonic()
            _current_file = ""
            # Batch accumulator for full-hash cache writes (Phase 5).
            _full_hash_batch: list = []
            _FULL_HASH_FLUSH_SIZE = 500

            if cancel_aborted:
                pass
            else:
                for future in as_completed(futures):
                    _path_for_emit = ""
                    try:
                        path, mtime, hash_val = future.result()
                        _path_for_emit = str(path)
                        if hash_val:
                            hash_groups[hash_val].append((path, mtime))
                            # Collect for batch write when in full-hash batch mode.
                            if _batch_write_full:
                                p_sig = _batch_sigs.get(str(path))
                                if p_sig is not None:
                                    _full_hash_batch.append(
                                        (path, p_sig, hash_val, effective_algorithm)
                                    )
                    except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
                        pass
                    finally:
                        processed += 1
                        _current_file = _path_for_emit
                        _now = time.monotonic()
                        # Every 200 completions or 0.3s — keeps UI + cancellation responsive.
                        if emit and (
                            processed <= 1
                            or processed % 200 == 0
                            or processed == total
                            or (_now - _last_emit_time) >= 0.3
                        ):
                            _last_emit_time = _now
                            completed_units = prep_done + processed
                            normalized_files_done = min(
                                total,
                                int((completed_units / max(1, work_total)) * total),
                            )
                            emit(
                                stage_name,
                                completed_units,
                                work_total,
                                _current_file,
                                {
                                    "total_files_in_scope": total,
                                    "files_processed": normalized_files_done,
                                    "candidates_found": total,
                                    "active_hash_algorithm": effective_algorithm,
                                },
                            )
                        # Flush batch every _FULL_HASH_FLUSH_SIZE results.
                        if _batch_write_full and len(_full_hash_batch) >= _FULL_HASH_FLUSH_SIZE:
                            try:
                                self.hash_cache.set_many_full(_full_hash_batch)
                            except Exception:
                                pass
                            _full_hash_batch = []
                    if cancel_event is not None and cancel_event.is_set():
                        if not _cancel_log_hash_emit_emitted:
                            logger.info(
                                "[Turbo] Cancel observed during %s hashing: completed=%d/%d",
                                stage_name,
                                processed,
                                total,
                            )
                            _cancel_log_hash_emit_emitted = True
                        cancel_aborted = True
                        break
                # Flush remaining batch after loop.
                if _batch_write_full and _full_hash_batch:
                    try:
                        self.hash_cache.set_many_full(_full_hash_batch)
                    except Exception:
                        pass
                    _full_hash_batch = []
        finally:
            try:
                if cancel_aborted:
                    executor.shutdown(wait=False, cancel_futures=True)
                else:
                    executor.shutdown(wait=True)
            except TypeError:
                executor.shutdown(wait=False if cancel_aborted else True)
            # Hashing uses short-lived worker thread pools; each worker may create a
            # dedicated SQLite connection in HashCache. Proactively close those
            # connections after every hash phase so rescans do not accumulate them.
            if self.hash_cache is not None:
                try:
                    self.hash_cache.close_all_connections()
                except (sqlite3.Error, OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
                    pass

        # Filter out groups with only one file
        if cancel_event is not None and cancel_event.is_set() and not _cancel_log_post_pool_emitted:
            logger.info(
                "[Turbo] %s unwind complete after cancel: hash_groups=%d",
                stage_name,
                len(hash_groups),
            )
            _cancel_log_post_pool_emitted = True
        return {k: v for k, v in hash_groups.items() if len(v) >= 2}

    def _auto_pick_hash_algorithm(self, sample_paths: List[Path], *, quick: bool) -> str:
        candidates = _algorithms_for_auto_pick()
        if not candidates:
            return "sha256"
        if len(candidates) == 1:
            return candidates[0]
        if not sample_paths:
            return candidates[0]

        elapsed_by_algo: Dict[str, float] = {}
        for algo in candidates:
            t0 = time.monotonic()
            ok = 0
            for p in sample_paths:
                try:
                    hv = (
                        compute_quick_hash_fast(p, algo)
                        if quick
                        else compute_full_hash_mmap(p, algo)
                    )
                    if hv:
                        ok += 1
                except OSError:
                    continue
            dt = max(0.000001, time.monotonic() - t0)
            if ok > 0:
                elapsed_by_algo[algo] = dt
        if not elapsed_by_algo:
            return "sha256"
        return min(elapsed_by_algo.items(), key=lambda kv: kv[1])[0]
    
    def close(self):
        """Clean up resources."""
        if self.hash_cache:
            self.hash_cache.close()
        if self.tier_a_cache:
            try:
                self.tier_a_cache.close()
            except sqlite3.Error:
                pass
    
    def __enter__(self):
        return self
    
    def __exit__(self, *args):
        self.close()


# ============================================================================
# CONVENIENCE FUNCTIONS
# ============================================================================

def quick_scan(roots: List[Path], **kwargs) -> List[FileMetadata]:
    """
    Quick scan with default settings optimized for speed.
    
    Usage:
        files = quick_scan([Path("/data")])
    """
    config = TurboScanConfig(**kwargs)
    scanner = TurboScanner(config)
    
    try:
        return list(scanner.scan(roots))
    finally:
        scanner.close()


def incremental_scan(roots: List[Path], **kwargs) -> List[FileMetadata]:
    """
    Incremental scan that uses caching to skip unchanged directories.
    
    Usage:
        files = incremental_scan([Path("/data")])
    """
    config = TurboScanConfig(incremental=True, **kwargs)
    scanner = TurboScanner(config)
    
    try:
        return list(scanner.scan(roots))
    finally:
        scanner.close()
