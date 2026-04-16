"""
Scan Orchestrator

Dispatches to the correct engine based on the active scan mode.
Manages engine lifecycle and provides unified interface for the UI.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable, List, Optional

from cerebro.engines.base_engine import (
    BaseEngine,
    DuplicateGroup,
    EngineOption,
    ScanProgress,
    ScanState,
)

# Import engines (these will be created in subsequent tasks)
# For now, we'll create placeholder imports that will be updated


class ScanOrchestrator:
    """
    Engine orchestrator that dispatches scan operations to the correct engine.

    Maintains a registry of all available engines and manages the active
    engine's lifecycle (start, pause, resume, cancel).
    """

    def __init__(self):
        """Initialize the orchestrator with engine registry."""
        self._engines: dict[str, BaseEngine] = {}
        self._active_engine: Optional[BaseEngine] = None
        self._active_mode: str = ""
        self._scan_thread: Optional[threading.Thread] = None
        self._progress_callback: Optional[Callable[[ScanProgress], None]] = None
        self._lock = threading.RLock()

        # Register engines (these will be added as they're implemented)
        self._register_engines()

    def _register_engines(self) -> None:
        """Register all available scan engines."""
        from cerebro.engines.empty_folder_engine import EmptyFolderEngine
        from cerebro.engines.file_dedup_engine import FileDedupEngine
        from cerebro.engines.image_dedup_engine import ImageDedupEngine
        from cerebro.engines.large_file_engine import LargeFileEngine
        from cerebro.engines.music_dedup_engine import MusicDedupEngine
        from cerebro.engines.turbo_file_engine import TurboFileEngine
        from cerebro.engines.video_dedup_engine import VideoDedupEngine

        self._engines["files"]         = TurboFileEngine()
        self._engines["files_classic"] = FileDedupEngine()
        self._engines["photos"]        = ImageDedupEngine()
        self._engines["videos"]        = VideoDedupEngine()
        self._engines["music"]         = MusicDedupEngine()
        self._engines["empty_folders"] = EmptyFolderEngine()
        self._engines["large_files"]   = LargeFileEngine()

    def register_engine(self, mode: str, engine: BaseEngine) -> None:
        """
        Register an engine for a scan mode.

        Args:
            mode: Scan mode identifier ('files', 'photos', etc.)
            engine: Engine instance implementing BaseEngine.
        """
        with self._lock:
            self._engines[mode] = engine

    def get_available_modes(self) -> List[str]:
        """Get list of available scan modes."""
        with self._lock:
            return list(self._engines.keys())

    def set_mode(self, mode: str) -> List[EngineOption]:
        """
        Switch to a scan mode and return its options.

        Args:
            mode: Scan mode to activate.

        Returns:
            List of EngineOption objects for the mode.

        Raises:
            ValueError: If mode is not available.
        """
        with self._lock:
            if mode not in self._engines:
                raise ValueError(f"Unknown scan mode: {mode}")

            # Cancel any active scan
            if self._scan_thread and self._scan_thread.is_alive():
                self.cancel()

            self._active_mode = mode
            self._active_engine = self._engines[mode]
            return self._active_engine.get_mode_options()

    def get_active_mode(self) -> str:
        """Get the currently active scan mode."""
        with self._lock:
            return self._active_mode

    def get_active_engine(self) -> Optional[BaseEngine]:
        """Get the currently active engine instance."""
        with self._lock:
            return self._active_engine

    def start_scan(
        self,
        folders: List[Path],
        protected: List[Path],
        options: dict,
        progress_callback: Optional[Callable[[ScanProgress], None]] = None
    ) -> None:
        """
        Start a scan in a background thread.

        Args:
            folders: List of directory paths to scan.
            protected: List of directory paths to protect from deletion.
            options: Dict of engine-specific option values.
            progress_callback: Function called with progress updates.

        Raises:
            RuntimeError: If a scan is already running.
            ValueError: If no engine is active.
        """
        with self._lock:
            if self._scan_thread and self._scan_thread.is_alive():
                raise RuntimeError("Scan already in progress")

            if not self._active_engine:
                raise ValueError("No scan mode selected")

            self._progress_callback = progress_callback

            # Configure the active engine
            self._active_engine.configure(folders, protected, options)

            # Start scan in background thread
            self._scan_thread = threading.Thread(
                target=self._run_scan,
                daemon=True,
                name=f"ScanThread-{self._active_mode}"
            )
            self._scan_thread.start()

    def _run_scan(self) -> None:
        """Run the scan in a background thread."""
        try:
            def wrapper_callback(progress: ScanProgress) -> None:
                """Thread-safe wrapper for progress callback."""
                # Update progress callback if provided
                if self._progress_callback:
                    # Schedule callback on main thread via the engine's mechanism
                    # For now, call directly (UI should handle thread safety)
                    self._progress_callback(progress)

            self._active_engine.start(wrapper_callback)
        except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError) as e:
            # Report error via progress callback — must be dispatched on the main
            # thread because the callback updates Tkinter widgets (C-1 fix).
            if self._progress_callback:
                error_progress = ScanProgress(
                    state=ScanState.ERROR,
                    current_file=f"Error: {str(e)}"
                )
                try:
                    import tkinter as _tk
                    root = _tk._default_root  # type: ignore[attr-defined]
                    if root is not None:
                        root.after(0, lambda p=error_progress: self._progress_callback(p) if self._progress_callback else None)
                        return
                except Exception:
                    pass
                # Fallback: no Tk root available (tests, headless)
                self._progress_callback(error_progress)

    def pause(self) -> None:
        """Pause the current scan."""
        with self._lock:
            if self._active_engine and self._active_engine.state == ScanState.SCANNING:
                self._active_engine.pause()

    def resume(self) -> None:
        """Resume a paused scan."""
        with self._lock:
            if self._active_engine and self._active_engine.state == ScanState.PAUSED:
                self._active_engine.resume()

    def cancel(self) -> None:
        """Cancel the current scan."""
        # Capture thread reference *inside* the lock, then join *outside* it.
        # Joining inside the lock would deadlock if the scan thread calls any
        # locked orchestrator method while winding down (C-2 fix).
        with self._lock:
            if self._active_engine:
                self._active_engine.cancel()
            thread = self._scan_thread

        if thread and thread.is_alive():
            thread.join(timeout=5.0)

    def get_results(self) -> List[DuplicateGroup]:
        """
        Get scan results from the active engine.

        Returns:
            List of DuplicateGroup objects with scan results.
        """
        with self._lock:
            if not self._active_engine:
                return []

            return self._active_engine.get_results()

    def get_progress(self) -> ScanProgress:
        """
        Get current progress snapshot.

        Returns:
            ScanProgress object with current scan state.
        """
        with self._lock:
            if not self._active_engine:
                return ScanProgress(state=ScanState.IDLE)

            return self._active_engine.get_progress()

    def is_scanning(self) -> bool:
        """Check if a scan is currently running."""
        with self._lock:
            if not self._active_engine:
                return False
            return self._active_engine.state in (ScanState.SCANNING, ScanState.PAUSED)

    def is_paused(self) -> bool:
        """Check if the current scan is paused."""
        with self._lock:
            if not self._active_engine:
                return False
            return self._active_engine.state == ScanState.PAUSED

    def is_completed(self) -> bool:
        """Check if the current scan is completed."""
        with self._lock:
            if not self._active_engine:
                return False
            return self._active_engine.state == ScanState.COMPLETED

    def get_engine_name(self) -> str:
        """Get the name of the currently active engine."""
        with self._lock:
            if not self._active_engine:
                return ""
            return self._active_engine.get_name()

    def wait_for_completion(self, timeout: Optional[float] = None) -> bool:
        """
        Wait for the current scan to complete.

        Args:
            timeout: Maximum seconds to wait. None for infinite wait.

        Returns:
            True if scan completed, False if timeout.
        """
        if self._scan_thread:
            return self._scan_thread.join(timeout=timeout) is None
        return True
