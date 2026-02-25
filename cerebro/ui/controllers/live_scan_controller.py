# cerebro/ui/controllers/live_scan_controller.py
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Optional

from PySide6.QtCore import QObject, Signal, Slot, QTimer

from cerebro.services.logger import get_logger
from cerebro.ui.state_bus import get_state_bus
from cerebro.ui.models.live_scan_snapshot import LiveScanSnapshot

from cerebro.workers.fast_scan_worker import FastScanWorker
from cerebro.core.models import ScanProgress


@dataclass(frozen=True, slots=True)
class ControllerConfig:
    # Signal throttling
    file_emit_interval_ms: int = 80
    progress_emit_interval_ms: int = 120

    # Snapshot updates (10Hz max)
    snapshot_update_interval_ms: int = 100

    # Smoothing
    smoothing_window_size: int = 5

    # Mode preferences (kept for compatibility; FAST_ONLY ignores standard path)
    prefer_fast_mode: bool = True


class LiveScanController(QObject):
    """
    FAST_ONLY controller.

    Maintains a single LiveScanSnapshot as the source of truth.
    UI should read from snapshot_updated updates.

    NOTE:
    - This controller is the ONLY component that publishes scan lifecycle events onto the StateBus.
    - Pages should NOT re-emit bus scan_started/scan_completed/etc (prevents duplicates).
    """

    # Core lifecycle signals
    scan_started = Signal(str)
    scan_completed = Signal(dict)
    scan_cancelled = Signal()
    scan_failed = Signal(str)

    # Snapshot updates (single source of truth)
    snapshot_updated = Signal(object)  # LiveScanSnapshot

    # Legacy signals (backward compatibility)
    progress_changed = Signal(object)
    file_changed = Signal(str)
    phase_changed = Signal(str)
    status_changed = Signal(str)
    groups_updated = Signal(int)
    warnings_logged = Signal(object)

    def __init__(self, cfg: Optional[ControllerConfig] = None, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.cfg = cfg or ControllerConfig()
        self._logger = get_logger("ui.LiveScanController")
        self._bus = get_state_bus()

        # Single source of truth
        self._snapshot = LiveScanSnapshot()

        # Worker state
        self._scan_id: Optional[str] = None
        self._worker: Optional[FastScanWorker] = None
        self._is_running = False

        # Throttling timestamps
        self._last_file_emit = 0.0
        self._last_progress_emit = 0.0
        self._last_snapshot_emit = 0.0

        # Buffered updates for snapshot
        self._pending_snapshot_updates: Dict[str, Any] = {}

        # Pulse timer for navigator
        self._pulse_timer = QTimer(self)
        self._pulse_timer.setInterval(450)
        self._pulse_timer.timeout.connect(self._on_pulse)

        # Snapshot update timer (10Hz max)
        self._snapshot_timer = QTimer(self)
        self._snapshot_timer.setInterval(self.cfg.snapshot_update_interval_ms)
        self._snapshot_timer.timeout.connect(self._emit_snapshot_update)

    def is_running(self) -> bool:
        return self._is_running

    def current_scan_id(self) -> Optional[str]:
        return self._scan_id

    def get_snapshot(self) -> LiveScanSnapshot:
        """Get current snapshot (read-only)."""
        return self._snapshot

    # -------------------------
    # Public control
    # -------------------------

    def start_scan(self, config: Dict[str, Any]) -> str:
        """
        Start a new scan (FAST_ONLY).
        config dict expected keys:
            root (required)
        """
        if self._is_running:
            self._logger.warning("start_scan called while running; ignored.")
            return self._scan_id or ""

        root = str(config.get("root") or config.get("scan_root") or "")
        if not root:
            raise ValueError("Scan config missing 'root'")

        # Force FAST mode (single execution path)
        config = dict(config or {})
        config["root"] = root
        config["fast_mode"] = True
        config["mode"] = "fast"

        self._scan_id = str(config.get("scan_id") or uuid.uuid4())
        self._is_running = True

        # Initialize snapshot
        self._snapshot.start_scan(self._scan_id)
        self._pending_snapshot_updates.clear()

        # Start timers
        self._pulse_timer.start()
        self._snapshot_timer.start()

        # Emit initial snapshot early
        self.snapshot_updated.emit(self._snapshot)

        # Lifecycle signals (emit ONCE)
        self.status_changed.emit("starting")

        # Publish to bus ONCE (controller is the sole publisher)
        try:
            self._bus.scan_started.emit(self._scan_id)
        except Exception:
            pass

        self.scan_started.emit(self._scan_id)

        self._logger.info(f"Starting FAST scan {self._scan_id} root={root}")
        self._start_fast_scan(config)
        return self._scan_id

    def cancel_scan(self) -> None:
        if not self._is_running:
            return

        self._logger.info("Scan cancel requested")

        # Update snapshot
        self._snapshot.cancel_scan()
        self._emit_snapshot_update()

        # Stop worker
        if isinstance(self._worker, FastScanWorker):
            self._worker.cancel()

        self.status_changed.emit("cancelling")

    # -------------------------
    # Internal start (FAST_ONLY)
    # -------------------------

    def _start_fast_scan(self, config: Dict[str, Any]) -> None:
        w = FastScanWorker(config)
        self._worker = w

        # Connect worker -> controller snapshot buffering
        w.phase_changed.connect(self._on_phase_changed)
        w.file_changed.connect(self._on_file_changed)
        w.group_discovered.connect(self._on_groups_delta)
        w.warning_raised.connect(self._on_warning)
        w.progress_updated.connect(self._on_progress)

        w.finished.connect(self._on_completed)
        w.cancelled.connect(self._on_cancelled)
        w.failed.connect(self._on_failed)

        w.start()

    # -------------------------
    # Signal handlers (buffered for snapshot)
    # -------------------------

    @Slot()
    def _on_pulse(self) -> None:
        if not self._is_running:
            self._pulse_timer.stop()
            return
        try:
            self._bus.publish_station_status("scan", is_pulsing=True)
        except Exception:
            pass

    @Slot(str)
    def _on_phase_changed(self, phase: str) -> None:
        self._pending_snapshot_updates["phase"] = phase

        # Legacy signals
        self.phase_changed.emit(phase or "")
        try:
            self._bus.publish_scan_progress(0.0, phase=phase or "", is_pulsing=True)
        except Exception:
            pass

    @Slot(str)
    def _on_file_changed(self, path: str) -> None:
        now = time.perf_counter()
        if (now - self._last_file_emit) * 1000.0 < self.cfg.file_emit_interval_ms:
            return

        self._last_file_emit = now
        self._pending_snapshot_updates["current_file"] = path

        self.file_changed.emit(path or "")

    @Slot(int)
    def _on_groups_delta(self, delta: int) -> None:
        current = self._snapshot.groups_found
        new_groups = current + max(0, int(delta))
        self._pending_snapshot_updates["groups_found"] = new_groups
        self.groups_updated.emit(new_groups)

    @Slot(str, str)
    def _on_warning(self, path: str, reason: str) -> None:
        warning_msg = f"{path}: {reason}" if path else reason
        current_warnings = self._snapshot.warnings.copy()
        current_warnings.append(warning_msg)
        self._pending_snapshot_updates["warnings"] = current_warnings

        self.warnings_logged.emit(current_warnings)

    @Slot(object)
    def _on_progress(self, progress: ScanProgress) -> None:
        now = time.perf_counter()
        if (now - self._last_progress_emit) * 1000.0 < self.cfg.progress_emit_interval_ms:
            # still buffer latest progress fields for snapshot
            if progress:
                self._pending_snapshot_updates["progress_percent"] = float(progress.percent or 0.0)
                self._pending_snapshot_updates["scanned_files"] = int(progress.scanned_files or 0)
                self._pending_snapshot_updates["scanned_bytes"] = int(progress.scanned_bytes or 0)
                self._pending_snapshot_updates["elapsed_seconds"] = float(progress.elapsed_seconds or 0.0)
            return

        self._last_progress_emit = now

        if progress:
            self._pending_snapshot_updates.update({
                "progress_percent": float(progress.percent or 0.0),
                "scanned_files": int(progress.scanned_files or 0),
                "scanned_bytes": int(progress.scanned_bytes or 0),
                "elapsed_seconds": float(progress.elapsed_seconds or 0.0),
            })

        self.progress_changed.emit(progress)

    # -------------------------
    # Snapshot emission
    # -------------------------

    @Slot()
    def _emit_snapshot_update(self) -> None:
        if not self._is_running and not self._pending_snapshot_updates:
            return

        # Apply buffered updates
        if self._pending_snapshot_updates:
            try:
                self._snapshot.apply_updates(**self._pending_snapshot_updates)
            except Exception:
                # If snapshot model changes, never crash UI loop
                pass
            self._pending_snapshot_updates.clear()

        self.snapshot_updated.emit(self._snapshot)

    def _finish_running(self) -> None:
        self._is_running = False
        try:
            self._pulse_timer.stop()
            self._snapshot_timer.stop()
        except Exception:
            pass

    # -------------------------
    # Terminal handlers
    # -------------------------

    @Slot(dict)
    def _on_completed(self, result: Dict[str, Any]) -> None:
        self._logger.info("Scan completed")

        self._snapshot.complete_scan()
        self._pending_snapshot_updates.update({
            "duplicates_found": int(result.get("duplicate_count", 0) or 0),
            "groups_found": int(result.get("group_count", result.get("groups_found", 0)) or 0),
        })
        self._emit_snapshot_update()
        self._finish_running()

        payload = dict(result or {})
        payload.setdefault("scan_id", self._scan_id)

        # Publish to bus ONCE (controller is the sole publisher)
        try:
            self._bus.scan_completed.emit(payload)
        except Exception:
            pass

        self.scan_completed.emit(payload)

    @Slot()
    def _on_cancelled(self) -> None:
        self._logger.info("Scan cancelled")
        self._snapshot.cancel_scan()
        self._emit_snapshot_update()
        self._finish_running()

        try:
            self._bus.scan_cancelled.emit(self._scan_id or "unknown")
        except Exception:
            pass

        self.scan_cancelled.emit()

    @Slot(str)
    def _on_failed(self, tb: str) -> None:
        self._logger.error("Scan failed")
        self._snapshot.fail_scan(tb)
        self._emit_snapshot_update()
        self._finish_running()

        try:
            self._bus.scan_failed.emit(tb)
        except Exception:
            pass

        self.scan_failed.emit(tb)
