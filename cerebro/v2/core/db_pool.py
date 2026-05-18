"""
cerebro/v2/core/db_pool.py — Shared SQLite connection factory (LT-3 / Decision F).

Same file paths, no migration required.
All connections are opened with WAL journal mode and a 5000ms busy timeout so
concurrent readers never block behind writers.

scan_history_db and deletion_history_db should obtain connections through
connect() when appropriate, but they are not forced to (degraded mode works).
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from pathlib import Path
from typing import Dict, Tuple

_log = logging.getLogger(__name__)

_pool_lock = threading.Lock()
# (path_str, thread_id) -> connection
_connections: Dict[Tuple[str, int], sqlite3.Connection] = {}


def connect(path: Path | str) -> sqlite3.Connection:
    """
    Return a per-thread SQLite connection to `path` with WAL mode and 5s timeout.

    Connections are reused within the same thread (per-thread pool).
    On first open, PRAGMA journal_mode=WAL and busy_timeout=5000 are set.
    On failure, falls back to a direct connection (degraded, not blocked).
    """
    path_str = str(Path(path).resolve())
    thread_id = threading.get_ident()
    key = (path_str, thread_id)

    with _pool_lock:
        conn = _connections.get(key)
        if conn is not None:
            # Verify connection is still open.
            try:
                conn.execute("SELECT 1")
                return conn
            except sqlite3.ProgrammingError:
                del _connections[key]

    try:
        conn = sqlite3.connect(path_str, check_same_thread=False, timeout=10.0)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        with _pool_lock:
            _connections[key] = conn
        return conn
    except Exception as exc:  # noqa: BLE001
        _log.warning("db_pool: falling back to direct connect for %s: %s", path_str, exc)
        return sqlite3.connect(path_str, check_same_thread=False, timeout=10.0)


def close_all() -> None:
    """Close all pooled connections (useful for test teardown)."""
    with _pool_lock:
        for conn in list(_connections.values()):
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass
        _connections.clear()
