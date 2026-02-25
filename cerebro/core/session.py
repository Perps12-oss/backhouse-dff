# path: cerebro/core/session.py
"""
core/session.py — Enhanced Session Manager

Thread-safe session management with:
- Scan lifecycle tracking
- State persistence
- UI intent management
- Delete plan storage
"""

from __future__ import annotations

import threading
import time
import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union


class ScanState(str, Enum):
    """Scan lifecycle states."""
    NEW = "new"
    RUNNING = "running"
    SCANNED = "scanned"
    DECIDED = "decided"
    DELETING = "deleting"
    DELETED = "deleted"
    CANCELLED = "cancelled"
    FAILED = "failed"


@dataclass
class SurvivorLock:
    """Survivor lock (file that should not be deleted)."""
    path: Path
    reason: str = "user_locked"
    timestamp: float = field(default_factory=time.time)


@dataclass
class DeleteIntent:
    """User deletion intent."""
    path: Path
    reason: str = "user_selected"
    timestamp: float = field(default_factory=time.time)


@dataclass
class DeletionResult:
    """Deletion execution result."""
    deleted: List[Path] = field(default_factory=list)
    failed: List[Tuple[Path, str]] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)


@dataclass
class ScanRecord:
    """Complete scan record."""
    scan_id: str
    roots: List[Path]
    metadata: Dict[str, Any] = field(default_factory=dict)
    state: ScanState = ScanState.NEW
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    
    # Core data
    groups: List[Any] = field(default_factory=list)  # List[DuplicateGroup]
    delete_plan: Optional[Any] = None  # DeletePlan
    
    # UI intents
    survivor_locks: Dict[str, SurvivorLock] = field(default_factory=dict)
    delete_intents: Dict[str, DeleteIntent] = field(default_factory=dict)
    
    # Results
    deletion_result: Optional[DeletionResult] = None
    
    # Diagnostics
    warnings: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to serializable dictionary."""
        return {
            'scan_id': self.scan_id,
            'roots': [str(p) for p in self.roots],
            'metadata': self.metadata,
            'state': self.state.value,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
            'groups': self.groups,
            'delete_plan': self.delete_plan,
            'survivor_locks': {
                str(path): {'reason': lock.reason, 'timestamp': lock.timestamp}
                for path, lock in self.survivor_locks.items()
            },
            'delete_intents': {
                str(path): {'reason': intent.reason, 'timestamp': intent.timestamp}
                for path, intent in self.delete_intents.items()
            },
            'deletion_result': {
                'deleted': [str(p) for p in (self.deletion_result.deleted if self.deletion_result else [])],
                'failed': [(str(p), e) for p, e in (self.deletion_result.failed if self.deletion_result else [])],
                'timestamp': self.deletion_result.timestamp if self.deletion_result else None,
            } if self.deletion_result else None,
            'warnings': self.warnings,
            'notes': self.notes,
        }


class SessionManager:
    """
    Thread-safe session manager.
    
    Usage:
        session = SessionManager()
        session.begin_scan("scan_123", [Path("/home/user")], {"mode": "quick"})
        snapshot = session.snapshot("scan_123")
    """
    
    def __init__(self, persist_path: Optional[Path] = None):
        self._lock = threading.RLock()
        self._scans: Dict[str, ScanRecord] = {}
        self._current_scan_id: Optional[str] = None
        self._persist_path = persist_path or Path.home() / ".cerebro" / "sessions"
        
        # Load persisted sessions
        self._load_persisted()
    
    # =================================================================
    # CORE API (Pipeline writes)
    # =================================================================
    
    def begin_scan(
        self,
        scan_id: str,
        roots: List[Union[str, Path]],
        metadata: Dict[str, Any],
    ) -> None:
        """Begin a new scan."""
        with self._lock:
            # Normalize paths
            normalized_roots = []
            for root in roots:
                try:
                    normalized_roots.append(Path(root).resolve())
                except Exception:
                    normalized_roots.append(Path(root))
            
            record = ScanRecord(
                scan_id=scan_id,
                roots=normalized_roots,
                metadata=metadata or {},
                state=ScanState.RUNNING,
            )
            
            self._scans[scan_id] = record
            self._current_scan_id = scan_id
            self._persist_record(record)
    
    def set_groups(self, scan_id: str, groups: List[Any]) -> None:
        """Store duplicate groups."""
        with self._lock:
            if scan_id not in self._scans:
                raise KeyError(f"Unknown scan_id: {scan_id}")
            
            record = self._scans[scan_id]
            record.groups = groups or []
            record.state = ScanState.SCANNED
            record.updated_at = time.time()
            self._persist_record(record)
    
    def set_delete_plan(self, scan_id: str, plan: Any) -> None:
        """Store delete plan."""
        with self._lock:
            if scan_id not in self._scans:
                raise KeyError(f"Unknown scan_id: {scan_id}")
            
            record = self._scans[scan_id]
            record.delete_plan = plan
            record.state = ScanState.DECIDED
            record.updated_at = time.time()
            self._persist_record(record)
    
    def record_deleted(
        self,
        scan_id: str,
        deleted: List[Path],
        failed: List[Tuple[Path, str]],
    ) -> None:
        """Record deletion results."""
        with self._lock:
            if scan_id not in self._scans:
                raise KeyError(f"Unknown scan_id: {scan_id}")
            
            record = self._scans[scan_id]
            record.deletion_result = DeletionResult(
                deleted=deleted or [],
                failed=failed or [],
            )
            record.state = ScanState.DELETED
            record.updated_at = time.time()
            self._persist_record(record)
    
    def mark_deleting(self, scan_id: str) -> None:
        """Mark scan as currently deleting."""
        with self._lock:
            if scan_id in self._scans:
                self._scans[scan_id].state = ScanState.DELETING
                self._scans[scan_id].updated_at = time.time()
    
    def mark_cancelled(self, scan_id: str, reason: str = "") -> None:
        """Mark scan as cancelled."""
        with self._lock:
            if scan_id in self._scans:
                record = self._scans[scan_id]
                record.state = ScanState.CANCELLED
                record.updated_at = time.time()
                if reason:
                    record.notes.append(f"Cancelled: {reason}")
                self._persist_record(record)
    
    def mark_failed(self, scan_id: str, error: str = "") -> None:
        """Mark scan as failed."""
        with self._lock:
            if scan_id in self._scans:
                record = self._scans[scan_id]
                record.state = ScanState.FAILED
                record.updated_at = time.time()
                if error:
                    record.notes.append(f"Failed: {error}")
                self._persist_record(record)
    
    # =================================================================
    # QUERY API (UI reads)
    # =================================================================
    
    def current_scan_id(self) -> Optional[str]:
        """Get current scan ID."""
        with self._lock:
            return self._current_scan_id
    
    def list_scans(self, limit: int = 50) -> List[Dict[str, Any]]:
        """List recent scans."""
        with self._lock:
            records = list(self._scans.values())
            records.sort(key=lambda r: r.created_at, reverse=True)
            
            result = []
            for record in records[:limit]:
                result.append({
                    'scan_id': record.scan_id,
                    'state': record.state.value,
                    'created_at': record.created_at,
                    'updated_at': record.updated_at,
                    'roots': [str(p) for p in record.roots],
                    'group_count': len(record.groups),
                    'has_plan': record.delete_plan is not None,
                })
            return result
    
    def snapshot(self, scan_id: Optional[str] = None) -> Dict[str, Any]:
        """Get complete snapshot of scan."""
        with self._lock:
            target_id = scan_id or self._current_scan_id
            if not target_id or target_id not in self._scans:
                return {
                    'ok': False,
                    'error': 'No active scan',
                    'scan_id': target_id,
                }
            
            record = self._scans[target_id]
            return {
                'ok': True,
                **record.to_dict(),
            }
    
    def snapshot_json(self, scan_id: Optional[str] = None) -> Dict[str, Any]:
        """Get JSON-serializable snapshot."""
        snap = self.snapshot(scan_id)
        if not snap.get('ok'):
            return snap
        
        # Convert groups to dicts if they have to_dict method
        groups = snap.get('groups', [])
        converted_groups = []
        for group in groups:
            if hasattr(group, 'to_dict'):
                try:
                    converted_groups.append(group.to_dict())
                except Exception:
                    converted_groups.append(str(group))
            else:
                converted_groups.append(str(group))
        
        snap['groups'] = converted_groups
        return snap
    
    # =================================================================
    # UI INTENT MANAGEMENT
    # =================================================================
    
    def lock_survivor(
        self,
        scan_id: str,
        path: Union[str, Path],
        reason: str = "user_locked",
    ) -> None:
        """Lock a file as survivor (prevent deletion)."""
        with self._lock:
            if scan_id not in self._scans:
                raise KeyError(f"Unknown scan_id: {scan_id}")
            
            record = self._scans[scan_id]
            path_str = str(Path(path).resolve())
            record.survivor_locks[path_str] = SurvivorLock(
                path=Path(path),
                reason=reason,
            )
            # Remove any delete intent for this path
            record.delete_intents.pop(path_str, None)
            record.updated_at = time.time()
            self._persist_record(record)
    
    def unlock_survivor(self, scan_id: str, path: Union[str, Path]) -> None:
        """Remove survivor lock."""
        with self._lock:
            if scan_id in self._scans:
                path_str = str(Path(path).resolve())
                self._scans[scan_id].survivor_locks.pop(path_str, None)
                self._scans[scan_id].updated_at = time.time()
    
    def set_delete_intent(
        self,
        scan_id: str,
        path: Union[str, Path],
        reason: str = "user_selected",
    ) -> None:
        """Set deletion intent for a file."""
        with self._lock:
            if scan_id not in self._scans:
                raise KeyError(f"Unknown scan_id: {scan_id}")
            
            record = self._scans[scan_id]
            path_str = str(Path(path).resolve())
            
            # Check if survivor locked
            if path_str in record.survivor_locks:
                record.warnings.append(
                    f"Delete intent ignored (survivor locked): {path_str}"
                )
                return
            
            record.delete_intents[path_str] = DeleteIntent(
                path=Path(path),
                reason=reason,
            )
            record.updated_at = time.time()
            self._persist_record(record)
    
    def clear_delete_intent(self, scan_id: str, path: Union[str, Path]) -> None:
        """Clear deletion intent."""
        with self._lock:
            if scan_id in self._scans:
                path_str = str(Path(path).resolve())
                self._scans[scan_id].delete_intents.pop(path_str, None)
                self._scans[scan_id].updated_at = time.time()
    
    def clear_all_intents(self, scan_id: str) -> None:
        """Clear all UI intents."""
        with self._lock:
            if scan_id in self._scans:
                record = self._scans[scan_id]
                record.delete_intents.clear()
                record.survivor_locks.clear()
                record.updated_at = time.time()
                self._persist_record(record)
    
    # =================================================================
    # UTILITIES
    # =================================================================
    
    def build_effective_plan(
        self,
        scan_id: str,
        token: Optional[str] = None,
        policy: str = "dry_run",
    ) -> Optional[Dict[str, Any]]:
        """Build effective delete plan from UI intents."""
        with self._lock:
            if scan_id not in self._scans:
                return None
            
            record = self._scans[scan_id]
            if not record.groups:
                return None
            
            # Use provided token or generate one
            plan_token = token or f"ui_{int(time.time() * 1000)}"
            
            # Build items from intents
            items = []
            
            # Add survivor locks
            for lock in record.survivor_locks.values():
                items.append({
                    'path': str(lock.path),
                    'reason': lock.reason,
                    'group_id': '',  # Will be filled by UI
                    'survivor': True,
                    'size_bytes': 0,
                })
            
            # Add delete intents
            for intent in record.delete_intents.values():
                items.append({
                    'path': str(intent.path),
                    'reason': intent.reason,
                    'group_id': '',  # Will be filled by UI
                    'survivor': False,
                    'size_bytes': 0,
                })
            
            return {
                'token': plan_token,
                'policy': policy,
                'items': items,
            }
    
    # =================================================================
    # PERSISTENCE
    # =================================================================
    
    def _persist_record(self, record: ScanRecord) -> None:
        """Persist scan record to disk."""
        try:
            self._persist_path.mkdir(parents=True, exist_ok=True)
            file_path = self._persist_path / f"{record.scan_id}.json"
            
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(record.to_dict(), f, indent=2, default=str)
        except Exception as e:
            # Log but don't fail
            print(f"Failed to persist session: {e}")
    
    def _load_persisted(self) -> None:
        """Load persisted sessions from disk."""
        try:
            if not self._persist_path.exists():
                return
            
            for file_path in self._persist_path.glob("*.json"):
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    
                    # Create record from data
                    record = ScanRecord(
                        scan_id=data['scan_id'],
                        roots=[Path(p) for p in data['roots']],
                        metadata=data.get('metadata', {}),
                        state=ScanState(data['state']),
                        created_at=float(data['created_at']),
                        updated_at=float(data['updated_at']),
                        groups=data.get('groups', []),
                        delete_plan=data.get('delete_plan'),
                        warnings=data.get('warnings', []),
                        notes=data.get('notes', []),
                    )
                    
                    # Load survivor locks
                    for path_str, lock_data in data.get('survivor_locks', {}).items():
                        record.survivor_locks[path_str] = SurvivorLock(
                            path=Path(path_str),
                            reason=lock_data['reason'],
                            timestamp=float(lock_data['timestamp']),
                        )
                    
                    # Load delete intents
                    for path_str, intent_data in data.get('delete_intents', {}).items():
                        record.delete_intents[path_str] = DeleteIntent(
                            path=Path(path_str),
                            reason=intent_data['reason'],
                            timestamp=float(intent_data['timestamp']),
                        )
                    
                    # Load deletion result
                    if data.get('deletion_result'):
                        result_data = data['deletion_result']
                        record.deletion_result = DeletionResult(
                            deleted=[Path(p) for p in result_data['deleted']],
                            failed=[(Path(p), e) for p, e in result_data['failed']],
                            timestamp=float(result_data['timestamp']),
                        )
                    
                    self._scans[record.scan_id] = record
                    
                except Exception as e:
                    print(f"Failed to load session {file_path}: {e}")
        
        except Exception as e:
            print(f"Failed to load persisted sessions: {e}")
    
    def cleanup_old_sessions(self, max_age_days: int = 30) -> int:
        """Clean up old session files."""
        with self._lock:
            count = 0
            cutoff = time.time() - (max_age_days * 86400)
            
            for scan_id, record in list(self._scans.items()):
                if record.updated_at < cutoff:
                    # Remove from memory
                    self._scans.pop(scan_id, None)
                    
                    # Remove from disk
                    file_path = self._persist_path / f"{scan_id}.json"
                    if file_path.exists():
                        file_path.unlink(missing_ok=True)
                    
                    count += 1
            
            return count


# =====================================================================
# FACTORY
# =====================================================================

def create_session_manager(
    persist_path: Optional[Path] = None,
) -> SessionManager:
    """
    Create a session manager.
    
    Args:
        persist_path: Path to persist sessions (default: ~/.cerebro/sessions)
    
    Returns:
        Configured SessionManager
    """
    return SessionManager(persist_path=persist_path)


__all__ = [
    'SessionManager',
    'create_session_manager',
    'ScanState',
    'ScanRecord',
    'SurvivorLock',
    'DeleteIntent',
    'DeletionResult',
]