"""
CheckpointDB — per-scan, file-level progress tracking.

Three tables
------------
scan_manifests   the scope / intent of each scan
scan_sessions    heartbeat + crash detection
file_checkpoints per-file status (pending / complete / error)

Write-behind pattern
--------------------
Hash results are queued in-memory and flushed by a background thread
every _FLUSH_INTERVAL seconds OR every _FLUSH_BATCH rows — whichever
comes first.  The scanner never waits for disk; it hashes at full CPU
speed.  Worst-case data loss on crash: 2 seconds of completed hashes
(those re-hash in ~1s on the next resume because hash_cache still has
the valid entries).
"""

from __future__ import annotations

import json
import logging
import queue
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Generator, List, Optional, Tuple

_DEFAULT_DB_PATH = Path.home() / ".cerebro" / "checkpoints.db"
_FLUSH_INTERVAL: float = 2.0
_FLUSH_BATCH: int = 500
_log = logging.getLogger(__name__)


@dataclass
class ScanManifest:
    scan_id: str
    created_at: float
    updated_at: float
    root_paths: List[str]
    scope_json: str
    status: str
    label: str = ""
    total_files: int = 0
    completed_files: int = 0



class CheckpointDB:
    """SQLite checkpoint store with async write-behind bulk inserts."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self._db_path = db_path or _DEFAULT_DB_PATH
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = self._open_conn()
        self._init_schema()

        # Write-behind queue items: (scan_id, path, file_hash, group_id, status, ts)
        self._write_queue: queue.Queue = queue.Queue()
        self._writer_stop = threading.Event()
        self._writer_thread = threading.Thread(
            target=self._writer_loop, daemon=True, name="ckpt-writer"
        )
        self._writer_thread.start()

    # ------------------------------------------------------------------ #
    # Connection helpers                                                   #
    # ------------------------------------------------------------------ #

    def _open_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA cache_size=-16000")   # 16 MB page cache
        return conn

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.executescript("""
                CREATE TABLE IF NOT EXISTS scan_manifests (
                    scan_id         TEXT PRIMARY KEY,
                    created_at      REAL NOT NULL,
                    updated_at      REAL NOT NULL,
                    root_paths      TEXT NOT NULL,
                    scope_json      TEXT NOT NULL,
                    status          TEXT NOT NULL DEFAULT 'active',
                    label           TEXT NOT NULL DEFAULT '',
                    total_files     INTEGER NOT NULL DEFAULT 0,
                    completed_files INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS scan_sessions (
                    scan_id        TEXT PRIMARY KEY,
                    last_heartbeat REAL NOT NULL,
                    status         TEXT NOT NULL DEFAULT 'running'
                );

                CREATE TABLE IF NOT EXISTS file_checkpoints (
                    scan_id       TEXT NOT NULL,
                    file_path     TEXT NOT NULL,
                    file_size     INTEGER NOT NULL DEFAULT 0,
                    last_modified REAL    NOT NULL DEFAULT 0,
                    file_hash     TEXT,
                    hash_status   TEXT NOT NULL DEFAULT 'pending',
                    group_id      TEXT,
                    updated_at    REAL NOT NULL DEFAULT 0,
                    PRIMARY KEY (scan_id, file_path)
                );

                CREATE INDEX IF NOT EXISTS idx_fc_status
                    ON file_checkpoints (scan_id, hash_status);

                CREATE INDEX IF NOT EXISTS idx_fc_hash
                    ON file_checkpoints (scan_id, file_hash)
                    WHERE file_hash IS NOT NULL;

                CREATE INDEX IF NOT EXISTS idx_fc_group
                    ON file_checkpoints (scan_id, group_id)
                    WHERE group_id IS NOT NULL;
            """)
            self._conn.commit()

    # ------------------------------------------------------------------ #
    # Manifest management                                                  #
    # ------------------------------------------------------------------ #

    def create_manifest(
        self,
        root_paths: List[str],
        scope: Dict,
        label: str = "",
    ) -> str:
        """Create a new scan manifest; return its UUID scan_id."""
        scan_id = str(uuid.uuid4())
        now = time.time()
        roots_json = json.dumps(sorted(str(p) for p in root_paths))
        scope_str = json.dumps(scope, sort_keys=True)
        with self._lock:
            self._conn.execute(
                """INSERT INTO scan_manifests
                   (scan_id, created_at, updated_at, root_paths, scope_json, status, label)
                   VALUES (?, ?, ?, ?, ?, 'active', ?)""",
                (scan_id, now, now, roots_json, scope_str, label),
            )
            self._conn.execute(
                "INSERT INTO scan_sessions (scan_id, last_heartbeat, status) VALUES (?, ?, 'running')",
                (scan_id, now),
            )
            self._conn.commit()
        return scan_id

    def find_resumable_manifest(
        self,
        root_paths: List[str],
        scope: Dict,
        max_age_days: int = 7,
    ) -> Optional[ScanManifest]:
        """Return the most recent paused/interrupted manifest matching scope, or None."""
        roots_json = json.dumps(sorted(str(p) for p in root_paths))
        scope_str = json.dumps(scope, sort_keys=True)
        cutoff = time.time() - max_age_days * 86400
        with self._lock:
            row = self._conn.execute(
                """SELECT scan_id, created_at, updated_at, root_paths, scope_json,
                          status, label, total_files, completed_files
                   FROM scan_manifests
                   WHERE root_paths = ? AND scope_json = ?
                     AND status IN ('active', 'paused', 'crashed')
                     AND created_at >= ?
                     AND total_files > 0
                   ORDER BY created_at DESC LIMIT 1""",
                (roots_json, scope_str, cutoff),
            ).fetchone()
        if not row:
            return None
        return ScanManifest(
            scan_id=row[0], created_at=row[1], updated_at=row[2],
            root_paths=json.loads(row[3]), scope_json=row[4],
            status=row[5], label=row[6], total_files=row[7], completed_files=row[8],
        )

    def list_resumable_manifests(self, max_age_days: int = 7) -> List[ScanManifest]:
        """All paused/interrupted manifests sorted by recency."""
        cutoff = time.time() - max_age_days * 86400
        with self._lock:
            rows = self._conn.execute(
                """SELECT scan_id, created_at, updated_at, root_paths, scope_json,
                          status, label, total_files, completed_files
                   FROM scan_manifests
                   WHERE status IN ('active', 'paused', 'crashed')
                     AND created_at >= ?
                     AND total_files > 0
                   ORDER BY created_at DESC""",
                (cutoff,),
            ).fetchall()
        out: List[ScanManifest] = []
        for row in rows:
            out.append(ScanManifest(
                scan_id=row[0], created_at=row[1], updated_at=row[2],
                root_paths=json.loads(row[3]), scope_json=row[4],
                status=row[5], label=row[6], total_files=row[7], completed_files=row[8],
            ))
        return out

    def update_manifest_status(self, scan_id: str, status: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE scan_manifests SET status=?, updated_at=? WHERE scan_id=?",
                (status, time.time(), scan_id),
            )
            self._conn.commit()

    def set_manifest_total(self, scan_id: str, total: int) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE scan_manifests SET total_files=?, updated_at=? WHERE scan_id=?",
                (total, time.time(), scan_id),
            )
            self._conn.commit()

    # ------------------------------------------------------------------ #
    # Session / heartbeat                                                  #
    # ------------------------------------------------------------------ #

    def beat(self, scan_id: str) -> None:
        """Refresh heartbeat (call every ~10 s from the scanner thread)."""
        with self._lock:
            self._conn.execute(
                "UPDATE scan_sessions SET last_heartbeat=? WHERE scan_id=?",
                (time.time(), scan_id),
            )
            self._conn.commit()

    def mark_stale_as_crashed(self, stale_minutes: int = 5) -> None:
        """Mark 'active' manifests whose session heartbeat is stale as 'crashed'."""
        cutoff = time.time() - stale_minutes * 60
        with self._lock:
            self._conn.execute(
                """UPDATE scan_manifests SET status='crashed', updated_at=?
                   WHERE status='active'
                     AND scan_id IN (
                         SELECT scan_id FROM scan_sessions
                         WHERE last_heartbeat < ?
                     )""",
                (time.time(), cutoff),
            )
            self._conn.commit()

    # ------------------------------------------------------------------ #
    # File checkpoints — initial bulk insert                               #
    # ------------------------------------------------------------------ #

    def insert_pending_files(
        self,
        scan_id: str,
        files: List[Tuple[str, int, float]],
    ) -> None:
        """Bulk-insert discovered files as 'pending'.  files = [(path, size, mtime)]."""
        now = time.time()
        rows = [
            (scan_id, path, size, mtime, None, "pending", None, now)
            for path, size, mtime in files
        ]
        with self._lock:
            self._conn.executemany(
                """INSERT OR IGNORE INTO file_checkpoints
                   (scan_id, file_path, file_size, last_modified, file_hash,
                    hash_status, group_id, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                rows,
            )
            self._conn.execute(
                "UPDATE scan_manifests SET total_files=?, updated_at=? WHERE scan_id=?",
                (len(files), time.time(), scan_id),
            )
            self._conn.commit()
        total, pending = self.get_counts(scan_id)
        _log.info(
            "[Checkpoint] seed pending: scan_id=%s inserted=%d total=%d pending=%d completed=%d",
            scan_id,
            len(files),
            total,
            pending,
            max(0, total - pending),
        )

    # ------------------------------------------------------------------ #
    # Write-behind: async hash result persistence                          #
    # ------------------------------------------------------------------ #

    def enqueue_hash_result(
        self,
        scan_id: str,
        file_path: str,
        file_hash: Optional[str],
        group_id: Optional[str] = None,
        status: str = "complete",
    ) -> None:
        """Non-blocking: queue a hash result for async bulk-flush."""
        self._write_queue.put_nowait(
            (scan_id, file_path, file_hash, group_id, status, time.time())
        )

    def _writer_loop(self) -> None:
        """Background thread: drain write queue with time-gated bulk inserts."""
        pending: List = []
        last_flush = time.monotonic()

        while not self._writer_stop.is_set():
            deadline = last_flush + _FLUSH_INTERVAL
            while len(pending) < _FLUSH_BATCH:
                timeout = max(0.05, deadline - time.monotonic())
                try:
                    item = self._write_queue.get(timeout=timeout)
                    pending.append(item)
                except queue.Empty:
                    break
                if time.monotonic() >= deadline:
                    break

            if pending:
                self._flush_items(pending)
                pending.clear()
                last_flush = time.monotonic()

        # Final flush on shutdown
        leftover: List = []
        try:
            while True:
                leftover.append(self._write_queue.get_nowait())
        except queue.Empty:
            pass
        if leftover:
            self._flush_items(leftover)

    def _flush_items(self, items: List) -> None:
        """Bulk UPDATE completed hashes into file_checkpoints."""
        rows = [
            (item[2], item[3], item[4], item[5], item[0], item[1])
            #  hash    group   status  ts       scan_id  path
            for item in items
        ]
        completed_count = sum(1 for item in items if item[4] == "complete")
        error_count = sum(1 for item in items if item[4] == "error")
        try:
            with self._lock:
                self._conn.executemany(
                    """UPDATE file_checkpoints
                       SET file_hash=?, group_id=?, hash_status=?, updated_at=?
                       WHERE scan_id=? AND file_path=?""",
                    rows,
                )
                if completed_count and items:
                    self._conn.execute(
                        """UPDATE scan_manifests
                           SET completed_files = completed_files + ?, updated_at=?
                           WHERE scan_id=?""",
                        (completed_count, time.time(), items[0][0]),
                    )
                self._conn.commit()
            if items:
                scan_id = str(items[0][0])
                _log.debug(
                    "[Checkpoint] writer flush: scan_id=%s rows=%d complete=%d error=%d",
                    scan_id,
                    len(items),
                    completed_count,
                    error_count,
                )
        except sqlite3.Error:
            pass  # non-fatal; hash_cache is the authoritative fast-resume store

    def flush_sync(self) -> None:
        """Drain the write queue synchronously (call before close/pause)."""
        pending: List = []
        try:
            while True:
                pending.append(self._write_queue.get_nowait())
        except queue.Empty:
            pass
        if pending:
            self._flush_items(pending)
            scan_ids = sorted({str(item[0]) for item in pending if item and item[0]})
            _log.info(
                "[Checkpoint] flush_sync drained=%d scan_ids=%s",
                len(pending),
                ",".join(scan_ids) if scan_ids else "-",
            )

    # ------------------------------------------------------------------ #
    # Resume helpers                                                       #
    # ------------------------------------------------------------------ #

    def get_counts(self, scan_id: str) -> Tuple[int, int]:
        """Return (total_files, pending_files) for a scan."""
        with self._lock:
            row = self._conn.execute(
                """SELECT
                     COUNT(*),
                     SUM(CASE WHEN hash_status='pending' THEN 1 ELSE 0 END)
                   FROM file_checkpoints WHERE scan_id=?""",
                (scan_id,),
            ).fetchone()
        if not row:
            return 0, 0
        return (int(row[0] or 0), int(row[1] or 0))

    def iter_pending_files(
        self,
        scan_id: str,
        batch_size: int = 50_000,
    ) -> Generator[List[Tuple[str, int, float]], None, None]:
        """Yield batches of (path, size, mtime) for files still pending."""
        offset = 0
        while True:
            with self._lock:
                rows = self._conn.execute(
                    """SELECT file_path, file_size, last_modified
                       FROM file_checkpoints
                       WHERE scan_id=? AND hash_status='pending'
                       ORDER BY file_size DESC
                       LIMIT ? OFFSET ?""",
                    (scan_id, batch_size, offset),
                ).fetchall()
            if not rows:
                break
            yield [(r[0], int(r[1]), float(r[2])) for r in rows]
            if len(rows) < batch_size:
                break
            offset += batch_size

    def iter_completed_hashes(
        self,
        scan_id: str,
        batch_size: int = 50_000,
    ) -> Generator[List[Tuple[str, int, float, str]], None, None]:
        """Yield batches of (path, size, mtime, hash) for completed files."""
        offset = 0
        while True:
            with self._lock:
                rows = self._conn.execute(
                    """SELECT file_path, file_size, last_modified, file_hash
                       FROM file_checkpoints
                       WHERE scan_id=? AND hash_status='complete'
                             AND file_hash IS NOT NULL
                       ORDER BY file_path
                       LIMIT ? OFFSET ?""",
                    (scan_id, batch_size, offset),
                ).fetchall()
            if not rows:
                break
            yield [(r[0], int(r[1]), float(r[2]), str(r[3])) for r in rows]
            if len(rows) < batch_size:
                break
            offset += batch_size

    # ------------------------------------------------------------------ #
    # Integrity check before re-hashing                                    #
    # ------------------------------------------------------------------ #

    def validate_pending_file(
        self, file_path: str, stored_size: int, stored_mtime: float
    ) -> bool:
        """Return True if the file still exists and metadata matches checkpoint."""
        try:
            import os
            st = os.stat(file_path)
            return st.st_size == stored_size and abs(st.st_mtime - stored_mtime) < 2.0
        except OSError:
            return False

    # ------------------------------------------------------------------ #
    # Garbage collection                                                   #
    # ------------------------------------------------------------------ #

    def purge_old_scans(self, max_age_days: int = 7) -> int:
        """Delete abandoned scans older than max_age_days. Returns count removed."""
        cutoff = time.time() - max_age_days * 86400
        with self._lock:
            rows = self._conn.execute(
                """SELECT scan_id FROM scan_manifests
                   WHERE status != 'completed' AND created_at < ?""",
                (cutoff,),
            ).fetchall()
            ids = [r[0] for r in rows]
            if ids:
                ph = ",".join("?" * len(ids))
                self._conn.execute(f"DELETE FROM file_checkpoints WHERE scan_id IN ({ph})", ids)
                self._conn.execute(f"DELETE FROM scan_sessions WHERE scan_id IN ({ph})", ids)
                self._conn.execute(f"DELETE FROM scan_manifests WHERE scan_id IN ({ph})", ids)
                self._conn.commit()
        return len(ids)

    # ------------------------------------------------------------------ #
    # Lifecycle                                                            #
    # ------------------------------------------------------------------ #

    def close(self) -> None:
        self._writer_stop.set()
        self._writer_thread.join(timeout=5)
        with self._lock:
            try:
                self._conn.close()
            except sqlite3.Error:
                pass

    def __enter__(self) -> "CheckpointDB":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()



_DEFAULT_INSTANCE: Optional[CheckpointDB] = None
_INSTANCE_LOCK = threading.Lock()


def get_checkpoint_db() -> CheckpointDB:
    """Return the shared CheckpointDB singleton (created on first call)."""
    global _DEFAULT_INSTANCE
    if _DEFAULT_INSTANCE is None:
        with _INSTANCE_LOCK:
            if _DEFAULT_INSTANCE is None:
                _DEFAULT_INSTANCE = CheckpointDB()
    return _DEFAULT_INSTANCE
