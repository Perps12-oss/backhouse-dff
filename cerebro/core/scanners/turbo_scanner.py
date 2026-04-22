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
"""

from __future__ import annotations

import os
import sys
import time
import hashlib
import threading
import multiprocessing as mp
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, Callable, Any, Generator
from collections import defaultdict
import sqlite3
import mmap
from cerebro.core.models import FileMetadata
from cerebro.services.hash_cache import HashCache, StatSignature
from cerebro.services.logger import get_logger
from cerebro.core.root_dedup import dedupe_roots
from cerebro.core.group_invariants import _assert_no_self_duplicates

logger = get_logger(__name__)


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
    
    # Hashing
    use_quick_hash: bool = True
    use_full_hash: bool = False
    hash_algorithm: str = "md5"
    
    # Performance
    use_mmap: bool = True  # Use memory-mapped I/O
    batch_processing: bool = True
    prefetch_enabled: bool = True  # Prefetch file metadata
    
    # Progress
    progress_callback: Optional[Callable] = None
    

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
        conn.close()


# ============================================================================
# OPTIMIZED HASH FUNCTIONS
# ============================================================================

def compute_quick_hash_fast(path: Path, algorithm: str = "md5") -> Optional[str]:
    """
    Compute quick hash using first 32KB + last 32KB.
    This is much faster than full file hash for large files.
    """
    try:
        size = path.stat().st_size
        if size == 0:
            return None
        
        hasher = hashlib.new(algorithm)
        
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
        
        hasher = hashlib.new(algorithm)
        
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
            cached = cache.get_quick(str(path), sig)
            if cached:
                return cached
            
            # Compute and cache
            hash_val = compute_quick_hash_fast(path, algorithm)
            if hash_val:
                cache.set_quick(path, sig, hash_val, algo=algorithm, quick_bytes=QUICK_HASH_SIZE)
            return hash_val
        else:
            cached = cache.get_full(str(path), sig)
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

def walk_directory_worker(args: Tuple) -> List[Tuple[Path, int, float]]:
    """Worker function for parallel directory traversal.

    Uses os.scandir to avoid redundant stat() calls — DirEntry.stat()
    reuses the data returned by the underlying directory enumeration
    syscall, which is materially faster on Windows (FindFirstFile)
    and on SMB/network mounts.

    Returns list of (path, size, mtime) tuples.
    """
    directory, skip_hidden, exclude_dirs, min_size, max_size = args
    results: List[Tuple[Path, int, float]] = []

    # Iterative DFS with an explicit stack. Avoids recursion-depth limits
    # on pathological trees and gives us tight control over symlink/junction
    # behaviour.
    stack: List[str] = [str(directory)]

    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as it:
                for entry in it:
                    name = entry.name
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            if skip_hidden and name.startswith('.'):
                                continue
                            if name in exclude_dirs:
                                continue
                            stack.append(entry.path)
                            continue

                        if not entry.is_file(follow_symlinks=False):
                            continue
                        if skip_hidden and name.startswith('.'):
                            continue

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
        except OSError:
            # Directory unreadable as a whole — skip and continue.
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
        cache_dir = self.config.cache_dir or (Path.home() / ".cerebro" / "cache")
        cache_dir.mkdir(parents=True, exist_ok=True)
        
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
        
    def scan(self, roots: List[Path]) -> Generator[FileMetadata, None, None]:
        """
        Scan directories and yield file metadata.
        
        Uses aggressive parallelization and caching for maximum speed.
        """
        start_time = time.time()

        def _emit(stage: str, processed: int, total: int) -> None:
            cb = self.config.progress_callback
            if cb is None:
                return
            try:
                cb(stage, processed, total)
            except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
                # Never allow UI callback errors to break scanning.
                pass
        
        # Phase 1: Parallel directory discovery
        user_roots = list(roots)
        scan_roots = dedupe_roots(user_roots)
        if len(scan_roots) != len(user_roots):
            collapsed = [str(r) for r in user_roots if Path(r).resolve() not in {Path(s).resolve() for s in scan_roots}]
            logger.info(
                "[ROOT_DEDUP] user_roots=%d deduped_roots=%d collapsed=%s",
                len(user_roots), len(scan_roots), collapsed,
            )
        else:
            logger.info("[ROOT_DEDUP] user_roots=%d deduped_roots=%d (no overlap)", len(user_roots), len(scan_roots))
        logger.info("[Turbo] Phase 1: Discovering files...")
        _emit("discovering", 0, 0)
        discovered_files = self._discover_files_parallel(scan_roots, emit=_emit)
        _emit("discovering", len(discovered_files), len(discovered_files))
        logger.info(
            "[Turbo] Discovered %d files in %.2fs",
            len(discovered_files),
            time.time() - start_time,
        )
        # Phase 2: Group by size (instant duplicate detection)
        _emit("grouping_by_size", len(discovered_files), len(discovered_files))
        size_groups = defaultdict(list)
        for path, size, mtime in discovered_files:
            size_groups[size].append((path, mtime))
        
        # Filter out unique sizes
        size_groups = {k: v for k, v in size_groups.items() if len(v) >= 2}
        logger.info("[Turbo] Found %d size groups with potential duplicates", len(size_groups))
        _diag_size_candidates = sum(len(v) for v in size_groups.values())

        # Phase 3: Quick hash for size groups (parallel with caching)
        if self.config.use_quick_hash and size_groups:
            logger.info("[Turbo] Phase 2: Computing quick hashes...")
            quick_hash_groups = self._compute_hashes_parallel(
                size_groups, 
                quick=True,
                emit=_emit,
                stage_name="hashing_partial",
            )
            logger.info("[Turbo] Found %d quick-hash groups", len(quick_hash_groups))
        else:
            quick_hash_groups = size_groups
        
        # Phase 4: Full hash if needed (parallel with caching)
        if self.config.use_full_hash and quick_hash_groups:
            logger.info("[Turbo] Phase 3: Computing full hashes...")
            final_groups = self._compute_hashes_parallel(
                quick_hash_groups,
                quick=False,
                emit=_emit,
                stage_name="hashing_full",
            )
            logger.info("[Turbo] Found %d duplicate groups", len(final_groups))
        else:
            final_groups = quick_hash_groups
        
        # Expose groups for Review page (worker reads scanner.last_groups)
        def _group_recoverable(paths_list):
            total = 0
            for p, _ in paths_list:
                try:
                    total += os.path.getsize(str(p))
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

        for h, group_paths in final_groups.items():
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
        logger.info("Candidates: %d", candidate_count)
        logger.info("Emitted: %d", emitted_count)
        logger.info("Time: %.2fs", elapsed)
        logger.info("Speed: %.0f files/sec", discovered_count / elapsed)
        logger.info("Cache hits: %d", self.stats["hash_cache_hits"])
        logger.info("Cache misses: %d", self.stats["hash_cache_misses"])
        if self.stats['hash_cache_hits'] + self.stats['hash_cache_misses'] > 0:
            hit_rate = self.stats['hash_cache_hits'] / (self.stats['hash_cache_hits'] + self.stats['hash_cache_misses']) * 100
            logger.info("Hit rate: %.1f%%", hit_rate)
        _total_cache = self.stats["hash_cache_hits"] + self.stats["hash_cache_misses"]
        _hit_pct = (self.stats["hash_cache_hits"] / _total_cache * 100) if _total_cache else 0.0
        _final_ngroups = len(final_groups) if final_groups else 0
        logger.info(
            "[Turbo] summary: discovered=%d candidates_at_size=%d final_groups=%d "
            "emitted=%d elapsed=%.2fs cache_hits=%d cache_misses=%d cache_hit_pct=%.1f%%",
            discovered_count,
            _diag_size_candidates,
            _final_ngroups,
            emitted_count,
            elapsed,
            self.stats["hash_cache_hits"],
            self.stats["hash_cache_misses"],
            _hit_pct,
        )
        _emit("complete", discovered_count, discovered_count)
    def _discover_files_parallel(
        self,
        roots: List[Path],
        emit: Optional[Callable[[str, int, int], None]] = None,
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

        worker_args = [
            (
                d,
                self.config.skip_hidden,
                self.config.exclude_dirs,
                self.config.min_size,
                self.config.max_size,
            )
            for d in dirs_to_scan
        ]

        def _collect(future_to_root, warn_prefix: str) -> None:
            """Drain futures, extend all_files, and populate dir/file caches."""
            nonlocal discovered_so_far
            for future in as_completed(future_to_root):
                root_dir = future_to_root[future]
                try:
                    results = future.result()
                    all_files.extend(results)
                    discovered_so_far += len(results)
                    if emit and discovered_so_far % 1000 <= len(results):
                        emit("discovering", discovered_so_far, 0)
                    # Persist signature + file list so the next scan can skip this root.
                    if self.dir_cache and results:
                        sig = DirectorySignature.from_directory(root_dir)
                        if sig:
                            self.dir_cache.put(sig)
                            self.dir_cache.set_files(root_dir, results)
                except OSError as e:
                    logger.warning("%s: %s", warn_prefix, e)

        if self.config.use_multiprocessing and len(dirs_to_scan) > 1:
            workers = min(self.config.dir_workers, len(dirs_to_scan))
            with ProcessPoolExecutor(max_workers=workers) as executor:
                future_to_root = {
                    executor.submit(walk_directory_worker, args): d
                    for args, d in zip(worker_args, dirs_to_scan)
                }
                _collect(future_to_root, "[Turbo] Worker error")
        else:
            # Threads are sufficient and avoid the spawn overhead of processes.
            # Hash work is GIL-bound but directory traversal is I/O-bound, so
            # threads give true parallelism here.
            workers = min(self.config.dir_workers, max(1, len(dirs_to_scan)))
            with ThreadPoolExecutor(max_workers=workers) as executor:
                future_to_root = {
                    executor.submit(walk_directory_worker, args): d
                    for args, d in zip(worker_args, dirs_to_scan)
                }
                _collect(future_to_root, "[Turbo] Worker error walking directory")

        return all_files
    
    def _compute_hashes_parallel(
        self, 
        groups: Dict[Any, List[Tuple[Path, float]]],
        quick: bool = True,
        emit: Optional[Callable[[str, int, int], None]] = None,
        stage_name: str = "hashing_partial",
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
        
        # Use thread pool (not process pool) for hashing to share cache
        workers = min(self.config.hash_workers, len(files_to_hash))
        
        def hash_worker(path_mtime: Tuple[Path, float]) -> Tuple[Path, float, Optional[str]]:
            path, mtime = path_mtime
            if self.hash_cache:
                hash_val = compute_hash_cached(
                    path, 
                    self.hash_cache,
                    self.config.hash_algorithm,
                    quick=quick
                )
                if hash_val:
                    self.stats['hash_cache_hits'] += 1
                else:
                    self.stats['hash_cache_misses'] += 1
            else:
                if quick:
                    hash_val = compute_quick_hash_fast(path, self.config.hash_algorithm)
                else:
                    hash_val = compute_full_hash_mmap(path, self.config.hash_algorithm)
            
            return path, mtime, hash_val
        
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(hash_worker, pm) for pm in files_to_hash]
            total = len(futures)
            processed = 0
            
            for future in as_completed(futures):
                try:
                    path, mtime, hash_val = future.result()
                    if hash_val:
                        hash_groups[hash_val].append((path, mtime))
                except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
                    continue
                finally:
                    processed += 1
                    if emit and (processed % 50 == 0 or processed == total):
                        emit(stage_name, processed, total)
        
        # Filter out groups with only one file
        return {k: v for k, v in hash_groups.items() if len(v) >= 2}
    
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
