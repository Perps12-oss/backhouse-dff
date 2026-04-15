"""
Scan Result Store — persistent SQLite store for duplicate scan results.

Enables query-backed Review: worker writes results here; Review loads by scan_id
with paged group windows instead of full in-memory result.

Schema: scans, duplicate_groups, group_files, selection_state (optional).
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Category from path (extension) — mirrors Review filter categories; no UI dependency
_CATEGORY_EXTS: Dict[str, set] = {
    "Images": {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".webp", ".heic", ".heif", ".ico", ".svg"},
    "Videos": {".mp4", ".avi", ".mkv", ".mov", ".wmv", ".webm", ".flv", ".m4v", ".mpg", ".mpeg", ".3gp"},
    "Audio": {".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".wma", ".opus", ".aiff"},
    "Archives": {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".lz", ".cab"},
    "Documents": {".pdf", ".doc", ".docx", ".txt", ".rtf", ".odt", ".xls", ".xlsx", ".ppt", ".pptx", ".csv"},
}


def _category_from_path(path: str) -> str:
    ext = Path(path).suffix.lower()
    for category, exts in _CATEGORY_EXTS.items():
        if ext in exts:
            return category
    return "Other"


class ScanResultStore:
    """SQLite-backed store for scan metadata and duplicate groups. Thread-safe per connection."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self._db_path = Path(db_path) if db_path else (Path.home() / ".cerebro" / "scan_results.db")
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self, conn: sqlite3.Connection) -> None:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS scans (
                scan_id TEXT PRIMARY KEY,
                scan_root TEXT NOT NULL,
                scan_name TEXT,
                status TEXT NOT NULL DEFAULT 'completed',
                files_scanned INTEGER NOT NULL DEFAULT 0,
                groups_count INTEGER NOT NULL DEFAULT 0,
                total_size INTEGER NOT NULL DEFAULT 0,
                scan_duration_seconds REAL,
                created_at REAL NOT NULL,
                config_json TEXT
            );
            CREATE TABLE IF NOT EXISTS duplicate_groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scan_id TEXT NOT NULL,
                group_index INTEGER NOT NULL,
                duplicate_hash TEXT,
                file_count INTEGER NOT NULL,
                total_bytes INTEGER NOT NULL DEFAULT 0,
                category TEXT,
                FOREIGN KEY (scan_id) REFERENCES scans(scan_id) ON DELETE CASCADE,
                UNIQUE(scan_id, group_index)
            );
            CREATE INDEX IF NOT EXISTS idx_duplicate_groups_scan ON duplicate_groups(scan_id);
            CREATE INDEX IF NOT EXISTS idx_duplicate_groups_scan_category ON duplicate_groups(scan_id, category);
            CREATE TABLE IF NOT EXISTS group_files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scan_id TEXT NOT NULL,
                group_index INTEGER NOT NULL,
                file_index INTEGER NOT NULL,
                path TEXT NOT NULL,
                size_bytes INTEGER NOT NULL DEFAULT 0,
                match_source TEXT DEFAULT 'current_scan',
                FOREIGN KEY (scan_id) REFERENCES scans(scan_id) ON DELETE CASCADE,
                UNIQUE(scan_id, group_index, file_index)
            );
            CREATE INDEX IF NOT EXISTS idx_group_files_scan_group ON group_files(scan_id, group_index);
        """)
        try:
            conn.execute("ALTER TABLE group_files ADD COLUMN match_source TEXT DEFAULT 'current_scan'")
            conn.commit()
        except sqlite3.OperationalError:
            pass
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS selection_state (
                scan_id TEXT NOT NULL,
                group_index INTEGER NOT NULL,
                path TEXT NOT NULL,
                keep INTEGER NOT NULL DEFAULT 1,
                updated_at REAL,
                PRIMARY KEY (scan_id, group_index, path),
                FOREIGN KEY (scan_id) REFERENCES scans(scan_id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_selection_state_scan ON selection_state(scan_id);
        """)
        conn.commit()

    @property
    def db_path(self) -> Path:
        return self._db_path

    def write_scan_result(
        self,
        scan_id: str,
        scan_root: str,
        groups: List[Dict[str, Any]],
        *,
        scan_name: str = "",
        status: str = "completed",
        files_scanned: int = 0,
        total_size: int = 0,
        scan_duration_seconds: Optional[float] = None,
        config_json: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Write a full scan result to the store. Replaces any existing data for this scan_id."""
        if not scan_id or not scan_root:
            return
        created_at = time.time()
        conn = self._connect()
        try:
            self._ensure_schema(conn)
            conn.execute(
                "DELETE FROM scans WHERE scan_id = ?", (scan_id,)
            )
            conn.execute(
                """INSERT INTO scans (
                    scan_id, scan_root, scan_name, status, files_scanned, groups_count,
                    total_size, scan_duration_seconds, created_at, config_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    scan_id,
                    scan_root,
                    scan_name or f"Scan of {scan_root}",
                    status,
                    int(files_scanned),
                    len(groups),
                    int(total_size),
                    float(scan_duration_seconds) if scan_duration_seconds is not None else None,
                    created_at,
                    json.dumps(config_json) if config_json else None,
                ),
            )
            # Duplicate groups: all files in a group have the same size — stat once per group
            # and use executemany for group_files to avoid 2*N getsize() and N single-row INSERTs.
            group_rows: List[Tuple] = []
            file_rows: List[Tuple] = []
            for group_index, g in enumerate(groups):
                # Paths: from "paths" or from "files" list (Phase 7B: files have path + match_source)
                files_list = g.get("files")
                if files_list:
                    paths = [str(f.get("path", f) if isinstance(f, dict) else f) for f in files_list]
                else:
                    paths = g.get("paths") or g.get("items") or []
                    paths = [str(p) for p in paths]
                if not paths:
                    continue
                dup_hash = g.get("hash")
                category = _category_from_path(paths[0])
                # Use scanner-provided size when present to avoid per-group stat() on slow FS
                size = g.get("size")
                if size is None:
                    try:
                        size = os.path.getsize(paths[0])
                    except OSError:
                        size = 0
                else:
                    size = int(size)
                total_bytes = size * len(paths)
                group_rows.append((scan_id, group_index, dup_hash, len(paths), total_bytes, category))
                for file_index, path in enumerate(paths):
                    match_src = "current_scan"
                    if files_list and file_index < len(files_list):
                        ent = files_list[file_index]
                        if isinstance(ent, dict):
                            match_src = ent.get("match_source", "current_scan") or "current_scan"
                    file_rows.append((scan_id, group_index, file_index, path, size, match_src))
            if group_rows:
                conn.executemany(
                    """INSERT INTO duplicate_groups (
                        scan_id, group_index, duplicate_hash, file_count, total_bytes, category
                    ) VALUES (?, ?, ?, ?, ?, ?)""",
                    group_rows,
                )
            if file_rows:
                conn.executemany(
                    """INSERT INTO group_files (
                        scan_id, group_index, file_index, path, size_bytes, match_source
                    ) VALUES (?, ?, ?, ?, ?, ?)""",
                    file_rows,
                )
            conn.commit()
            self._prune_old_scans(conn, keep_last_n=50, max_age_days=30.0)
        finally:
            conn.close()

    def _prune_old_scans(
        self,
        conn: Optional[sqlite3.Connection] = None,
        keep_last_n: int = 50,
        max_age_days: Optional[float] = 30.0,
    ) -> int:
        """Delete old scans to limit DB size. Keeps at most keep_last_n scans and removes those older than max_age_days.
        Returns number of scans deleted. Caller can pass conn from write_scan_result to reuse connection."""
        own_conn = False
        if conn is None:
            conn = self._connect()
            own_conn = True
        try:
            self._ensure_schema(conn)
            now = time.time()
            cutoff = now - (max_age_days * 86400) if max_age_days else None
            rows = conn.execute(
                "SELECT scan_id, created_at FROM scans ORDER BY created_at DESC"
            ).fetchall()
            to_delete: List[str] = []
            for i, r in enumerate(rows):
                if i >= keep_last_n:
                    to_delete.append(r["scan_id"])
                elif cutoff is not None and (r["created_at"] or 0) < cutoff:
                    to_delete.append(r["scan_id"])
            for scan_id in to_delete:
                conn.execute("DELETE FROM scans WHERE scan_id = ?", (scan_id,))
            if to_delete:
                conn.commit()
            return len(to_delete)
        finally:
            if own_conn:
                conn.close()

    def get_scan_summary(self, scan_id: str) -> Optional[Dict[str, Any]]:
        """Return scan metadata for a scan_id, or None if not found."""
        conn = self._connect()
        try:
            self._ensure_schema(conn)
            row = conn.execute(
                """SELECT scan_id, scan_root, scan_name, status, files_scanned, groups_count,
                          total_size, scan_duration_seconds, created_at, config_json
                   FROM scans WHERE scan_id = ?""",
                (scan_id,),
            ).fetchone()
            if row is None:
                return None
            config = None
            if row["config_json"]:
                try:
                    config = json.loads(row["config_json"])
                except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
                    pass
            return {
                "scan_id": row["scan_id"],
                "scan_root": row["scan_root"],
                "scan_name": row["scan_name"],
                "status": row["status"],
                "files_scanned": row["files_scanned"],
                "groups_count": row["groups_count"],
                "total_size": row["total_size"],
                "scan_duration_seconds": row["scan_duration_seconds"],
                "created_at": row["created_at"],
                "config": config,
            }
        finally:
            conn.close()

    def get_group_count(self, scan_id: str, category: Optional[str] = None) -> int:
        """Return number of duplicate groups for this scan, optionally filtered by category."""
        conn = self._connect()
        try:
            self._ensure_schema(conn)
            if category:
                r = conn.execute(
                    "SELECT COUNT(*) AS c FROM duplicate_groups WHERE scan_id = ? AND category = ?",
                    (scan_id, category),
                ).fetchone()
            else:
                r = conn.execute(
                    "SELECT COUNT(*) AS c FROM duplicate_groups WHERE scan_id = ?",
                    (scan_id,),
                ).fetchone()
            return int(r["c"]) if r else 0
        finally:
            conn.close()

    def get_group_window(
        self,
        scan_id: str,
        offset: int,
        limit: int,
        category: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Return a window of duplicate_groups rows (group_index, file_count, total_bytes, category)."""
        conn = self._connect()
        try:
            self._ensure_schema(conn)
            if category:
                rows = conn.execute(
                    """SELECT group_index, file_count, total_bytes, category, duplicate_hash
                       FROM duplicate_groups WHERE scan_id = ? AND category = ?
                       ORDER BY group_index LIMIT ? OFFSET ?""",
                    (scan_id, category, limit, offset),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT group_index, file_count, total_bytes, category, duplicate_hash
                       FROM duplicate_groups WHERE scan_id = ?
                       ORDER BY group_index LIMIT ? OFFSET ?""",
                    (scan_id, limit, offset),
                ).fetchall()
            return [
                {
                    "group_index": r["group_index"],
                    "file_count": r["file_count"],
                    "total_bytes": r["total_bytes"],
                    "category": r["category"],
                    "duplicate_hash": r["duplicate_hash"],
                }
                for r in rows
            ]
        finally:
            conn.close()

    def get_group_details(self, scan_id: str, group_index: int) -> Optional[Dict[str, Any]]:
        """Return paths and metadata for one group. Paths ordered by file_index."""
        conn = self._connect()
        try:
            self._ensure_schema(conn)
            grp = conn.execute(
                """SELECT group_index, file_count, total_bytes, category, duplicate_hash
                   FROM duplicate_groups WHERE scan_id = ? AND group_index = ?""",
                (scan_id, group_index),
            ).fetchone()
            if grp is None:
                return None
            rows = conn.execute(
                """SELECT path, size_bytes, COALESCE(match_source, 'current_scan') AS match_source
                   FROM group_files
                   WHERE scan_id = ? AND group_index = ? ORDER BY file_index""",
                (scan_id, group_index),
            ).fetchall()
            paths = [r["path"] for r in rows]
            match_sources = [str(r["match_source"] or "current_scan") for r in rows]
            return {
                "group_index": grp["group_index"],
                "paths": paths,
                "match_sources": match_sources,
                "file_count": grp["file_count"],
                "total_bytes": grp["total_bytes"],
                "category": grp["category"],
                "duplicate_hash": grp["duplicate_hash"],
            }
        finally:
            conn.close()

    def get_categories(self, scan_id: str) -> List[str]:
        """Return distinct categories for this scan (for filter dropdown)."""
        conn = self._connect()
        try:
            self._ensure_schema(conn)
            rows = conn.execute(
                "SELECT DISTINCT category FROM duplicate_groups WHERE scan_id = ? ORDER BY category",
                (scan_id,),
            ).fetchall()
            return [r["category"] for r in rows if r["category"]]
        finally:
            conn.close()

    def has_scan(self, scan_id: str) -> bool:
        """Return True if the store has data for this scan_id."""
        return self.get_scan_summary(scan_id) is not None

    def set_selection_state(self, scan_id: str, group_index: int, path: str, keep: bool) -> None:
        """Persist one path's keep/delete state for a group. Path should be normalized (e.g. os.path.normcase)."""
        if not scan_id:
            return
        conn = self._connect()
        try:
            self._ensure_schema(conn)
            now = time.time()
            conn.execute(
                """INSERT INTO selection_state (scan_id, group_index, path, keep, updated_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(scan_id, group_index, path) DO UPDATE SET keep = excluded.keep, updated_at = excluded.updated_at""",
                (scan_id, group_index, path, 1 if keep else 0, now),
            )
            conn.commit()
        finally:
            conn.close()

    def set_selection_state_group(
        self, scan_id: str, group_index: int, path_keep: Dict[str, bool]
    ) -> None:
        """Replace selection state for one group with the given path -> keep map. Use after group checkbox toggle."""
        if not scan_id:
            return
        conn = self._connect()
        try:
            self._ensure_schema(conn)
            conn.execute(
                "DELETE FROM selection_state WHERE scan_id = ? AND group_index = ?",
                (scan_id, group_index),
            )
            now = time.time()
            for path, keep in path_keep.items():
                if path is None or path == "":
                    continue
                conn.execute(
                    """INSERT INTO selection_state (scan_id, group_index, path, keep, updated_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    (scan_id, group_index, path, 1 if keep else 0, now),
                )
            conn.commit()
        finally:
            conn.close()

    def get_selection_state(self, scan_id: str) -> Dict[int, Dict[str, bool]]:
        """Return persisted keep/delete state: group_index -> {path: keep (True/False)}. Paths normalized."""
        if not scan_id:
            return {}
        conn = self._connect()
        try:
            self._ensure_schema(conn)
            rows = conn.execute(
                "SELECT group_index, path, keep FROM selection_state WHERE scan_id = ?",
                (scan_id,),
            ).fetchall()
            out: Dict[int, Dict[str, bool]] = {}
            for r in rows:
                gi = int(r["group_index"])
                if gi not in out:
                    out[gi] = {}
                out[gi][r["path"]] = bool(r["keep"])
            return out
        finally:
            conn.close()


# Singleton accessor for UI/worker (optional)
_store: Optional[ScanResultStore] = None


def get_scan_result_store(db_path: Optional[Path] = None) -> ScanResultStore:
    global _store
    if _store is None:
        _store = ScanResultStore(db_path)
    return _store
