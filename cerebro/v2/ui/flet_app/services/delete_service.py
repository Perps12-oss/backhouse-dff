"""Delete service — wraps DeletionEngine for the Flet UI."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import logging
from pathlib import Path
from types import SimpleNamespace
import shutil
import threading
from typing import Callable, List, Optional

from cerebro.core.deletion import DeletionEngine, DeletionPolicy, DeletionRequest
from cerebro.engines.base_engine import DuplicateGroup
from cerebro.v2.core.deletion_history_db import log_deletion_event
from cerebro.v2.state.groups_prune import prune_paths_from_groups

_log = logging.getLogger(__name__)


@dataclass
class TrashUndoTransaction:
    """Represents one managed-trash delete batch that can be undone."""

    tx_id: str
    moved: list[tuple[str, str]]  # (src, dst)
    created_at: float


_TRASH_HISTORY: list[TrashUndoTransaction] = []
_MAX_TRASH_HISTORY = 5


class DeleteService:
    """High-level delete orchestration for the UI layer."""

    def __init__(self) -> None:
        self._engine = DeletionEngine()

    def delete_files(
        self,
        paths: List[str],
        policy: DeletionPolicy = DeletionPolicy.TRASH,
        progress_cb: Optional[Callable[[int, int, str], None]] = None,
    ) -> tuple[int, int, int, list[str]]:
        """Delete files and return (deleted_count, failed_count, bytes_reclaimed, deleted_paths)."""
        if not paths:
            return 0, 0, 0, []

        sizes_by_path: dict[str, int] = {}
        for p in paths:
            try:
                sizes_by_path[str(p)] = Path(p).stat().st_size
            except OSError:
                sizes_by_path[str(p)] = 0

        if policy == DeletionPolicy.TRASH:
            deleted_paths = self._delete_to_managed_trash(paths, sizes_by_path, progress_cb)
            deleted_n = len(deleted_paths)
            failed_n = max(0, len(paths) - deleted_n)
            reclaimed = int(sum(sizes_by_path.get(p, 0) for p in deleted_paths))
            return deleted_n, failed_n, reclaimed, deleted_paths

        operations = [SimpleNamespace(path=Path(p)) for p in paths]
        plan = SimpleNamespace(
            scan_id="flet_ui",
            mode=policy.value,
            operations=operations,
        )
        request = DeletionRequest(policy=policy)

        def _progress(i: int, total: int, name: str) -> bool:
            if progress_cb:
                progress_cb(i, total, name)
            return True

        result = self._engine.execute_plan(plan, request=request, progress_cb=_progress)
        deleted_n = len(result.deleted)
        failed_n = len(result.failed)
        mode_tag = policy.value
        for p in result.deleted:
            log_deletion_event(str(p), sizes_by_path.get(str(p), 0), mode_tag)
        deleted_paths = [str(p) for p in result.deleted]
        return deleted_n, failed_n, int(result.bytes_reclaimed or 0), deleted_paths

    def delete_and_prune(
        self,
        paths: List[str],
        groups: List[DuplicateGroup],
        policy: DeletionPolicy = DeletionPolicy.TRASH,
    ) -> tuple[List[DuplicateGroup], int, int, int]:
        """Delete files, prune groups, return (new_groups, deleted, failed, bytes)."""
        deleted_n, failed_n, bytes_reclaimed, deleted_paths = self.delete_files(paths, policy)
        new_groups = prune_paths_from_groups(groups, deleted_paths)
        return new_groups, deleted_n, failed_n, bytes_reclaimed

    def delete_and_prune_async(
        self,
        paths: List[str],
        groups: List[DuplicateGroup],
        policy: DeletionPolicy,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
        done_callback: Optional[Callable[[List[DuplicateGroup], int, int, int, Optional[Exception]], None]] = None,
    ) -> None:
        """Run deletion on a worker thread and report progress/completion callbacks."""
        total = len(paths)

        def _worker() -> None:
            try:
                last_reported = 0
                min_step = max(10, int(total * 0.05)) if total > 0 else 1

                def _progress(i: int, t: int, name: str) -> None:
                    nonlocal last_reported
                    if progress_callback is None:
                        return
                    if i >= t or (i - last_reported) >= min_step:
                        last_reported = i
                        progress_callback(i, t, name)

                deleted_n, failed_n, bytes_reclaimed, deleted_paths = self.delete_files(
                    paths,
                    policy,
                    progress_cb=_progress,
                )
                new_groups = prune_paths_from_groups(groups, deleted_paths)
                if done_callback:
                    done_callback(new_groups, deleted_n, failed_n, bytes_reclaimed, None)
            except Exception as exc:  # pragma: no cover - defensive
                _log.exception("delete_and_prune_async failed")
                if done_callback:
                    done_callback(groups, 0, 0, 0, exc)

        threading.Thread(target=_worker, daemon=True).start()

    @classmethod
    def undo_last_trash_delete(cls) -> tuple[bool, int]:
        """Restore files from the last managed-trash transaction."""
        tx = _TRASH_HISTORY[-1] if _TRASH_HISTORY else None
        if tx is None or not tx.moved:
            return False, 0

        restored = 0
        ok = True
        for src, dst in reversed(tx.moved):
            src_p = Path(src)
            dst_p = Path(dst)
            try:
                if dst_p.exists():
                    src_p.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(dst_p), str(src_p))
                    restored += 1
            except (OSError, shutil.Error):
                ok = False

        if ok:
            try:
                _TRASH_HISTORY.pop()
            except Exception:
                pass
        return ok, restored

    def _delete_to_managed_trash(
        self,
        paths: list[str],
        sizes_by_path: dict[str, int],
        progress_cb: Optional[Callable[[int, int, str], None]],
    ) -> list[str]:
        trash_root = Path.home() / ".cerebro" / "trash" / "managed"
        trash_root.mkdir(parents=True, exist_ok=True)
        tx_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        tx_root = trash_root / tx_id
        tx_root.mkdir(parents=True, exist_ok=True)

        moved: list[tuple[str, str]] = []
        deleted_paths: list[str] = []
        events_to_log: list[tuple[str, int, str]] = []
        total = len(paths)
        for i, raw in enumerate(paths):
            src = Path(raw)
            if progress_cb:
                try:
                    progress_cb(i + 1, total, src.name)
                except Exception:
                    pass
            if not src.exists():
                continue
            try:
                rel = src.drive.replace(":", "") + src.as_posix().replace(":", "")
                safe_rel = rel.lstrip("/").replace("..", "_")
                dst = tx_root / safe_rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                if dst.exists():
                    dst = dst.with_name(f"{dst.stem}__dup{dst.suffix}")
                shutil.move(str(src), str(dst))
                moved.append((str(src), str(dst)))
                deleted_paths.append(str(src))
                events_to_log.append((str(src), sizes_by_path.get(str(src), 0), DeletionPolicy.TRASH.value))
            except (OSError, shutil.Error):
                _log.exception("Managed trash move failed for %s", src)

        if moved:
            _TRASH_HISTORY.append(TrashUndoTransaction(
                tx_id=tx_id,
                moved=moved,
                created_at=datetime.now().timestamp(),
            ))
            while len(_TRASH_HISTORY) > _MAX_TRASH_HISTORY:
                _TRASH_HISTORY.pop(0)
        for path, size, mode_tag in events_to_log:
            try:
                log_deletion_event(path, size, mode_tag)
            except Exception:
                _log.debug("Failed to log deletion event for %s", path, exc_info=True)
        return deleted_paths
