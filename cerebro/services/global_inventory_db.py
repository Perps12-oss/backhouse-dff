# cerebro/services/global_inventory_db.py
"""
Global file inventory for v6.1 scale foundation (Phase 7A).
Stores devices + inventory_files for cross-root duplicate matching.
Separate from cerebro.services.inventory_db (resumable-scan discovery cache).
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

_DEFAULT_DB_PATH = Path.home() / ".cerebro" / "global_inventory.db"

_global_instance: Optional["GlobalInventoryDB"] = None


def get_global_inventory_db(db_path: Optional[Path] = None) -> "GlobalInventoryDB":
    """Return the singleton GlobalInventoryDB instance."""
    global _global_instance
    if _global_instance is None:
        _global_instance = GlobalInventoryDB(db_path)
    return _global_instance


def _device_id_for_root(root_path: str) -> str:
    """Stable device id; uses device_identity (volume UUID) when available, else path hash."""
    try:
        from cerebro.services.device_identity import get_device_id
        return get_device_id(root_path) or _path_hash_device_id(root_path)
    except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
        return _path_hash_device_id(root_path)


def _path_hash_device_id(root_path: str) -> str:
    canonical = os.path.normpath(os.path.abspath(root_path))
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


class GlobalInventoryDB:
    """
    SQLite-backed global file inventory: devices + inventory_files.
    Used for Phase 7A (populate from scan) and 7B (get_paths_by_hash for matching).
    """

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self._db_path = Path(db_path) if db_path else _DEFAULT_DB_PATH
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        self._ensure_schema(conn)
        return conn

    def _ensure_schema(self, conn: sqlite3.Connection) -> None:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS devices (
                device_id TEXT PRIMARY KEY,
                device_label TEXT NOT NULL,
                device_type TEXT NOT NULL,
                root_path TEXT NOT NULL UNIQUE,
                last_seen_timestamp REAL,
                is_online INTEGER NOT NULL DEFAULT 1,
                created_at REAL NOT NULL,
                updated_at REAL
            );
            CREATE INDEX IF NOT EXISTS idx_devices_online ON devices(is_online);
            CREATE INDEX IF NOT EXISTS idx_devices_root ON devices(root_path);

            CREATE TABLE IF NOT EXISTS inventory_files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT NOT NULL,
                path TEXT NOT NULL,
                relative_path TEXT,
                size_bytes INTEGER NOT NULL,
                mtime_ns INTEGER NOT NULL,
                quick_hash TEXT,
                full_hash TEXT,
                last_seen_scan_id TEXT,
                last_seen_timestamp REAL NOT NULL,
                is_present INTEGER NOT NULL DEFAULT 1,
                FOREIGN KEY (device_id) REFERENCES devices(device_id) ON DELETE CASCADE,
                UNIQUE(device_id, path)
            );
            CREATE INDEX IF NOT EXISTS idx_inventory_device ON inventory_files(device_id);
            CREATE INDEX IF NOT EXISTS idx_inventory_size ON inventory_files(size_bytes);
            CREATE INDEX IF NOT EXISTS idx_inventory_quick_hash ON inventory_files(quick_hash);
            CREATE INDEX IF NOT EXISTS idx_inventory_last_seen ON inventory_files(last_seen_scan_id);
            CREATE INDEX IF NOT EXISTS idx_inventory_device_present ON inventory_files(device_id, is_present);
        """)
        conn.commit()

    @property
    def db_path(self) -> Path:
        return self._db_path

    def get_or_create_device(
        self,
        root_path: str,
        *,
        label: Optional[str] = None,
        device_type: Optional[str] = None,
    ) -> str:
        """Return device_id for root; create device row if new."""
        canonical = os.path.normpath(os.path.abspath(root_path))
        device_id = _device_id_for_root(canonical)
        if device_type is None:
            try:
                from cerebro.services.device_identity import get_device_type
                device_type = get_device_type(canonical)
            except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
                device_type = "internal"
        now = time.time()
        conn = self._connect()
        try:
            cur = conn.execute(
                "SELECT device_id FROM devices WHERE device_id = ?",
                (device_id,),
            )
            if cur.fetchone():
                conn.execute(
                    "UPDATE devices SET last_seen_timestamp = ?, is_online = 1, updated_at = ? WHERE device_id = ?",
                    (now, now, device_id),
                )
                conn.commit()
                return device_id
            label = label or canonical or str(Path(root_path))
            conn.execute(
                """INSERT INTO devices (device_id, device_label, device_type, root_path, last_seen_timestamp, is_online, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, 1, ?, ?)""",
                (device_id, label, device_type, canonical, now, now, now),
            )
            conn.commit()
            return device_id
        finally:
            conn.close()

    def get_file(self, device_id: str, path: str) -> Optional[Any]:
        """Lookup one file for classification."""
        conn = self._connect()
        try:
            cur = conn.execute(
                "SELECT * FROM inventory_files WHERE device_id = ? AND path = ?",
                (device_id, path),
            )
            row = cur.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def upsert_file(
        self,
        device_id: str,
        path: str,
        size_bytes: int,
        mtime_ns: int,
        last_seen_scan_id: str,
        last_seen_timestamp: float,
        *,
        quick_hash: Optional[str] = None,
        relative_path: Optional[str] = None,
    ) -> str:
        """Insert or update one file. Returns classification: 'new' | 'unchanged' | 'changed'."""
        conn = self._connect()
        try:
            existing = conn.execute(
                "SELECT size_bytes, mtime_ns, quick_hash FROM inventory_files WHERE device_id = ? AND path = ?",
                (device_id, path),
            ).fetchone()
            if existing is None:
                conn.execute(
                    """INSERT INTO inventory_files (
                        device_id, path, relative_path, size_bytes, mtime_ns, quick_hash,
                        last_seen_scan_id, last_seen_timestamp, is_present
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)""",
                    (device_id, path, relative_path or path, size_bytes, mtime_ns, quick_hash or "", last_seen_scan_id, last_seen_timestamp),
                )
                conn.commit()
                return "new"
            prev_size, prev_mtime, prev_hash = existing[0], existing[1], existing[2] or ""
            if prev_size == size_bytes and prev_mtime == mtime_ns and (prev_hash == (quick_hash or "")):
                conn.execute(
                    "UPDATE inventory_files SET last_seen_scan_id = ?, last_seen_timestamp = ? WHERE device_id = ? AND path = ?",
                    (last_seen_scan_id, last_seen_timestamp, device_id, path),
                )
                conn.commit()
                return "unchanged"
            conn.execute(
                """UPDATE inventory_files SET
                    size_bytes = ?, mtime_ns = ?, quick_hash = COALESCE(?, quick_hash),
                    last_seen_scan_id = ?, last_seen_timestamp = ?, is_present = 1
                   WHERE device_id = ? AND path = ?""",
                (size_bytes, mtime_ns, quick_hash, last_seen_scan_id, last_seen_timestamp, device_id, path),
            )
            conn.commit()
            return "changed"
        finally:
            conn.close()

    def populate_from_scan_result(
        self,
        scan_id: str,
        scan_root: str,
        groups: List[Dict[str, Any]],
    ) -> Dict[str, int]:
        """Upsert all files in duplicate groups to inventory. Returns {added, updated, unchanged}."""
        counts: Dict[str, int] = {"added": 0, "updated": 0, "unchanged": 0}
        device_id = self.get_or_create_device(scan_root)
        root_canonical = os.path.normpath(os.path.abspath(scan_root))
        now = time.time()

        for g in groups:
            paths = g.get("paths") or []
            if not paths:
                paths = [f.get("path") for f in (g.get("files") or []) if f.get("path")]
            qhash = g.get("hash") or ""
            for path in paths:
                path = str(path)
                try:
                    st = os.stat(path)
                    size_bytes = int(st.st_size)
                    mtime_ns = int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1_000_000_000)))
                except OSError:
                    continue
                classification = self.upsert_file(
                    device_id,
                    path,
                    size_bytes,
                    mtime_ns,
                    scan_id,
                    now,
                    quick_hash=qhash or None,
                )
                counts[classification] = counts.get(classification, 0) + 1
        return counts

    def get_paths_by_hash(
        self,
        quick_hash: str,
        exclude_device_ids: Optional[Set[str]] = None,
    ) -> List[Tuple[str, str, bool]]:
        """Return [(path, device_id, is_online), ...] for all inventory files with this hash.
        exclude_device_ids: current scan device(s) — omit those (they're in current scan)."""
        if not quick_hash:
            return []
        conn = self._connect()
        try:
            cur = conn.execute(
                """SELECT inv.path, inv.device_id, COALESCE(d.is_online, 1)
                   FROM inventory_files inv
                   LEFT JOIN devices d ON d.device_id = inv.device_id
                   WHERE inv.quick_hash = ? AND inv.is_present = 1""",
                (quick_hash,),
            )
            rows = cur.fetchall()
            out: List[Tuple[str, str, bool]] = []
            excl = exclude_device_ids or set()
            for r in rows:
                path, dev_id, is_online = str(r[0]), str(r[1]), bool(r[2] if r[2] is not None else 1)
                if dev_id in excl:
                    continue
                out.append((path, dev_id, is_online))
            return out
        finally:
            conn.close()

    def refresh_device_status(self) -> None:
        """Set is_online=1 for devices whose root_path is accessible, else 0 (Phase 7C)."""
        conn = self._connect()
        try:
            cur = conn.execute("SELECT device_id, root_path FROM devices")
            now = time.time()
            for row in cur.fetchall():
                dev_id, root = row[0], row[1]
                try:
                    online = 1 if (os.path.exists(root) and os.access(root, os.R_OK)) else 0
                except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
                    online = 0
                conn.execute(
                    "UPDATE devices SET is_online = ?, last_seen_timestamp = ?, updated_at = ? WHERE device_id = ?",
                    (online, now if online else None, now, dev_id),
                )
            conn.commit()
        finally:
            conn.close()

    def get_devices_with_counts(self) -> List[Dict[str, Any]]:
        """Return list of {device_id, device_label, device_type, root_path, is_online, last_seen_timestamp, file_count}."""
        self.refresh_device_status()
        conn = self._connect()
        try:
            cur = conn.execute(
                """SELECT d.device_id, d.device_label, d.device_type, d.root_path, d.is_online, d.last_seen_timestamp,
                          (SELECT COUNT(*) FROM inventory_files f WHERE f.device_id = d.device_id AND f.is_present = 1) AS file_count
                   FROM devices d ORDER BY d.last_seen_timestamp DESC"""
            )
            return [dict(row) for row in cur.fetchall()]
        finally:
            conn.close()
