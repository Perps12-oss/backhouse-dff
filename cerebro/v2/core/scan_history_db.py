"""SQLite-backed scan history for v2."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


def _default_db_path() -> Path:
    return Path.home() / ".cerebro" / "scan_history.db"


@dataclass
class ScanHistoryEntry:
    timestamp: float
    mode: str
    folders: list[str]
    groups_found: int
    files_found: int
    bytes_reclaimable: int
    duration_seconds: float


class ScanHistoryDB:
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or _default_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS scan_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    mode TEXT NOT NULL,
                    folders_json TEXT NOT NULL,
                    groups_found INTEGER NOT NULL,
                    files_found INTEGER NOT NULL,
                    bytes_reclaimable INTEGER NOT NULL,
                    duration_seconds REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_scan_history_ts ON scan_history(timestamp DESC);
                """
            )
            self._conn.commit()

    def record_scan(
        self,
        mode: str,
        folders: list[str],
        groups_found: int,
        files_found: int,
        bytes_reclaimable: int,
        duration_seconds: float,
        timestamp: float | None = None,
    ) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO scan_history (
                    timestamp, mode, folders_json, groups_found, files_found, bytes_reclaimable, duration_seconds
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    float(time.time() if timestamp is None else timestamp),
                    mode,
                    json.dumps(folders),
                    int(groups_found),
                    int(files_found),
                    int(bytes_reclaimable),
                    float(duration_seconds),
                ),
            )
            self._conn.commit()

    def get_recent(self, limit: int = 100) -> list[ScanHistoryEntry]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT timestamp, mode, folders_json, groups_found, files_found, bytes_reclaimable, duration_seconds
                FROM scan_history
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()
        out: list[ScanHistoryEntry] = []
        for row in rows:
            out.append(
                ScanHistoryEntry(
                    timestamp=float(row[0]),
                    mode=str(row[1]),
                    folders=list(json.loads(row[2] or "[]")),
                    groups_found=int(row[3]),
                    files_found=int(row[4]),
                    bytes_reclaimable=int(row[5]),
                    duration_seconds=float(row[6]),
                )
            )
        return out

    def clear(self) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM scan_history")
            self._conn.commit()

    def import_legacy_json(self, json_path: Path) -> int:
        if not json_path.exists():
            return 0
        try:
            payload = json.loads(json_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
            return 0
        if not isinstance(payload, Iterable):
            return 0
        count = 0
        for row in payload:
            try:
                self.record_scan(
                    mode=str(row.get("mode", "files")),
                    folders=[str(x) for x in row.get("folders", [])],
                    groups_found=int(row.get("groups_found", 0)),
                    files_found=int(row.get("files_found", 0)),
                    bytes_reclaimable=int(row.get("bytes_reclaimable", 0)),
                    duration_seconds=float(row.get("duration_seconds", 0.0)),
                    timestamp=float(row.get("timestamp", time.time())),
                )
                count += 1
            except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
                continue
        return count


_DEFAULT_DB: ScanHistoryDB | None = None


def get_scan_history_db() -> ScanHistoryDB:
    global _DEFAULT_DB
    if _DEFAULT_DB is None:
        _DEFAULT_DB = ScanHistoryDB()
    return _DEFAULT_DB
