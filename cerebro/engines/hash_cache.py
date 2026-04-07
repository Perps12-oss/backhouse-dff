"""
Hash Cache

SQLite-backed cache for storing computed hashes to avoid re-reading unchanged files.
Provides Czkawka-level re-scan performance by caching file metadata and hashes.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Optional, List
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class HashCache:
    """
    SQLite-backed hash cache.

    Stores file metadata (path, mtime, size) alongside computed hashes
    to allow fast re-scans of unchanged directories.
    """

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS file_hashes (
        path TEXT NOT NULL,
        mtime REAL NOT NULL,
        size INTEGER NOT NULL,
        hash_type TEXT NOT NULL,
        hash_value TEXT NOT NULL,
        cached_at REAL NOT NULL,
        PRIMARY KEY (path, hash_type)
    );

    CREATE INDEX IF NOT EXISTS idx_hash ON file_hashes(hash_type, hash_value);
    CREATE INDEX IF NOT EXISTS idx_hash_type ON file_hashes(hash_type);
    CREATE INDEX IF NOT EXISTS idx_cached_at ON file_hashes(cached_at);
    """

    def __init__(self, cache_path: Optional[Path] = None):
        """
        Initialize the hash cache.

        Args:
            cache_path: Path to cache database. Defaults to config/hash_cache.db
        """
        self._cache_path = cache_path or Path("config") / "hash_cache.db"
        self._cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection: Optional[sqlite3.Connection] = None
        self._connect()

    def _connect(self) -> None:
        """Establish database connection and create schema."""
        try:
            self._connection = sqlite3.connect(
                str(self._cache_path),
                check_same_thread=False,
                isolation_level=None  # Autocommit mode
            )
            self._connection.row_factory = sqlite3.Row
            # Migrate old schema: if table exists with path as sole PK, drop it
            row = self._connection.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='file_hashes'"
            ).fetchone()
            if row and "PRIMARY KEY (path, hash_type)" not in row[0]:
                self._connection.execute("DROP TABLE IF EXISTS file_hashes")
            self._connection.executescript(self.SCHEMA)
            logger.info(f"Hash cache initialized at {self._cache_path}")
        except sqlite3.Error as e:
            logger.error(f"Failed to initialize hash cache: {e}")
            raise

    def get(self, path: Path, mtime: float, size: int,
            hash_type: str) -> Optional[str]:
        """
        Retrieve cached hash for a file if metadata matches.

        Args:
            path: File path to look up.
            mtime: File modification time.
            size: File size in bytes.
            hash_type: Type of hash ('sha256', 'blake3', 'phash', 'dhash').

        Returns:
            Cached hash value if metadata matches, None otherwise.
        """
        with self._lock:
            try:
                cursor = self._connection.execute(
                    """
                    SELECT hash_value FROM file_hashes
                    WHERE path = ? AND mtime = ? AND size = ? AND hash_type = ?
                    LIMIT 1
                    """,
                    (str(path), mtime, size, hash_type)
                )
                row = cursor.fetchone()
                if row:
                    logger.debug(f"Cache hit: {path}")
                    return row['hash_value']
                logger.debug(f"Cache miss: {path}")
                return None
            except sqlite3.Error as e:
                logger.error(f"Cache get error: {e}")
                return None

    def set(self, path: Path, mtime: float, size: int,
            hash_type: str, hash_value: str) -> None:
        """
        Store a hash value in the cache.

        Args:
            path: File path.
            mtime: File modification time.
            size: File size in bytes.
            hash_type: Type of hash.
            hash_value: Computed hash value.
        """
        with self._lock:
            try:
                cached_at = datetime.now().timestamp()
                self._connection.execute(
                    """
                    INSERT OR REPLACE INTO file_hashes
                    (path, mtime, size, hash_type, hash_value, cached_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (str(path), mtime, size, hash_type, hash_value, cached_at)
                )
            except sqlite3.Error as e:
                logger.error(f"Cache set error: {e}")

    def get_many(self, paths: List[Path], hash_type: str) -> dict:
        """
        Retrieve hashes for multiple paths at once.

        Args:
            paths: List of file paths to look up.
            hash_type: Type of hash to retrieve.

        Returns:
            Dict mapping path strings to cached hash values.
        """
        if not paths:
            return {}

        # Collect mtime/size for each path from disk
        path_meta: dict = {}
        for p in paths:
            try:
                st = p.stat()
                path_meta[str(p)] = (st.st_mtime, st.st_size)
            except OSError:
                pass

        if not path_meta:
            return {}

        with self._lock:
            try:
                path_strs = list(path_meta.keys())
                placeholders = ','.join('?' * len(path_strs))
                cursor = self._connection.execute(
                    f"""
                    SELECT path, mtime, size, hash_value FROM file_hashes
                    WHERE path IN ({placeholders}) AND hash_type = ?
                    """,
                    path_strs + [hash_type]
                )
                result = {}
                for row in cursor.fetchall():
                    meta = path_meta.get(row['path'])
                    if meta and row['mtime'] == meta[0] and row['size'] == meta[1]:
                        result[row['path']] = row['hash_value']
                return result
            except sqlite3.Error as e:
                logger.error(f"Cache get_many error: {e}")
                return {}

    def set_many(self, entries: List[tuple]) -> None:
        """
        Store multiple hash entries at once.

        Args:
            entries: List of (path, mtime, size, hash_type, hash_value) tuples.
        """
        if not entries:
            return

        with self._lock:
            try:
                cached_at = datetime.now().timestamp()
                entries_with_time = [(p, m, s, ht, hv, cached_at)
                                    for p, m, s, ht, hv in entries]
                self._connection.executemany(
                    """
                    INSERT OR REPLACE INTO file_hashes
                    (path, mtime, size, hash_type, hash_value, cached_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    entries_with_time
                )
            except sqlite3.Error as e:
                logger.error(f"Cache set_many error: {e}")

    def prune_missing(self, existing_paths: Optional[set[Path]] = None) -> int:
        """
        Remove cache entries for files that no longer exist.

        Args:
            existing_paths: Set of currently existing file paths.
                          If None, checks disk for each entry (slow).

        Returns:
            Number of entries removed.
        """
        with self._lock:
            try:
                if existing_paths is not None:
                    # Fast path: delete entries not in provided set
                    path_strs = [str(p) for p in existing_paths]
                    if not path_strs:
                        # No files exist, clear everything
                        deleted = self._connection.execute("DELETE FROM file_hashes").rowcount
                    else:
                        placeholders = ','.join('?' * len(path_strs))
                        deleted = self._connection.execute(
                            f"""
                            DELETE FROM file_hashes
                            WHERE path NOT IN ({placeholders})
                            """,
                            path_strs
                        ).rowcount
                else:
                    # Slow path: check each file on disk
                    cursor = self._connection.execute("SELECT path FROM file_hashes")
                    to_delete = [row['path'] for row in cursor.fetchall()
                                 if not Path(row['path']).exists()]
                    if to_delete:
                        placeholders = ','.join('?' * len(to_delete))
                        deleted = self._connection.execute(
                            f"DELETE FROM file_hashes WHERE path IN ({placeholders})",
                            to_delete
                        ).rowcount
                    else:
                        deleted = 0

                logger.info(f"Pruned {deleted} missing file(s) from cache")
                return deleted
            except sqlite3.Error as e:
                logger.error(f"Cache prune error: {e}")
                return 0

    def prune_old(self, days: int = 90) -> int:
        """
        Remove cache entries older than specified days.

        Args:
            days: Maximum age of entries in days.

        Returns:
            Number of entries removed.
        """
        with self._lock:
            try:
                cutoff = datetime.now().timestamp() - (days * 86400)
                deleted = self._connection.execute(
                    "DELETE FROM file_hashes WHERE cached_at < ?",
                    (cutoff,)
                ).rowcount
                logger.info(f"Pruned {deleted} old entries (> {days} days)")
                return deleted
            except sqlite3.Error as e:
                logger.error(f"Cache prune_old error: {e}")
                return 0

    def clear(self) -> None:
        """Remove all entries from the cache."""
        with self._lock:
            try:
                deleted = self._connection.execute("DELETE FROM file_hashes").rowcount
                logger.info(f"Cleared {deleted} entries from cache")
            except sqlite3.Error as e:
                logger.error(f"Cache clear error: {e}")

    def stats(self) -> dict:
        """
        Get cache statistics.

        Returns:
            Dict with keys: total_entries, unique_hashes, cache_size_bytes,
                           oldest_entry, newest_entry, hit_rate (if tracked).
        """
        with self._lock:
            try:
                total = self._connection.execute(
                    "SELECT COUNT(*) as c FROM file_hashes"
                ).fetchone()['c']

                unique_hashes = self._connection.execute(
                    "SELECT COUNT(DISTINCT hash_value) as c FROM file_hashes"
                ).fetchone()['c']

                oldest = self._connection.execute(
                    "SELECT MIN(cached_at) as t FROM file_hashes"
                ).fetchone()['t']

                newest = self._connection.execute(
                    "SELECT MAX(cached_at) as t FROM file_hashes"
                ).fetchone()['t']

                cache_size = self._cache_path.stat().st_size if self._cache_path.exists() else 0

                return {
                    'total_entries': total,
                    'unique_hashes': unique_hashes,
                    'cache_size_bytes': cache_size,
                    'oldest_entry': datetime.fromtimestamp(oldest) if oldest else None,
                    'newest_entry': datetime.fromtimestamp(newest) if newest else None,
                }
            except sqlite3.Error as e:
                logger.error(f"Cache stats error: {e}")
                return {}

    def get_hash_types(self) -> List[str]:
        """Get list of hash types stored in cache."""
        with self._lock:
            try:
                cursor = self._connection.execute(
                    "SELECT DISTINCT hash_type FROM file_hashes ORDER BY hash_type"
                )
                return [row['hash_type'] for row in cursor.fetchall()]
            except sqlite3.Error as e:
                logger.error(f"Cache get_hash_types error: {e}")
                return []

    def close(self) -> None:
        """Close database connection."""
        with self._lock:
            if self._connection:
                self._connection.close()
                self._connection = None
                logger.info("Hash cache connection closed")

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
