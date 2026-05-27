"""
CEREBRO Pipeline - Target Architecture (Authoritative)

Review flow UI produces DeletionPlan (intent only).
The live deletion path passes DeletionPlan to Pipeline.
Pipeline:
  - validates invariants (keeper cannot equal delete target)
  - calls should_block_delete() per path (hardlink / symlink policy)
  - expands + enriches metadata -> ExecutableDeletePlan
  - executes via DeletionEngine
  - records dual audit trail (HistoryStore JSONL + deletion_history_db SQLite)
Returns DeletionResult (plan-level) to UI.

Gate lifecycle (Decision A):
  - One DeletionGate per CerebroPipeline instance.
  - Callers issue token on self.gate, embed in plan.policy["token"].
  - execute_delete_plan() calls self.gate.assert_allowed() — never creates a fresh gate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from .deletion import DeletionEngine, DeletionPolicy, DeletionRequest, BatchDeletionResult
from .fs_policy import HardlinkPolicy, should_block_delete
from .safety.deletion_gate import DeletionGate, DeletionGateConfig, DeletionGateError
from ..history.store import HistoryStore


@dataclass(frozen=True)
class ExecutableDeleteOperation:
    """Single validated delete operation."""
    path: Path
    size: int
    group_index: int
    kept_path: Optional[Path]
    mtime: float = 0.0


@dataclass(frozen=True)
class ExecutableDeletePlan:
    """Validated, enriched deletion plan ready for execution."""
    scan_id: str
    mode: str  # 'trash' or 'permanent'
    operations: List[ExecutableDeleteOperation]
    stats: Dict[str, Any] = field(default_factory=dict)
    policy: Dict[str, Any] = field(default_factory=dict)
    source: str = "review_flow"

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
    Owns side-effects: execution + dual audit write-through.
    """

    def __init__(
        self,
        deletion_engine: Optional[DeletionEngine] = None,
        history_store: Optional[HistoryStore] = None,
        deletion_gate: Optional[DeletionGate] = None,
    ) -> None:
        self._deletion_engine = deletion_engine or DeletionEngine()
        self._history = history_store or HistoryStore()
        # gate is owned by this pipeline instance — Decision A.
        self.gate: DeletionGate = deletion_gate or DeletionGate()

        self._logger = None
        try:
            from ..services.logger import Logger  # type: ignore
            self._logger = Logger()
        except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
            self._logger = None

    def _log(self, message: str, level: str = "info") -> None:
        if self._logger:
            try:
                getattr(self._logger, level, self._logger.info)(message)
            except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
                pass

    # ------------------------------------------------------------------
    # Build plan helpers (validate + enrich)
    # ------------------------------------------------------------------

    def _check_hardlink(self, path: Path, errors: List[str], label: str) -> bool:
        """Returns True if the path should be blocked (and appends to errors)."""
        reason = should_block_delete(
            path,
            hardlink_policy=HardlinkPolicy(allow_hardlink_deletes=False),
        )
        if reason and reason != "missing":
            errors.append(f"{label}: blocked ({reason}): {path}")
            return True
        return False

    def build_delete_plan(self, deletion_plan: Dict[str, Any]) -> ExecutableDeletePlan:
        """
        Validate keeper invariants, check hardlink policy, enrich metadata.

        Expected UI DeletionPlan:
        {
          "scan_id": "...",
          "policy": {"mode":"trash"|"permanent", ...},
          "groups": [{"group_index":0,"keep":"...","delete":["..."]}, ...],
          "source": "review_flow" (optional; legacy "review_page" accepted),
        }
        """
        scan_id = str(deletion_plan.get("scan_id", "unknown"))
        policy = dict(deletion_plan.get("policy", {}) or {})
        mode = str(policy.get("mode", "trash"))
        source = str(deletion_plan.get("source", "review_flow"))
        groups = list(deletion_plan.get("groups", []) or [])

        self._log(f"Building delete plan scan={scan_id} mode={mode} groups={len(groups)}")

        operations: List[ExecutableDeleteOperation] = []
        errors: List[str] = []

        for group_data in groups:
            try:
                group_idx = int(group_data.get("group_index", 0) or 0)
            except (ValueError, TypeError):
                group_idx = 0

            keep_path_str = str(group_data.get("keep", "") or "")
            delete_paths = list(group_data.get("delete", []) or [])

            keep_path = Path(keep_path_str) if keep_path_str else None
            if not keep_path or not keep_path.exists():
                errors.append(f"Group {group_idx}: keep missing: {keep_path_str}")
                continue

            try:
                keep_resolved = keep_path.resolve()
            except OSError:
                keep_resolved = keep_path

            for del_path_str in delete_paths:
                del_path_str = str(del_path_str)
                if not del_path_str:
                    continue
                del_path = Path(del_path_str)

                if not del_path.exists():
                    continue

                try:
                    del_resolved = del_path.resolve()
                except OSError:
                    del_resolved = del_path

                if keep_resolved == del_resolved:
                    errors.append(f"Group {group_idx}: keeper included in delete: {del_path_str}")
                    continue

                # C-3: hardlink protection at plan-build time.
                if self._check_hardlink(del_path, errors, f"Group {group_idx}"):
                    continue

                try:
                    st = del_path.stat()
                    size = int(st.st_size or 0)
                    mtime = float(st.st_mtime or 0.0)
                except OSError:
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

        if errors:
            self._log(f"Deletion plan warnings: {'; '.join(errors)}", level="warning")
        if groups and not operations:
            self._log("Deletion plan: no valid operations", level="error")
            raise ValueError(
                "Deletion plan: no valid operations. "
                "All keep files are missing, all delete targets gone, or all blocked by policy."
            )

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

    def build_explicit_paths_plan(
        self,
        paths: List[str],
        *,
        scan_id: str = "explicit",
        mode: str = "trash",
        source: str = "explicit",
    ) -> ExecutableDeletePlan:
        """
        Build a plan from a flat list of paths with no group/keeper invariant
        (used when user has explicitly marked individual files).
        Still enforces hardlink policy and enriches metadata.
        """
        operations: List[ExecutableDeleteOperation] = []
        errors: List[str] = []

        for raw in paths:
            del_path = Path(raw)
            if not del_path.exists():
                continue
            if self._check_hardlink(del_path, errors, "explicit"):
                continue
            try:
                st = del_path.stat()
                size = int(st.st_size or 0)
                mtime = float(st.st_mtime or 0.0)
            except OSError:
                size = 0
                mtime = 0.0
            operations.append(
                ExecutableDeleteOperation(
                    path=del_path,
                    size=size,
                    group_index=0,
                    kept_path=None,
                    mtime=mtime,
                )
            )

        if errors:
            self._log(f"Explicit paths plan warnings: {'; '.join(errors)}", level="warning")

        stats = {
            "groups": 0,
            "files": len(operations),
            "bytes": sum(int(op.size or 0) for op in operations),
            "validated_at": datetime.now().isoformat(),
        }
        return ExecutableDeletePlan(
            scan_id=scan_id,
            mode=mode,
            operations=operations,
            stats=stats,
            policy={"mode": mode},
            source=source,
        )

    # ------------------------------------------------------------------
    # Execute plan (engine) + write dual audit — AUTHORITATIVE
    # ------------------------------------------------------------------

    def execute_delete_plan(
        self,
        plan: ExecutableDeletePlan,
        progress_cb: Optional[Callable[[int, int, str], bool]] = None,
    ) -> DeletionResult:
        """
        Execute validated deletion plan, then record dual audit trail.

        For permanent mode: caller MUST have called self.gate.issue_token() first
        and embedded the token in plan.policy["token"].

        progress_cb(current, total, current_file_name) -> bool (True = continue)
        """
        self._log(f"Executing delete plan scan={plan.scan_id} mode={plan.mode} ops={plan.total_files}")

        # C-1/Decision A: permanent deletions verified via this pipeline's own gate.
        if str(plan.mode) == "permanent":
            token = None
            try:
                token = (plan.policy or {}).get("token")
            except (AttributeError, TypeError):
                token = None
            # assert_allowed() verifies + consumes the token atomically.
            self.gate.assert_allowed(validation_mode=True, token=token)

        del_policy = DeletionPolicy.PERMANENT if plan.mode == "permanent" else DeletionPolicy.TRASH
        request = DeletionRequest(
            policy=del_policy,
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
                    "kept_path": str(op.kept_path) if op.kept_path else None,
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

        # Dual audit (Decision C).
        self._record_dual_audit(
            deleted_paths=[str(p) for p in batch.deleted],
            mode=plan.mode,
            scan_id=plan.scan_id,
            source=plan.source or "review_flow",
            groups=int(plan.stats.get("groups", 0) or 0),
            failed=len(result.failed),
            bytes_reclaimed=result.bytes_reclaimed,
            policy=plan.policy or {"mode": plan.mode},
            details=details,
        )

        self._log(
            f"Deletion complete scan={plan.scan_id} deleted={len(result.deleted)} "
            f"failed={len(result.failed)} bytes={result.bytes_reclaimed}"
        )
        return result

    def _record_dual_audit(
        self,
        *,
        deleted_paths: List[str],
        mode: str,
        scan_id: str,
        source: str,
        groups: int,
        failed: int,
        bytes_reclaimed: int,
        policy: Dict[str, Any],
        details: List[Dict[str, Any]],
    ) -> None:
        """Write to both HistoryStore (JSONL) and deletion_history_db (SQLite). Decision C."""
        # 1) HistoryStore JSONL audit.
        try:
            self._history.record_deletion(
                scan_id=scan_id,
                mode=mode,
                groups=groups,
                deleted=len(deleted_paths),
                failed=failed,
                bytes_reclaimed=bytes_reclaimed,
                source=source,
                policy=policy,
                details=details,
            )
        except Exception as e:  # noqa: BLE001
            self._log(f"HistoryStore audit write failed (non-fatal): {e}", level="warning")

        # 2) deletion_history_db SQLite (UI history tab).
        try:
            from cerebro.v2.core.deletion_history_db import log_deletion_event  # type: ignore
            for path_str in deleted_paths:
                try:
                    size = next(
                        (d["bytes"] for d in details if d.get("path") == path_str), 0
                    )
                    log_deletion_event(path_str, int(size or 0), mode)
                except Exception:  # noqa: BLE001
                    pass
        except Exception as e:  # noqa: BLE001
            self._log(f"deletion_history_db audit write failed (non-fatal): {e}", level="warning")


# ==============================================================================
# LEGACY COMPATIBILITY SHIMS (v5 scan pipeline) — MC-4: moved here from inline
# ==============================================================================

class PipelineResult:
    """Legacy scan pipeline result placeholder. Do not use in new code."""
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class PipelineEvent:
    """Legacy pipeline event placeholder. Do not use in new code."""
    def __init__(self, name: str = "", payload: dict | None = None):
        self.name = name
        self.payload = payload or {}


class PipelineStats:
    """Legacy pipeline statistics placeholder. Do not use in new code."""
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


def create_default_pipeline():
    """Legacy factory. Returns CerebroPipeline (authoritative implementation)."""
    return CerebroPipeline()


class CancelToken:
    """Legacy cancellation token. Do not use in new code."""

    def __init__(self):
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def is_cancelled(self) -> bool:
        return self._cancelled

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def __call__(self) -> bool:
        return self._cancelled


class PipelineRequest:
    """Legacy pipeline request container. Do not use in new code."""

    def __init__(self, config=None, cancel_token: CancelToken | None = None, progress_cb=None, **kwargs):
        self.config = config
        self.cancel_token = cancel_token or CancelToken()
        self.progress_cb = progress_cb
        for k, v in kwargs.items():
            setattr(self, k, v)


class DeletePlan:
    """Legacy delete plan placeholder. Do not use in new code."""

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)

    def to_executable(self):
        return self


class DeletePlanItem:
    """Legacy delete plan item. Do not use in new code."""

    def __init__(self, path=None, keep: bool | None = None, group_index: int | None = None,
                 score: float | None = None, **kwargs):
        self.path = path
        self.keep = keep
        self.group_index = group_index
        self.score = score
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
