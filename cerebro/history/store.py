"""
CEREBRO History Store - Target Architecture (Authoritative)
Records deletion audit trail (append-only JSONL) with query helpers.

Storage:
~/.cerebro/history/audit/deletions_YYYY-MM-DD.jsonl  (one line per batch, append-only)

Persistence: O(1) append + fsync. Corrupt lines are skipped with one warning per read.
The module docstring previously claimed "atomic write (temp → rename)" — that pattern
is used for resume_payload.json only, not for the append JSONL audit log.

P-3: get_deletion_stats() now uses a SQLite aggregate table (deletion_stats_daily)
for O(1) queries over large histories, with a one-time JSONL migration on first open.
"""

from __future__ import annotations

import dataclasses
import json
import os
import sqlite3
import tempfile
import threading
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

SCHEMA_VERSION = 1


@dataclass
class ResumePayload:
    """Payload for resuming a scan from checkpoint."""
    scan_id: str
    config: Dict[str, Any]
    inventory_db_path: str
    checkpoint_path: str
    timestamp: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scan_id": self.scan_id,
            "config": self.config,
            "inventory_db_path": self.inventory_db_path,
            "checkpoint_path": self.checkpoint_path,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ResumePayload":
        return cls(
            scan_id=str(data.get("scan_id", "")),
            config=dict(data.get("config", {}) or {}),
            inventory_db_path=str(data.get("inventory_db_path", "")),
            checkpoint_path=str(data.get("checkpoint_path", "")),
            timestamp=float(data.get("timestamp", 0) or 0),
        )


def _migrate_record(data: Dict[str, Any]) -> Dict[str, Any]:
    """Stub for future schema migrations."""
    version = data.get("schema_version", 0)
    if version < SCHEMA_VERSION:
        data = dict(data)
        data["schema_version"] = SCHEMA_VERSION
    return data


@dataclass
class DeletionAuditRecord:
    """
    Audit record for deletion operations.
    Who/what/why/when for full traceability.
    """
    scan_id: str
    timestamp: float
    mode: str
    groups: int
    deleted: int
    failed: int
    bytes_reclaimed: int
    source: str
    policy: Dict[str, Any]
    details: List[Dict[str, Any]]

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["schema_version"] = SCHEMA_VERSION
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Optional["DeletionAuditRecord"]:
        """
        H-3: safe forward + backward compat deserialization.

        - Unknown extra fields are ignored (forward compat).
        - Missing required fields cause the record to be skipped (returns None).
        """
        data = _migrate_record(data)
        known = {f.name for f in dataclasses.fields(cls)}
        filtered = {k: v for k, v in data.items() if k in known and k != "schema_version"}
        try:
            return cls(**filtered)
        except TypeError:
            return None


