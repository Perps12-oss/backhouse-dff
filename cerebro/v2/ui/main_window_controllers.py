"""Incremental MainWindow decomposition helpers.

These controllers keep behavior in MainWindow stable while separating
scan lifecycle, selection/preview orchestration, and history recording.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, List

from cerebro.engines.base_engine import ScanState
from cerebro.v2.ui.status_bar import StatusBarMetrics
from cerebro.services.logger import get_logger

logger = get_logger(__name__)  # wraps logging.getLogger(__name__)


class HistoryRecorder:
    """Records completed scans into history storage."""

    def __init__(self, window: Any) -> None:
        self._window = window

    def record_completed_scan(
        self,
        mode: str,
        groups_found: int,
        files_found: int,
        bytes_reclaimable: int,
        duration_seconds: float,
    ) -> None:
        try:
            from cerebro.v2.ui.scan_history_dialog import record_scan

            record_scan(
                mode=mode,
                folders=[str(f) for f in self._window._folder_panel.get_scan_folders()],
                groups_found=groups_found,
                files_found=files_found,
                bytes_reclaimable=bytes_reclaimable,
                duration_seconds=duration_seconds,
            )
        except (ImportError, OSError, ValueError) as exc:
            logger.warning("Failed to record scan history entry: %s", exc)


class PreviewCoordinator:
    """Coordinates toolbar selection state and preview panel hydration."""

    def __init__(self, window: Any) -> None:
        self._window = window

    def on_selection_changed(self, checked_items: List[str]) -> None:
        has_sel = len(checked_items) > 0
        self._window._toolbar.set_has_selection(has_sel)
        self.update_preview_panel(checked_items)

    def update_preview_panel(self, checked_items: List[str]) -> None:
        # Store selected file IDs for keep buttons.
        self._window._selected_file_ids = checked_items[:2]

        files_data: list[Any] = []
        for item_id in checked_items[:2]:
            file_data = self._window._get_file_data_by_id(item_id)
            if file_data:
                files_data.append(file_data)

        if not files_data:
            self._window._preview_panel.clear()
        elif len(files_data) == 1:
            self._window._preview_panel.load_single(files_data[0])
        else:
            self._window._preview_panel.load_comparison(files_data[0], files_data[1])


class ScanController:
    """Owns scan start/stop/finish lifecycle transitions for MainWindow."""

    def __init__(self, window: Any, history: HistoryRecorder) -> None:
        self._window = window
        self._history = history

    def start_search(self) -> None:
        folders = self._window._folder_panel.get_scan_folders()
        if not folders:
            self._window.show_info("No Folders", "Please add at least one folder to scan.")
            return

        self._window._scan_results.clear()
        self._window._results_panel.clear()
        self._window._status_bar.reset()

        self._window._scan_start_time = time.time()
        self._window._eta_smoothed = 0.0
        self._window._scanning = True
        self._window._toolbar.set_scanning(True)
        self._window._status_bar.set_scanning(True)
        self._window._status_bar.start_polling(
            lambda: self._window._status_bar.update_elapsed(time.time() - self._window._scan_start_time),
            interval=200,
        )

        scan_mode = self._window.get_scan_mode()
        protected_folders = self._window._folder_panel.get_protected_folders()
        scan_options = self._window._folder_panel.get_options()

        logger.info("Starting scan in %s mode", scan_mode)
        logger.debug("Scan folders count: %d", len(folders))
        logger.debug("Protected folders count: %d", len(protected_folders))
        logger.debug("Scan options: %s", scan_options)

        if self._window._app_settings.general.get("auto_collapse", True):
            self._window._folder_panel.set_collapsed(True)

        self._window._orchestrator.set_mode(scan_mode)

        try:
            self._window._orchestrator.start_scan(
                folders=folders,
                protected=protected_folders,
                options=scan_options,
                progress_callback=self._window._on_scan_progress,
            )
            self._window._start_progress_polling()
        except RuntimeError as exc:
            logger.warning("Failed to start scan: %s", exc)
            self.finish_scan()

    def stop_search(self) -> None:
        logger.info("Stopping active scan")
        self._window._orchestrator.cancel()

    def finish_scan(self, final_state: ScanState = ScanState.COMPLETED) -> None:
        self._window._stop_progress_polling()
        self._window._status_bar.stop_polling()

        self._window._scanning = False
        self._window._toolbar.set_scanning(False)
        self._window._status_bar.set_scanning(False)

        self._window._folder_panel.set_collapsed(False)
        self._window._scan_results = self._window._orchestrator.get_results()

        logger.info("Scan finished with state %s", final_state)
        logger.info("Found %d duplicate groups", len(self._window._scan_results))

        if self._window._scan_results:
            self._window._load_results_to_panel()

        if final_state == ScanState.COMPLETED:
            total_files = sum(len(g.files) for g in self._window._scan_results)
            reclaimable = sum(g.reclaimable for g in self._window._scan_results)
            elapsed = (
                time.time() - self._window._scan_start_time
                if self._window._scan_start_time > 0
                else 0.0
            )

            self._history.record_completed_scan(
                mode=self._window._current_scan_mode,
                groups_found=len(self._window._scan_results),
                files_found=total_files,
                bytes_reclaimable=reclaimable,
                duration_seconds=elapsed,
            )

            self._window._status_bar.update_metrics(
                StatusBarMetrics(
                    files_scanned=total_files,
                    duplicates_found=total_files - len(self._window._scan_results),
                    groups_found=len(self._window._scan_results),
                    bytes_reclaimable=reclaimable,
                    elapsed_seconds=elapsed,
                    eta_seconds=0.0,
                    is_scanning=False,
                    progress_percent=100.0,
                )
            )
