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
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

import flet as ft

from cerebro.engines.base_engine import DuplicateGroup, ScanProgress, ScanState
from cerebro.engines.scan_stage import ScanStage
from cerebro.engines.orchestrator import ScanOrchestrator
from cerebro.v2.ui.flet_app.services.ui_marshal import run_on_ui_thread

if TYPE_CHECKING:
    from cerebro.v2.coordinator import CerebroCoordinator

_log = logging.getLogger(__name__)


class BackendService:
    """Facade over ScanOrchestrator with threaded execution and Flet-safe callbacks."""

    def __init__(
        self,
        page: Optional[ft.Page] = None,
        coordinator: Optional["CerebroCoordinator"] = None,
    ) -> None:
        self._orchestrator = ScanOrchestrator()
        self._coordinator = coordinator
        self._cancel_event = threading.Event()
        self._scanning = False
        self._scan_lock = threading.Lock()
        self._page = page

        self._on_progress: Optional[Callable[[Dict[str, Any]], None]] = None
        self._on_complete: Optional[Callable[[List[DuplicateGroup], str], None]] = None
        self._on_error: Optional[Callable[[str], None]] = None
        self._last_progress_time: float = 0.0  # throttle: emit at most 4×/s
        # Rolling rate: list of (monotonic_time, files_scanned) samples; reset on phase change.
        self._rate_samples: List[tuple] = []
        self._rate_stage: str = ""
        self._last_dispatched_scanned: int = -1
        self._last_dispatched_path: str = ""
        self._ema_rate: Optional[float] = None
        self._prev_progress_cf: str = ""
        self._ema_warm_ticks: int = 0

    @property
    def orchestrator(self) -> ScanOrchestrator:
        return self._orchestrator

    @property
    def is_scanning(self) -> bool:
        return self._scanning

    @property
    def is_paused(self) -> bool:
        """True when the orchestrator reports the active engine is paused."""
        try:
            return bool(self._orchestrator.is_paused())
        except Exception:
            return False

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
        mode: Any = "files",
        protected: Optional[List[Path]] = None,
        options: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Start a scan in a background thread. Returns False if already scanning."""
        with self._scan_lock:
            if self._scanning:
                return False
            self._scanning = True
            self._cancel_event.clear()
            self._ema_rate = None
            self._rate_samples.clear()
            self._prev_progress_cf = ""
            self._ema_warm_ticks = 0
        mode_list: List[str]
        if isinstance(mode, (list, tuple, set)):
            mode_list = [str(m) for m in mode if str(m).strip()]
        else:
            mode_list = [str(mode or "files")]
        if not mode_list:
            mode_list = ["files"]
        resolved_modes = [self._resolve_engine_mode(m) for m in mode_list]
        combined_mode = "+".join(mode_list) if len(mode_list) > 1 else mode_list[0]

        def _worker() -> None:
            try:
                if self._coordinator is not None:
                    self._coordinator.scan_started(combined_mode)
                all_results: List[DuplicateGroup] = []
                for engine_mode in resolved_modes:
                    if self._cancel_event.is_set():
                        break
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
                    all_results.extend(self._orchestrator.get_results())
                # Ensure stable unique group ids after mode aggregation.
                for idx, group in enumerate(all_results, start=1):
                    group.group_id = idx
                if self._on_complete:
                    self._deliver_on_ui_thread(self._on_complete, all_results, combined_mode)
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
        _log.info(
            "cancel_scan requested: scanning=%s cancel_event_set=%s",
            self._scanning,
            self._cancel_event.is_set(),
        )
        self._cancel_event.set()
        try:
            _log.info("cancel_scan forwarding to orchestrator.cancel()")
            self._orchestrator.cancel()
            _log.info("cancel_scan forwarded to orchestrator.cancel()")
        except Exception:
            _log.exception("Cancel failed")

    def pause_scan(self) -> None:
        """Pause the active scan if possible."""
        try:
            self._orchestrator.pause()
            if self._coordinator is not None:
                self._coordinator.scan_paused()
        except Exception:
            _log.exception("Pause failed")

    def resume_scan(self) -> None:
        """Resume a paused scan if possible."""
        try:
            self._orchestrator.resume()
            if self._coordinator is not None:
                self._coordinator.scan_resumed()
        except Exception:
            _log.exception("Resume failed")

    # -- Engine introspection -------------------------------------------------

    def get_results(self) -> List[DuplicateGroup]:
        return self._orchestrator.get_results()

    def probe_mode(self, mode_key: str) -> Optional[Any]:
        from cerebro.v2.core.engine_deps import probe_mode as _probe
        return _probe(mode_key)

    # -- Internal -------------------------------------------------------------

    def _deliver_on_ui_thread(self, fn: Callable[..., None], *args: Any) -> None:
        run_on_ui_thread(self._page, fn, *args)

    def _handle_progress(self, progress: ScanProgress) -> None:
        import time as _time
        if self._coordinator is not None:
            self._coordinator.report_scan_progress(progress)
        is_terminal = progress.state in (ScanState.COMPLETED, ScanState.CANCELLED, ScanState.ERROR)
        # Allow terminal events through even when cancel was requested.
        if self._cancel_event.is_set() and not is_terminal:
            return
        if self._on_progress:
            stage = (progress.stage or "")
            phase_changed = (stage != self._rate_stage)
            moved = (
                (progress.files_scanned or 0) != self._last_dispatched_scanned
                or (progress.current_file or "") != self._last_dispatched_path
            )
            min_gap = 0.09 if stage in (ScanStage.HASHING_PARTIAL, ScanStage.HASHING_FULL) else 0.22
            now = _time.monotonic()
            if is_terminal or phase_changed or moved or (now - self._last_progress_time) >= min_gap:
                self._last_progress_time = now
                if phase_changed:
                    self._last_dispatched_scanned = -1
                    self._last_dispatched_path = ""
                    self._ema_rate = None
                    self._ema_warm_ticks = 0
                self._last_dispatched_scanned = progress.files_scanned or 0
                self._last_dispatched_path = progress.current_file or ""

                # Rolling rate + EMA — append only when files_scanned advances so
                # path-only ticks and cache bursts do not distort throughput.
                is_hashing = stage in (ScanStage.HASHING_PARTIAL, ScanStage.HASHING_FULL)
                if stage != self._rate_stage:
                    _log.info(
                        "scan phase transition: %r → %r  (scanned=%d total=%d)",
                        self._rate_stage, stage,
                        progress.files_scanned, progress.files_total,
                    )
                if is_hashing and self._rate_stage not in (ScanStage.HASHING_PARTIAL, ScanStage.HASHING_FULL):
                    self._rate_samples = []
                    self._ema_rate = None
                    self._prev_progress_cf = ""
                    self._ema_warm_ticks = 0
                self._rate_stage = stage

                scanned = progress.files_scanned or 0
                prev_sample_scanned = self._rate_samples[-1][1] if self._rate_samples else -1
                if scanned > prev_sample_scanned:
                    self._rate_samples.append((now, scanned))
                # Keep a 5-second sliding window.
                cutoff = now - 5.0
                self._rate_samples = [s for s in self._rate_samples if s[0] >= cutoff]

                instant_rate: Optional[float] = None
                if len(self._rate_samples) >= 2:
                    dt = self._rate_samples[-1][0] - self._rate_samples[0][0]
                    dc = self._rate_samples[-1][1] - self._rate_samples[0][1]
                    if dt > 0.1 and dc > 0:
                        instant_rate = dc / dt

                cf_now = progress.current_file or ""
                if is_hashing:
                    prev_cf = self._prev_progress_cf
                    slipped_cache = ("Retrieving cached signatures" not in cf_now and "Retrieving cached signatures" in prev_cf)
                    if slipped_cache:
                        self._ema_warm_ticks = max(self._ema_warm_ticks, 3)

                rate_adj: Optional[float] = instant_rate

                warm = False
                if self._ema_warm_ticks > 0 and is_hashing:
                    self._ema_warm_ticks -= 1
                    warm = True

                alpha = 0.25
                if warm:
                    alpha = 0.42

                if not warm and rate_adj is not None and self._ema_rate is not None and self._ema_rate > 0:
                    ceiling = max(3.0 * self._ema_rate, 850.0)
                    if instant_rate is not None and instant_rate > ceiling:
                        rate_adj = ceiling
                        alpha *= 0.35

                rate: Optional[float] = None
                if is_hashing:
                    if rate_adj is not None:
                        if self._ema_rate is None:
                            self._ema_rate = rate_adj
                        else:
                            self._ema_rate = alpha * rate_adj + (1.0 - alpha) * self._ema_rate
                    if self._ema_rate is not None:
                        rate = self._ema_rate
                else:
                    self._ema_rate = None

                self._prev_progress_cf = cf_now if is_hashing else ""

                data = {
                    "state": progress.state.value if progress.state else "",
                    "files_scanned": progress.files_scanned,
                    "files_total": progress.files_total,
                    "duplicates_found": progress.duplicates_found,
                    "groups_found": progress.groups_found,
                    "bytes_reclaimable": progress.bytes_reclaimable,
                    "elapsed_seconds": progress.elapsed_seconds,
                    "current_file": progress.current_file or "",
                    "current_file_path": progress.current_file_path or progress.current_file or "",
                    "stage": stage,
                    "rate": rate,
                    "total_files_in_scope": int(progress.total_files_in_scope or 0),
                    "files_processed": int(progress.files_processed or 0),
                    "candidates_found": int(progress.candidates_found or 0),
                    "active_hash_algorithm": str(progress.active_hash_algorithm or ""),
                    # camelCase aliases for UI/event consumers
                    "totalFilesInScope": int(progress.total_files_in_scope or 0),
                    "filesProcessed": int(progress.files_processed or 0),
                    "candidatesFound": int(progress.candidates_found or 0),
                    "activeHashAlgorithm": str(progress.active_hash_algorithm or ""),
                    "currentFilePath": progress.current_file_path or progress.current_file or "",
                }
                _log.debug(
                    "progress dispatch: stage=%s scanned=%d total=%d",
                    stage, progress.files_scanned, progress.files_total,
                )
                # Route to UI thread so page.update() runs safely.
                self._deliver_on_ui_thread(self._on_progress, data)
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
