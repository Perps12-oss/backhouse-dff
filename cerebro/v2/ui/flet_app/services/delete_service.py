"""Delete service — hybrid deletion orchestration for the Flet UI.

TRASH mode:  validate via pipeline, execute via managed-trash (undo stack preserved, H-4).
PERMANENT mode: full gate + CerebroPipeline.execute_delete_plan path.

Decision B (hybrid model):
  - _delete_to_managed_trash() owns the undo stack and rollback (H-4).
  - Permanent deletes go through self._pipeline.execute_delete_plan().
  - Both paths write dual audit via CerebroPipeline._record_dual_audit().

Decision A (gate lifecycle):
  - self._pipeline owns the DeletionGate.
  - For permanent deletes the confirm dialog calls self._pipeline.gate.issue_token().

MC-5: _trash_history is an instance field (not a module global) so test fixtures
  can clear it by constructing a fresh DeleteService.
"""

from __future__ import annotations

import os
import shutil
import stat
import sys
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional, Tuple
import logging

from cerebro.core.deletion import DeletionPolicy
from cerebro.core.pipeline import CerebroPipeline
from cerebro.engines.base_engine import DuplicateGroup
from cerebro.v2.state.groups_prune import prune_paths_from_groups

_log = logging.getLogger(__name__)

_MAX_TRASH_HISTORY = 5


@dataclass
class TrashUndoTransaction:
    """Represents one managed-trash delete batch that can be undone."""
    tx_id: str
    moved: list[tuple[str, str]]  # (src, dst)
    created_at: float


@dataclass
class DeleteFilesResult:
    """Outcome of a delete batch (managed trash or engine policy)."""
    deleted_count: int
    failed_count: int
    bytes_reclaimed: int
    deleted_paths: List[str]
    failures: List[Tuple[str, str]]


