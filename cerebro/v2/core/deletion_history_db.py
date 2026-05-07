"""SQLite deletion history for v2."""

from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


def _default_db_path() -> Path:
    return Path.home() / ".cerebro" / "deletion_history.db"


@dataclass
class DeletionHistoryEntry:
    id: int
    filename: str
    original_path: str
    file_size: int
    deletion_date: str
    scan_mode: str


class HistoryManager:
    """Robust sqlite history provider for deletion audit trail."""

    def __init__(self, db_path: str | None = None):
        if db_path:
            self.db_path = str(Path(db_path).resolve())
        else:
            self.db_path = str(_default_db_path())
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_db()

    def _init_db(self) -> None:
        with self._lock, sqlite3.connect(self.db_path, timeout=10.0) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS deletion_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    filename TEXT NOT NULL,
                    original_path TEXT NOT NULL,
                    file_size INTEGER NOT NULL,
                    deletion_date TEXT NOT NULL,
                    scan_mode TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_deletion_date ON deletion_history(deletion_date DESC)"
            )
            conn.execute("CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT)")
            conn.execute(
                "INSERT OR IGNORE INTO metadata (key, value) VALUES ('schema_version', '1')"
            )

    def log_deletion(self, file_path: str, size: int, mode: str) -> bool:
        try:
            filename = Path(file_path).name
            timestamp = datetime.now(timezone.utc).isoformat()
            with self._lock, sqlite3.connect(self.db_path, timeout=10.0) as conn:
                conn.execute(
                    """
                    INSERT INTO deletion_history
                    (filename, original_path, file_size, deletion_date, scan_mode)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (filename, str(file_path), int(size), timestamp, str(mode)),
                )
            return True
        except sqlite3.Error:
            return False

    def get_recent_history(self, limit: int = 100) -> list[tuple[Any, ...]]:
        try:
            with self._lock, sqlite3.connect(self.db_path, timeout=10.0) as conn:
                cur = conn.execute(
                    """
                    SELECT id, filename, original_path, file_size, deletion_date, scan_mode
                    FROM deletion_history
                    ORDER BY deletion_date DESC
                    LIMIT ?
                    """,
                    (int(limit),),
                )
                return cur.fetchall()
        except sqlite3.Error:
            return []

    def search_history(self, pattern: str) -> list[tuple[Any, ...]]:
        q = f"%{pattern}%"
        try:
            with self._lock, sqlite3.connect(self.db_path, timeout=10.0) as conn:
                cur = conn.execute(
                    """
                    SELECT id, filename, original_path, file_size, deletion_date, scan_mode
                    FROM deletion_history
                    WHERE filename LIKE ? OR original_path LIKE ?
                    ORDER BY deletion_date DESC
                    """,
                    (q, q),
                )
                return cur.fetchall()
        except sqlite3.Error:
            return []

    def prune_history(self, days: int = 30) -> int:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        try:
            with self._lock, sqlite3.connect(self.db_path, timeout=10.0) as conn:
                cur = conn.execute("DELETE FROM deletion_history WHERE deletion_date < ?", (cutoff,))
                return int(cur.rowcount)
        except sqlite3.Error:
            return 0

    def clear_history(self) -> bool:
        try:
            with self._lock, sqlite3.connect(self.db_path, timeout=10.0) as conn:
                conn.execute("DELETE FROM deletion_history")
            return True
        except sqlite3.Error:
            return False


_DEFAULT_MANAGER: HistoryManager | None = None


def get_default_history_manager() -> HistoryManager:
    global _DEFAULT_MANAGER
    if _DEFAULT_MANAGER is None:
        _DEFAULT_MANAGER = HistoryManager()
    return _DEFAULT_MANAGER


def log_deletion_event(file_path: str, size: int, mode: str) -> bool:
    return get_default_history_manager().log_deletion(file_path=file_path, size=size, mode=mode)
