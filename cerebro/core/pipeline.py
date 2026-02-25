"""
CEREBRO Pipeline - Target Architecture (Authoritative)

ReviewPage (UI) produces DeletionPlan (intent only)
MainWindow passes DeletionPlan to Pipeline
Pipeline:
  - validates invariants
  - expands + enriches metadata -> ExecutableDeletePlan
  - executes via DeletionEngine
  - records audit via HistoryStore
Returns DeletionResult (plan-level) to UI.

This file is DELETE-PIPELINE authoritative and intentionally headless.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from .deletion import DeletionEngine, DeletionPolicy, DeletionRequest, BatchDeletionResult
from ..history.store import HistoryStore


@dataclass(frozen=True)
class ExecutableDeleteOperation:
    """Single validated delete operation."""
    path: Path
    size: int
    group_index: int
    kept_path: Path
    mtime: float = 0.0


@dataclass(frozen=True)
class ExecutableDeletePlan:
    """Validated, enriched deletion plan ready for execution."""
    scan_id: str
    mode: str  # 'trash' or 'permanent'
    operations: List[ExecutableDeleteOperation]
    stats: Dict[str, Any] = field(default_factory=dict)
    policy: Dict[str, Any] = field(default_factory=dict)
    source: str = "review_page"

    @property
    def total_bytes(self) -> int:
        return sum(int(op.size or 0) for op in self.operations)

    @property
    def total_files(self) -> int:
        return len(self.operations)


@dataclass(frozen=True)
class DeletionResult:
    """Result of deletion execution (plan-level)."""
    scan_id: str
    mode: str
    deleted: List[Path]
    failed: List[Tuple[Path, str]]
    bytes_reclaimed: int
    stats: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=lambda: datetime.now().timestamp())


class CerebroPipeline:
    """
    Pipeline owns truth for deletion operations.
    Validates UI intent and produces executable plans.
    Owns side-effects: execution + audit write-through.
    """

    def __init__(
        self,
        deletion_engine: Optional[DeletionEngine] = None,
        history_store: Optional[HistoryStore] = None,
    ) -> None:
        self._deletion_engine = deletion_engine or DeletionEngine()
        self._history = history_store or HistoryStore()

        self._logger = None
        try:
            from ..services.logger import Logger  # type: ignore
            self._logger = Logger()
        except Exception:
            self._logger = None

    def _log(self, message: str, level: str = "info") -> None:
        if self._logger:
            try:
                getattr(self._logger, level, self._logger.info)(message)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Build plan (validate + enrich)
    # ------------------------------------------------------------------

    def build_delete_plan(self, deletion_plan: Dict[str, Any]) -> ExecutableDeletePlan:
        """
        Validate invariants, enrich metadata, and prepare executable plan.

        Expected UI DeletionPlan:
        {
          "scan_id": "...",
          "policy": {"mode":"trash"|"permanent", ...},
          "groups": [{"group_index":0,"keep":"...","delete":["..."]}, ...],
          "source": "review_page" (optional),
          "timestamp": ... (optional)
        }
        """
        scan_id = str(deletion_plan.get("scan_id", "unknown"))
        policy = dict(deletion_plan.get("policy", {}) or {})
        mode = str(policy.get("mode", "trash"))
        source = str(deletion_plan.get("source", "review_page"))
        groups = list(deletion_plan.get("groups", []) or [])

        self._log(f"Building delete plan scan={scan_id} mode={mode} groups={len(groups)}")

        operations: List[ExecutableDeleteOperation] = []
        errors: List[str] = []

        # Validate + expand
        for group_data in groups:
            try:
                group_idx = int(group_data.get("group_index", 0) or 0)
            except Exception:
                group_idx = 0

            keep_path_str = str(group_data.get("keep", "") or "")
            delete_paths = list(group_data.get("delete", []) or [])

            keep_path = Path(keep_path_str) if keep_path_str else None
            if not keep_path or not keep_path.exists():
                errors.append(f"Group {group_idx}: keep missing: {keep_path_str}")
                continue

            try:
                keep_resolved = keep_path.resolve()
            except Exception:
                keep_resolved = keep_path

            # Invariant: cannot delete keeper. Missing delete file → skip that file only (race/stale UI).
            for del_path_str in delete_paths:
                del_path_str = str(del_path_str)
                if not del_path_str:
                    continue
                del_path = Path(del_path_str)

                if not del_path.exists():
                    # Skip this file; do not fail the group or the plan
                    continue

                try:
                    del_resolved = del_path.resolve()
                except Exception:
                    del_resolved = del_path

                if keep_resolved == del_resolved:
                    errors.append(f"Group {group_idx}: keeper included in delete: {del_path_str}")
                    continue

                # Enrich metadata
                try:
                    st = del_path.stat()
                    size = int(st.st_size or 0)
                    mtime = float(st.st_mtime or 0.0)
                except Exception:
                    size = 0
                    mtime = 0.0

                operations.append(
                    ExecutableDeleteOperation(
                        path=del_path,
                        size=size,
                        group_index=group_idx,
                        kept_path=keep_path,
                        mtime=mtime,
                    )
                )

        # Raise only if no keeper for all groups, or deletion requested but no operations produced
        if errors:
            msg = "; ".join(errors)
            self._log(f"Deletion plan validation failed: {msg}", level="error")
            raise ValueError(f"Deletion plan validation failed: {msg}")
        if groups and not operations:
            self._log("Deletion plan: groups present but no valid operations (all keepers missing or all delete paths missing)", level="error")
            raise ValueError("Deletion plan: no valid operations (missing keepers or all delete paths missing)")

        stats = {
            "groups": len(groups),
            "files": len(operations),
            "bytes": sum(int(op.size or 0) for op in operations),
            "validated_at": datetime.now().isoformat(),
        }

        self._log(f"Plan validated: files={stats['files']} bytes={stats['bytes']}")
        return ExecutableDeletePlan(
            scan_id=scan_id,
            mode=mode,
            operations=operations,
            stats=stats,
            policy=policy,
            source=source,
        )

    # ------------------------------------------------------------------
    # Execute plan (engine) + write audit (history) - AUTHORITATIVE
    # ------------------------------------------------------------------

    def execute_delete_plan(
        self,
        plan: ExecutableDeletePlan,
        progress_cb: Optional[Callable[[int, int, str], bool]] = None,
    ) -> DeletionResult:
        """
        Execute validated deletion plan, then record audit trail.

        progress_cb(current, total, current_file_name) -> bool (continue?)
        """
        self._log(f"Executing delete plan scan={plan.scan_id} mode={plan.mode} ops={plan.total_files}")

        policy = DeletionPolicy.PERMANENT if plan.mode == "permanent" else DeletionPolicy.TRASH
        request = DeletionRequest(
            policy=policy,
            metadata={
                "scan_id": plan.scan_id,
                "source": plan.source,
                "mode": plan.mode,
                "operation_count": plan.total_files,
            },
        )

        batch: BatchDeletionResult = self._deletion_engine.execute_plan(
            plan,
            request=request,
            progress_cb=progress_cb,
        )

        # Build per-file audit details from the plan and execution results
        deleted_set = {str(p) for p in batch.deleted}
        failed_map = {str(p): err for p, err in batch.failed}

        details: List[Dict[str, Any]] = []
        for op in plan.operations:
            p = str(op.path)
            status = "deleted" if p in deleted_set else ("failed" if p in failed_map else "skipped")
            details.append(
                {
                    "path": p,
                    "group_index": int(op.group_index),
                    "kept_path": str(op.kept_path),
                    "bytes": int(op.size or 0),
                    "mtime": float(op.mtime or 0.0),
                    "status": status,
                    "error": failed_map.get(p),
                }
            )

        result = DeletionResult(
            scan_id=str(plan.scan_id),
            mode=str(plan.mode),
            deleted=list(batch.deleted),
            failed=list(batch.failed),
            bytes_reclaimed=int(batch.bytes_reclaimed or 0),
            stats=dict(plan.stats or {}),
        )

        # AUTHORITATIVE AUDIT WRITE (Pipeline owns history)
        try:
            self._history.record_deletion(
                scan_id=plan.scan_id,
                mode=plan.mode,
                groups=int(plan.stats.get("groups", 0) or 0),
                deleted=len(result.deleted),
                failed=len(result.failed),
                bytes_reclaimed=result.bytes_reclaimed,
                source=plan.source or "review_page",
                policy=plan.policy or {"mode": plan.mode},
                details=details,
            )
        except Exception as e:
            self._log(f"Audit write failed (non-fatal): {e}", level="warning")

        self._log(
            f"Deletion complete scan={plan.scan_id} deleted={len(result.deleted)} failed={len(result.failed)} bytes={result.bytes_reclaimed}"
        )
        return result
# ==============================================================================
# LEGACY COMPATIBILITY SHIMS (v5 scan pipeline)
# ==============================================================================

class PipelineResult:
    """
    Legacy scan pipeline result placeholder.

    This exists ONLY to satisfy older v5 imports
    (ScanWorker, FastScanWorker, LiveScanController).

    The authoritative scan result handling lives elsewhere.
    """
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)

# ==============================================================================
# LEGACY COMPATIBILITY SHIMS (v5 event signaling)
# ==============================================================================

class PipelineEvent:
    """
    Legacy pipeline event placeholder.

    Exists ONLY to satisfy older v5 imports that reference
    PipelineEvent during scan execution.

    Event dispatching is now handled by controllers / StateBus.
    """
    def __init__(self, name: str = "", payload: dict | None = None):
        self.name = name
        self.payload = payload or {}

# ==============================================================================
# LEGACY COMPATIBILITY SHIMS (v5 scan statistics)
# ==============================================================================

class PipelineStats:
    """
    Legacy pipeline statistics placeholder.

    Exists ONLY to satisfy older v5 imports that expect
    PipelineStats during scan execution.

    Authoritative stats are now handled by:
    - performance_monitor
    - controllers
    - result objects
    """
    def __init__(self, **kwargs):
        # Allow arbitrary attributes for backward compatibility
        for k, v in kwargs.items():
            setattr(self, k, v)

# ==============================================================================
# LEGACY COMPATIBILITY SHIMS (v5 import stability)
# ==============================================================================

def create_default_pipeline():
    """
    Legacy factory used by older v5 code paths (scan workers, main bootstrap).

    Returns:
        CerebroPipeline (authoritative implementation)
    """
    return CerebroPipeline()

# ==============================================================================
# LEGACY COMPATIBILITY SHIMS (v5 cancellation token)
# ==============================================================================

class CancelToken:
    """
    Legacy cancellation token.

    Used by older core modules (grouping, discovery, hashing)
    to cooperatively cancel long-running operations.

    In the new architecture, cancellation is handled by
    workers and controllers. This class exists ONLY to
    preserve backward compatibility.
    """

    def __init__(self):
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def is_cancelled(self) -> bool:
        return self._cancelled

    # Backward compatibility aliases
    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def __call__(self) -> bool:
        """Allow token to be called as a function."""
        return self._cancelled

# ==============================================================================
# LEGACY COMPATIBILITY SHIMS (v5 pipeline request)
# ==============================================================================

class PipelineRequest:
    """
    Legacy pipeline request container.

    Used by older scan workers and core stages to pass:
    - scan configuration
    - cancel token
    - progress hooks

    In the new architecture, these responsibilities live
    in workers/controllers. This class exists ONLY for
    backward compatibility.
    """

    def __init__(
        self,
        config=None,
        cancel_token: CancelToken | None = None,
        progress_cb=None,
        **kwargs
    ):
        self.config = config
        self.cancel_token = cancel_token or CancelToken()
        self.progress_cb = progress_cb

        # Allow arbitrary legacy attributes
        for k, v in kwargs.items():
            setattr(self, k, v)

# ==============================================================================
# LEGACY COMPATIBILITY SHIMS (v5 delete plan)
# ==============================================================================

class DeletePlan:
    """
    Legacy delete plan placeholder.

    Used by older decision/curation logic to represent
    an intended deletion outcome before execution.

    In the new architecture, this role is fulfilled by
    ExecutableDeletePlan. This class exists ONLY for
    backward compatibility.
    """

    def __init__(self, **kwargs):
        # Store arbitrary legacy attributes
        for k, v in kwargs.items():
            setattr(self, k, v)

    def to_executable(self):
        """
        Best-effort adapter for legacy code paths that
        expect a conversion step.
        """
        return self

# ==============================================================================
# LEGACY COMPATIBILITY SHIMS (v5 delete plan item)
# ==============================================================================

class DeletePlanItem:
    """
    Legacy delete plan item.

    Represents a single file-level delete/keep decision
    produced by older decision logic.

    In the new architecture, this role is handled by
    ExecutableDeleteOperation. This class exists ONLY
    for backward compatibility.
    """

    def __init__(
        self,
        path=None,
        keep: bool | None = None,
        group_index: int | None = None,
        score: float | None = None,
        **kwargs
    ):
        self.path = path
        self.keep = keep
        self.group_index = group_index
        self.score = score

        # Allow arbitrary legacy attributes
        for k, v in kwargs.items():
            setattr(self, k, v)


__all__ = [
    "CerebroPipeline",
    "ExecutableDeletePlan",
    "ExecutableDeleteOperation",
    "DeletionResult",
    "DeletePlan",
    "DeletePlanItem",
    "PipelineResult",
    "PipelineEvent",
    "PipelineStats",
    "CancelToken",
    "PipelineRequest",
    "create_default_pipeline",
]


