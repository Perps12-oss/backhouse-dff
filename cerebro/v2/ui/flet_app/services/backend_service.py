"""Backend service: threads scan execution behind an async-safe interface.

Wraps ScanOrchestrator and provides:
- Threaded scan execution with progress callbacks
- Cancellation support via threading.Event
- Async-safe result delivery back to Flet's UI thread
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import flet as ft

from cerebro.engines.base_engine import DuplicateGroup, ScanProgress, ScanState
from cerebro.engines.orchestrator import ScanOrchestrator

_log = logging.getLogger(__name__)


class BackendService:
    """Facade over ScanOrchestrator with threaded execution and Flet-safe callbacks."""

    def __init__(self, page: Optional[ft.Page] = None) -> None:
        self._orchestrator = ScanOrchestrator()
        self._cancel_event = threading.Event()
        self._scanning = False
        self._scan_lock = threading.Lock()
        self._page = page

        self._on_progress: Optional[Callable[[Dict[str, Any]], None]] = None
        self._on_complete: Optional[Callable[[List[DuplicateGroup], str], None]] = None
        self._on_error: Optional[Callable[[str], None]] = None
        self._last_progress_time: float = 0.0  # throttle: emit at most 4×/s

    @property
    def orchestrator(self) -> ScanOrchestrator:
        return self._orchestrator

    @property
    def is_scanning(self) -> bool:
        return self._scanning

    # -- Callback registration ------------------------------------------------

    def set_on_progress(self, cb: Callable[[Dict[str, Any]], None]) -> None:
        self._on_progress = cb

    def set_on_complete(self, cb: Callable[[List[DuplicateGroup], str], None]) -> None:
        self._on_complete = cb

    def set_on_error(self, cb: Callable[[str], None]) -> None:
        self._on_error = cb

    # -- Scan lifecycle -------------------------------------------------------

    def start_scan(
        self,
        folders: List[Path],
        mode: str = "files",
        protected: Optional[List[Path]] = None,
        options: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Start a scan in a background thread. Returns False if already scanning."""
        with self._scan_lock:
            if self._scanning:
                return False
            self._scanning = True
            self._cancel_event.clear()
        engine_mode = self._resolve_engine_mode(mode)

        def _worker() -> None:
            try:
                self._orchestrator.set_mode(engine_mode)
                self._orchestrator.start_scan(
                    folders=folders,
                    protected=protected or [],
                    options=options or {},
                    progress_callback=self._handle_progress,
                )
                # start_scan only spawns ScanOrchestrator's thread; it returns immediately.
                # Without waiting, get_results() runs while the scan is still running (empty).
                self._orchestrator.wait_for_completion(timeout=None)
                results = self._orchestrator.get_results()
                if self._on_complete:
                    self._deliver_on_ui_thread(self._on_complete, results, mode)
            except Exception as exc:
                _log.exception("Scan worker failed")
                if self._on_error:
                    self._deliver_on_ui_thread(self._on_error, str(exc))
            finally:
                with self._scan_lock:
                    self._scanning = False

        t = threading.Thread(target=_worker, daemon=True)
        t.start()
        return True

    def cancel_scan(self) -> None:
        """Request scan cancellation."""
        self._cancel_event.set()
        try:
            self._orchestrator.cancel()
        except Exception:
            _log.exception("Cancel failed")

    # -- Engine introspection -------------------------------------------------

    def get_results(self) -> List[DuplicateGroup]:
        return self._orchestrator.get_results()

    def probe_mode(self, mode_key: str) -> Optional[Any]:
        from cerebro.v2.core.engine_deps import probe_mode as _probe
        return _probe(mode_key)

    # -- Internal -------------------------------------------------------------

    def _deliver_on_ui_thread(self, fn: Callable[..., None], *args: Any) -> None:
        """Run a callback on the Flet page thread (StateStore + control updates are not thread-safe)."""
        if self._page is not None:
            self._page.run_thread(fn, *args)
        else:
            fn(*args)

    def _handle_progress(self, progress: ScanProgress) -> None:
        import time as _time
        if self._cancel_event.is_set():
            return
        is_terminal = progress.state in (ScanState.COMPLETED, ScanState.CANCELLED, ScanState.ERROR)
        if self._on_progress:
            # Throttle intermediate progress to ≤4 updates/second; always deliver terminal events.
            now = _time.monotonic()
            if is_terminal or (now - self._last_progress_time) >= 0.25:
                self._last_progress_time = now
                data = {
                    "state": progress.state.value if progress.state else "",
                    "files_scanned": progress.files_scanned,
                    "files_total": progress.files_total,
                    "duplicates_found": progress.duplicates_found,
                    "groups_found": progress.groups_found,
                    "bytes_reclaimable": progress.bytes_reclaimable,
                    "elapsed_seconds": progress.elapsed_seconds,
                    "current_file": progress.current_file or "",
                    "stage": progress.stage or "",
                }
                self._on_progress(data)
        if is_terminal:
            with self._scan_lock:
                self._scanning = False

    def _resolve_engine_mode(self, mode: str) -> str:
        """Map UI-facing mode keys to available orchestrator engine keys."""
        normalized = (mode or "files").strip().lower()
        aliases = {
            # UI card exists, but backend currently only supports exact photo dedup.
            "similar_photos": "photos",
        }
        resolved = aliases.get(normalized, normalized)
        available = set(self._orchestrator.get_available_modes())
        if resolved in available:
            if resolved != normalized:
                _log.info("Mode alias applied: %s -> %s", normalized, resolved)
            return resolved
        if "files" in available:
            _log.warning("Unknown mode '%s', falling back to 'files'", mode)
            return "files"
        return resolved
