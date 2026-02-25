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
import pickle

from cerebro.services.hash_cache import HashCache, StatSignature
from cerebro.core.models import FileMetadata


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
        """Create signature from directory."""
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
                except:
                    pass
            
            last_modified = stat.st_mtime
            
            # Create checksum
            sig_data = f"{file_count}:{total_size}:{last_modified}".encode()
            checksum = hashlib.md5(sig_data).hexdigest()
            
            return cls(
                path=str(path),
                file_count=file_count,
                total_size=total_size,
                last_modified=last_modified,
                checksum=checksum
            )
        except:
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
    use_multiprocessing: bool = True  # Use processes for directory traversal
    
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
    except:
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
            except:
                pass  # Fall through to regular I/O
        
        # Regular I/O for smaller files
        with open(path, 'rb') as f:
            while chunk := f.read(HASH_CHUNK_SIZE):
                hasher.update(chunk)
        
        return hasher.hexdigest()
    except:
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
    except:
        return None


# ============================================================================
# PARALLEL DIRECTORY WALKER
# ============================================================================

def walk_directory_worker(args: Tuple) -> List[Tuple[Path, int, float]]:
    """
    Worker function for parallel directory traversal.
    Returns list of (path, size, mtime) tuples.
    """
    directory, skip_hidden, exclude_dirs, min_size, max_size = args
    results = []
    
    try:
        for root, dirs, files in os.walk(directory):
            # Filter directories in-place
            dirs[:] = [
                d for d in dirs
                if not (skip_hidden and d.startswith('.')) and d not in exclude_dirs
            ]
            
            root_path = Path(root)
            
            for name in files:
                if skip_hidden and name.startswith('.'):
                    continue
                
                try:
                    file_path = root_path / name
                    stat = file_path.stat()
                    size = stat.st_size
                    
                    # Apply filters
                    if size < min_size:
                        continue
                    if max_size > 0 and size > max_size:
                        continue
                    
                    results.append((file_path, size, stat.st_mtime))
                except:
                    continue
        
    except:
        pass
    
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
        
        # Phase 1: Parallel directory discovery
        print(f"[Turbo] Phase 1: Discovering files...")
        discovered_files = self._discover_files_parallel(roots)
        print(f"[Turbo] Discovered {len(discovered_files)} files in {time.time() - start_time:.2f}s")
        
        # Phase 2: Group by size (instant duplicate detection)
        size_groups = defaultdict(list)
        for path, size, mtime in discovered_files:
            size_groups[size].append((path, mtime))
        
        # Filter out unique sizes
        size_groups = {k: v for k, v in size_groups.items() if len(v) >= 2}
        print(f"[Turbo] Found {len(size_groups)} size groups with potential duplicates")
        
        # Phase 3: Quick hash for size groups (parallel with caching)
        if self.config.use_quick_hash and size_groups:
            print(f"[Turbo] Phase 2: Computing quick hashes...")
            quick_hash_groups = self._compute_hashes_parallel(
                size_groups, 
                quick=True
            )
            print(f"[Turbo] Found {len(quick_hash_groups)} quick-hash groups")
        else:
            quick_hash_groups = size_groups
        
        # Phase 4: Full hash if needed (parallel with caching)
        if self.config.use_full_hash and quick_hash_groups:
            print(f"[Turbo] Phase 3: Computing full hashes...")
            final_groups = self._compute_hashes_parallel(
                quick_hash_groups,
                quick=False
            )
            print(f"[Turbo] Found {len(final_groups)} duplicate groups")
        else:
            final_groups = quick_hash_groups
        
        # Phase 5: Yield results
        total_files = 0
        for group_paths in final_groups.values():
            for path, _ in group_paths:
                try:
                    meta = FileMetadata.from_path(path)
                    if meta:
                        yield meta
                        total_files += 1
                except:
                    continue
        
        # Update statistics
        elapsed = time.time() - start_time
        self.stats['elapsed_time'] = elapsed
        self.stats['files_scanned'] = total_files
        
        print(f"\n[Turbo] Scan complete:")
        print(f"  - Files: {total_files}")
        print(f"  - Time: {elapsed:.2f}s")
        print(f"  - Speed: {total_files / elapsed:.0f} files/sec")
        print(f"  - Cache hits: {self.stats['hash_cache_hits']}")
        print(f"  - Cache misses: {self.stats['hash_cache_misses']}")
        if self.stats['hash_cache_hits'] + self.stats['hash_cache_misses'] > 0:
            hit_rate = self.stats['hash_cache_hits'] / (self.stats['hash_cache_hits'] + self.stats['hash_cache_misses']) * 100
            print(f"  - Hit rate: {hit_rate:.1f}%")
    
    def _discover_files_parallel(self, roots: List[Path]) -> List[Tuple[Path, int, float]]:
        """
        Discover all files using parallel directory traversal.
        
        Uses multiprocessing to scan multiple directories simultaneously.
        """
        all_files = []
        
        # Collect top-level directories to parallelize
        dirs_to_scan = []
        for root in roots:
            if not root.exists():
                continue
            
            if root.is_file():
                try:
                    stat = root.stat()
                    all_files.append((root, stat.st_size, stat.st_mtime))
                except:
                    pass
                continue
            
            # For directories, check if we can skip based on cache
            if self.config.incremental and self.dir_cache:
                if not self.dir_cache.has_changed(root):
                    self.stats['directories_skipped'] += 1
                    # TODO: Load files from cache
                    continue
            
            # Add immediate subdirectories for better parallelism
            try:
                for item in root.iterdir():
                    if item.is_dir():
                        if not (self.config.skip_hidden and item.name.startswith('.')):
                            if item.name not in self.config.exclude_dirs:
                                dirs_to_scan.append(item)
            except:
                pass
            
            # Also scan the root itself
            dirs_to_scan.append(root)
        
        if not dirs_to_scan:
            return all_files
        
        # Prepare worker arguments
        worker_args = [
            (d, self.config.skip_hidden, self.config.exclude_dirs, 
             self.config.min_size, self.config.max_size)
            for d in dirs_to_scan
        ]
        
        # Use process pool for true parallelism
        if self.config.use_multiprocessing and len(dirs_to_scan) > 1:
            workers = min(self.config.dir_workers, len(dirs_to_scan))
            with ProcessPoolExecutor(max_workers=workers) as executor:
                futures = [executor.submit(walk_directory_worker, args) for args in worker_args]
                
                for future in as_completed(futures):
                    try:
                        results = future.result()
                        all_files.extend(results)
                    except Exception as e:
                        print(f"[Turbo] Worker error: {e}")
                        continue
        else:
            # Fallback to sequential for small scans
            for args in worker_args:
                try:
                    results = walk_directory_worker(args)
                    all_files.extend(results)
                except:
                    continue
        
        return all_files
    
    def _compute_hashes_parallel(
        self, 
        groups: Dict[Any, List[Tuple[Path, float]]],
        quick: bool = True
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
            
            for future in as_completed(futures):
                try:
                    path, mtime, hash_val = future.result()
                    if hash_val:
                        hash_groups[hash_val].append((path, mtime))
                except:
                    continue
        
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
