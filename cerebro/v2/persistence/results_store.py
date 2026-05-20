"""Spill large scan result sets to SQLite instead of holding all groups in RAM."""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Iterator, List, Optional

from cerebro.core.paths import cerebro_user_root
from cerebro.engines.base_engine import DuplicateFile, DuplicateGroup

_DEFAULT_DB = "results_store.db"


def _db_path() -> Path:
    root = cerebro_user_root() / "results"
    root.mkdir(parents=True, exist_ok=True)
    return root / _DEFAULT_DB


class ResultsStore:
    """Session-scoped duplicate groups on disk (WAL SQLite)."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self._path = db_path or _db_path()
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA busy_timeout=5000")
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    scan_mode TEXT NOT NULL,
                    created_ts REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS groups (
                    session_id TEXT NOT NULL,
                    ord INTEGER NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY (session_id, ord)
                );
                """
            )
            self._conn.commit()

    def clear_session(self, session_id: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM groups WHERE session_id=?", (session_id,))
            self._conn.execute("DELETE FROM sessions WHERE session_id=?", (session_id,))
            self._conn.commit()

    def import_groups(
        self,
        session_id: str,
        groups: List[DuplicateGroup],
        *,
        scan_mode: str = "files",
        created_ts: float = 0.0,
    ) -> int:
        from cerebro.v2.persistence.scan_snapshot import _group_to_dict

        with self._lock:
            self.clear_session(session_id)
            self._conn.execute(
                "INSERT OR REPLACE INTO sessions(session_id, scan_mode, created_ts) VALUES (?,?,?)",
                (session_id, scan_mode, float(created_ts)),
            )
            for i, g in enumerate(groups):
                payload = json.dumps(_group_to_dict(g), ensure_ascii=False)
                self._conn.execute(
                    "INSERT INTO groups(session_id, ord, payload) VALUES (?,?,?)",
                    (session_id, i, payload),
                )
            self._conn.commit()
        return len(groups)

    def count(self, session_id: str) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM groups WHERE session_id=?", (session_id,)
            ).fetchone()
        return int(row[0] if row else 0)

    def iter_groups(
        self,
        session_id: str,
        offset: int = 0,
        limit: int = 500,
    ) -> Iterator[DuplicateGroup]:
        from cerebro.v2.persistence.scan_snapshot import _group_from_dict

        with self._lock:
            rows = self._conn.execute(
                """
                SELECT payload FROM groups
                WHERE session_id=?
                ORDER BY ord
                LIMIT ? OFFSET ?
                """,
                (session_id, int(limit), int(offset)),
            ).fetchall()
        for (payload,) in rows:
            data = json.loads(payload)
            if isinstance(data, dict):
                yield _group_from_dict(data)

    def load_all(self, session_id: str, *, max_groups: int = 50_000) -> List[DuplicateGroup]:
        return list(self.iter_groups(session_id, offset=0, limit=max_groups))

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                pass


_store_singleton: Optional[ResultsStore] = None
_store_lock = threading.Lock()


def get_results_store() -> ResultsStore:
    global _store_singleton
    with _store_lock:
        if _store_singleton is None:
            _store_singleton = ResultsStore()
        return _store_singleton
