# path: cerebro/workers/delete_worker.py
from __future__ import annotations

import traceback
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

from PySide6.QtCore import QThread, Signal

from cerebro.core.models import PipelineRequest, PipelineMode, DeletionPolicy


_DELETE_PHASE_PCT = {
    "confirm_delete": 8,
    "delete": 80,
    "record": 95,
    "complete": 100,
    "failed": 0,
    "cancelled": 0,
}


@dataclass(slots=True)
class DeleteRequest:
    scan_id: str
    deletion_policy: DeletionPolicy = DeletionPolicy.MOVE_TO_TRASH
    require_explicit_confirmation: bool = False
    confirmation_token: Optional[str] = None
    options: Dict[str, Any] = field(default_factory=dict)
    validation_mode: bool = False


class DeleteWorker(QThread):
    progress = Signal(int, str)   # pct, message
    finished = Signal(object)     # PipelineResult
    cancelled = Signal()
    error = Signal(str)

    def __init__(self, *, pipeline: Any, request: DeleteRequest, parent=None):
        super().__init__(parent)
        self._pipeline = pipeline
        self._request = request
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        self._cancel_event.set()

    def run(self) -> None:
        try:
            self.progress.emit(0, "Preparing delete...")

            opts = dict(self._request.options or {})
            opts["scan_id"] = str(self._request.scan_id)

            req = PipelineRequest(
                roots=[],
                mode=PipelineMode.DELETE,
                deletion_policy=self._request.deletion_policy,
                require_explicit_confirmation=bool(self._request.require_explicit_confirmation),
                confirmation_token=self._request.confirmation_token,
                validation_mode=self._request.validation_mode,
                options=opts,
            )

            def progress_cb(pct: int, msg: str = ""):
                pct = max(0, min(100, int(pct)))
                self.progress.emit(pct, msg or "")

            class _UISink:
                def __init__(self, emit_fn):
                    self._emit_fn = emit_fn

                def emit(self, event: Any) -> None:
                    try:
                        phase = getattr(getattr(event, "phase", None), "value", getattr(event, "phase", ""))
                        phase = str(phase or "")
                        msg = str(getattr(event, "message", "") or "")
                        pct = _DELETE_PHASE_PCT.get(phase)
                        if pct is None:
                            return
                        self._emit_fn(int(pct), msg or phase)
                    except Exception:
                        return

            result = self._pipeline.run(
                req,
                progress_cb=progress_cb,
                cancel_event=self._cancel_event,
                sink=_UISink(progress_cb),
            )

            if self._cancel_event.is_set():
                self.cancelled.emit()
                return

            self.progress.emit(100, "Delete complete.")
            self.finished.emit(result)

        except Exception:
            self.error.emit(traceback.format_exc())
