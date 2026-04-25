"""Delete service — wraps DeletionEngine for the Flet UI."""

from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Callable, List, Optional

from cerebro.core.deletion import DeletionEngine, DeletionPolicy, DeletionRequest
from cerebro.engines.base_engine import DuplicateGroup
from cerebro.v2.core.deletion_history_db import log_deletion_event
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
        """Delete files and return (deleted_count, failed_count, bytes_reclaimed)."""
        if not paths:
            return 0, 0, 0

        sizes_by_path: dict[str, int] = {}
        for p in paths:
            try:
                sizes_by_path[str(p)] = Path(p).stat().st_size
            except OSError:
                sizes_by_path[str(p)] = 0

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
        return deleted_n, failed_n, int(result.bytes_reclaimed or 0)

    def delete_and_prune(
        self,
        paths: List[str],
        groups: List[DuplicateGroup],
        policy: DeletionPolicy = DeletionPolicy.TRASH,
    ) -> tuple[List[DuplicateGroup], int, int, int]:
        """Delete files, prune groups, return (new_groups, deleted, failed, bytes)."""
        deleted_n, failed_n, bytes_reclaimed = self.delete_files(paths, policy)
        new_groups = prune_paths_from_groups(groups, paths)
        return new_groups, deleted_n, failed_n, bytes_reclaimed
