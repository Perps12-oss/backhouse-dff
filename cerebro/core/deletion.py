"""
CEREBRO Deletion Engine - Target Architecture (Authoritative)
Executes validated ExecutableDeletePlan operations with policy adapters.

- Trash deletion uses send2trash if available; otherwise uses ~/.cerebro/trash fallback
- Permanent deletion uses os.remove / shutil.rmtree
- Engine exposes execute_plan(plan, progress_cb) -> BatchDeletionResult
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import os
import shutil


class DeletionPolicy(Enum):
    TRASH = "trash"
    PERMANENT = "permanent"


@dataclass(frozen=True)
class SingleDeletionResult:
    """Result of a single file deletion attempt."""
    success: bool
    path: Path
    policy: DeletionPolicy
    bytes_reclaimed: int = 0
    error: Optional[str] = None


@dataclass(frozen=True)
class DeletionRequest:
    """Request context for deletion execution."""
    policy: DeletionPolicy
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BatchDeletionResult:
    """Batch execution result (plan-level)."""
    scan_id: str
    mode: str  # 'trash' | 'permanent'
    deleted: List[Path]
    failed: List[Tuple[Path, str]]
    bytes_reclaimed: int
    timestamp: float = field(default_factory=lambda: datetime.now().timestamp())


class DeletionPort:
    """Port interface for deletion operations."""

    def can_handle(self, policy: DeletionPolicy) -> bool:
        raise NotImplementedError

    def delete(self, path: Path, request: DeletionRequest) -> SingleDeletionResult:
        raise NotImplementedError


class TrashDeletionAdapter(DeletionPort):
    """Moves files to system trash/recycle bin; fallback to ~/.cerebro/trash."""

    def __init__(self) -> None:
        self._send2trash_available = self._check_send2trash()

    def _check_send2trash(self) -> bool:
        try:
            import send2trash  # noqa: F401
            return True
        except Exception:
            return False

    def can_handle(self, policy: DeletionPolicy) -> bool:
        return policy == DeletionPolicy.TRASH

    def delete(self, path: Path, request: DeletionRequest) -> SingleDeletionResult:
        if not path.exists():
            return SingleDeletionResult(
                success=False,
                path=path,
                policy=request.policy,
                error="File does not exist",
            )

        try:
            size = path.stat().st_size if path.is_file() else 0

            if self._send2trash_available:
                import send2trash
                send2trash.send2trash(str(path))
            else:
                trash_dir = Path.home() / ".cerebro" / "trash"
                trash_dir.mkdir(parents=True, exist_ok=True)

                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                dest = trash_dir / f"{timestamp}_{path.name}"
                shutil.move(str(path), str(dest))

            return SingleDeletionResult(
                success=True,
                path=path,
                policy=request.policy,
                bytes_reclaimed=size,
            )
        except Exception as e:
            return SingleDeletionResult(
                success=False,
                path=path,
                policy=request.policy,
                error=str(e),
            )


class PermanentDeletionAdapter(DeletionPort):
    """Permanently deletes files/folders."""

    def can_handle(self, policy: DeletionPolicy) -> bool:
        return policy == DeletionPolicy.PERMANENT

    def delete(self, path: Path, request: DeletionRequest) -> SingleDeletionResult:
        if not path.exists():
            return SingleDeletionResult(
                success=False,
                path=path,
                policy=request.policy,
                error="File does not exist",
            )

        try:
            size = path.stat().st_size if path.is_file() else 0

            if path.is_file():
                os.remove(path)
            else:
                shutil.rmtree(path)

            return SingleDeletionResult(
                success=True,
                path=path,
                policy=request.policy,
                bytes_reclaimed=size,
            )
        except Exception as e:
            return SingleDeletionResult(
                success=False,
                path=path,
                policy=request.policy,
                error=str(e),
            )


class DeletionEngine:
    """
    Core deletion engine.
    Executes validated plans. Owns deletion semantics (not the UI, not the pipeline).
    """

    def __init__(self) -> None:
        self._adapters: List[DeletionPort] = [
            TrashDeletionAdapter(),
            PermanentDeletionAdapter(),
        ]
        self._logger = None
        try:
            # optional logger (non-fatal)
            from ..services.logger import Logger  # type: ignore
            self._logger = Logger()
        except Exception:
            self._logger = None

    def delete_one(self, path: Path, request: DeletionRequest) -> SingleDeletionResult:
        """Delete a single path via adapter based on policy."""
        for adapter in self._adapters:
            if adapter.can_handle(request.policy):
                res = adapter.delete(path, request)
                if self._logger:
                    if res.success:
                        self._logger.info(f"Deleted [{request.policy.value}]: {path}")
                    else:
                        self._logger.warning(f"Failed delete [{request.policy.value}]: {path} - {res.error}")
                return res

        return SingleDeletionResult(
            success=False,
            path=path,
            policy=request.policy,
            error=f"No adapter for policy: {request.policy.value}",
        )

    def execute_plan(
        self,
        plan: Any,
        *,
        request: DeletionRequest,
        progress_cb: Optional[Callable[[int, int, str], bool]] = None,
    ) -> BatchDeletionResult:
        """
        Execute a validated plan with optional progress callback.
        plan must have: scan_id, mode, operations (each op has .path and .size)
        """
        scan_id = getattr(plan, "scan_id", "unknown")
        mode = getattr(plan, "mode", request.policy.value)
        operations = getattr(plan, "operations", None)

        if operations is None and isinstance(plan, dict):
            operations = plan.get("operations", [])
        if not operations:
            return BatchDeletionResult(
                scan_id=scan_id,
                mode=str(mode),
                deleted=[],
                failed=[],
                bytes_reclaimed=0,
            )

        deleted: List[Path] = []
        failed: List[Tuple[Path, str]] = []
        bytes_reclaimed = 0

        total = len(operations)

        for i, op in enumerate(operations):
            # cancellation / progress
            current_file = ""
            try:
                current_file = str(getattr(op, "path", op))
            except Exception:
                current_file = ""

            if progress_cb:
                try:
                    if not progress_cb(i + 1, total, Path(current_file).name):
                        if self._logger:
                            self._logger.info("Deletion cancelled by user")
                        break
                except Exception:
                    # never allow UI callback to crash engine
                    pass

            path = getattr(op, "path", None)
            if path is None:
                try:
                    path = Path(op)
                except Exception:
                    continue

            res = self.delete_one(Path(path), request)
            if res.success:
                deleted.append(res.path)
                bytes_reclaimed += int(res.bytes_reclaimed or 0)
            else:
                failed.append((res.path, res.error or "Unknown error"))

        return BatchDeletionResult(
            scan_id=str(scan_id),
            mode=str(mode),
            deleted=deleted,
            failed=failed,
            bytes_reclaimed=bytes_reclaimed,
        )
