# path: cerebro/services/inventory_db.py
from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence, Tuple


def _default_inventory_path() -> Path:
    """
    Default location for the inventory DB.

    Kept separate from history payloads — this is a fast, resumable
    "working index" for active/partial scans.
    """
    home = Path.home()
    return home / ".cerebro_cache" / "inventory.sqlite"


@dataclass(frozen=True, slots=True)
class InventoryScanState:
    scan_id: str
    status: str
    last_phase: str
    created_ts: float
    updated_ts: float
    roots: Tuple[str, ...]
    file_count: int


class InventoryDB:
    """
    SQLite-backed scan inventory for resumable scans.

    What it stores:
    - scans table: one row per scan_id (status, last_phase, roots, timestamps)
    - files table: discovered files for that scan_id (path, size, mtime_ns)

    What the pipeline uses:
    - begin_scan(...)            → register a scan & its roots
    - record_discovery(...)      → persist discovered files
    - get_scan_state(...)        → metadata + file_count
    - load_discovered_files(...) → list[(path, size, mtime_ns)]
    """

    def __init__(self, db_path: Optional[Path | str] = None):
        self.db_path: Path = Path(db_path) if db_path is not None else _default_inventory_path()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        """
        Open a connection and ensure schema is ready.

        Each public method uses its own connection context, so the caller
        does not need to manage open/close.
        """
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA temp_store=MEMORY;")
        conn.execute("PRAGMA cache_size=-20000;")
        self._init_schema(conn)
        return conn

    @staticmethod
    def _init_schema(conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS scans (
                scan_id     TEXT PRIMARY KEY,
                status      TEXT NOT NULL,
                last_phase  TEXT NOT NULL,
                created_ts  REAL NOT NULL,
                updated_ts  REAL NOT NULL,
                roots       TEXT NOT NULL,
                file_count  INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS files (
                scan_id  TEXT NOT NULL,
                path     TEXT NOT NULL,
                size     INTEGER NOT NULL,
                mtime_ns INTEGER NOT NULL,
                PRIMARY KEY (scan_id, path)
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_files_scan_id ON files(scan_id)")
        conn.commit()

    # ------------------------------------------------------------------
    # Scan metadata
    # ------------------------------------------------------------------

    def begin_scan(self, scan_id: str, roots: Sequence[str | Path]) -> None:
        """
        Register a scan and its roots.

        Idempotent: if the row already exists we simply overwrite the
        status/phase/timestamps and keep file_count = 0.
        """
        roots_str = "\n".join(str(Path(r)) for r in roots)
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO scans (
                    scan_id, status, last_phase, created_ts, updated_ts, roots, file_count
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (scan_id, "in_progress", "init", now, now, roots_str, 0),
            )
            conn.commit()

    def get_scan_state(self, scan_id: str) -> Optional[InventoryScanState]:
        with self._connect() as conn:
            cur = conn.execute(
                """
                SELECT scan_id, status, last_phase, created_ts, updated_ts, roots, file_count
                FROM scans
                WHERE scan_id = ?
                """,
                (scan_id,),
            )
            row = cur.fetchone()
        if not row:
            return None
        roots = tuple((row[5] or "").split("\n")) if row[5] else ()
        return InventoryScanState(
            scan_id=row[0],
            status=str(row[1]),
            last_phase=str(row[2]),
            created_ts=float(row[3]),
            updated_ts=float(row[4]),
            roots=roots,
            file_count=int(row[6] or 0),
        )

    # ------------------------------------------------------------------
    # Discovery persistence
    # ------------------------------------------------------------------

    def record_discovery(self, scan_id: str, files: List[tuple[str, int, int]]) -> None:
        """
        Persist discovered files for a scan.

        `files` is a list of (path, size, mtime_ns).
        """
        now = time.time()
        with self._connect() as conn:
            conn.execute("DELETE FROM files WHERE scan_id = ?", (scan_id,))
            if files:
                conn.executemany(
                    "INSERT INTO files (scan_id, path, size, mtime_ns) VALUES (?, ?, ?, ?)",
                    [(scan_id, str(p), int(sz), int(mn)) for (p, sz, mn) in files],
                )
            conn.execute(
                """
                INSERT OR REPLACE INTO scans (
                    scan_id, status, last_phase, created_ts, updated_ts, roots, file_count
                )
                VALUES (
                    ?,
                    COALESCE((SELECT status FROM scans WHERE scan_id = ?), 'in_progress'),
                    'discover',
                    COALESCE((SELECT created_ts FROM scans WHERE scan_id = ?), ?),
                    ?,
                    COALESCE((SELECT roots FROM scans WHERE scan_id = ?), ''),
                    ?
                )
                """,
                (scan_id, scan_id, scan_id, now, now, scan_id, len(files)),
            )
            conn.commit()

    def load_discovered_files(self, scan_id: str) -> List[tuple[str, int, int]]:
        """
        Return list of (path, size, mtime_ns) for the given scan_id.
        """
        with self._connect() as conn:
            cur = conn.execute(
                """
                SELECT path, size, mtime_ns
                FROM files
                WHERE scan_id = ?
                ORDER BY path COLLATE NOCASE
                """,
                (scan_id,),
            )
            rows = cur.fetchall()
        return [(str(p), int(sz), int(mn)) for (p, sz, mn) in rows]