class HistoryStore:
    """Stores and retrieves deletion history with full audit trail."""

    def __init__(self, base_dir: Optional[Path] = None) -> None:
        self._base_dir = base_dir or (Path.home() / ".cerebro" / "history")
        self._audit_dir = self._base_dir / "audit"
        self._resume_file = self._base_dir / "resume_payload.json"
        self._stats_db_path = self._base_dir / "deletion_stats.db"
        self._stats_db_lock = threading.Lock()
        # M-4: serialize concurrent JSONL appends — on Windows, concurrent writes
        # to the same file interleave bytes and corrupt JSONL lines.
        self._audit_lock = threading.Lock()
        self._ensure_dirs()
        self._init_stats_db()
        self._logger = None
        try:
            from ..services.logger import get_logger
            self._logger = get_logger("history.store")
        except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
            self._logger = None

    def _ensure_dirs(self) -> None:
        self._audit_dir.mkdir(parents=True, exist_ok=True)

    def _log(self, message: str, level: str = "info") -> None:
        if self._logger:
            try:
                getattr(self._logger, level, self._logger.info)(message)
            except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
                pass

    # ------------------------------------------------------------------
    # P-3: SQLite aggregate stats table
    # ------------------------------------------------------------------

    def _init_stats_db(self) -> None:
        """Create deletion_stats_daily table and migrate existing JSONL on first open."""
        try:
            with self._stats_db_lock, sqlite3.connect(str(self._stats_db_path), timeout=10) as conn:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS deletion_stats_daily (
                        date TEXT PRIMARY KEY,
                        operations INTEGER NOT NULL DEFAULT 0,
                        deleted INTEGER NOT NULL DEFAULT 0,
                        failed INTEGER NOT NULL DEFAULT 0,
                        bytes_reclaimed INTEGER NOT NULL DEFAULT 0,
                        by_mode TEXT NOT NULL DEFAULT '{}',
                        by_source TEXT NOT NULL DEFAULT '{}'
                    )
                    """
                )
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS _meta (key TEXT PRIMARY KEY, value TEXT)"
                )
                migrated = conn.execute(
                    "SELECT value FROM _meta WHERE key='jsonl_migrated'"
                ).fetchone()
                if not migrated:
                    self._migrate_jsonl_to_stats_db(conn)
                    conn.execute(
                        "INSERT OR REPLACE INTO _meta(key,value) VALUES('jsonl_migrated','1')"
                    )
        except Exception:  # noqa: BLE001
            pass  # stats DB failure must never break the audit path

    def _migrate_jsonl_to_stats_db(self, conn: sqlite3.Connection) -> None:
        """One-time migration: read all JSONL audit files into stats aggregate."""
        try:
            for audit_file in sorted(self._audit_dir.glob("deletions_*.jsonl")):
                try:
                    with open(audit_file, encoding="utf-8") as fh:
                        for raw_line in fh:
                            line = raw_line.strip()
                            if not line:
                                continue
                            try:
                                data = json.loads(line)
                                self._update_stats_row(conn, data)
                            except (json.JSONDecodeError, Exception):
                                continue
                except OSError:
                    continue
        except Exception:  # noqa: BLE001
            pass

    def _update_stats_row(self, conn: sqlite3.Connection, record_data: Dict[str, Any]) -> None:
        """Upsert one record into deletion_stats_daily."""
        try:
            ts = float(record_data.get("timestamp", 0) or 0)
            date = datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
            deleted = int(record_data.get("deleted", 0) or 0)
            failed = int(record_data.get("failed", 0) or 0)
            mode = str(record_data.get("mode", ""))
            source = str(record_data.get("source", ""))
            breclaim = int(record_data.get("bytes_reclaimed", 0) or 0)

            row = conn.execute(
                "SELECT operations, deleted, failed, bytes_reclaimed, by_mode, by_source "
                "FROM deletion_stats_daily WHERE date=?", (date,)
            ).fetchone()

            if row:
                ops = row[0] + 1
                new_del = row[1] + deleted
                new_fail = row[2] + failed
                new_bytes = row[3] + breclaim
                by_mode: dict = json.loads(row[4] or "{}")
                by_source: dict = json.loads(row[5] or "{}")
            else:
                ops, new_del, new_fail, new_bytes = 1, deleted, failed, breclaim
                by_mode, by_source = {}, {}

            if mode:
                by_mode[mode] = by_mode.get(mode, 0) + deleted
            if source:
                by_source[source] = by_source.get(source, 0) + deleted

            conn.execute(
                """
                INSERT OR REPLACE INTO deletion_stats_daily
                (date, operations, deleted, failed, bytes_reclaimed, by_mode, by_source)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (date, ops, new_del, new_fail, new_bytes,
                 json.dumps(by_mode), json.dumps(by_source)),
            )
        except Exception:  # noqa: BLE001
            pass

    def record_deletion(
        self,
        *,
        scan_id: str,
        mode: str,
        groups: int,
        deleted: int,
        failed: int,
        bytes_reclaimed: int,
        source: str,
        policy: Optional[Dict[str, Any]] = None,
        details: Optional[List[Dict[str, Any]]] = None,
    ) -> DeletionAuditRecord:
        """Record a deletion operation to audit trail (JSONL + stats aggregate)."""
        now = datetime.now()
        record = DeletionAuditRecord(
            scan_id=str(scan_id),
            timestamp=now.timestamp(),
            mode=str(mode),
            groups=int(groups or 0),
            deleted=int(deleted or 0),
            failed=int(failed or 0),
            bytes_reclaimed=int(bytes_reclaimed or 0),
            source=str(source),
            policy=dict(policy or {}),
            details=list(details or []),
        )

        date_str = now.strftime("%Y-%m-%d")
        audit_file = self._audit_dir / f"deletions_{date_str}.jsonl"
        line = json.dumps(record.to_dict(), default=str) + "\n"

        last_exc: Exception | None = None
        with self._audit_lock:  # M-4: serialise concurrent JSONL appends
            for attempt in range(3):
                try:
                    with open(audit_file, "a", encoding="utf-8") as f:
                        f.write(line)
                        f.flush()
                        os.fsync(f.fileno())
                    last_exc = None
                    break
                except OSError as e:
                    last_exc = e
                    time.sleep(0.1 * (attempt + 1))
        if last_exc is not None:
            self._log(f"Failed to write audit record after retries: {last_exc}", level="warning")
        else:
            self._log(
                f"Recorded deletion audit: scan={record.scan_id} deleted={record.deleted} "
                f"failed={record.failed} bytes={record.bytes_reclaimed}"
            )

        # P-3: update aggregate.
        try:
            with self._stats_db_lock, sqlite3.connect(str(self._stats_db_path), timeout=10) as conn:
                conn.execute("PRAGMA journal_mode=WAL")
                self._update_stats_row(conn, record.to_dict())
        except Exception:  # noqa: BLE001
            pass

        return record

    def get_deletion_history(
        self,
        *,
        scan_id: Optional[str] = None,
        source: Optional[str] = None,
        since: Optional[float] = None,
        limit: int = 100,
    ) -> List[DeletionAuditRecord]:
        """Query deletion history with filters. Skips corrupt lines; logs one warning per run."""
        records: List[DeletionAuditRecord] = []
        files = sorted(self._audit_dir.glob("deletions_*.jsonl"), reverse=True)
        _corrupt_warned: bool = False

        for audit_file in files:
            try:
                with open(audit_file, "r", encoding="utf-8") as f:
                    for raw_line in f:
                        line = raw_line.strip()
                        if not line:
                            continue
                        try:
                            data = json.loads(line)
                            data = _migrate_record(data)
                            if scan_id and data.get("scan_id") != scan_id:
                                continue
                            if source and data.get("source") != source:
                                continue
                            if since and float(data.get("timestamp", 0) or 0) < float(since):
                                continue
                            rec = DeletionAuditRecord.from_dict(data)
                            if rec is None:
                                if not _corrupt_warned:
                                    self._log("History: skipping record with missing fields", level="warning")
                                    _corrupt_warned = True
                                continue
                            records.append(rec)
                            if len(records) >= limit:
                                break
                        except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
                            if not _corrupt_warned:
                                self._log("History: skipping corrupt line in audit file", level="warning")
                                _corrupt_warned = True
                            continue
            except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
                continue

            if len(records) >= limit:
                break

        return records

    def get_deletion_stats(self, *, days: int = 30) -> Dict[str, Any]:
        """P-3: Aggregate deletion statistics over last N days from SQLite (O(1))."""
        try:
            cutoff = datetime.fromtimestamp(
                datetime.now().timestamp() - int(days) * 86400
            ).strftime("%Y-%m-%d")
            with self._stats_db_lock, sqlite3.connect(str(self._stats_db_path), timeout=10) as conn:
                conn.execute("PRAGMA journal_mode=WAL")
                rows = conn.execute(
                    "SELECT operations, deleted, failed, bytes_reclaimed, by_mode, by_source "
                    "FROM deletion_stats_daily WHERE date >= ?",
                    (cutoff,),
                ).fetchall()

            if not rows:
                return {
                    "period_days": int(days),
                    "total_operations": 0,
                    "total_deleted": 0,
                    "total_failed": 0,
                    "total_bytes_reclaimed": 0,
                    "by_mode": {},
                    "by_source": {},
                    "average_files_per_operation": 0.0,
                }

            total_ops = sum(r[0] for r in rows)
            total_del = sum(r[1] for r in rows)
            total_fail = sum(r[2] for r in rows)
            total_bytes = sum(r[3] for r in rows)
            by_mode: Dict[str, int] = {}
            by_source: Dict[str, int] = {}
            for r in rows:
                for k, v in json.loads(r[4] or "{}").items():
                    by_mode[k] = by_mode.get(k, 0) + int(v)
                for k, v in json.loads(r[5] or "{}").items():
                    by_source[k] = by_source.get(k, 0) + int(v)

            return {
                "period_days": int(days),
                "total_operations": total_ops,
                "total_deleted": total_del,
                "total_failed": total_fail,
                "total_bytes_reclaimed": total_bytes,
                "by_mode": by_mode,
                "by_source": by_source,
                "average_files_per_operation": (total_del / total_ops) if total_ops else 0.0,
            }
        except Exception:  # noqa: BLE001 — stats failure must not break callers
            # Fallback to JSONL scan (old behaviour).
            since = datetime.now().timestamp() - int(days) * 86400
            records = self.get_deletion_history(since=since, limit=10000)
            total_deleted = sum(r.deleted for r in records)
            total_failed = sum(r.failed for r in records)
            total_bytes = sum(r.bytes_reclaimed for r in records)
            by_mode_fallback: Dict[str, int] = {}
            by_source_fallback: Dict[str, int] = {}
            for r in records:
                by_mode_fallback[r.mode] = by_mode_fallback.get(r.mode, 0) + r.deleted
                by_source_fallback[r.source] = by_source_fallback.get(r.source, 0) + r.deleted
            return {
                "period_days": int(days),
                "total_operations": len(records),
                "total_deleted": total_deleted,
                "total_failed": total_failed,
                "total_bytes_reclaimed": total_bytes,
                "by_mode": by_mode_fallback,
                "by_source": by_source_fallback,
                "average_files_per_operation": (total_deleted / len(records)) if records else 0.0,
            }

    def export_to_json(
        self,
        file_path: Path,
        *,
        limit: int = 10000,
        progress_cb: Optional[Callable[[int, int], None]] = None,
    ) -> None:
        """Export deletion history to a JSON file."""
        records = self.get_deletion_history(limit=limit)
        total = len(records)
        data = [r.to_dict() for r in records]
        if progress_cb:
            progress_cb(total, total)
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)
            f.flush()
            os.fsync(f.fileno())

    def export_to_csv(
        self,
        file_path: Path,
        *,
        limit: int = 10000,
        progress_cb: Optional[Callable[[int, int], None]] = None,
    ) -> None:
        """Export deletion history to CSV."""
        import csv
        records = self.get_deletion_history(limit=limit)
        total = len(records)
        if progress_cb:
            progress_cb(0, total)
        with open(file_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["scan_id", "timestamp", "mode", "groups", "deleted", "failed",
                             "bytes_reclaimed", "source"])
            for i, r in enumerate(records):
                writer.writerow([r.scan_id, r.timestamp, r.mode, r.groups, r.deleted,
                                  r.failed, r.bytes_reclaimed, r.source])
                if progress_cb and (i + 1) % 50 == 0:
                    progress_cb(i + 1, total)
            if progress_cb:
                progress_cb(total, total)
            f.flush()
            os.fsync(f.fileno())

    def save_resume_payload(self, payload: ResumePayload) -> None:
        """Persist resume payload (atomic write via mkstemp + os.replace)."""
        self._base_dir.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(prefix="resume_", suffix=".json", dir=str(self._base_dir))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload.to_dict(), f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, self._resume_file)
        except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    def get_latest_resume_payload(self) -> Optional[ResumePayload]:
        """Load latest resume payload if any."""
        if not self._resume_file.exists():
            return None
        try:
            with open(self._resume_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            return ResumePayload.from_dict(data)
        except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
            return None

    def get_undo_candidates(self, *, since_hours: int = 24) -> List[Dict[str, Any]]:
        """Get recent trash deletions that could potentially be undone."""
        since = datetime.now().timestamp() - int(since_hours) * 3600
        records = self.get_deletion_history(since=since, limit=1000)
        candidates: List[Dict[str, Any]] = []
        for r in records:
            if r.mode == "trash":
                candidates.append({
                    "scan_id": r.scan_id,
                    "timestamp": r.timestamp,
                    "files": r.details,
                    "bytes": r.bytes_reclaimed,
                })
        return candidates
