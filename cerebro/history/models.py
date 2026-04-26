# cerebro/history/models.py
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List


HISTORY_SCHEMA_VERSION = 2  # Bumped for health data
PAYLOAD_SCHEMA_VERSION = 1


class ScanStatus(str, Enum):
    COMPLETED = "completed"
    IN_PROGRESS = "in_progress"
    FAILED = "failed"
    CANCELLED = "cancelled"
    STALLED = "stalled"  # New: detected hang


@dataclass
class ScanHealthSnapshot:
    """Health metrics captured during scan (from ReviewPage health panel)."""
    cpu_percent: float = 0.0
    memory_percent: float = 0.0
    disk_read_mb: float = 0.0
    disk_write_mb: float = 0.0
    open_file_handles: int = 0
    thread_count: int = 0
    timestamp_iso: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "ScanHealthSnapshot":
        return ScanHealthSnapshot(**d)


@dataclass
class ScanResultSummary:
    groups: int = 0
    items: int = 0
    duplicate_bytes: int = 0
    scanned_files: int = 0
    scanned_bytes: int = 0
    # New: timing breakdown
    discovery_ms: int = 0
    hashing_ms: int = 0
    clustering_ms: int = 0


@dataclass
class ScanWarningsSummary:
    permission_denied: int = 0
    unreadable: int = 0
    skipped_hidden: int = 0
    skipped_system: int = 0
    other: int = 0
    # New: error log paths
    error_log_refs: List[str] = field(default_factory=list)


@dataclass
class ScanHistoryEntry:
    scan_id: str
    name: str
    root_path: str

    status: ScanStatus = ScanStatus.IN_PROGRESS

    started_at_iso: str = ""          
    finished_at_iso: str = ""         
    duration_ms: int = 0

    root_mtime: float = 0.0           
    engine_version: str = ""          
    history_schema_version: int = HISTORY_SCHEMA_VERSION
    payload_schema_version: int = PAYLOAD_SCHEMA_VERSION

    settings_snapshot: Dict[str, Any] = field(default_factory=dict)
    result_summary: ScanResultSummary = field(default_factory=ScanResultSummary)
    warnings_summary: ScanWarningsSummary = field(default_factory=ScanWarningsSummary)
    
    # New: Health monitoring data (list of snapshots during scan)
    health_snapshots: List[ScanHealthSnapshot] = field(default_factory=list)
    peak_memory_percent: float = 0.0
    peak_cpu_percent: float = 0.0

    payload_ref: str = ""  
    error_message: str = ""
    
    # UX enhancements
    tags: List[str] = field(default_factory=list)
    pinned: bool = False
    color_code: str = ""  # User-assigned color tag
    
    # Comparison metadata
    parent_scan_id: str = ""  # For incremental scans
    baseline_scan_id: str = ""  # If compared against another

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        d["health_snapshots"] = [h.to_dict() for h in self.health_snapshots]
        return d

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "ScanHistoryEntry":
        rs = d.get("result_summary") or {}
        ws = d.get("warnings_summary") or {}
        hs_list = d.get("health_snapshots") or []
        
        return ScanHistoryEntry(
            scan_id=str(d.get("scan_id", "")),
            name=str(d.get("name", "")),
            root_path=str(d.get("root_path", "")),
            status=ScanStatus(d.get("status", ScanStatus.IN_PROGRESS.value)),
            started_at_iso=str(d.get("started_at_iso", "")),
            finished_at_iso=str(d.get("finished_at_iso", "")),
            duration_ms=int(d.get("duration_ms", 0)),
            root_mtime=float(d.get("root_mtime", 0.0)),
            engine_version=str(d.get("engine_version", "")),
            history_schema_version=int(d.get("history_schema_version", HISTORY_SCHEMA_VERSION)),
            payload_schema_version=int(d.get("payload_schema_version", PAYLOAD_SCHEMA_VERSION)),
            settings_snapshot=dict(d.get("settings_snapshot") or {}),
            result_summary=ScanResultSummary(**rs),
            warnings_summary=ScanWarningsSummary(**ws),
            health_snapshots=[ScanHealthSnapshot.from_dict(h) for h in hs_list],
            peak_memory_percent=float(d.get("peak_memory_percent", 0.0)),
            peak_cpu_percent=float(d.get("peak_cpu_percent", 0.0)),
            payload_ref=str(d.get("payload_ref", "")),
            error_message=str(d.get("error_message", "")),
            tags=list(d.get("tags") or []),
            pinned=bool(d.get("pinned", False)),
            color_code=str(d.get("color_code", "")),
            parent_scan_id=str(d.get("parent_scan_id", "")),
            baseline_scan_id=str(d.get("baseline_scan_id", "")),
        )
    
    def get_efficiency_score(self) -> float:
        """Calculate scan efficiency (0-100) based on dupes found vs time."""
        if self.duration_ms <= 0 or self.result_summary.scanned_files <= 0:
            return 0.0
        dupes_per_file = self.result_summary.items / self.result_summary.scanned_files
        speed = self.result_summary.scanned_files / (self.duration_ms / 1000)  # files/sec
        return min(100.0, (dupes_per_file * 1000) + (speed / 100))