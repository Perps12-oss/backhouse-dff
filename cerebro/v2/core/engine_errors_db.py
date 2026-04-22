"""
SQLite-backed log of engine load failures (Phase-7 diagnostics overhaul).

Every time :class:`DiagnosticsPage` (or, in the future, ``ScanPage``'s
pre-scan banner) probes an engine and gets anything other than
:class:`~cerebro.v2.core.engine_deps.EngineState.AVAILABLE`, the outcome
is written here. The user can then see a "last failure" audit trail
instead of just the current live state — useful when a transient
``RUNTIME_ERROR`` clears up on retry and leaves no forensic breadcrumb.

Mirrors the shape of :mod:`cerebro.v2.core.scan_history_db` and
:mod:`cerebro.v2.core.deletion_history_db`:

* Long-lived connection with a re-entrant lock.
* Idempotent ``CREATE TABLE IF NOT EXISTS``.
* Singleton accessor :func:`get_engine_errors_db`.
"""
from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


def _default_db_path() -> Path:
    return Path.home() / ".cerebro" / "engine_errors.db"


@dataclass
class EngineErrorEntry:
    timestamp: float
    engine_key: str
    state: str
    detail: str
    module_path: Optional[str]
    exception_class: Optional[str]
    exception_message: Optional[str]


class EngineErrorsDB:
    """Append-only log of non-AVAILABLE engine probe outcomes."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or _default_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._init_schema()

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS engine_load_errors (
                    id                INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp         REAL NOT NULL,
                    engine_key        TEXT NOT NULL,
                    state             TEXT NOT NULL,
                    detail            TEXT NOT NULL,
                    module_path       TEXT,
                    exception_class   TEXT,
                    exception_message TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_engine_errors_ts
                    ON engine_load_errors(timestamp DESC);
                CREATE INDEX IF NOT EXISTS idx_engine_errors_key_ts
                    ON engine_load_errors(engine_key, timestamp DESC);
                """
            )
            self._conn.commit()

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def record_error(
        self,
        engine_key: str,
        state: str,
        detail: str,
        module_path: Optional[str] = None,
        exception_class: Optional[str] = None,
        exception_message: Optional[str] = None,
        timestamp: Optional[float] = None,
    ) -> None:
        """Append one row. Writes are best-effort — no exceptions escape."""
        try:
            with self._lock:
                self._conn.execute(
                    """
                    INSERT INTO engine_load_errors (
                        timestamp, engine_key, state, detail,
                        module_path, exception_class, exception_message
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        float(time.time() if timestamp is None else timestamp),
                        str(engine_key),
                        str(state),
                        str(detail),
                        module_path,
                        exception_class,
                        exception_message,
                    ),
                )
                self._conn.commit()
        except sqlite3.Error:
            # Diagnostics telemetry must never break the app.
            pass

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def get_recent_errors(self, limit: int = 50) -> list[EngineErrorEntry]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT timestamp, engine_key, state, detail,
                       module_path, exception_class, exception_message
                FROM engine_load_errors
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()
        return [
            EngineErrorEntry(
                timestamp=float(r[0]),
                engine_key=str(r[1]),
                state=str(r[2]),
                detail=str(r[3]),
                module_path=(r[4] if r[4] is None else str(r[4])),
                exception_class=(r[5] if r[5] is None else str(r[5])),
                exception_message=(r[6] if r[6] is None else str(r[6])),
            )
            for r in rows
        ]

    def get_last_error_for(self, engine_key: str) -> Optional[EngineErrorEntry]:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT timestamp, engine_key, state, detail,
                       module_path, exception_class, exception_message
                FROM engine_load_errors
                WHERE engine_key = ?
                ORDER BY timestamp DESC
                LIMIT 1
                """,
                (str(engine_key),),
            ).fetchone()
        if row is None:
            return None
        return EngineErrorEntry(
            timestamp=float(row[0]),
            engine_key=str(row[1]),
            state=str(row[2]),
            detail=str(row[3]),
            module_path=(row[4] if row[4] is None else str(row[4])),
            exception_class=(row[5] if row[5] is None else str(row[5])),
            exception_message=(row[6] if row[6] is None else str(row[6])),
        )

    def count(self) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM engine_load_errors"
            ).fetchone()
        return int(row[0]) if row else 0

    def clear(self) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM engine_load_errors")
            self._conn.commit()

    def close(self) -> None:
        """Close the underlying SQLite connection.

        The production singleton stays open for the life of the process,
        but tests and the optional "Clear history" flow need an explicit
        handle-release so the DB file can be deleted on Windows (which
        refuses to unlink files that still have open handles)."""
        with self._lock:
            try:
                self._conn.close()
            except sqlite3.Error:
                pass


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_DEFAULT_DB: EngineErrorsDB | None = None


def get_engine_errors_db() -> EngineErrorsDB:
    global _DEFAULT_DB
    if _DEFAULT_DB is None:
        _DEFAULT_DB = EngineErrorsDB()
    return _DEFAULT_DB


__all__ = ["EngineErrorEntry", "EngineErrorsDB", "get_engine_errors_db"]
