"""TurboFileEngine — BaseEngine adapter wrapping the high-speed TurboScanner.

This engine wires the already-optimised TurboScanner into the
BaseEngine lifecycle so the GUI gets fast scans with proper progress
reporting, cancellation at phase boundaries, and DuplicateGroup results.

Since the post-v1 audit "single entrance" cleanup, this is the sole
file-dedup scan core in the app. It is registered as mode "files" by
ScanOrchestrator; there is no "files_classic" alternative anymore.

Limitations (v1):
  - pause()/resume() raise NotImplementedError (TurboScanner has no
    mid-scan suspension).  Cancel takes effect at phase boundaries.
  - follow_symlinks is accepted in configure() but TurboScanner's
    recursive walk always follows symlinks when os.scandir is used;
    the option is stored but currently a no-op in the fast path.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from cerebro.core.scanners.turbo_scanner import TurboScanConfig, TurboScanner
from cerebro.engines.base_engine import (
    BaseEngine,
    DuplicateFile,
    DuplicateGroup,
    EngineOption,
    ScanProgress,
    ScanState,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Stage -> ScanState mapping
# ---------------------------------------------------------------------------
_STAGE_MAP: Dict[str, ScanState] = {
    "discovering": ScanState.SCANNING,
    "grouping_by_size": ScanState.SCANNING,
    "hashing_partial": ScanState.SCANNING,
    "hashing_full": ScanState.SCANNING,
    # Keep SCANNING until _do_scan emits the final ScanProgress(COMPLETED).
    "complete": ScanState.SCANNING,
}


class TurboFileEngine(BaseEngine):
    """Fast file-dedup engine powered by TurboScanner."""

    # -- BaseEngine abstracts --------------------------------------------------

    def get_name(self) -> str:
        return "files"

    def get_mode_options(self) -> List[EngineOption]:
        return [
            EngineOption(
                name="hash_algorithm",
                display_name="Hash Algorithm",
                type="choice",
                default="sha256",
                choices=["sha256", "xxhash", "blake3", "md5"],
            ),
            EngineOption(
                name="min_size_bytes",
                display_name="Minimum File Size (bytes)",
                type="int",
                default=0,
            ),
            EngineOption(
                name="max_size_bytes",
                display_name="Maximum File Size (bytes)",
                type="int",
                default=0,
            ),
            EngineOption(
                name="include_hidden",
                display_name="Include Hidden Files",
                type="bool",
                default=False,
            ),
            EngineOption(
                name="follow_symlinks",
                display_name="Follow Symlinks",
                type="bool",
                default=False,
            ),
        ]

    # -- lifecycle -------------------------------------------------------------

    def __init__(self) -> None:
        super().__init__()
        self._folders: List[Path] = []
        self._protected: List[Path] = []
        self._options: Dict[str, Any] = {}
        self._results: List[DuplicateGroup] = []
        self._progress: ScanProgress = ScanProgress(state=ScanState.IDLE)
        self._cancel_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._callback: Optional[Callable[[ScanProgress], None]] = None

    def configure(
        self,
        folders: List[Path],
        protected: List[Path],
        options: Dict[str, Any],
    ) -> None:
        self._folders = list(folders)
        self._protected = list(protected)
        self._options = dict(options)

    def start(self, progress_callback: Callable[[ScanProgress], None]) -> None:
        self._callback = progress_callback
        self._cancel_event.clear()
        self._results = []
        self._state = ScanState.SCANNING
        self._progress = ScanProgress(state=ScanState.SCANNING)
        self._thread = threading.Thread(
            target=self._run_scan, daemon=True, name="turbo-scan"
        )
        self._thread.start()

    def pause(self) -> None:
        raise NotImplementedError("TurboFileEngine does not support pause/resume.")

    def resume(self) -> None:
        raise NotImplementedError("TurboFileEngine does not support pause/resume.")

    def cancel(self) -> None:
        self._cancel_event.set()
        self._state = ScanState.CANCELLED

    def get_results(self) -> List[DuplicateGroup]:
        return self._results

    def get_progress(self) -> ScanProgress:
        return self._progress

    # -- internal --------------------------------------------------------------

    def _run_scan(self) -> None:
        try:
            self._state = ScanState.SCANNING
            self._do_scan()
        except (sqlite3.Error, OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError) as exc:
            logger.exception("Turbo scan failed: %s", exc)
            self._state = ScanState.ERROR
            self._progress = ScanProgress(state=ScanState.ERROR)
            self._emit_progress()

    def _do_scan(self) -> None:
        opts = self._options

        # Resolve hash algorithm — support both key names used in the wild.
        hash_algo = str(
            opts.get("hash_algorithm")
            or opts.get("hash_algo")
            or "sha256"
        ).lower()
        if hash_algo == "xxhash":
            try:
                import xxhash  # noqa: F401
            except ImportError:
                hash_algo = "sha256"
                logger.info("xxhash not installed — using sha256 fallback")

        # Build TurboScanConfig from UI options — accept both naming conventions.
        cfg = TurboScanConfig(
            min_size=int(opts.get("min_size_bytes") or opts.get("min_size") or 0),
            max_size=int(opts.get("max_size_bytes") or opts.get("max_size") or 0),
            skip_hidden=not bool(opts.get("include_hidden", False)),
            use_multiprocessing=False,  # safer on Windows; still threaded
            use_quick_hash=True,
            use_full_hash=True,
            hash_algorithm=hash_algo,
            progress_callback=self._on_turbo_progress,
        )

        # Filter protected folders out of roots
        roots = [
            f
            for f in self._folders
            if not any(f.is_relative_to(p) for p in self._protected)
        ]

        if not roots:
            self._state = ScanState.COMPLETED
            self._progress = ScanProgress(state=ScanState.COMPLETED)
            self._emit_progress()
            return

        scanner = TurboScanner(cfg)

        # Drain the generator ( TurboScanner.scan yields nothing but is a gen )
        for _ in scanner.scan(roots):
            if self._cancel_event.is_set():
                self._state = ScanState.CANCELLED
                self._progress = ScanProgress(state=ScanState.CANCELLED)
                self._emit_progress()
                return

        # Convert scanner.last_groups → DuplicateGroup list
        self._results = self._convert_groups(scanner.last_groups)
        self._state = ScanState.COMPLETED
        self._progress = ScanProgress(
            state=ScanState.COMPLETED,
            files_scanned=self._progress.files_scanned,
            files_total=self._progress.files_scanned,
            duplicates_found=sum(len(g.files) for g in self._results),
            groups_found=len(self._results),
            bytes_reclaimable=sum(g.reclaimable for g in self._results),
            stage="complete",
        )
        self._emit_progress()

    # -- progress bridge -------------------------------------------------------

    def _on_turbo_progress(self, stage: str, processed: int, total: int) -> None:
        if self._cancel_event.is_set():
            return

        state = _STAGE_MAP.get(stage, ScanState.SCANNING)
        self._state = state
        prev = self._progress
        # Keep a monotonic scan counter; hashing phases report progress for the current
        # batch only, which can be smaller than the discovery count — never shrink total.
        scanned = max(processed, prev.files_scanned)
        ft = total if total > 0 else (prev.files_total or 0)
        ft = max(ft, prev.files_total or 0, scanned)

        self._progress = ScanProgress(
            state=state,
            files_scanned=scanned,
            files_total=ft,
            stage=stage,
        )
        self._emit_progress()

    def _emit_progress(self) -> None:
        if self._callback:
            try:
                self._callback(self._progress)
            except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
                pass

    # -- result conversion -----------------------------------------------------

    @staticmethod
    def _convert_groups(raw_groups: List[dict]) -> List[DuplicateGroup]:
        results: List[DuplicateGroup] = []
        for idx, g in enumerate(raw_groups):
            paths: List[str] = g.get("paths", [])
            if len(paths) < 2:
                continue

            files: List[DuplicateFile] = []
            for p in paths:
                pp = Path(p)
                try:
                    st = pp.stat()
                    files.append(
                        DuplicateFile(
                            path=pp,
                            size=st.st_size,
                            modified=st.st_mtime,
                            extension=pp.suffix.lower(),
                            is_keeper=False,
                            similarity=1.0,
                            metadata={},
                        )
                    )
                except OSError:
                    continue

            if len(files) < 2:
                continue

            total_size = sum(f.size for f in files)
            keeper_size = max(f.size for f in files)
            results.append(
                DuplicateGroup(
                    group_id=idx,
                    files=files,
                    total_size=total_size,
                    reclaimable=total_size - keeper_size,
                    similarity_type="exact",
                )
            )
        return results
