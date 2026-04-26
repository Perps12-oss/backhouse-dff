"""Background scan scheduler — persists jobs to SQLite, fires via threading.Timer."""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional

from cerebro.core.paths import default_cerebro_cache_dir

_log = logging.getLogger(__name__)

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS scheduled_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    label TEXT NOT NULL,
    folders TEXT NOT NULL,
    mode TEXT NOT NULL DEFAULT 'files',
    interval_hours REAL NOT NULL DEFAULT 24.0,
    enabled INTEGER NOT NULL DEFAULT 1,
    last_run REAL,
    next_run REAL NOT NULL
);
"""


@dataclass
class ScheduledJob:
    id: int
    label: str
    folders: List[str]
    mode: str
    interval_hours: float
    enabled: bool
    last_run: Optional[float]
    next_run: float


def _row_to_job(row: tuple) -> ScheduledJob:
    job_id, label, folders_json, mode, interval_hours, enabled, last_run, next_run = row
    return ScheduledJob(
        id=int(job_id),
        label=str(label),
        folders=json.loads(folders_json),
        mode=str(mode),
        interval_hours=float(interval_hours),
        enabled=bool(enabled),
        last_run=float(last_run) if last_run is not None else None,
        next_run=float(next_run),
    )


class CerebroScheduler:
    """Persists scheduled scan jobs to SQLite and fires them via a daemon thread."""

    def __init__(
        self,
        db_path: Path,
        on_scan_due: Callable[[ScheduledJob], None],
    ) -> None:
        self._db_path = db_path
        self._on_scan_due = on_scan_due
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    # ------------------------------------------------------------------
    # DB init
    # ------------------------------------------------------------------

    def _init_db(self) -> None:
        with self._lock, sqlite3.connect(str(self._db_path), timeout=10.0) as conn:
            conn.execute(_CREATE_TABLE)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the daemon thread that checks for due jobs every 60 s."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="CerebroScheduler",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """Signal the check thread to stop and wait for it to exit."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None

    # ------------------------------------------------------------------
    # Public CRUD
    # ------------------------------------------------------------------

    def add_job(
        self,
        label: str,
        folders: List[str],
        mode: str,
        interval_hours: float,
    ) -> ScheduledJob:
        """Persist a new job and return it with its assigned id."""
        next_run = time.time() + interval_hours * 3600.0
        folders_json = json.dumps(folders)
        with self._lock, sqlite3.connect(str(self._db_path), timeout=10.0) as conn:
            cur = conn.execute(
                """
                INSERT INTO scheduled_jobs
                    (label, folders, mode, interval_hours, enabled, last_run, next_run)
                VALUES (?, ?, ?, ?, 1, NULL, ?)
                """,
                (label, folders_json, mode, float(interval_hours), next_run),
            )
            job_id = cur.lastrowid
        return ScheduledJob(
            id=int(job_id),
            label=label,
            folders=folders,
            mode=mode,
            interval_hours=interval_hours,
            enabled=True,
            last_run=None,
            next_run=next_run,
        )

    def remove_job(self, job_id: int) -> None:
        """Delete a job by id (no-op if not found)."""
        with self._lock, sqlite3.connect(str(self._db_path), timeout=10.0) as conn:
            conn.execute("DELETE FROM scheduled_jobs WHERE id = ?", (int(job_id),))

    def toggle_job(self, job_id: int, enabled: bool) -> None:
        """Enable or disable a job without deleting it."""
        with self._lock, sqlite3.connect(str(self._db_path), timeout=10.0) as conn:
            conn.execute(
                "UPDATE scheduled_jobs SET enabled = ? WHERE id = ?",
                (1 if enabled else 0, int(job_id)),
            )

    def list_jobs(self) -> List[ScheduledJob]:
        """Return all persisted jobs ordered by id."""
        with self._lock, sqlite3.connect(str(self._db_path), timeout=10.0) as conn:
            cur = conn.execute(
                """
                SELECT id, label, folders, mode, interval_hours, enabled, last_run, next_run
                FROM scheduled_jobs
                ORDER BY id
                """
            )
            return [_row_to_job(row) for row in cur.fetchall()]

    # ------------------------------------------------------------------
    # Internal: check loop
    # ------------------------------------------------------------------

    def _run_loop(self) -> None:
        """Check for due jobs every 60 s until stop() is called."""
        while not self._stop_event.wait(60):
            try:
                self._check_and_fire()
            except Exception:
                _log.exception("CerebroScheduler._check_and_fire raised unexpectedly")

    def _check_and_fire(self) -> None:
        """Fire every enabled job whose next_run <= now, then reschedule it."""
        now = time.time()
        due: List[ScheduledJob] = []
        with self._lock, sqlite3.connect(str(self._db_path), timeout=10.0) as conn:
            cur = conn.execute(
                """
                SELECT id, label, folders, mode, interval_hours, enabled, last_run, next_run
                FROM scheduled_jobs
                WHERE enabled = 1 AND next_run <= ?
                """,
                (now,),
            )
            rows = cur.fetchall()
            for row in rows:
                job = _row_to_job(row)
                next_run = now + job.interval_hours * 3600.0
                conn.execute(
                    "UPDATE scheduled_jobs SET last_run = ?, next_run = ? WHERE id = ?",
                    (now, next_run, job.id),
                )
                due.append(job)

        for job in due:
            try:
                self._on_scan_due(job)
            except Exception:
                _log.exception("on_scan_due raised for job %d (%s)", job.id, job.label)


def default_scheduler_db_path() -> Path:
    """Canonical DB path: ~/.cerebro/cache/scheduler.db"""
    return default_cerebro_cache_dir() / "scheduler.db"
