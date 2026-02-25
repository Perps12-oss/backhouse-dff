# cerebro/workers/cleanup_worker.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import Signal

from cerebro.core.models import DuplicateItem, DeletionPolicy
from cerebro.services.logger import log_info, log_warning, log_error
from cerebro.workers.base_worker import BaseWorker


@dataclass(slots=True)
class CleanupRequest:
    duplicates: List[DuplicateItem]
    deletion_policy: DeletionPolicy = DeletionPolicy.MOVE_TO_TRASH
    validate_only: bool = False
    scan_id: Optional[str] = None


class CleanupWorker(BaseWorker):
    """
    Fixed:
      - Uses BaseWorker cancellation correctly (check_cancelled)
      - DuplicateItem access corrected (item.file.path)
      - DeletionPolicy values corrected (MOVE_TO_TRASH / DELETE_PERMANENTLY)
      - Emits BaseWorker.progress (int,str) + cleanup_complete(deleted, failed)
    """
    cleanup_complete = Signal(int, int)  # deleted, failed

    def __init__(self, request: CleanupRequest, parent=None):
        super().__init__()
        self.request = request
        self.setParent(parent)
        self._deleted = 0
        self._failed = 0

    def execute(self):
        log_info("[CLEANUP] Starting cleanup job")
        total = max(1, len(self.request.duplicates))

        for i, item in enumerate(self.request.duplicates):
            self.check_cancelled()
            try:
                fpath = Path(item.file.path)
            except Exception:
                # Defensive: malformed item
                self._failed += 1
                continue

            pct = int((i / total) * 100)
            self.update_progress(pct, f"Cleaning: {fpath.name}")

            try:
                if self.request.validate_only:
                    log_info(f"[CLEANUP] Validate-only: {fpath}")
                else:
                    self._delete_path(fpath)
                self._deleted += 1
            except Exception as e:
                self._failed += 1
                log_error(f"[CLEANUP] Failed: {fpath} :: {e}")

        self.update_progress(100, "Cleanup complete.")
        self.cleanup_complete.emit(self._deleted, self._failed)
        log_info(f"[CLEANUP] Finished - Deleted: {self._deleted}, Failed: {self._failed}")
        return {"deleted": self._deleted, "failed": self._failed}

    def _delete_path(self, path: Path) -> None:
        if not path.exists():
            log_warning(f"[CLEANUP] Skipping missing: {path}")
            return

        if self.request.deletion_policy == DeletionPolicy.DELETE_PERMANENTLY:
            path.unlink(missing_ok=True)  # py3.8+ supports missing_ok
            log_info(f"[CLEANUP] Permanently deleted: {path}")
            return

        # MOVE_TO_TRASH
        try:
            from send2trash import send2trash
        except Exception as e:
            raise RuntimeError("send2trash is required for MOVE_TO_TRASH policy") from e

        send2trash(str(path))
        log_info(f"[CLEANUP] Moved to trash: {path}")
