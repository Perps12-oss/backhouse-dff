# path: cerebro/services/hash_cache.py
"""
cerebro/services/hash_cache.py — Persistent hash cache (SQLite, WAL)

Purpose
- Speed repeated scans by caching computed hashes per file metadata snapshot.
- Safe-by-default: cache is a pure optimization (never changes semantics).
- Thread-friendly: single connection per worker thread/process.

Storage model
- We cache by a "signature" derived from stat(): size + mtime_ns (+ optional dev/inode)
  so changed files invalidate automatically.
- Stores both:
  - quick_hash (fast sampled hash, e.g., MD5 hexdigest)
  - full_hash  (full-content hash, if/when you compute it)

Notes
- This module is engine-only (UI-agnostic) and works under PySide6 worker threads.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple


SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class StatSignature:
    """A minimal signature used to invalidate cache entries when files change."""
    size: int
    mtime_ns: int
    dev: int = 0
    inode: int = 0

    @staticmethod
    def from_path(path: Path, *, follow_symlinks: bool = False) -> "StatSignature":
        st = path.stat() if follow_symlinks else path.lstat()
        size = int(getattr(st, "st_size", 0))
        # Prefer nanosecond precision where available
        mtime_ns = int(getattr(st, "st_mtime_ns", int(float(getattr(st, "st_mtime", 0.0)) * 1_000_000_000)))
        dev = int(getattr(st, "st_dev", 0) or 0)
        inode = int(getattr(st, "st_ino", 0) or 0)
        return StatSignature(size=size, mtime_ns=mtime_ns, dev=dev, inode=inode)


class HashCache:
    """
    SQLite-backed hash cache.

    Thread-safe: each thread uses its own connection (thread-local).
    Recommended location: ~/.cerebro_cache/hash_cache.sqlite
    """

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self._local = threading.local()
        self._open = False

    # ------------------------------------------------------------------
    # Lifecycle (thread-local)
    # ------------------------------------------------------------------

    def open(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._open = True

    def close(self) -> None:
        self._open = False
        self.close_connection()

    def get_connection(self) -> sqlite3.Connection:
        """Return the SQLite connection for the current thread; create if needed."""
        if not self._open:
            raise RuntimeError("HashCache is not open()")
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(str(self.db_path), timeout=10.0)
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            conn.execute("PRAGMA temp_store=MEMORY;")
            conn.execute("PRAGMA cache_size=-20000;")
            self._init_schema(conn)
            self._local.conn = conn
        return conn

    def close_connection(self) -> None:
        """Close the current thread's connection if any."""
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            try:
                conn.commit()
            except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
                pass
            try:
                conn.close()
            except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
                pass
            self._local.conn = None

    def _init_schema(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS file_hashes (
              path TEXT PRIMARY KEY,
              size INTEGER NOT NULL,
              mtime_ns INTEGER NOT NULL,
              dev INTEGER NOT NULL,
              inode INTEGER NOT NULL,
              quick_hash TEXT,
              quick_algo TEXT,
              quick_bytes INTEGER,
              full_hash TEXT,
              full_algo TEXT,
              updated_ts REAL NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sig ON file_hashes(size, mtime_ns, dev, inode)")
        cur = conn.execute("PRAGMA user_version;")
        v = int(cur.fetchone()[0] or 0)
        if v < SCHEMA_VERSION:
            conn.execute(f"PRAGMA user_version={SCHEMA_VERSION};")
        conn.commit()

    # ------------------------------------------------------------------
    # Quick hash
    # ------------------------------------------------------------------

    def get_quick(self, path: str | Path, sig: StatSignature) -> Optional[str]:
        row = self._get_row(path)
        if not row:
            return None
        size, mtime_ns, dev, inode, quick_hash = row
        if (size, mtime_ns, dev, inode) != (sig.size, sig.mtime_ns, sig.dev, sig.inode):
            return None
        return quick_hash

    def set_quick(
        self,
        path: str | Path,
        sig: StatSignature,
        quick_hash: str,
        *,
        algo: str = "md5",
        quick_bytes: int = 0,
    ) -> None:
        self._upsert(
            Path(path),
            sig,
            quick_hash=quick_hash,
            quick_algo=algo,
            quick_bytes=int(quick_bytes or 0),
        )

    # ------------------------------------------------------------------
    # Full hash
    # ------------------------------------------------------------------

    def get_full(self, path: str | Path, sig: StatSignature) -> Optional[str]:
        row = self._get_row_full(path)
        if not row:
            return None
        size, mtime_ns, dev, inode, full_hash = row
        if (size, mtime_ns, dev, inode) != (sig.size, sig.mtime_ns, sig.dev, sig.inode):
            return None
        return full_hash

    def set_full(
        self,
        path: str | Path,
        sig: StatSignature,
        full_hash: str,
        *,
        algo: str = "sha256",
    ) -> None:
        self._upsert(Path(path), sig, full_hash=full_hash, full_algo=algo)

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    def get_stats(self) -> dict:
        """Return basic cache statistics (total entries, db size on disk)."""
        stats: dict = {"total_entries": 0, "cache_size_mb": 0.0, "hit_rate": 0.0}
        try:
            conn = self.get_connection()
            cur = conn.execute("SELECT COUNT(*) FROM file_hashes")
            stats["total_entries"] = int(cur.fetchone()[0] or 0)
        except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
            pass
        try:
            if self.db_path.exists():
                stats["cache_size_mb"] = round(self.db_path.stat().st_size / (1024 * 1024), 2)
        except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
            pass
        return stats

    def vacuum(self) -> None:
        """Run VACUUM on the database to reclaim space."""
        conn = self.get_connection()
        conn.execute("VACUUM")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _require_conn(self) -> sqlite3.Connection:
        return self.get_connection()

    def _get_row(self, path: str | Path) -> Optional[Tuple[int, int, int, int, Optional[str]]]:
        conn = self._require_conn()
        p = str(path)
        cur = conn.execute(
            "SELECT size, mtime_ns, dev, inode, quick_hash FROM file_hashes WHERE path=?",
            (p,),
        )
        return cur.fetchone()

    def _get_row_full(self, path: str | Path) -> Optional[Tuple[int, int, int, int, Optional[str]]]:
        conn = self._require_conn()
        p = str(path)
        cur = conn.execute(
            "SELECT size, mtime_ns, dev, inode, full_hash FROM file_hashes WHERE path=?",
            (p,),
        )
        return cur.fetchone()

    def _upsert(
        self,
        path: Path,
        sig: StatSignature,
        *,
        quick_hash: Optional[str] = None,
        quick_algo: Optional[str] = None,
        quick_bytes: Optional[int] = None,
        full_hash: Optional[str] = None,
        full_algo: Optional[str] = None,
    ) -> None:
        conn = self._require_conn()
        now = time.time()
        # Bounded transaction: single upsert per call (thread-local conn, no cross-thread lock)
        cur = conn.execute(
            "SELECT quick_hash, quick_algo, quick_bytes, full_hash, full_algo FROM file_hashes WHERE path=?",
            (str(path),),
        )
        existing = cur.fetchone()
        if existing:
            ex_qh, ex_qa, ex_qb, ex_fh, ex_fa = existing
        else:
            ex_qh = ex_qa = ex_fh = ex_fa = None
            ex_qb = None

        qh = quick_hash if quick_hash is not None else ex_qh
        qa = quick_algo if quick_algo is not None else ex_qa
        qb = int(quick_bytes) if quick_bytes is not None else (int(ex_qb) if ex_qb is not None else 0)
        fh = full_hash if full_hash is not None else ex_fh
        fa = full_algo if full_algo is not None else ex_fa

        conn.execute(
            """
            INSERT INTO file_hashes
              (path, size, mtime_ns, dev, inode,
               quick_hash, quick_algo, quick_bytes,
               full_hash, full_algo, updated_ts)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(path) DO UPDATE SET
              size=excluded.size,
              mtime_ns=excluded.mtime_ns,
              dev=excluded.dev,
              inode=excluded.inode,
              quick_hash=excluded.quick_hash,
              quick_algo=excluded.quick_algo,
              quick_bytes=excluded.quick_bytes,
              full_hash=excluded.full_hash,
              full_algo=excluded.full_algo,
              updated_ts=excluded.updated_ts
            """,
            (str(path), sig.size, sig.mtime_ns, sig.dev, sig.inode, qh, qa, qb, fh, fa, now),
        )
        conn.commit()

    def get_stats(self) -> dict:
        """Return cache statistics (total_entries, cache_size_mb, hit_rate). Requires open()."""
        conn = self._require_conn()
        cur = conn.execute("SELECT COUNT(*) FROM file_hashes")
        total = int(cur.fetchone()[0] or 0)
        size_mb = 0.0
        if self.db_path.exists():
            try:
                size_mb = self.db_path.stat().st_size / (1024 * 1024)
            except OSError:
                pass
        return {
            "total_entries": total,
            "cache_size_mb": round(size_mb, 2),
            "hit_rate": 0.0,
        }

    def vacuum(self) -> None:
        """Reclaim space. Requires open()."""
        conn = self._require_conn()
        conn.execute("VACUUM")
        conn.commit()
