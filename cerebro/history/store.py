"""
CEREBRO History Store - Target Architecture (Authoritative)
Records deletion audit trail (append-only JSONL) with query helpers.

Storage:
~/.cerebro/history/audit/deletions_YYYY-MM-DD.jsonl

Persistence: atomic write (temp → fsync → rename), schema_version, skip corrupt lines with single warning.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

SCHEMA_VERSION = 1


@dataclass
class ResumePayload:
    """Payload for resuming a scan from checkpoint (scan_id, config, inventory_db_path, checkpoint_path, timestamp)."""
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
    """Stub for future schema migrations. Returns data suitable for from_dict."""
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
    mode: str  # 'trash' or 'permanent'
    groups: int
    deleted: int
    failed: int
    bytes_reclaimed: int
    source: str  # 'review_page', 'auto_cleanup', etc.
    policy: Dict[str, Any]
    details: List[Dict[str, Any]]  # per-file details

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["schema_version"] = SCHEMA_VERSION
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DeletionAuditRecord":
        data = _migrate_record(data)
        # Allow schema_version in dict but do not pass to dataclass
        data = {k: v for k, v in data.items() if k != "schema_version"}
        return cls(**data)


class HistoryStore:
    """Stores and retrieves deletion history with full audit trail."""

    def __init__(self, base_dir: Optional[Path] = None) -> None:
        self._base_dir = base_dir or (Path.home() / ".cerebro" / "history")
        self._audit_dir = self._base_dir / "audit"
        self._resume_file = self._base_dir / "resume_payload.json"
        self._ensure_dirs()
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
        """Record a deletion operation to audit trail."""
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

        try:
            line = json.dumps(record.to_dict(), default=str) + "\n"
            fd, tmp_path = tempfile.mkstemp(prefix="cerebro_audit_", suffix=".jsonl", dir=str(self._audit_dir))
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    if audit_file.exists():
                        with open(audit_file, "r", encoding="utf-8") as existing:
                            f.write(existing.read())
                    f.write(line)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp_path, audit_file)
            except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
                try:
                    os.unlink(tmp_path)
                except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
                    pass
                raise
            self._log(
                f"Recorded deletion audit: scan={record.scan_id} deleted={record.deleted} failed={record.failed} bytes={record.bytes_reclaimed}"
            )
        except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError) as e:
            self._log(f"Failed to write audit record: {e}", level="warning")

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
                            records.append(DeletionAuditRecord.from_dict(data))
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
        """Aggregate deletion statistics over last N days."""
        since = datetime.now().timestamp() - (int(days) * 24 * 60 * 60)
        records = self.get_deletion_history(since=since, limit=10000)

        total_deleted = sum(r.deleted for r in records)
        total_failed = sum(r.failed for r in records)
        total_bytes = sum(r.bytes_reclaimed for r in records)

        by_mode: Dict[str, int] = {}
        by_source: Dict[str, int] = {}

        for r in records:
            by_mode[r.mode] = by_mode.get(r.mode, 0) + r.deleted
            by_source[r.source] = by_source.get(r.source, 0) + r.deleted

        return {
            "period_days": int(days),
            "total_operations": len(records),
            "total_deleted": total_deleted,
            "total_failed": total_failed,
            "total_bytes_reclaimed": total_bytes,
            "by_mode": by_mode,
            "by_source": by_source,
            "average_files_per_operation": (total_deleted / len(records)) if records else 0.0,
        }

    def export_to_json(
        self,
        file_path: Path,
        *,
        limit: int = 10000,
        progress_cb: Optional[Callable[[int, int], None]] = None,
    ) -> None:
        """Export deletion history to a JSON file. progress_cb(current, total) if provided."""
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
        """Export deletion history to CSV. progress_cb(current, total) if provided."""
        import csv
        records = self.get_deletion_history(limit=limit)
        total = len(records)
        if progress_cb:
            progress_cb(0, total)
        with open(file_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["scan_id", "timestamp", "mode", "groups", "deleted", "failed", "bytes_reclaimed", "source"])
            for i, r in enumerate(records):
                writer.writerow([r.scan_id, r.timestamp, r.mode, r.groups, r.deleted, r.failed, r.bytes_reclaimed, r.source])
                if progress_cb and (i + 1) % 50 == 0:
                    progress_cb(i + 1, total)
            if progress_cb:
                progress_cb(total, total)
            f.flush()
            os.fsync(f.fileno())

    def save_resume_payload(self, payload: ResumePayload) -> None:
        """Persist resume payload (atomic write). Call when scan is cancelled for later resume."""
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
            except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
                pass

    def get_latest_resume_payload(self) -> Optional[ResumePayload]:
        """Load latest resume payload if any (e.g. for History Resume button)."""
        if not self._resume_file.exists():
            return None
        try:
            with open(self._resume_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            return ResumePayload.from_dict(data)
        except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
            return None

    def get_undo_candidates(self, *, since_hours: int = 24) -> List[Dict[str, Any]]:
        """
        Get recent deletions that could potentially be undone.
        Only works for trash deletions.
        """
        since = datetime.now().timestamp() - (int(since_hours) * 60 * 60)
        records = self.get_deletion_history(since=since, limit=1000)

        candidates: List[Dict[str, Any]] = []
        for r in records:
            if r.mode == "trash":
                candidates.append(
                    {
                        "scan_id": r.scan_id,
                        "timestamp": r.timestamp,
                        "files": r.details,
                        "bytes": r.bytes_reclaimed,
                    }
                )
        return candidates
