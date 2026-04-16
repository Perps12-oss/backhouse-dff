import logging
# cerebro/services/cache_manager.py

import sqlite3
import hashlib
import json
import gzip
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, asdict
from enum import Enum
import threading
from contextlib import contextmanager
import time

from cerebro.core.models import FileItem
logger = logging.getLogger(__name__)


class CacheEntryStatus(Enum):
    """Status of a cache entry."""
    VALID = "valid"
    STALE = "stale"  # File might have changed
    EXPIRED = "expired"  # Cache entry too old
    INVALID = "invalid"  # File no longer exists


@dataclass
class CacheEntry:
    """Represents a cache entry for a file."""
    file_path: str
    file_size: int
    modified_time: float
    hash_value: str
    hash_algorithm: str
    partial_hash: bool
    cache_timestamp: float
    access_count: int
    last_accessed: float
    
    def is_stale(self, current_mtime: float, tolerance_seconds: int = 2) -> bool:
        """Check if cache entry is stale compared to current file."""
        # Allow small tolerance for filesystem timestamp precision
        return abs(current_mtime - self.modified_time) > tolerance_seconds
        
    def is_expired(self, max_age_hours: int = 720) -> bool:
        """Check if cache entry has expired."""
        age_hours = (time.time() - self.cache_timestamp) / 3600
        return age_hours > max_age_hours
        
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage."""
        return asdict(self)
        
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'CacheEntry':
        """Create from dictionary."""
        return cls(**data)


@dataclass
class CacheStats:
    """Statistics about cache performance."""
    total_entries: int
    total_size_bytes: int
    hits: int
    misses: int
    hit_rate: float
    avg_access_time_ms: float
    oldest_entry_days: float
    newest_entry_days: float
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


class CacheManager:
    """Manages file hash cache for improved scan performance."""
    
    def __init__(self, cache_dir: Optional[Path] = None):
        """
        Initialize cache manager.
        
        Args:
            cache_dir: Directory for cache storage. If None, uses default location.
        """
        if cache_dir is None:
            cache_dir = Path.home() / ".cerebro" / "cache"
            
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        # Cache database
        self.db_path = cache_dir / "hash_cache.db"
        self.db_lock = threading.RLock()
        
        # Statistics
        self.stats = {
            'hits': 0,
            'misses': 0,
            'total_queries': 0,
            'total_inserts': 0,
            'total_updates': 0,
            'total_evictions': 0
        }
        
        # Configuration
        self.config = {
            'max_cache_size_mb': 500,  # Maximum cache size in MB
            'max_entry_age_hours': 720,  # 30 days
            'auto_cleanup_days': 7,  # Cleanup interval
            'compression_enabled': True,
            'memory_cache_size': 10000,  # Number of entries to keep in memory
        }
        
        # In-memory cache (LRU-like)
        self._memory_cache: Dict[str, CacheEntry] = {}
        
        # Initialize database
        self._init_database()
        
        # Load recent entries into memory
        self._load_memory_cache()
        
        # Start cleanup thread
        self._cleanup_thread = threading.Thread(target=self._auto_cleanup_worker, daemon=True)
        self._cleanup_thread.start()
        
    def _init_database(self):
        """Initialize cache database schema."""
        with self.db_lock:
            conn = sqlite3.connect(str(self.db_path))
            try:
                cursor = conn.cursor()
                
                # Create cache entries table
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS cache_entries (
                        file_path TEXT PRIMARY KEY,
                        file_size INTEGER,
                        modified_time REAL,
                        hash_value TEXT,
                        hash_algorithm TEXT,
                        partial_hash BOOLEAN,
                        cache_timestamp REAL,
                        access_count INTEGER DEFAULT 0,
                        last_accessed REAL
                    )
                ''')
                
                # Create indexes for faster queries
                cursor.execute('''
                    CREATE INDEX IF NOT EXISTS idx_cache_timestamp 
                    ON cache_entries(cache_timestamp)
                ''')
                cursor.execute('''
                    CREATE INDEX IF NOT EXISTS idx_last_accessed 
                    ON cache_entries(last_accessed)
                ''')
                cursor.execute('''
                    CREATE INDEX IF NOT EXISTS idx_hash_value 
                    ON cache_entries(hash_value)
                ''')
                
                # Create statistics table
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS cache_stats (
                        key TEXT PRIMARY KEY,
                        value TEXT
                    )
                ''')
                
                # Create configuration table
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS cache_config (
                        key TEXT PRIMARY KEY,
                        value TEXT
                    )
                ''')
                
                conn.commit()
            finally:
                conn.close()
                
    def _load_memory_cache(self):
        """Load frequently accessed entries into memory cache."""
        with self.db_lock:
            conn = sqlite3.connect(str(self.db_path))
            try:
                cursor = conn.cursor()
                
                # Get most frequently accessed entries
                cursor.execute('''
                    SELECT file_path, file_size, modified_time, hash_value,
                           hash_algorithm, partial_hash, cache_timestamp,
                           access_count, last_accessed
                    FROM cache_entries
                    ORDER BY access_count DESC
                    LIMIT ?
                ''', (self.config['memory_cache_size'],))
                
                for row in cursor.fetchall():
                    entry = CacheEntry(
                        file_path=row[0],
                        file_size=row[1],
                        modified_time=row[2],
                        hash_value=row[3],
                        hash_algorithm=row[4],
                        partial_hash=bool(row[5]),
                        cache_timestamp=row[6],
                        access_count=row[7],
                        last_accessed=row[8]
                    )
                    self._memory_cache[entry.file_path] = entry
                    
            finally:
                conn.close()
                
    def _auto_cleanup_worker(self):
        """Background worker for automatic cache cleanup."""
        while True:
            try:
                time.sleep(3600)  # Run every hour
                self.cleanup_expired()
                self.cleanup_oversized()
            except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError) as e:
                # Log but don't crash
                logger.info(f"Cache cleanup error: {e}")
                
    @contextmanager
    def _get_connection(self):
        """Context manager for database connections."""
        conn = sqlite3.connect(str(self.db_path))
        try:
            yield conn
        finally:
            conn.close()
            
    def get_hash(self, file_path: Path, 
                 hash_algorithm: str = "md5",
                 partial_bytes: Optional[int] = None) -> Optional[str]:
        """
        Get hash for a file, using cache if available.
        
        Args:
            file_path: Path to the file
            hash_algorithm: Hash algorithm to use
            partial_bytes: If set, only hash first N bytes
            
        Returns:
            Hash value if cached and valid, None otherwise
        """
        file_path_str = str(file_path.resolve())
        
        # Check memory cache first
        if file_path_str in self._memory_cache:
            entry = self._memory_cache[file_path_str]
            if self._validate_entry(file_path, entry, hash_algorithm, partial_bytes):
                self.stats['hits'] += 1
                self.stats['total_queries'] += 1
                
                # Update access statistics
                self._update_access_stats(file_path_str)
                return entry.hash_value
                
        # Check database cache
        with self.db_lock:
            conn = sqlite3.connect(str(self.db_path))
            try:
                cursor = conn.cursor()
                cursor.execute(
                    'SELECT * FROM cache_entries WHERE file_path = ?',
                    (file_path_str,)
                )
                
                row = cursor.fetchone()
                if row:
                    entry = CacheEntry(
                        file_path=row[0],
                        file_size=row[1],
                        modified_time=row[2],
                        hash_value=row[3],
                        hash_algorithm=row[4],
                        partial_hash=bool(row[5]),
                        cache_timestamp=row[6],
                        access_count=row[7],
                        last_accessed=row[8]
                    )
                    
                    if self._validate_entry(file_path, entry, hash_algorithm, partial_bytes):
                        self.stats['hits'] += 1
                        self.stats['total_queries'] += 1
                        
                        # Update memory cache
                        self._memory_cache[file_path_str] = entry
                        
                        # Update access statistics
                        self._update_access_stats(file_path_str)
                        return entry.hash_value
                        
                self.stats['misses'] += 1
                self.stats['total_queries'] += 1
                return None
                
            finally:
                conn.close()
                
    def _validate_entry(self, file_path: Path, entry: CacheEntry,
                       hash_algorithm: str, partial_bytes: Optional[int]) -> bool:
        """Validate if a cache entry is still valid."""
        try:
            # Check if file exists
            if not file_path.exists():
                return False
                
            # Check file size
            current_size = file_path.stat().st_size
            if current_size != entry.file_size:
                return False
                
            # Check modification time (with tolerance)
            current_mtime = file_path.stat().st_mtime
            if entry.is_stale(current_mtime):
                return False
                
            # Check hash algorithm
            if entry.hash_algorithm != hash_algorithm:
                return False
                
            # Check if partial hash matches requested
            if (partial_bytes is not None) != entry.partial_hash:
                return False
                
            # Check if entry is expired
            if entry.is_expired(self.config['max_entry_age_hours']):
                return False
                
            return True
            
        except OSError:
            return False
            
    def store_hash(self, file_path: Path, hash_value: str,
                   hash_algorithm: str = "md5",
                   partial_bytes: Optional[int] = None):
        """
        Store hash value in cache.
        
        Args:
            file_path: Path to the file
            hash_value: Computed hash value
            hash_algorithm: Hash algorithm used
            partial_bytes: If set, indicates partial hash of first N bytes
        """
        try:
            stat = file_path.stat()
            file_path_str = str(file_path.resolve())
            
            entry = CacheEntry(
                file_path=file_path_str,
                file_size=stat.st_size,
                modified_time=stat.st_mtime,
                hash_value=hash_value,
                hash_algorithm=hash_algorithm,
                partial_hash=(partial_bytes is not None),
                cache_timestamp=time.time(),
                access_count=0,
                last_accessed=time.time()
            )
            
            with self.db_lock:
                conn = sqlite3.connect(str(self.db_path))
                try:
                    cursor = conn.cursor()
                    
                    # Insert or replace entry
                    cursor.execute('''
                        INSERT OR REPLACE INTO cache_entries 
                        (file_path, file_size, modified_time, hash_value,
                         hash_algorithm, partial_hash, cache_timestamp,
                         access_count, last_accessed)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        entry.file_path, entry.file_size, entry.modified_time,
                        entry.hash_value, entry.hash_algorithm, entry.partial_hash,
                        entry.cache_timestamp, entry.access_count, entry.last_accessed
                    ))
                    
                    conn.commit()
                    self.stats['total_inserts'] += 1
                    
                    # Update memory cache (with LRU eviction if needed)
                    self._memory_cache[file_path_str] = entry
                    if len(self._memory_cache) > self.config['memory_cache_size']:
                        # Remove least recently accessed entry
                        oldest_key = min(self._memory_cache.items(),
                                        key=lambda x: x[1].last_accessed)[0]
                        del self._memory_cache[oldest_key]
                        
                finally:
                    conn.close()
                    
        except OSError:
            pass  # Silently ignore if file doesn't exist
            
    def _update_access_stats(self, file_path: str):
        """Update access statistics for a cache entry."""
        current_time = time.time()
        
        with self.db_lock:
            conn = sqlite3.connect(str(self.db_path))
            try:
                cursor = conn.cursor()
                
                # Update database
                cursor.execute('''
                    UPDATE cache_entries 
                    SET access_count = access_count + 1,
                        last_accessed = ?
                    WHERE file_path = ?
                ''', (current_time, file_path))
                
                conn.commit()
                
                # Update memory cache
                if file_path in self._memory_cache:
                    self._memory_cache[file_path].access_count += 1
                    self._memory_cache[file_path].last_accessed = current_time
                    
            finally:
                conn.close()
                
    def get_hit_rate(self) -> float:
        """Get current cache hit rate."""
        total = self.stats['total_queries']
        if total == 0:
            return 0.0
        return (self.stats['hits'] / total) * 100
        
    def get_cache_info(self) -> Dict[str, Any]:
        """Get detailed cache information."""
        with self.db_lock:
            conn = sqlite3.connect(str(self.db_path))
            try:
                cursor = conn.cursor()
                
                # Get total entries and size
                cursor.execute('SELECT COUNT(*), SUM(file_size) FROM cache_entries')
                count, total_size = cursor.fetchone()
                if total_size is None:
                    total_size = 0
                    
                # Get oldest and newest entries
                cursor.execute('SELECT MIN(cache_timestamp), MAX(cache_timestamp) FROM cache_entries')
                min_time, max_time = cursor.fetchone()
                
                # Calculate ages
                now = time.time()
                oldest_days = (now - (min_time or now)) / 86400
                newest_days = (now - (max_time or now)) / 86400
                
                return {
                    'entries': count or 0,
                    'size_mb': total_size / (1024 * 1024),
                    'hit_rate': self.get_hit_rate(),
                    'hits': self.stats['hits'],
                    'misses': self.stats['misses'],
                    'oldest_days': oldest_days,
                    'newest_days': newest_days,
                    'path': str(self.db_path),
                    'memory_cache_size': len(self._memory_cache),
                    'total_inserts': self.stats['total_inserts'],
                    'total_updates': self.stats['total_updates']
                }
            finally:
                conn.close()
                
    def cleanup_expired(self, max_age_hours: Optional[int] = None):
        """
        Remove expired cache entries.
        
        Args:
            max_age_hours: Maximum age in hours (uses config value if None)
        """
        if max_age_hours is None:
            max_age_hours = self.config['max_entry_age_hours']
            
        cutoff_time = time.time() - (max_age_hours * 3600)
        
        with self.db_lock:
            conn = sqlite3.connect(str(self.db_path))
            try:
                cursor = conn.cursor()
                
                # Get entries to remove from memory cache
                cursor.execute(
                    'SELECT file_path FROM cache_entries WHERE cache_timestamp < ?',
                    (cutoff_time,)
                )
                expired_paths = [row[0] for row in cursor.fetchall()]
                
                # Remove from database
                cursor.execute(
                    'DELETE FROM cache_entries WHERE cache_timestamp < ?',
                    (cutoff_time,)
                )
                
                # Remove from memory cache
                for path in expired_paths:
                    self._memory_cache.pop(path, None)
                    
                deleted_count = cursor.rowcount
                conn.commit()
                
                self.stats['total_evictions'] += deleted_count
                return deleted_count
                
            finally:
                conn.close()
                
    def cleanup_oversized(self, max_size_mb: Optional[int] = None):
        """
        Remove old entries to keep cache under size limit.
        
        Args:
            max_size_mb: Maximum cache size in MB (uses config value if None)
        """
        if max_size_mb is None:
            max_size_mb = self.config['max_cache_size_mb']
            
        max_size_bytes = max_size_mb * 1024 * 1024
        
        with self.db_lock:
            conn = sqlite3.connect(str(self.db_path))
            try:
                cursor = conn.cursor()
                
                # Get current total size
                cursor.execute('SELECT SUM(file_size) FROM cache_entries')
                total_size = cursor.fetchone()[0] or 0
                
                if total_size <= max_size_bytes:
                    return 0
                    
                # Calculate how much to remove
                excess_bytes = total_size - max_size_bytes
                
                # Get least recently accessed entries to remove
                cursor.execute('''
                    SELECT file_path, file_size 
                    FROM cache_entries 
                    ORDER BY last_accessed ASC, cache_timestamp ASC
                ''')
                
                removed_bytes = 0
                paths_to_remove = []
                
                for row in cursor.fetchall():
                    if removed_bytes >= excess_bytes:
                        break
                        
                    paths_to_remove.append(row[0])
                    removed_bytes += row[1]
                    
                # Remove selected entries
                if paths_to_remove:
                    placeholders = ','.join(['?' for _ in paths_to_remove])
                    cursor.execute(
                        f'DELETE FROM cache_entries WHERE file_path IN ({placeholders})',
                        paths_to_remove
                    )
                    
                    # Remove from memory cache
                    for path in paths_to_remove:
                        self._memory_cache.pop(path, None)
                        
                    deleted_count = cursor.rowcount
                    conn.commit()
                    
                    self.stats['total_evictions'] += deleted_count
                    return deleted_count
                    
                return 0
                
            finally:
                conn.close()
                
    def clear_cache(self):
        """Clear all cache entries."""
        with self.db_lock:
            conn = sqlite3.connect(str(self.db_path))
            try:
                cursor = conn.cursor()
                
                # Clear all entries
                cursor.execute('DELETE FROM cache_entries')
                conn.commit()
                
                # Clear memory cache
                self._memory_cache.clear()
                
                # Reset statistics
                self.stats = {
                    'hits': 0,
                    'misses': 0,
                    'total_queries': 0,
                    'total_inserts': 0,
                    'total_updates': 0,
                    'total_evictions': 0
                }
                
                return True
                
            finally:
                conn.close()
                
    def export_cache(self, export_path: Path) -> bool:
        """
        Export cache to a file.
        
        Args:
            export_path: Path to export file
            
        Returns:
            True if export successful
        """
        try:
            with self.db_lock:
                conn = sqlite3.connect(str(self.db_path))
                
                # Read all entries
                cursor = conn.cursor()
                cursor.execute('SELECT * FROM cache_entries')
                entries = cursor.fetchall()
                
                # Prepare export data
                export_data = {
                    'version': '1.0',
                    'export_time': datetime.now().isoformat(),
                    'entries_count': len(entries),
                    'entries': entries,
                    'stats': self.stats,
                    'config': self.config
                }
                
                # Write to file
                with open(export_path, 'w') as f:
                    json.dump(export_data, f, indent=2)
                    
                return True
                
        except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError) as e:
            logger.info(f"Export failed: {e}")
            return False
            
    def import_cache(self, import_path: Path) -> bool:
        """
        Import cache from a file.
        
        Args:
            import_path: Path to import file
            
        Returns:
            True if import successful
        """
        try:
            with open(import_path, 'r') as f:
                import_data = json.load(f)
                
            if import_data.get('version') != '1.0':
                raise ValueError("Unsupported cache format")
                
            entries = import_data.get('entries', [])
            
            with self.db_lock:
                conn = sqlite3.connect(str(self.db_path))
                cursor = conn.cursor()
                
                # Clear existing entries
                cursor.execute('DELETE FROM cache_entries')
                
                # Insert imported entries
                for entry in entries:
                    cursor.execute('''
                        INSERT INTO cache_entries 
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', entry)
                    
                conn.commit()
                
                # Reload memory cache
                self._memory_cache.clear()
                self._load_memory_cache()
                
                return True
                
        except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError) as e:
            logger.info(f"Import failed: {e}")
            return False
            
    def __del__(self):
        """Cleanup on destruction."""
        if hasattr(self, '_cleanup_thread'):
            self._cleanup_thread.join(timeout=1)


# Singleton instance for global access
_cache_manager_instance: Optional[CacheManager] = None


def get_cache_manager(cache_dir: Optional[Path] = None) -> CacheManager:
    """
    Get or create global cache manager instance.
    
    Args:
        cache_dir: Optional custom cache directory
        
    Returns:
        CacheManager instance
    """
    global _cache_manager_instance
    
    if _cache_manager_instance is None:
        _cache_manager_instance = CacheManager(cache_dir)
        
    return _cache_manager_instance