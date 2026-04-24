"""Delete service — wraps DeletionEngine for the Flet UI.

Provides a simple API the Flet pages can call to delete files with
confirmation dialogs and state updates.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, List, Optional

from cerebro.core.deletion import DeletionEngine, DeletionPolicy
from cerebro.engines.base_engine import DuplicateGroup
from cerebro.v2.state.groups_prune import prune_paths_from_groups

_log = logging.getLogger(__name__)


class DeleteService:
    """High-level delete orchestration for the UI layer."""

    def __init__(self) -> None:
        self._engine = DeletionEngine()

    def delete_files(
        self,
        paths: List[str],
        policy: DeletionPolicy = DeletionPolicy.TRASH,
        progress_cb: Optional[Callable[[int, int, str], None]] = None,
    ) -> tuple[int, int, int]:
        """Delete files and return (deleted, failed, bytes_reclaimed).

        Args:
            paths: File paths to delete.
            policy: TRASH (send2trash) or PERMANENT (irreversible).
            progress_cb: Optional callback (current, total, filename).
        """
        if not paths:
            return 0, 0, 0

        from cerebro.core.deletion import ExecutableDeletePlan, SingleDeleteOp

        ops = [
            SingleDeleteOp(path=Path(p), size=0, policy=policy)
            for p in paths
        ]
        plan = ExecutableDeletePlan(
            operations=ops,
            policy=policy,
            created_at="",
            token="",
        )

        def _progress(i: int, total: int, name: str) -> bool:
            if progress_cb:
                progress_cb(i, total, name)
            return True  # continue

        result = self._engine.execute_plan(plan, progress_cb=_progress)
        return result.deleted, result.failed, result.bytes_reclaimed

    def delete_and_prune(
        self,
        paths: List[str],
        groups: List[DuplicateGroup],
        policy: DeletionPolicy = DeletionPolicy.TRASH,
    ) -> tuple[List[DuplicateGroup], int, int, int]:
        """Delete files, prune groups, return (new_groups, deleted, failed, bytes)."""
        deleted, failed, bytes_reclaimed = self.delete_files(paths, policy)
        new_groups = prune_paths_from_groups(groups, paths)
        return new_groups, deleted, failed, bytes_reclaimed
