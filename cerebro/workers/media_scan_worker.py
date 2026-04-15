# cerebro/workers/media_scan_worker.py
"""
Media Scan Worker - Specialized worker for media deduplication engines.

Integrates with specialized engines (VideoDedupEngine, MusicDedupEngine, etc.)
for media-specific scanning with proper progress reporting and error handling.
"""

from __future__ import annotations

import time
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional

from PySide6.QtCore import QThread, Signal, QObject

from cerebro.core.models import ScanProgress, ScanState
from cerebro.engines.orchestrator import ScanOrchestrator


class MediaScanWorker(QThread):
    """
    Worker thread for specialized media scanning using dedicated engines.

    Supports:
    - Video deduplication (VideoDedupEngine)
    - Music deduplication (MusicDedupEngine)
    - Image deduplication (ImageDedupEngine)

    Signals:
      - progress_updated(ScanProgress)
      - phase_changed(str)
      - file_changed(str)
      - group_discovered(int)      # delta
      - warning_raised(str, str)   # path, reason
      - error_occurred(str)
      - finished(dict)
      - failed(str)
      - cancelled()
    """
    progress_updated = Signal(object)
    phase_changed = Signal(str)
    file_changed = Signal(str)
    group_discovered = Signal(int)
    warning_raised = Signal(str, str)
    error_occurred = Signal(str)
    finished = Signal(dict)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, config: Dict[str, Any], parent: Optional[QObject] = None):
        super().__init__(parent)
        self._config = config
        self._orchestrator = ScanOrchestrator()
        self._cancelled = False
        self._scan_mode = config.get("media_type", "all")

        # Map UI media types to orchestrator modes
        self._mode_mapping = {
            "videos": "videos",
            "audio": "music",
            "photos": "photos",
            "all": "files"  # Default to file dedup for "all"
        }

        # Track progress
        self._start_time = 0.0
        self._last_groups = 0

    def cancel(self) -> None:
        """Cancel the scan."""
        self._cancelled = True
        try:
            self._orchestrator.cancel()
        except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
            pass

    def run(self) -> None:
        """Execute the media scan using the specialized engine."""
        self._start_time = time.perf_counter()
        self._last_groups = 0

        try:
            # Get the appropriate mode for the orchestrator
            orchestrator_mode = self._mode_mapping.get(self._scan_mode, "files")

            # Check if this mode is supported
            available_modes = self._orchestrator.get_available_modes()
            if orchestrator_mode not in available_modes:
                self.failed.emit(f"Scan mode '{orchestrator_mode}' not available. Available modes: {available_modes}")
                return

            # Set the mode and get engine options
            try:
                engine_options = self._orchestrator.set_mode(orchestrator_mode)
                engine_name = self._orchestrator.get_engine_name()
            except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError) as e:
                self.failed.emit(f"Failed to initialize {orchestrator_mode} engine: {e}")
                return

            # Check for FFmpeg availability for video mode
            if orchestrator_mode == "videos":
                import shutil
                if not shutil.which("ffmpeg"):
                    self.phase_changed.emit("FFmpeg not found - using metadata-only mode")
                    self.warning_raised("", "FFmpeg not installed. Video deduplication will use metadata-only mode (duration + size). Install FFmpeg for frame-based detection.")

            self.phase_changed.emit(f"Using {engine_name}")

            # Get scan folders and options
            folders = [Path(self._config.get("root", ""))]
            protected = [Path(p) for p in self._config.get("protected", [])]

            # Build engine options from config
            options = self._build_engine_options(engine_options)

            # Start the scan
            def progress_callback(progress: ScanProgress) -> None:
                """Handle progress updates from the engine."""
                if self._cancelled:
                    return

                # Emit phase changes
                if progress.phase:
                    self.phase_changed.emit(str(progress.phase))

                # Emit file changes
                if progress.current_file:
                    self.file_changed.emit(str(progress.current_file))

                # Emit progress updates
                self.progress_updated.emit(progress)

                # Emit group discoveries
                if progress.groups_found and progress.groups_found > self._last_groups:
                    delta = progress.groups_found - self._last_groups
                    self.group_discovered.emit(delta)
                    self._last_groups = progress.groups_found

                # Emit warnings
                if progress.warnings:
                    for warning in progress.warnings:
                        self.warning_raised.emit("", str(warning))

            self._orchestrator.start_scan(
                folders=folders,
                protected=protected,
                options=options,
                progress_callback=progress_callback
            )

            # Wait for scan to complete
            self._orchestrator.wait_for_completion()

            if self._cancelled:
                self.cancelled.emit()
                return

            # Get results
            results = self._orchestrator.get_results()
            progress = self._orchestrator.get_progress()

            # Build result dict
            result = {
                "ok": True,
                "scan_id": self._config.get("scan_id", ""),
                "groups": self._convert_groups_to_dict(results),
                "stats": {
                    "groups_found": progress.groups_found,
                    "duplicates_found": progress.duplicates_found,
                    "files_scanned": progress.files_scanned,
                    "total_files": progress.files_total,
                    "bytes_scanned": progress.bytes_scanned,
                    "bytes_reclaimable": progress.bytes_reclaimable,
                    "elapsed_seconds": progress.elapsed_seconds,
                    "scan_mode": self._scan_mode,
                    "engine": engine_name
                }
            }

            self.finished.emit(result)

        except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError) as e:
            tb = traceback.format_exc()
            error_msg = f"Media scan failed: {e}"
            self.error_occurred.emit(error_msg)
            self.failed.emit(tb)

    def _build_engine_options(self, engine_options: List[Any]) -> Dict[str, Any]:
        """Build engine options dict from config and engine options."""
        options = {}

        # Extract values from config
        if "min_size_bytes" in self._config:
            options["min_size_mb"] = self._config["min_size_bytes"] // (1024 * 1024)

        if "include_hidden" in self._config:
            options["include_hidden"] = self._config["include_hidden"]

        # For video engine
        if self._scan_mode == "videos":
            if "similarity_threshold" in self._config:
                options["similarity_threshold"] = self._config["similarity_threshold"]
            if "duration_tolerance" in self._config:
                options["duration_tolerance"] = self._config["duration_tolerance"]

        # For music engine
        if self._scan_mode == "audio":
            if "bitrate_comparison" in self._config:
                options["bitrate_comparison"] = self._config["bitrate_comparison"]
            if "duration_tolerance" in self._config:
                options["duration_tolerance"] = self._config["duration_tolerance"]

        return options

    def _convert_groups_to_dict(self, groups: List[Any]) -> List[Dict[str, Any]]:
        """Convert engine DuplicateGroup objects to dict format."""
        result = []
        for group in groups:
            try:
                group_dict = {
                    "hash": getattr(group, "similarity_type", "unknown"),
                    "size": getattr(group, "total_size", 0),
                    "reclaimable": getattr(group, "reclaimable", 0),
                    "count": len(getattr(group, "files", [])),
                    "paths": [str(f.path) for f in getattr(group, "files", [])],
                    "files": [
                        {
                            "path": str(f.path),
                            "size": f.size,
                            "modified": f.modified,
                            "extension": f.extension,
                            "is_keeper": f.is_keeper,
                            "similarity": f.similarity
                        }
                        for f in getattr(group, "files", [])
                    ]
                }
                result.append(group_dict)
            except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
                # Skip malformed groups
                continue
        return result

    def get_engine_name(self) -> str:
        """Get the name of the active engine."""
        return self._orchestrator.get_engine_name()