class DeleteService:
    """High-level delete orchestration for the UI layer."""

    def __init__(self, pipeline: Optional[CerebroPipeline] = None) -> None:
        # Decision A: one pipeline = one gate for this service's lifetime.
        self._pipeline: CerebroPipeline = pipeline or CerebroPipeline()
        # MC-5: instance-scoped undo stack — no module global.
        self._trash_history: list[TrashUndoTransaction] = []

    @property
    def pipeline(self) -> CerebroPipeline:
        """Expose pipeline so callers can call pipeline.gate.issue_token() for permanent."""
        return self._pipeline

    # ------------------------------------------------------------------
    # Public API (unchanged signature — Decision B)
    # ------------------------------------------------------------------

    def delete_files(
        self,
        paths: List[str],
        policy: DeletionPolicy = DeletionPolicy.TRASH,
        progress_cb: Optional[Callable[[int, int, str], None]] = None,
    ) -> DeleteFilesResult:
        """Delete files and return structured counts, paths, and per-path failure reasons."""
        if not paths:
            return DeleteFilesResult(0, 0, 0, [], [])

        existing_paths: list[str] = []
        sizes_by_path: dict[str, int] = {}
        failures: list[tuple[str, str]] = []

        for p in paths:
            try:
                pp = Path(p)
                if not pp.exists():
                    sizes_by_path[str(p)] = 0
                    failures.append((str(p), "File not found"))
                    continue
                sizes_by_path[str(p)] = pp.stat().st_size
                existing_paths.append(str(p))
            except OSError as exc:
                sizes_by_path[str(p)] = 0
                failures.append((str(p), str(exc) or "Path not accessible"))

        missing_count = len(paths) - len(existing_paths) - len(failures) + len(failures)
        # recalculate: missing = total - (existing + already-failed paths that don't exist)
        missing_count = len(paths) - len(existing_paths)

        if not existing_paths:
            return DeleteFilesResult(0, len(paths), 0, [], failures)

        if policy == DeletionPolicy.TRASH:
            plan = self._pipeline.build_explicit_paths_plan(
                existing_paths,
                scan_id="delete_service",
                mode="trash",
                source="delete_service",
            )
            validated_paths = [str(op.path) for op in plan.operations]
            blocked = set(existing_paths) - set(validated_paths)
            for bp in sorted(blocked):
                failures.append((bp, "Blocked by deletion policy (hardlink/symlink guard)"))
            deleted_paths, move_failures = self._delete_to_managed_trash(
                validated_paths, sizes_by_path, progress_cb
            )
            failures.extend(move_failures)
            deleted_n = len(deleted_paths)
            failed_n = max(0, len(existing_paths) - deleted_n) + missing_count
            reclaimed = int(sum(sizes_by_path.get(p, 0) for p in deleted_paths))
            # Dual audit for managed-trash path.
            self._pipeline._record_dual_audit(
                deleted_paths=deleted_paths,
                mode="trash",
                scan_id="delete_service",
                source="delete_service",
                groups=0,
                failed=len(move_failures),
                bytes_reclaimed=reclaimed,
                policy={"mode": "trash"},
                details=[{"path": p, "bytes": sizes_by_path.get(p, 0), "status": "deleted",
                          "group_index": 0, "kept_path": None, "mtime": 0.0, "error": None}
                         for p in deleted_paths],
            )
            return DeleteFilesResult(deleted_n, failed_n, reclaimed, deleted_paths, failures)

        # PERMANENT: issue token on this service's pipeline gate, then execute.
        # C-2: token must be issued here so UI callers don't have to plumb gate access.
        token = self._pipeline.gate.issue_token(reason="delete_service_permanent")
        plan = self._pipeline.build_explicit_paths_plan(
            existing_paths,
            scan_id="delete_service_permanent",
            mode="permanent",
            source="delete_service",
        )
        import dataclasses as _dc
        plan = _dc.replace(plan, policy={**(plan.policy or {}), "token": token})
        result = self._pipeline.execute_delete_plan(plan)
        deleted_paths_p = [str(p) for p in result.deleted]
        for fp, msg in result.failed:
            failures.append((str(fp), msg or "Deletion failed"))
        failed_n = len(result.failed) + missing_count
        return DeleteFilesResult(
            len(result.deleted), failed_n, int(result.bytes_reclaimed or 0),
            deleted_paths_p, failures,
        )

    def delete_and_prune(
        self,
        paths: List[str],
        groups: List[DuplicateGroup],
        policy: DeletionPolicy = DeletionPolicy.TRASH,
        progress_cb: Optional[Callable[[int, int, str], None]] = None,
    ) -> tuple[List[DuplicateGroup], DeleteFilesResult]:
        """Delete files, prune groups, return (new_groups, delete result). Signature unchanged."""
        dfr = self.delete_files(paths, policy, progress_cb)
        new_groups = prune_paths_from_groups(groups, dfr.deleted_paths)
        return new_groups, dfr

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

                dfr = self.delete_files(paths, policy, progress_cb=_progress)
                new_groups = prune_paths_from_groups(groups, dfr.deleted_paths)
                if done_callback:
                    done_callback(new_groups, dfr.deleted_count, dfr.failed_count, dfr.bytes_reclaimed, None)
            except Exception as exc:  # pragma: no cover
                _log.exception("delete_and_prune_async failed")
                if done_callback:
                    done_callback(groups, 0, 0, 0, exc)

        threading.Thread(target=_worker, daemon=True).start()

    def undo_last_trash_delete(self) -> tuple[bool, int]:
        """Restore files from the last managed-trash transaction (instance method — MC-5)."""
        tx = self._trash_history[-1] if self._trash_history else None
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
                self._trash_history.pop()
            except Exception:
                pass
        return ok, restored

    # ------------------------------------------------------------------
    # Internal managed-trash implementation (H-4: rollback on failure)
    # ------------------------------------------------------------------

    def _managed_trash_root_for(self, src: Path, tx_id: str) -> Path:
        """Return the managed-trash tx dir on the SAME volume as ``src`` when possible.

        A same-volume move is an atomic rename: fast, and immune to the WinError 5
        a read-only source file triggers when a cross-drive ``shutil.move`` tries to
        ``unlink`` the original after copying it. Falls back to the home-volume trash
        when a per-volume dir can't be created (e.g. read-only volume) or on POSIX,
        where a mount point isn't reliably derivable from a path.
        """
        home_root = Path.home() / ".cerebro" / "trash" / "managed" / tx_id

        # Same volume as home → no need to scatter trash dirs; use the home trash.
        try:
            if src.stat().st_dev == Path.home().stat().st_dev:
                home_root.mkdir(parents=True, exist_ok=True)
                return home_root
        except OSError:
            pass

        # Different volume: on Windows place trash on the source drive so the move
        # stays same-volume. POSIX mounts fall through to the home trash.
        if sys.platform == "win32" and src.drive:
            candidate = Path(src.drive + "\\") / ".cerebro" / "trash" / "managed" / tx_id
            try:
                candidate.mkdir(parents=True, exist_ok=True)
                if candidate.stat().st_dev == src.stat().st_dev:
                    return candidate
            except OSError:
                pass

        home_root.mkdir(parents=True, exist_ok=True)
        return home_root

    @staticmethod
    def _move_with_readonly_retry(src: Path, dst: Path) -> None:
        """``shutil.move`` with a one-shot Windows retry that clears the read-only
        attribute, which otherwise makes the source ``unlink`` fail with WinError 5."""
        try:
            shutil.move(str(src), str(dst))
            return
        except PermissionError:
            # WinError 5 on a read-only file. Clearing write bits is destructive on
            # POSIX (strips group/other), so only do this on Windows.
            if sys.platform != "win32":
                raise
            os.chmod(src, stat.S_IWRITE)
            _log.info("Cleared read-only attribute and retrying trash move: %s", src)
            shutil.move(str(src), str(dst))

    def _delete_to_managed_trash(
        self,
        paths: list[str],
        sizes_by_path: dict[str, int],
        progress_cb: Optional[Callable[[int, int, str], None]],
    ) -> tuple[list[str], list[tuple[str, str]]]:
        """Move files to a managed-trash dir with rollback on mid-batch failure.

        The trash dir is placed on the same volume as each source file when possible
        (see ``_managed_trash_root_for``) so the move is an atomic rename.
        """
        tx_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")

        moved: list[tuple[str, str]] = []
        deleted_paths: list[str] = []
        failures: list[tuple[str, str]] = []
        total = len(paths)

        for i, raw in enumerate(paths):
            src = Path(raw)
            if progress_cb:
                try:
                    progress_cb(i + 1, total, src.name)
                except Exception:
                    pass

            if not src.exists():
                failures.append((str(src), "File disappeared before move"))
                continue

            try:
                tx_root = self._managed_trash_root_for(src, tx_id)
                rel = src.drive.replace(":", "") + src.as_posix().replace(":", "")
                safe_rel = rel.lstrip("/").replace("..", "_")
                dst = tx_root / safe_rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                counter = 0
                while dst.exists():
                    counter += 1
                    dst = dst.with_name(f"{dst.stem}__dup{counter}{dst.suffix}")
                self._move_with_readonly_retry(src, dst)
                moved.append((str(src), str(dst)))
                deleted_paths.append(str(src))
            except (OSError, shutil.Error) as exc:
                # H-4: rollback all moves so far before re-raising.
                _log.error("Managed trash move failed for %s: %s — rolling back %d moves", src, exc, len(moved))
                for mv_src, mv_dst in reversed(moved):
                    try:
                        mv_dst_p = Path(mv_dst)
                        mv_src_p = Path(mv_src)
                        if mv_dst_p.exists():
                            mv_src_p.parent.mkdir(parents=True, exist_ok=True)
                            shutil.move(str(mv_dst_p), str(mv_src_p))
                    except (OSError, shutil.Error) as rb_exc:
                        # M-2: rollback failed — file is orphaned in trash dir.
                        # Report it in failures so the user can manually recover.
                        _log.error(
                            "Rollback failed for %s → %s: %s — file is orphaned in trash at %s",
                            mv_src, mv_dst, rb_exc, mv_dst,
                        )
                        failures.append((
                            mv_src,
                            f"Rollback failed — file orphaned in trash at {mv_dst}: {rb_exc}",
                        ))
                failures.append((str(src), str(exc) or "Move to managed storage failed"))
                # Return partial results — rolled back files are no longer deleted.
                return [], failures

        if moved:
            self._trash_history.append(
                TrashUndoTransaction(tx_id=tx_id, moved=moved, created_at=datetime.now().timestamp())
            )
            while len(self._trash_history) > _MAX_TRASH_HISTORY:
                self._trash_history.pop(0)

        return deleted_paths, failures
