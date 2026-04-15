"""TurboFileEngine — BaseEngine adapter wrapping the high-speed TurboScanner.

This engine wires the already-optimised TurboScanner into the
BaseEngine lifecycle so the GUI gets fast scans with proper progress
reporting, cancellation at phase boundaries, and DuplicateGroup
results identical to the classic FileDedupEngine output shape.

Limitations (v1):
  - pause()/resume() raise NotImplementedError (TurboScanner has no
    mid-scan suspension).  Cancel takes effect at phase boundaries.
  - follow_symlinks is accepted in configure() but TurboScanner's
    recursive walk always follows symlinks when os.scandir is used;
    the option is stored but currently a no-op in the fast path.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from cerebro.engines.base_engine import (
    BaseEngine,
    DuplicateFile,
    DuplicateGroup,
    EngineOption,
    ScanProgress,
    ScanState,
)
from cerebro.core.scanners.turbo_scanner import TurboScanConfig, TurboScanner

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Stage -> ScanState mapping
# ---------------------------------------------------------------------------
_STAGE_MAP: Dict[str, ScanState] = {
    "discovering": ScanState.SCANNING,
    "grouping_by_size": ScanState.SCANNING,
    "hashing_partial": ScanState.SCANNING,
    "hashing_full": ScanState.SCANNING,
    "complete": ScanState.COMPLETED,
}


class TurboFileEngine(BaseEngine):
    """Fast file-dedup engine powered by TurboScanner."""

    # -- BaseEngine abstracts --------------------------------------------------

    def get_name(self) -> str:
        return "files"

    def get_mode_options(self) -> List[EngineOption]:
        return [
            EngineOption(
                key="hash_algorithm",
                label="Hash Algorithm",
                option_type="choice",
                default="sha256",
                choices=["sha256", "xxhash", "blake3", "md5"],
            ),
            EngineOption(
                key="min_size_bytes",
                label="Minimum File Size (bytes)",
                option_type="int",
                default=0,
            ),
            EngineOption(
                key="max_size_bytes",
                label="Maximum File Size (bytes)",
                option_type="int",
                default=0,
            ),
            EngineOption(
                key="include_hidden",
                label="Include Hidden Files",
                option_type="bool",
                default=False,
            ),
            EngineOption(
                key="follow_symlinks",
                label="Follow Symlinks",
                option_type="bool",
                default=False,
            ),
        ]

    # -- lifecycle -------------------------------------------------------------

    def __init__(self) -> None:
        self._folders: List[Path] = []
        self._protected: List[Path] = []
        self._options: Dict[str, Any] = {}
        self._results: List[DuplicateGroup] = []
        self._progress: ScanProgress = ScanProgress()
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

    def get_results(self) -> List[DuplicateGroup]:
        return self._results

    def get_progress(self) -> ScanProgress:
        return self._progress

    # -- internal --------------------------------------------------------------

    def _run_scan(self) -> None:
        try:
            self._do_scan()
        except Exception as exc:
            logger.exception("Turbo scan failed: %s", exc)
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
            follow_symlinks=bool(opts.get("follow_symlinks", False)),
            use_multiprocessing=False,  # safer on Windows; still threaded
            use_quick_hash=True,
            use_full_hash=True,
            hash_algorithm=hash_algo,
            max_group_size=10000,  # 0 in default means "no groups pass" — set high
            progress_callback=self._on_turbo_progress,
        )

        # Filter protected folders out of roots
        roots = [
            f
            for f in self._folders
            if not any(f.is_relative_to(p) for p in self._protected)
        ]

        if not roots:
            self._progress = ScanProgress(state=ScanState.COMPLETED)
            self._emit_progress()
            return

        scanner = TurboScanner(cfg)

        # Drain the generator ( TurboScanner.scan yields nothing but is a gen )
        for _ in scanner.scan(roots):
            if self._cancel_event.is_set():
                self._progress = ScanProgress(state=ScanState.CANCELLED)
                self._emit_progress()
                return

        # Convert scanner.last_groups → DuplicateGroup list
        self._results = self._convert_groups(scanner.last_groups)
        self._progress = ScanProgress(
            state=ScanState.COMPLETED,
            files_scanned=self._progress.files_scanned,
            files_total=self._progress.files_scanned,
            duplicates_found=sum(len(g.files) for g in self._results),
            groups_found=len(self._results),
            bytes_reclaimable=sum(g.reclaimable for g in self._results),
        )
        self._emit_progress()

    # -- progress bridge -------------------------------------------------------

    def _on_turbo_progress(self, stage: str, processed: int, total: int) -> None:
        if self._cancel_event.is_set():
            return

        state = _STAGE_MAP.get(stage, ScanState.SCANNING)
        scanned = processed if stage == "discovering" else self._progress.files_scanned

        self._progress = ScanProgress(
            state=state,
            files_scanned=max(scanned, self._progress.files_scanned),
            files_total=total if total > 0 else self._progress.files_total,
        )
        self._emit_progress()

    def _emit_progress(self) -> None:
        if self._callback:
            try:
                self._callback(self._progress)
            except Exception:
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
