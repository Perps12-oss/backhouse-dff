# cerebro/workers/scan_worker.py

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from cerebro.core.models import StartScanConfig, PipelineMode, PipelineRequest
from cerebro.core.pipeline import CerebroPipeline
from cerebro.services.logger import log_info
from cerebro.workers.base_worker import BaseWorker, CancelledError


class ScanWorker(BaseWorker):
    """
    Main scanning worker for discovery + grouping + hashing.

    Emits:
        - progress(int, str): Progress updates
        - finished(PipelineResult): On success
        - error(str): On failure
        - cancelled(): If user cancels scan
    """

    def __init__(self, config: StartScanConfig, parent=None):
        super().__init__()
        self.config = config
        self.pipeline = CerebroPipeline()
        self.setParent(parent)

    def execute(self) -> Any:
        """Run the scanning process with the provided configuration."""
        start_time = time.perf_counter()
        log_info(f"[ScanWorker] Starting scan with config: {self.config}")

        request = PipelineRequest(
            roots=[Path(self.config.root)],
            mode=PipelineMode.SCAN,
            deletion_policy=None,
            confirmation_token="",
            dry_run=False,
            validation_mode=False,
            options={
                "min_size_bytes": self.config.min_size_bytes,
                "hash_bytes": self.config.hash_bytes,
                "fast_mode": self.config.fast_mode,
                "max_workers": self.config.max_workers,
                "follow_symlinks": self.config.follow_symlinks,
                "include_hidden": self.config.include_hidden,
                "allowed_extensions": self.config.allowed_extensions or [],
            }
        )

        def on_progress(pct: int, msg: str = ""):
            self.check_cancelled()
            self.update_progress(pct, msg)

        result = self.pipeline.run(
            request,
            cancel_event=self._cancel_event,
            progress_cb=on_progress
        )

        self.check_cancelled()
        elapsed = time.perf_counter() - start_time
        log_info(f"[ScanWorker] Scan completed in {elapsed:.2f}s with {len(result.matches)} match groups")

        return result
