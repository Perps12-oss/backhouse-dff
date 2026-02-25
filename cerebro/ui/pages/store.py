# cerebro/history/store.py
from __future__ import annotations

import gzip
import json
import os
import shutil
import sys
import time
import uuid
import csv
import io
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Callable

from .models import (
    HISTORY_SCHEMA_VERSION,
    PAYLOAD_SCHEMA_VERSION,
    ScanHistoryEntry,
    ScanResultSummary,
    ScanStatus,
    ScanWarningsSummary,
    ScanHealthSnapshot,
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _safe_mkdir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def _atomic_write_text(path: Path, text: str, encoding: str = "utf-8") -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(text, encoding=encoding)
    os.replace(tmp, path)


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_bytes(data)
    os.replace(tmp, path)


@contextmanager
def _file_lock(lock_path: Path, timeout_s: float = 5.0, poll_s: float = 0.05):
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    start = time.time()
    fp = None
    try:
        fp = open(lock_path, "a+b")
        locked = False
        while time.time() - start <= timeout_s:
            try:
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(fp.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(fp.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
                break
            except Exception:
                time.sleep(poll_s)
        if not locked:
            raise TimeoutError(f"Could not acquire lock: {lock_path}")
        yield
    finally:
        if fp:
            try:
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(fp.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(fp.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass
            try:
                fp.close()
            except Exception:
                pass


def default_app_data_dir(app_name: str = "CEREBRO") -> Path:
    home = Path.home()
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", str(home / "AppData" / "Roaming")))
    elif sys.platform == "darwin":
        base = home / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", str(home / ".local" / "share")))
    return base / app_name


def to_jsonable(obj: Any) -> Any:
    from dataclasses import is_dataclass
    from enum import Enum
    from pathlib import Path as _Path
    from datetime import datetime as _dt

    if obj is None:
        return None
    if isinstance(obj, (bool, int, float, str)):
        return obj
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, _Path):
        return str(obj)
    if isinstance(obj, _dt):
        return obj.isoformat()
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(x) for x in obj]
    if isinstance(obj, dict):
        return {str(k): to_jsonable(v) for k, v in obj.items()}
    if is_dataclass(obj):
        return to_jsonable(asdict(obj))
    if hasattr(obj, "__dict__"):
        return to_jsonable(vars(obj))
    return str(obj)


class HistoryStore:
    def __init__(self, base_dir: Optional[Path] = None, engine_version: str = ""):
        self.base_dir = base_dir or (default_app_data_dir("CEREBRO") / "history")
        self.engine_version = engine_version

        self.index_path = self.base_dir / "history_index.json"
        self.lock_path = self.base_dir / "history_index.lock"
        self.payload_dir = self.base_dir / "payloads"
        self.exports_dir = self.base_dir / "exports"
        self.health_dir = self.base_dir / "health_logs"

        _safe_mkdir(self.base_dir)
        _safe_mkdir(self.payload_dir)
        _safe_mkdir(self.exports_dir)
        _safe_mkdir(self.health_dir)

        if not self.index_path.exists():
            self._write_index({"schema_version": HISTORY_SCHEMA_VERSION, "entries": []})

    # -------------------------
    # Core API (Compatible)
    # -------------------------

    def list_entries(self, tag_filter: Optional[str] = None) -> List[ScanHistoryEntry]:
        idx = self._read_index()
        entries = [ScanHistoryEntry.from_dict(d) for d in (idx.get("entries") or [])]
        if tag_filter:
            entries = [e for e in entries if tag_filter in e.tags]
        entries.sort(key=lambda e: (not e.pinned, e.started_at_iso), reverse=True)
        return entries

    def get_entry(self, scan_id: str) -> Optional[ScanHistoryEntry]:
        for e in self.list_entries():
            if e.scan_id == scan_id:
                return e
        return None

    def begin_scan(self, root_path: str, settings_snapshot: Dict[str, Any], 
                   name: Optional[str] = None, tags: Optional[List[str]] = None,
                   parent_scan_id: str = "") -> ScanHistoryEntry:
        scan_id = str(uuid.uuid4())
        started_at = _utc_now_iso()
        payload_ref = f"payloads/{scan_id}.json.gz"
        entry = ScanHistoryEntry(
            scan_id=scan_id,
            name=name or f"Scan {started_at}",
            root_path=str(root_path),
            status=ScanStatus.IN_PROGRESS,
            started_at_iso=started_at,
            finished_at_iso="",
            duration_ms=0,
            root_mtime=self._try_stat_mtime(root_path),
            engine_version=self.engine_version,
            history_schema_version=HISTORY_SCHEMA_VERSION,
            payload_schema_version=PAYLOAD_SCHEMA_VERSION,
            settings_snapshot=to_jsonable(settings_snapshot) or {},
            result_summary=ScanResultSummary(),
            warnings_summary=ScanWarningsSummary(),
            payload_ref=payload_ref,
            error_message="",
            tags=tags or [],
            pinned=False,
            parent_scan_id=parent_scan_id,
        )
        self._upsert_entry(entry)
        return entry

    def complete_scan(
        self,
        scan_id: str,
        result_summary: ScanResultSummary,
        payload: Any,
        warnings_summary: Optional[ScanWarningsSummary] = None,
        finished_at_iso: Optional[str] = None,
        health_snapshots: Optional[List[ScanHealthSnapshot]] = None,
    ) -> ScanHistoryEntry:
        entry = self.get_entry(scan_id)
        if not entry:
            raise KeyError(f"Scan entry not found: {scan_id}")

        finished_at = finished_at_iso or _utc_now_iso()
        entry.finished_at_iso = finished_at
        entry.status = ScanStatus.COMPLETED
        entry.error_message = ""
        entry.result_summary = result_summary
        entry.warnings_summary = warnings_summary or ScanWarningsSummary()
        entry.duration_ms = self._duration_ms(entry.started_at_iso, entry.finished_at_iso)
        entry.root_mtime = self._try_stat_mtime(entry.root_path)
        
        if health_snapshots:
            entry.health_snapshots = health_snapshots
            if health_snapshots:
                entry.peak_memory_percent = max(h.memory_percent for h in health_snapshots)
                entry.peak_cpu_percent = max(h.cpu_percent for h in health_snapshots)

        self._write_payload(entry.scan_id, payload, entry)
        self._upsert_entry(entry)
        return entry

    def fail_scan(self, scan_id: str, error_message: str, 
                  status: ScanStatus = ScanStatus.FAILED) -> ScanHistoryEntry:
        entry = self.get_entry(scan_id)
        if not entry:
            raise KeyError(f"Scan entry not found: {scan_id}")

        entry.status = status
        entry.error_message = str(error_message)
        entry.finished_at_iso = _utc_now_iso()
        entry.duration_ms = self._duration_ms(entry.started_at_iso, entry.finished_at_iso)
        self._upsert_entry(entry)
        return entry

    def update_health_snapshot(self, scan_id: str, snapshot: ScanHealthSnapshot):
        """Live update health data during scan (for Health Panel)."""
        entry = self.get_entry(scan_id)
        if entry and entry.status == ScanStatus.IN_PROGRESS:
            entry.health_snapshots.append(snapshot)
            # Update peak values
            entry.peak_memory_percent = max(entry.peak_memory_percent, snapshot.memory_percent)
            entry.peak_cpu_percent = max(entry.peak_cpu_percent, snapshot.cpu_percent)
            self._upsert_entry(entry)

    def rename_scan(self, scan_id: str, new_name: str) -> None:
        entry = self.get_entry(scan_id)
        if not entry:
            return
        entry.name = new_name.strip() or entry.name
        self._upsert_entry(entry)

    def set_pinned(self, scan_id: str, pinned: bool) -> None:
        entry = self.get_entry(scan_id)
        if not entry:
            return
        entry.pinned = bool(pinned)
        self._upsert_entry(entry)

    def set_color_code(self, scan_id: str, color: str) -> None:
        entry = self.get_entry(scan_id)
        if entry:
            entry.color_code = color
            self._upsert_entry(entry)

    def add_tags(self, scan_id: str, tags: List[str]) -> None:
        entry = self.get_entry(scan_id)
        if entry:
            entry.tags = list(set(entry.tags + tags))
            self._upsert_entry(entry)

    def delete_scan(self, scan_id: str, delete_payload: bool = True) -> None:
        with _file_lock(self.lock_path):
            idx = self._read_index_unlocked()
            entries = idx.get("entries") or []
            new_entries = [e for e in entries if str(e.get("scan_id")) != scan_id]
            idx["entries"] = new_entries
            self._write_index_unlocked(idx)

        if delete_payload:
            entry_payload = self.payload_dir / f"{scan_id}.json.gz"
            if entry_payload.exists():
                try:
                    entry_payload.unlink()
                except Exception:
                    pass
            # Also delete health log
            health_log = self.health_dir / f"{scan_id}.health.json"
            if health_log.exists():
                health_log.unlink()

    def load_payload(self, scan_id: str) -> Dict[str, Any]:
        payload_path = self.payload_dir / f"{scan_id}.json.gz"
        if not payload_path.exists():
            raise FileNotFoundError(f"Missing payload: {payload_path}")
        with gzip.open(payload_path, "rt", encoding="utf-8") as f:
            return json.load(f)

    def staleness_state(self, entry: ScanHistoryEntry) -> Tuple[str, str]:
        root = Path(entry.root_path)
        if not root.exists():
            return ("invalid", "Root folder not found.")
        try:
            now_mtime = root.stat().st_mtime
        except Exception:
            return ("stale", "Cannot stat folder; may be stale.")
        if entry.root_mtime <= 0:
            return ("stale", "No baseline timestamp; may be stale.")
        if now_mtime > entry.root_mtime + 1.0:
            return ("stale", "Folder changed since scan; results may be stale.")
        return ("fresh", "Likely unchanged since scan.")

    # -------------------------
    # New: Export & Comparison
    # -------------------------

    def export_to_csv(self, scan_id: str, output_path: Optional[Path] = None) -> Path:
        """Export scan results to CSV for external analysis."""
        entry = self.get_entry(scan_id)
        if not entry:
            raise ValueError(f"Scan not found: {scan_id}")
        
        payload = self.load_payload(scan_id)
        groups = payload.get("payload", {}).get("groups", [])
        
        if output_path is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = self.exports_dir / f"scan_{scan_id}_{timestamp}.csv"
        
        with open(output_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['Group ID', 'File Path', 'Size (Bytes)', 'Hash', 'Modified'])
            for group_idx, group in enumerate(groups):
                for file_path in group:
                    # Try to get file stats if path exists
                    try:
                        stat = Path(file_path).stat()
                        size = stat.st_size
                        mtime = datetime.fromtimestamp(stat.st_mtime).isoformat()
                    except:
                        size = 0
                        mtime = ""
                    writer.writerow([group_idx, file_path, size, "", mtime])
        
        return output_path

    def export_to_json(self, scan_id: str, output_path: Optional[Path] = None) -> Path:
        """Export full scan metadata to JSON."""
        entry = self.get_entry(scan_id)
        if not entry:
            raise ValueError(f"Scan not found: {scan_id}")
        
        if output_path is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = self.exports_dir / f"scan_{scan_id}_{timestamp}.json"
        
        data = {
            "metadata": entry.to_dict(),
            "payload": self.load_payload(scan_id)
        }
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        return output_path

    def compare_scans(self, baseline_id: str, compare_id: str) -> Dict[str, Any]:
        """Compare two scans and return differences."""
        baseline_entry = self.get_entry(baseline_id)
        compare_entry = self.get_entry(compare_id)
        
        if not baseline_entry or not compare_entry:
            raise ValueError("One or both scans not found")
        
        baseline_payload = self.load_payload(baseline_id)
        compare_payload = self.load_payload(compare_id)
        
        baseline_groups = set(tuple(sorted(g)) for g in baseline_payload.get("payload", {}).get("groups", []))
        compare_groups = set(tuple(sorted(g)) for g in compare_payload.get("payload", {}).get("groups", []))
        
        new_duplicates = compare_groups - baseline_groups
        resolved_duplicates = baseline_groups - compare_groups
        
        return {
            "baseline_scan": baseline_entry.name,
            "compare_scan": compare_entry.name,
            "baseline_date": baseline_entry.finished_at_iso,
            "compare_date": compare_entry.finished_at_iso,
            "new_duplicate_groups": len(new_duplicates),
            "resolved_duplicate_groups": len(resolved_duplicates),
            "new_duplicate_files": sum(len(g) for g in new_duplicates),
            "space_reclaimed": baseline_entry.result_summary.duplicate_bytes - compare_entry.result_summary.duplicate_bytes,
            "efficiency_delta": compare_entry.get_efficiency_score() - baseline_entry.get_efficiency_score(),
        }

    def get_statistics(self) -> Dict[str, Any]:
        """Get aggregate statistics across all scans."""
        entries = self.list_entries()
        completed = [e for e in entries if e.status == ScanStatus.COMPLETED]
        
        if not completed:
            return {}
        
        total_scanned = sum(e.result_summary.scanned_bytes for e in completed)
        total_dupes = sum(e.result_summary.duplicate_bytes for e in completed)
        total_duration = sum(e.duration_ms for e in completed)
        
        return {
            "total_scans": len(entries),
            "completed_scans": len(completed),
            "total_files_scanned": sum(e.result_summary.scanned_files for e in completed),
            "total_bytes_scanned": total_scanned,
            "total_duplicate_bytes": total_dupes,
            "average_scan_duration_ms": total_duration / len(completed) if completed else 0,
            "average_efficiency": sum(e.get_efficiency_score() for e in completed) / len(completed) if completed else 0,
            "peak_memory_ever": max((e.peak_memory_percent for e in completed), default=0),
        }

    def bulk_delete(self, scan_ids: List[str]) -> Tuple[int, List[str]]:
        """Delete multiple scans, return (success_count, errors)."""
        errors = []
        success = 0
        for scan_id in scan_ids:
            try:
                self.delete_scan(scan_id)
                success += 1
            except Exception as e:
                errors.append(f"{scan_id}: {e}")
        return success, errors

    def bulk_export(self, scan_ids: List[str], format: str = "json") -> List[Path]:
        """Export multiple scans."""
        paths = []
        for scan_id in scan_ids:
            try:
                if format == "csv":
                    paths.append(self.export_to_csv(scan_id))
                else:
                    paths.append(self.export_to_json(scan_id))
            except Exception:
                pass
        return paths

    # -------------------------
    # Internal helpers
    # -------------------------

    def _duration_ms(self, start_iso: str, end_iso: str) -> int:
        try:
            s = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
            e = datetime.fromisoformat(end_iso.replace("Z", "+00:00"))
            return max(0, int((e - s).total_seconds() * 1000))
        except Exception:
            return 0

    def _try_stat_mtime(self, path_str: str) -> float:
        try:
            p = Path(path_str)
            if p.exists():
                return float(p.stat().st_mtime)
        except Exception:
            pass
        return 0.0

    def _read_index(self) -> Dict[str, Any]:
        with _file_lock(self.lock_path):
            return self._read_index_unlocked()

    def _read_index_unlocked(self) -> Dict[str, Any]:
        if not self.index_path.exists():
            return {"schema_version": HISTORY_SCHEMA_VERSION, "entries": []}
        try:
            data = json.loads(self.index_path.read_text(encoding="utf-8"))
            if int(data.get("schema_version", 0)) != HISTORY_SCHEMA_VERSION:
                backup = self.index_path.with_suffix(".bak")
                shutil.copy2(self.index_path, backup)
                return {"schema_version": HISTORY_SCHEMA_VERSION, "entries": []}
            return data
        except Exception:
            backup = self.index_path.with_suffix(".corrupt.bak")
            try:
                shutil.copy2(self.index_path, backup)
            except Exception:
                pass
            return {"schema_version": HISTORY_SCHEMA_VERSION, "entries": []}

    def _write_index(self, data: Dict[str, Any]) -> None:
        with _file_lock(self.lock_path):
            self._write_index_unlocked(data)

    def _write_index_unlocked(self, data: Dict[str, Any]) -> None:
        data = dict(data)
        data["schema_version"] = HISTORY_SCHEMA_VERSION
        _atomic_write_text(self.index_path, json.dumps(data, indent=2, ensure_ascii=False))

    def _upsert_entry(self, entry: ScanHistoryEntry) -> None:
        with _file_lock(self.lock_path):
            idx = self._read_index_unlocked()
            entries = idx.get("entries") or []
            replaced = False
            for i, d in enumerate(entries):
                if str(d.get("scan_id")) == entry.scan_id:
                    entries[i] = entry.to_dict()
                    replaced = True
                    break
            if not replaced:
                entries.append(entry.to_dict())
            idx["entries"] = entries
            self._write_index_unlocked(idx)

    def _write_payload(self, scan_id: str, payload: Any, entry: ScanHistoryEntry) -> None:
        payload_path = self.payload_dir / f"{scan_id}.json.gz"
        blob = {
            "payload_schema_version": PAYLOAD_SCHEMA_VERSION,
            "scan_id": scan_id,
            "root_path": entry.root_path,
            "started_at_iso": entry.started_at_iso,
            "finished_at_iso": entry.finished_at_iso,
            "settings_snapshot": entry.settings_snapshot,
            "result_summary": asdict(entry.result_summary),
            "warnings_summary": asdict(entry.warnings_summary),
            "health_summary": {
                "peak_memory": entry.peak_memory_percent,
                "peak_cpu": entry.peak_cpu_percent,
                "snapshot_count": len(entry.health_snapshots),
            },
            "payload": to_jsonable(payload),
        }
        raw = json.dumps(blob, ensure_ascii=False).encode("utf-8")
        compressed = gzip.compress(raw, compresslevel=6)
        _atomic_write_bytes(payload_path, compressed)