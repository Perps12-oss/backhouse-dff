"""
CEREBRO Deletion Engine - Target Architecture (Authoritative)
Executes validated ExecutableDeletePlan operations with policy adapters.

- Trash deletion uses send2trash if available; otherwise uses ~/.cerebro/trash fallback
  with a manifest entry at ~/.cerebro/trash/manifest.jsonl (M-2).
- Permanent deletion uses os.remove / shutil.rmtree with TOCTOU-safe error handling (M-3).
- delete_one() enforces hardlink policy via should_block_delete() (C-3).
- Engine exposes execute_plan(plan, progress_cb) -> BatchDeletionResult
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import sys

from cerebro.core.fs_policy import HardlinkPolicy, should_block_delete

_log = logging.getLogger(__name__)

_FALLBACK_MANIFEST = Path.home() / ".cerebro" / "trash" / "manifest.jsonl"


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
    # Set True only for EmptyFolderEngine / SimilarFolderEngine directory plans.
    # Never set from the generic file-deletion path (C-3).
    allow_directory_delete: bool = False


@dataclass(frozen=True)
class BatchDeletionResult:
    """Batch execution result (plan-level)."""
    scan_id: str
    mode: str  # 'trash' | 'permanent'
    deleted: List[Path]
    failed: List[Tuple[Path, str]]
    bytes_reclaimed: int
    timestamp: float = field(default_factory=lambda: datetime.now().timestamp())


def _write_fallback_manifest(original_path: str, dest_path: str, size: int) -> None:
    """Append one JSON line to the fallback trash manifest (M-2)."""
    try:
        _FALLBACK_MANIFEST.parent.mkdir(parents=True, exist_ok=True)
        entry = json.dumps({
            "id": str(uuid.uuid4()),
            "original_path": original_path,
            "dest_path": dest_path,
            "timestamp": datetime.now().timestamp(),
            "size": int(size),
        })
        with open(_FALLBACK_MANIFEST, "a", encoding="utf-8") as fh:
            fh.write(entry + "\n")
    except OSError as exc:
        # Must never abort a deletion; surface incomplete undo coverage.
        _log.warning(
            "fallback trash manifest write failed for %s -> %s: %s",
            original_path,
            dest_path,
            exc,
        )


class DeletionPort:
    """Port interface for deletion operations."""

    def can_handle(self, policy: DeletionPolicy) -> bool:
        raise NotImplementedError

    def delete(self, path: Path, request: DeletionRequest) -> SingleDeletionResult:
        raise NotImplementedError


class TrashDeletionAdapter(DeletionPort):
    """Moves files to system trash/recycle bin; fallback to ~/.cerebro/trash with manifest."""

    def __init__(self) -> None:
        self._send2trash_available = self._check_send2trash()

    def _check_send2trash(self) -> bool:
        try:
            import send2trash  # noqa: F401
            return True
        except ImportError:
            return False
        except Exception as exc:
            # L-3: unexpected errors (e.g. broken .so, permission issues) are
            # real failures worth surfacing — not silently swallowed.
            _log.warning("send2trash import failed unexpectedly: %s — falling back to managed trash", exc)
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
                _write_fallback_manifest(str(path), str(dest), size)

            return SingleDeletionResult(
                success=True,
                path=path,
                policy=request.policy,
                bytes_reclaimed=size,
            )
        except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError) as e:
            return SingleDeletionResult(
                success=False,
                path=path,
                policy=request.policy,
                error=str(e),
            )


class PermanentDeletionAdapter(DeletionPort):
    """Permanently deletes files only (C-1: never auto-escalates to shutil.rmtree).

    Directory deletion is handled exclusively by DirectoryDeletionAdapter, which
    requires allow_directory_delete=True on the DeletionRequest.
    """

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

        # C-1: never auto-escalate to shutil.rmtree. If the path is a directory
        # but allow_directory_delete was not set, block it here.
        if path.is_dir():
            return SingleDeletionResult(
                success=False,
                path=path,
                policy=request.policy,
                error="is_directory: use DirectoryDeletionAdapter for directory deletion",
            )

        try:
            size = path.stat().st_size
            os.remove(path)
            return SingleDeletionResult(
                success=True,
                path=path,
                policy=request.policy,
                bytes_reclaimed=size,
            )
        except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError) as e:
            return SingleDeletionResult(
                success=False,
                path=path,
                policy=request.policy,
                error=str(e),
            )


class DirectoryDeletionAdapter(DeletionPort):
    """Deletes directory trees when allow_directory_delete is True (C-3).

    PERMANENT: shutil.rmtree. TRASH: same send2trash / managed-trash path as files.
    Used by EmptyFolderEngine and SimilarFolderEngine plans.
    """

    def __init__(self) -> None:
        self._trash_adapter = TrashDeletionAdapter()

    def can_handle(self, policy: DeletionPolicy) -> bool:
        return policy in (DeletionPolicy.PERMANENT, DeletionPolicy.TRASH)

    def delete(self, path: Path, request: DeletionRequest) -> SingleDeletionResult:
        if not getattr(request, "allow_directory_delete", False):
            return SingleDeletionResult(
                success=False,
                path=path,
                policy=request.policy,
                error="directory deletion not permitted without allow_directory_delete=True",
            )
        if not path.exists():
            return SingleDeletionResult(
                success=False,
                path=path,
                policy=request.policy,
                error="Directory does not exist",
            )
        if not path.is_dir():
            return SingleDeletionResult(
                success=False,
                path=path,
                policy=request.policy,
                error="Path is not a directory",
            )
        if request.policy == DeletionPolicy.TRASH:
            return self._trash_adapter.delete(path, request)
        try:
            shutil.rmtree(path)
            return SingleDeletionResult(
                success=True,
                path=path,
                policy=request.policy,
                bytes_reclaimed=0,
            )
        except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError) as e:
            return SingleDeletionResult(
                success=False,
                path=path,
                policy=request.policy,
                error=str(e),
            )


_WINDOWS_NLINK_THRESHOLD = 3  # NTFS baseline; see platform_hardlink_threshold()
_DEFAULT_NLINK_THRESHOLD = 3 if sys.platform == "win32" else 1


class DeletionEngine:
    """
    Core deletion engine.
    Executes validated plans. Owns deletion semantics (not the UI, not the pipeline).
    delete_one() enforces hardlink + directory policy before delegating to adapters.
    """

    def __init__(self) -> None:
        self._adapters: List[DeletionPort] = [
            TrashDeletionAdapter(),
            DirectoryDeletionAdapter(),
            PermanentDeletionAdapter(),
        ]

    def delete_one(self, path: Path, request: DeletionRequest) -> SingleDeletionResult:
        """Delete a single path, enforcing policy first (C-3, H-7)."""
        allow_dir = getattr(request, "allow_directory_delete", False)
        block_reason = should_block_delete(
            path,
            hardlink_policy=HardlinkPolicy(allow_hardlink_deletes=False),
            allow_directory_delete=allow_dir,
            hardlink_nlink_threshold=_DEFAULT_NLINK_THRESHOLD,
        )
        if block_reason is not None:
            if block_reason == "missing":
                _log.debug("delete_one skipped (missing): %s", path)
            else:
                _log.warning("delete_one blocked (%s): %s", block_reason, path)
            return SingleDeletionResult(
                success=False,
                path=path,
                policy=request.policy,
                error=block_reason,
            )

        # Route directories to DirectoryDeletionAdapter; files to file adapters.
        if path.is_dir():
            return self._adapters[1].delete(path, request)  # DirectoryDeletionAdapter

        for adapter in self._adapters:
            if isinstance(adapter, DirectoryDeletionAdapter):
                continue  # files never go through the directory adapter
            if adapter.can_handle(request.policy):
                res = adapter.delete(path, request)
                if res.success:
                    _log.info("Deleted [%s]: %s", request.policy.value, path)
                elif res.error == "File does not exist":
                    # Race: file vanished between block check and delete — not a real error.
                    _log.debug("delete_one: file disappeared before delete: %s", path)
                else:
                    _log.warning("Failed delete [%s]: %s — %s", request.policy.value, path, res.error)
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
            current_file = ""
            try:
                current_file = str(getattr(op, "path", op))
            except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
                current_file = ""

            if progress_cb:
                try:
                    if not progress_cb(i + 1, total, Path(current_file).name):
                        _log.info("Deletion cancelled by progress callback at op %d/%d", i + 1, total)
                        break
                except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
                    pass

            path = getattr(op, "path", None)
            if path is None:
                try:
                    path = Path(op)
                except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
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
