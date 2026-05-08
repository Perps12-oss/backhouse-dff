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
``docs/architecture/scan_paths.md``.
"""

from __future__ import annotations

import os
import time
import hashlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, Callable, Any, Generator
from collections import defaultdict
import sqlite3
import mmap
from cerebro.core.models import FileMetadata
from cerebro.core.paths import default_cerebro_cache_dir
from cerebro.services.hash_cache import HashCache, StatSignature
from cerebro.services.logger import get_logger
from cerebro.core.root_dedup import dedupe_roots
from cerebro.core.group_invariants import _assert_no_self_duplicates
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

    # Archive handling (off by default).
    # When False, archive files are hashed as opaque binary blobs — fast and
    # correct for whole-archive duplicate detection (.zip A == .zip B iff
    # byte-for-byte identical). When True, the scanner will attempt to extract
    # and hash each member file individually (very slow; not yet implemented
    # beyond the config flag).
    scan_archives: bool = False
    

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

    ``args`` is either a 7-tuple ending with optional ``cancel_event``
    (:class:`threading.Event`, same process only) or a legacy 6-tuple
    (process pool workers — no intra-walk cancel).
    """
    if len(args) >= 9:
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
        cancel_event = None
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
            if str(current_dir) == root_dir_s:
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
        
        if self.config.use_cache:
            self.hash_cache = HashCache(cache_dir / "hash_cache.sqlite")
            self.hash_cache.open()
            
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
            'total_bytes': 0,
            'elapsed_time': 0,
        }

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
        }

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

        # Phase 1: Parallel directory discovery
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
        logger.info("[Turbo] Phase 1: Discovering files...")
        _emit(
            ScanStage.DISCOVERING,
            0,
            0,
            metrics={"total_files_in_scope": 0, "files_processed": 0, "candidates_found": 0},
        )
        discovered_files = self._discover_files_parallel(scan_roots, emit=_emit)
        _emit(
            ScanStage.DISCOVERING,
            len(discovered_files),
            len(discovered_files),
            metrics={
                "total_files_in_scope": len(discovered_files),
                "files_processed": len(discovered_files),
                "candidates_found": 0,
            },
        )
        logger.info(
            "[Turbo] Discovered %d files in %.2fs",
            len(discovered_files),
            time.time() - start_time,
        )
        # Phase 2: Group by size (instant duplicate detection)
        _pause_gate()
        _emit(
            ScanStage.GROUPING_BY_SIZE,
            len(discovered_files),
            len(discovered_files),
            metrics={
                "total_files_in_scope": len(discovered_files),
                "files_processed": len(discovered_files),
                "candidates_found": 0,
            },
        )
        size_groups = defaultdict(list)
        _ce = self.config.cancel_event
        for gi, (path, size, mtime) in enumerate(discovered_files):
            if gi % 128 == 0 and _ce is not None and _ce.is_set():
                return
            size_groups[size].append((path, mtime))
        
        # Filter out unique sizes
        size_groups = {k: v for k, v in size_groups.items() if len(v) >= 2}
        logger.info("[Turbo] Found %d size groups with potential duplicates", len(size_groups))
        _diag_size_candidates = sum(len(v) for v in size_groups.values())

        # Phase 3: Quick hash for size groups (parallel with caching)
        _pause_gate()
        candidates_found = sum(len(v) for v in size_groups.values()) if size_groups else 0
        _emit(
            ScanStage.GROUPING_BY_SIZE,
            len(discovered_files),
            len(discovered_files),
            metrics={
                "total_files_in_scope": len(discovered_files),
                "files_processed": len(discovered_files),
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
        discovered_count = len(discovered_files)
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
        _total_cache = self.stats["hash_cache_hits"] + self.stats["hash_cache_misses"]
        _hit_pct = (self.stats["hash_cache_hits"] / _total_cache * 100) if _total_cache else 0.0
        _final_ngroups = len(final_groups) if final_groups else 0
        logger.info(
            "[Turbo] summary: discovered=%d files_in_size_candidate_groups=%d "
            "final_duplicate_groups=%d file_rows_emitted=%d elapsed=%.2fs "
            "cache_hits=%d cache_misses=%d cache_hit_pct=%.1f%%",
            discovered_count,
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
        if ce is None or not ce.is_set():
            self._turbo_completed_normally = True
            _emit(
                ScanStage.COMPLETE,
                discovered_count,
                discovered_count,
                metrics={
                    "total_files_in_scope": discovered_count,
                    "files_processed": discovered_count,
                    "candidates_found": candidates_found,
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

    def _discover_files_parallel(
        self,
        roots: List[Path],
        emit: Optional[Callable[..., None]] = None,
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
                    all_files.append((root, stat.st_size, stat.st_mtime))
                except OSError:
                    pass
                continue

            if self.config.incremental and self.dir_cache:
                if not self.dir_cache.has_changed(root):
                    cached_files = self.dir_cache.get_files(root)
                    if cached_files is not None:
                        self.stats['directories_skipped'] += 1
                        all_files.extend(cached_files)
                        continue
                    # Signature unchanged but no file cache yet — fall through to scan.

            dirs_to_scan.append(root)

        if not dirs_to_scan:
            return all_files

        worker_tpl = (
            self.config.skip_hidden,
            self.config.exclude_dirs,
            self.config.exclude_paths,
            self.config.recursive,
            self.config.min_size,
            self.config.max_size,
            self.config.scan_archives,
        )
        use_mp = bool(self.config.use_multiprocessing and len(dirs_to_scan) > 1)
        worker_args = []
        for d in dirs_to_scan:
            tup: Tuple[Any, ...] = (d,) + worker_tpl
            if not use_mp:
                tup = tup + (self.config.cancel_event,)
            worker_args.append(tup)

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
            """Drain futures; stop listing early when cancel_event is set."""
            nonlocal discovered_so_far
            for future in as_completed(future_to_root):
                if self.config.cancel_event is not None and self.config.cancel_event.is_set():
                    return
                root_dir = future_to_root[future]
                try:
                    results = future.result()
                    all_files.extend(results)
                    discovered_so_far += len(results)
                    if emit and discovered_so_far % 100 <= len(results):
                        emit(ScanStage.DISCOVERING, discovered_so_far, 0)
                    if self.dir_cache and results:
                        sig = DirectorySignature.from_directory(root_dir)
                        if sig:
                            self.dir_cache.put(sig)
                            self.dir_cache.set_files(root_dir, results)
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
                    return {}

                slice_paths = _batch_paths[page_off : page_off + chunk_sz]
                if not slice_paths:
                    break
                slice_sigs = {p: _batch_sigs[p] for p in slice_paths if p in _batch_sigs}

                if cancel_event is not None and cancel_event.is_set():
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

        # Use thread pool (not process pool) for hashing to share cache
        workers = min(self.config.hash_workers, len(files_to_hash))

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

            return path, mtime, hash_val

        try:
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = [executor.submit(hash_worker, pm) for pm in files_to_hash]
                processed = 0
                _last_emit_time = time.monotonic()
                _current_file = ""

                for future in as_completed(futures):
                    _path_for_emit = ""
                    try:
                        path, mtime, hash_val = future.result()
                        _path_for_emit = str(path)
                        if hash_val:
                            hash_groups[hash_val].append((path, mtime))
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
                    if cancel_event is not None and cancel_event.is_set():
                        break
        finally:
            # Hashing uses short-lived worker thread pools; each worker may create a
            # dedicated SQLite connection in HashCache. Proactively close those
            # connections after every hash phase so rescans do not accumulate them.
            if self.hash_cache is not None:
                try:
                    self.hash_cache.close_all_connections()
                except (sqlite3.Error, OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
                    pass
        
        # Filter out groups with only one file
        return {k: v for k, v in hash_groups.items() if len(v) >= 2}

    def _auto_pick_hash_algorithm(self, sample_paths: List[Path], *, quick: bool) -> str:
        candidates = _available_hash_algorithms()
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
