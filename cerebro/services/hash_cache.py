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
        self._write_lock = threading.Lock()
        self._conn_lock = threading.Lock()
        self._connections: set[sqlite3.Connection] = set()
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
        self.close_all_connections()

    def get_connection(self) -> sqlite3.Connection:
        """Return the SQLite connection for the current thread; create if needed."""
        if not self._open:
            raise RuntimeError("HashCache is not open()")
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            try:
                conn.execute("SELECT 1")
            except sqlite3.Error:
                # Stale/closed connection can remain in thread-local state after
                # cross-thread cleanup; discard and recreate safely.
                with self._conn_lock:
                    self._connections.discard(conn)
                conn = None
                self._local.conn = None
        if conn is None:
            conn = sqlite3.connect(str(self.db_path), timeout=10.0, check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            conn.execute("PRAGMA temp_store=MEMORY;")
            conn.execute("PRAGMA cache_size=-20000;")
            conn.execute("PRAGMA busy_timeout=5000;")
            self._init_schema(conn)
            self._local.conn = conn
            with self._conn_lock:
                self._connections.add(conn)
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
            with self._conn_lock:
                self._connections.discard(conn)
            self._local.conn = None

    def close_all_connections(self) -> None:
        """Close every tracked SQLite connection across all threads."""
        with self._conn_lock:
            conns = list(self._connections)
            self._connections.clear()
        for conn in conns:
            try:
                conn.commit()
            except (sqlite3.Error, OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
                pass
            try:
                conn.close()
            except (sqlite3.Error, OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
                pass

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

    def get_quick(
        self,
        path: str | Path,
        sig: StatSignature,
        *,
        expected_algo: Optional[str] = None,
    ) -> Optional[str]:
        row = self._get_row(path)
        if not row:
            return None
        size, mtime_ns, dev, inode, quick_hash, quick_algo = row
        if (size, mtime_ns, dev, inode) != (sig.size, sig.mtime_ns, sig.dev, sig.inode):
            return None
        if expected_algo and str(quick_algo or "").lower() != str(expected_algo).lower():
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

    def get_full(
        self,
        path: str | Path,
        sig: StatSignature,
        *,
        expected_algo: Optional[str] = None,
    ) -> Optional[str]:
        row = self._get_row_full(path)
        if not row:
            return None
        size, mtime_ns, dev, inode, full_hash, full_algo = row
        if (size, mtime_ns, dev, inode) != (sig.size, sig.mtime_ns, sig.dev, sig.inode):
            return None
        if expected_algo and str(full_algo or "").lower() != str(expected_algo).lower():
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

    def set_many_full(
        self,
        items: list[tuple[str | Path, StatSignature, str, str]],
    ) -> None:
        """Batch-write full hashes with a single lock acquisition.

        ``items`` is a list of ``(path, sig, full_hash, algo)`` tuples.
        Existing quick_hash / quick_algo values are preserved (merged via SELECT
        first, then a single executemany upsert).  Per-item locking overhead is
        avoided: the lock is held for the entire batch.
        """
        if not items:
            return
        now = time.time()
        for attempt in range(5):
            try:
                with self._write_lock:
                    conn = self._require_conn()
                    path_strs = [str(p) for p, _, _, _ in items]
                    existing: dict[str, tuple] = {}
                    # Batch-fetch existing quick_hash/quick_algo to preserve them.
                    chunk_sz = self._SQLITE_MAX_VARS
                    for i in range(0, len(path_strs), chunk_sz):
                        chunk = path_strs[i : i + chunk_sz]
                        ph = ",".join("?" * len(chunk))
                        for row in conn.execute(
                            f"SELECT path, quick_hash, quick_algo, quick_bytes "
                            f"FROM file_hashes WHERE path IN ({ph})",
                            chunk,
                        ):
                            existing[row[0]] = (row[1], row[2], row[3])

                    rows = []
                    for path, sig, full_hash, algo in items:
                        p = str(path)
                        ex = existing.get(p)
                        qh = ex[0] if ex else None
                        qa = ex[1] if ex else None
                        qb = int(ex[2]) if ex and ex[2] is not None else 0
                        rows.append((
                            p,
                            sig.size, sig.mtime_ns, sig.dev, sig.inode,
                            qh, qa, qb,
                            full_hash, algo, now,
                        ))

                    conn.executemany(
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
                        rows,
                    )
                    conn.commit()
                return
            except sqlite3.OperationalError as exc:
                if "locked" in str(exc).lower() and attempt < 4:
                    time.sleep(0.05 * (attempt + 1))
                    continue
                raise

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _require_conn(self) -> sqlite3.Connection:
        return self.get_connection()

    def _get_row(
        self,
        path: str | Path,
    ) -> Optional[Tuple[int, int, int, int, Optional[str], Optional[str]]]:
        conn = self._require_conn()
        p = str(path)
        cur = conn.execute(
            "SELECT size, mtime_ns, dev, inode, quick_hash, quick_algo FROM file_hashes WHERE path=?",
            (p,),
        )
        return cur.fetchone()

    def _get_row_full(
        self,
        path: str | Path,
    ) -> Optional[Tuple[int, int, int, int, Optional[str], Optional[str]]]:
        conn = self._require_conn()
        p = str(path)
        cur = conn.execute(
            "SELECT size, mtime_ns, dev, inode, full_hash, full_algo FROM file_hashes WHERE path=?",
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
        for attempt in range(5):
            try:
                with self._write_lock:
                    conn = self._require_conn()
                    now = time.time()
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
                return
            except sqlite3.OperationalError as exc:
                if "locked" in str(exc).lower() and attempt < 4:
                    time.sleep(0.05 * (attempt + 1))
                    continue
                raise

    # ------------------------------------------------------------------
    # Batch lookups (1M-file scale optimisation)
    # ------------------------------------------------------------------

    _SQLITE_MAX_VARS = 900  # SQLite default SQLITE_MAX_VARIABLE_NUMBER is 999

    def get_many_quick(
        self,
        paths: list,
        sigs: dict,
        *,
        expected_algo: Optional[str] = None,
    ) -> dict:
        """Batch lookup of quick hashes.

        paths — list of str|Path
        sigs  — dict mapping str(path) -> StatSignature (used for invalidation)

        Returns dict mapping str(path) -> hash string or None.
        Paths absent from the DB or with a stale sig return None.
        """
        if not paths:
            return {}
        conn = self._require_conn()
        path_strs = [str(p) for p in paths]
        results: dict = {p: None for p in path_strs}
        for i in range(0, len(path_strs), self._SQLITE_MAX_VARS):
            chunk = path_strs[i : i + self._SQLITE_MAX_VARS]
            ph = ",".join("?" * len(chunk))
            for row in conn.execute(
                f"SELECT path, size, mtime_ns, dev, inode, quick_hash, quick_algo FROM file_hashes WHERE path IN ({ph})",
                chunk,
            ):
                p_str, size, mtime_ns, dev, inode, quick_hash, quick_algo = row
                sig = sigs.get(p_str)
                if sig and (size, mtime_ns, dev, inode) == (sig.size, sig.mtime_ns, sig.dev, sig.inode):
                    if expected_algo and str(quick_algo or "").lower() != str(expected_algo).lower():
                        continue
                    results[p_str] = quick_hash
        return results

    def get_many_full(
        self,
        paths: list,
        sigs: dict,
        *,
        expected_algo: Optional[str] = None,
    ) -> dict:
        """Batch lookup of full hashes.

        Same contract as get_many_quick but returns full_hash values.
        """
        if not paths:
            return {}
        conn = self._require_conn()
        path_strs = [str(p) for p in paths]
        results: dict = {p: None for p in path_strs}
        for i in range(0, len(path_strs), self._SQLITE_MAX_VARS):
            chunk = path_strs[i : i + self._SQLITE_MAX_VARS]
            ph = ",".join("?" * len(chunk))
            for row in conn.execute(
                f"SELECT path, size, mtime_ns, dev, inode, full_hash, full_algo FROM file_hashes WHERE path IN ({ph})",
                chunk,
            ):
                p_str, size, mtime_ns, dev, inode, full_hash, full_algo = row
                sig = sigs.get(p_str)
                if sig and (size, mtime_ns, dev, inode) == (sig.size, sig.mtime_ns, sig.dev, sig.inode):
                    if expected_algo and str(full_algo or "").lower() != str(expected_algo).lower():
                        continue
                    results[p_str] = full_hash
        return results

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

    def clear_all(self) -> None:
        """Delete all cached hash rows. Requires open()."""
        with self._write_lock:
            conn = self._require_conn()
            conn.execute("DELETE FROM file_hashes")
            conn.commit()
