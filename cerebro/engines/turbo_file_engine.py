"""TurboFileEngine — BaseEngine adapter wrapping the high-speed TurboScanner.

This engine wires the already-optimised TurboScanner into the
BaseEngine lifecycle so the GUI gets fast scans with proper progress
reporting, cancellation at phase boundaries, and DuplicateGroup results.

Since the post-v1 audit "single entrance" cleanup, this is the sole
file-dedup scan core in the app. It is registered as mode "files" by
ScanOrchestrator; there is no "files_classic" alternative anymore.

Limitations (v1):
  - pause()/resume() use a threading.Event that gates each hashing worker
    per-file. Pause therefore takes effect within ~1 file (sub-second on
    typical workloads), but does not cancel an in-flight read of a single
    file. Cross-process pausing is not supported (use_multiprocessing=True
    bypasses the gate because threading.Event does not span processes).
  - follow_symlinks is accepted in configure() but TurboScanner's
    recursive walk always follows symlinks when os.scandir is used;
    the option is stored but currently a no-op in the fast path.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from cerebro.core.paths import default_cerebro_cache_dir
from cerebro.core.scanners.turbo_scanner import (
    DEFAULT_DIR_WORKERS,
    DEFAULT_HASH_WORKERS,
    TurboScanConfig,
    TurboScanner,
)
from cerebro.engines.scan_stage import ScanStage
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
# Monotonic terminal-state guard
# ---------------------------------------------------------------------------

# Once a scan enters a terminal state it must not regress to SCANNING/COMPLETED.
_TERMINAL_STATES = frozenset({ScanState.CANCELLED, ScanState.ERROR})

# ---------------------------------------------------------------------------
# I/O-aware hash worker cap
# ---------------------------------------------------------------------------

# Per-drive cache so we only probe once per session: drive_letter → (cap, label)
_storage_cap_cache: dict[str, tuple[int, str]] = {}


def _detect_io_worker_cap(folders: List[Path]) -> tuple[int, str]:
    """Return (max_hash_workers, storage_label) based on detected storage type.

    Conservative caps prevent disk thrash on single-spindle HDDs and avoid
    saturating network mounts.  Users can override via the max_threads option.

    Caps:
      network  → 4   (SMB/NFS latency masks any benefit from extra threads)
      hdd      → 4   (rotational: sequential I/O wins; threads just thrash)
      sata_ssd → 16  (SATA SSD saturates around 16 concurrent readers)
      nvme     → 32  (NVMe can sustain 32+ parallel reads)
      unknown  → 16  (safe middle ground)
    """
    import sys

    # Network paths (UNC \\server\share or forward-slash //host/share)
    for f in folders:
        s = str(f)
        if s.startswith("\\\\") or s.startswith("//"):
            return 4, "network"

    if sys.platform == "win32":
        # Identify the drive letter for the first folder.
        drive = None
        for f in folders:
            try:
                p = Path(f).resolve()
                s = str(p)
                if len(s) >= 2 and s[1] == ":":
                    drive = s[0].upper()
                    break
            except Exception:
                pass

        if drive and drive in _storage_cap_cache:
            return _storage_cap_cache[drive]

        cap, label = _probe_windows_storage(drive)
        if drive:
            _storage_cap_cache[drive] = (cap, label)
        return cap, label

    # Non-Windows: assume SATA SSD
    return 16, "sata_ssd_assumed"


def _probe_windows_storage(drive: Optional[str]) -> tuple[int, str]:
    """Query Windows for disk MediaType via PowerShell (best-effort, ≤3 s)."""
    import subprocess

    if drive is None:
        return 16, "unknown"

    try:
        # Get-PhysicalDisk returns MediaType: 3=HDD, 4=SSD, 5=SCM, 0=Unspecified.
        result = subprocess.run(
            [
                "powershell", "-NoProfile", "-NonInteractive", "-Command",
                "Get-PhysicalDisk | Select-Object MediaType, FriendlyName | ConvertTo-Json",
            ],
            capture_output=True, text=True, timeout=3,
        )
        out = result.stdout.strip()
        if not out:
            return 16, "unknown"

        import json as _json
        data = _json.loads(out)
        if isinstance(data, dict):
            data = [data]
        if not isinstance(data, list):
            return 16, "unknown"

        # Pick the first disk entry (good enough for single-disk machines).
        for entry in data:
            media = entry.get("MediaType", 0)
            name = str(entry.get("FriendlyName", "")).lower()
            if media == 3 or "hdd" in name or "rotational" in name:
                return 4, "hdd"
            if media == 4 or "ssd" in name:
                if "nvme" in name or "nvm" in name:
                    return 32, "nvme"
                return 16, "sata_ssd"
    except Exception:
        pass

    return 16, "unknown"


# ---------------------------------------------------------------------------
# Stage -> ScanState mapping
# ---------------------------------------------------------------------------
_STAGE_MAP: Dict[str, ScanState] = {
    ScanStage.DISCOVERING: ScanState.SCANNING,
    ScanStage.GROUPING_BY_SIZE: ScanState.SCANNING,
    ScanStage.HASHING_PARTIAL: ScanState.SCANNING,
    ScanStage.HASHING_FULL: ScanState.SCANNING,
    ScanStage.CANCELLED: ScanState.CANCELLED,
    # Keep SCANNING until _do_scan emits the final ScanProgress(COMPLETED).
    ScanStage.COMPLETE: ScanState.SCANNING,
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
                default="auto",
                choices=["auto", "xxhash", "blake3", "sha256", "md5"],
                tooltip=(
                    "auto: benchmark xxhash / blake3 / sha256 on a sample and pick the fastest "
                    "(full-file hashing; MD5 is not auto-selected). "
                    "Default scan options use auto + full hash for best speed and byte-accurate duplicates."
                ),
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
            EngineOption(
                name="incremental_scan",
                display_name="Incremental Scan (use hash cache)",
                type="bool",
                default=True,
                tooltip=(
                    "Re-use cached file hashes from previous scans. "
                    "Disable to force a full re-hash of every file."
                ),
            ),
            EngineOption(
                name="scan_archives",
                display_name="Scan inside archives (very slow)",
                type="bool",
                default=False,
                tooltip=(
                    "Extract and compare individual files inside .zip, .tar, .gz, .7z, etc. "
                    "OFF by default: archives are compared as opaque files (fast). "
                    "Enable only if you specifically need to find duplicate files hidden inside archives."
                ),
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
        self._pause_event = threading.Event()
        self._pause_event.set()
        self._callback: Optional[Callable[[ScanProgress], None]] = None
        self._scan_wall_t0: float = 0.0
        self._total_files_in_scope: int = 0
        self._files_processed: int = 0
        self._candidates_found: int = 0
        self._active_hash_algorithm: str = ""
        # Set by _do_scan when resuming; shifts progress bar to start at X% instead of 0%.
        self._ckpt_completed_offset: int = 0
        self._ckpt_total: int = 0

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
        self._pause_event.set()  # ensure unpaused at start
        self._results = []
        self._state = ScanState.SCANNING
        self._progress = ScanProgress(state=ScanState.SCANNING)
        self._scan_wall_t0 = time.monotonic()
        self._total_files_in_scope = 0
        self._files_processed = 0
        self._candidates_found = 0
        self._active_hash_algorithm = ""
        self._ckpt_completed_offset = 0
        self._ckpt_total = 0
        # Run on the orchestrator scan thread (same as other engines). A nested
        # thread here used to return immediately so wait_for_completion() joined
        # before the turbo pipeline finished, leaving get_results() empty.
        self._run_scan()

    def pause(self) -> None:
        self._pause_event.clear()
        self._state = ScanState.PAUSED
        self._progress = ScanProgress(
            state=ScanState.PAUSED,
            files_scanned=self._progress.files_scanned,
            files_total=self._progress.files_total,
            stage=self._progress.stage,
        )
        self._emit_progress()

    def resume(self) -> None:
        self._state = ScanState.SCANNING
        self._progress = ScanProgress(
            state=ScanState.SCANNING,
            files_scanned=self._progress.files_scanned,
            files_total=self._progress.files_total,
            stage=self._progress.stage,
        )
        self._emit_progress()
        self._pause_event.set()  # unblock the scan loop

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
            or "auto"
        ).lower()
        if hash_algo == "auto":
            hash_algo = "auto"
        elif hash_algo == "xxhash":
            try:
                import xxhash  # noqa: F401
            except ImportError:
                hash_algo = "sha256"
                logger.info("xxhash not installed — using sha256 fallback")
        elif hash_algo == "blake3":
            try:
                import blake3  # noqa: F401
            except ImportError:
                hash_algo = "sha256"
                logger.info("blake3 not installed — using sha256 fallback")

        # Parallelism: Settings → max_threads (0 = use scanner defaults).
        max_threads_opt = int(opts.get("max_threads") or 0)
        if max_threads_opt > 0:
            hash_workers = max(1, min(max_threads_opt, DEFAULT_HASH_WORKERS))
            dir_workers = max(1, min(max_threads_opt, DEFAULT_DIR_WORKERS))
        else:
            # I/O-aware cap: avoid disk thrash on HDD/network mounts.
            io_cap, storage_label = _detect_io_worker_cap(self._folders)
            hash_workers = min(DEFAULT_HASH_WORKERS, io_cap)
            dir_workers = DEFAULT_DIR_WORKERS
            logger.info(
                "Turbo storage detection: type=%s → hash_workers capped at %d",
                storage_label,
                hash_workers,
            )

        # Build TurboScanConfig from UI options — accept both naming conventions.
        use_cache = bool(opts.get("incremental_scan", True))

        # Checkpoint / resume wiring.
        # Build a scope dict that uniquely identifies this scan's filter set so
        # find_resumable_manifest can match it against a prior interrupted run.
        _folder_strs = sorted(str(f) for f in self._folders)
        _scope = {
            "min_size": int(opts.get("min_size_bytes") or opts.get("min_size") or 0),
            "max_size": int(opts.get("max_size_bytes") or opts.get("max_size") or 0),
            "skip_hidden": not bool(opts.get("include_hidden", False)),
            "recursive": bool(opts.get("include_subfolders", True)),
            "exclude_paths": sorted(
                str(p) for p in (opts.get("exclude_paths", []) or []) if str(p).strip()
            ),
            "scan_archives": bool(opts.get("scan_archives", False)),
        }
        _ckpt_db = None
        _scan_id = None
        _resume_from_ckpt = False
        _ckpt_total = 0
        _ckpt_completed_offset = 0
        if use_cache:
            try:
                from cerebro.v2.core.checkpoint_db import get_checkpoint_db
                _ckpt_db = get_checkpoint_db()
                _ckpt_db.mark_stale_as_crashed()
                existing = _ckpt_db.find_resumable_manifest(_folder_strs, _scope)
                if existing and bool(opts.get("resume_interrupted_scan")):
                    _scan_id = existing.scan_id
                    _ckpt_total, _ckpt_pending = _ckpt_db.get_counts(_scan_id)
                    _ckpt_completed_offset = _ckpt_total - _ckpt_pending
                    _resume_from_ckpt = _ckpt_pending > 0
                    logger.info(
                        "Checkpoint resume: scan_id=%s total=%d pending=%d completed=%d",
                        _scan_id, _ckpt_total, _ckpt_pending, _ckpt_completed_offset,
                    )
                else:
                    _scan_id = _ckpt_db.create_manifest(_folder_strs, _scope)
                    logger.info("Checkpoint new: scan_id=%s", _scan_id)
            except Exception:
                logger.debug("Checkpoint DB unavailable (non-fatal)", exc_info=True)
                _ckpt_db = None
                _scan_id = None

        self._ckpt_completed_offset = _ckpt_completed_offset
        self._ckpt_total = _ckpt_total

        cfg = TurboScanConfig(
            dir_workers=dir_workers,
            hash_workers=hash_workers,
            min_size=int(opts.get("min_size_bytes") or opts.get("min_size") or 0),
            max_size=int(opts.get("max_size_bytes") or opts.get("max_size") or 0),
            skip_hidden=not bool(opts.get("include_hidden", False)),
            exclude_paths={
                str(p)
                for p in (opts.get("exclude_paths", []) or [])
                if str(p).strip()
            },
            recursive=bool(opts.get("include_subfolders", True)),
            use_multiprocessing=False,
            use_quick_hash=True,
            use_full_hash=True,
            hash_algorithm=hash_algo,
            progress_callback=self._on_turbo_progress,
            cache_dir=default_cerebro_cache_dir() if use_cache else None,
            pause_event=self._pause_event,
            cancel_event=self._cancel_event,
            scan_archives=bool(opts.get("scan_archives", False)),
            checkpoint_db=_ckpt_db,
            scan_id=_scan_id,
            resume_from_checkpoint=_resume_from_ckpt,
        )
        if cfg.scan_archives:
            logger.warning(
                "scan_archives=True: archives will be hashed as opaque blobs only "
                "(internal extraction not yet implemented)."
            )
        logger.info(
            "Turbo workers: hash=%d dir=%d algorithm=%s cache=%s max_threads_setting=%s",
            hash_workers,
            dir_workers,
            hash_algo,
            use_cache,
            max_threads_opt if max_threads_opt > 0 else "auto",
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

        # Validate roots; emit a network_error progress for unreachable paths
        # but continue scanning any reachable ones.
        reachable_roots: List[Path] = []
        for root in roots:
            try:
                if root.exists():
                    reachable_roots.append(root)
                else:
                    logger.warning("Scan root not found, skipping: %s", root)
                    self._progress = ScanProgress(
                        state=ScanState.SCANNING,
                        stage="network_error",
                        current_file=f"Network path unreachable: {root}",
                    )
                    self._emit_progress()
            except (OSError, PermissionError, TimeoutError) as exc:
                logger.warning("Cannot reach scan root %s: %s", root, exc)
                self._progress = ScanProgress(
                    state=ScanState.SCANNING,
                    stage="network_error",
                    current_file=f"Network path unreachable: {root}",
                )
                self._emit_progress()

        if not reachable_roots:
            self._state = ScanState.COMPLETED
            self._progress = ScanProgress(state=ScanState.COMPLETED)
            self._emit_progress()
            return

        scanner = TurboScanner(cfg)

        # Drain the generator (TurboScanner.scan yields FileMetadata rows).
        _cancelled = False
        try:
            for _ in scanner.scan(reachable_roots):
                # Block here while paused; wakes immediately when resumed.
                self._pause_event.wait()
                if self._cancel_event.is_set():
                    _cancelled = True
                    break
        finally:
            scanner.force_emit_cancel_terminal_if_needed()

        # Convert scanner.last_groups → DuplicateGroup list.
        # Drop paths that sit under a protected directory (root filtering above
        # only skips scan roots that are themselves inside protected paths).
        protected = self._protected
        filtered_groups: List[dict] = []
        _asm_deadline = time.monotonic() + 10.0 if _cancelled else None
        for g in scanner.last_groups:
            if _asm_deadline is not None and time.monotonic() > _asm_deadline:
                break
            if self._cancel_event.is_set():
                break
            safe_paths = [
                p
                for p in g.get("paths", [])
                if not any(Path(p).is_relative_to(pp) for pp in protected)
            ]
            if len(safe_paths) >= 2:
                filtered_groups.append({**g, "paths": safe_paths})
        self._results = self._convert_groups(filtered_groups, self._cancel_event)
        # Monotonic: treat cancel_event set at any point as CANCELLED (race-safe).
        _cancelled = _cancelled or self._cancel_event.is_set()
        terminal_state = ScanState.CANCELLED if _cancelled else ScanState.COMPLETED
        # Never downgrade from CANCELLED to COMPLETED (another thread may have called cancel()).
        if self._state in _TERMINAL_STATES:
            terminal_state = self._state
        self._state = terminal_state
        stats_scanned = int(scanner.stats.get("files_scanned", 0) or 0)
        files_done = max(stats_scanned, self._progress.files_scanned)
        terminal_stage = "cancelled" if _cancelled else "complete"
        self._progress = ScanProgress(
            state=terminal_state,
            files_scanned=files_done,
            files_total=max(files_done, self._progress.files_total or 0),
            duplicates_found=sum(len(g.files) for g in self._results),
            groups_found=len(self._results),
            bytes_reclaimable=sum(g.reclaimable for g in self._results),
            stage=terminal_stage,
            total_files_in_scope=max(self._total_files_in_scope, files_done),
            files_processed=max(self._files_processed, files_done),
            candidates_found=self._candidates_found,
            active_hash_algorithm=self._active_hash_algorithm,
        )
        self._emit_progress()

    # -- progress bridge -------------------------------------------------------

    def _on_turbo_progress(
        self,
        stage: str,
        processed: int,
        total: int,
        current_file: str = "",
        metrics: Optional[Dict[str, Any]] = None,
    ) -> None:
        # Monotonic terminal-state guard: once CANCELLED or ERROR, never go back.
        if self._state in _TERMINAL_STATES:
            logger.debug(
                "Suppressed %s progress in terminal state %s", stage, self._state
            )
            return
        if self._cancel_event.is_set() and stage not in (
            ScanStage.COMPLETE,
            ScanStage.CANCELLED,
        ):
            return

        state = _STAGE_MAP.get(stage, ScanState.SCANNING)
        self._state = state
        prev = self._progress
        prev_stage = prev.stage or ""
        metric_data = metrics or {}

        is_hashing = stage in (ScanStage.HASHING_PARTIAL, ScanStage.HASHING_FULL)
        was_hashing = prev_stage in (ScanStage.HASHING_PARTIAL, ScanStage.HASHING_FULL)
        entering_hashing = is_hashing and not was_hashing

        offset = self._ckpt_completed_offset  # files already done in prior session
        total_scope = self._ckpt_total if self._ckpt_total > 0 else total

        if stage == ScanStage.DISCOVERING:
            # On resume the scanner emits completed_offset / total from checkpoint.
            scanned = processed  # may be non-zero if resuming
            ft = total if total > 0 else 0
        elif entering_hashing:
            # Phase handoff: start from offset so bar doesn't reset to 0% on resume.
            scanned = offset
            ft = total_scope if total_scope > 0 else total
        elif is_hashing:
            scanned = processed + offset
            ft = total_scope if total_scope > 0 else (total if total > 0 else (prev.files_total or 0))
        else:
            scanned = max(processed + offset, prev.files_scanned)
            ft = total if total > 0 else (prev.files_total or 0)
            ft = max(ft, prev.files_total or 0)

        self._progress = ScanProgress(
            state=state,
            files_scanned=scanned,
            files_total=ft,
            stage=stage,
            current_file=current_file,
            current_file_path=current_file,
            elapsed_seconds=max(0.0, time.monotonic() - self._scan_wall_t0),
        )
        metric_scope = int(metric_data.get("total_files_in_scope", 0) or 0)
        metric_processed = int(metric_data.get("files_processed", 0) or 0)
        metric_candidates = int(metric_data.get("candidates_found", 0) or 0)
        metric_hash_algo = str(metric_data.get("active_hash_algorithm", "") or "")
        if metric_scope > 0:
            self._total_files_in_scope = max(self._total_files_in_scope, metric_scope)
        if metric_processed >= 0:
            self._files_processed = max(self._files_processed, metric_processed)
        self._candidates_found = max(self._candidates_found, metric_candidates)
        if metric_hash_algo:
            self._active_hash_algorithm = metric_hash_algo

        # Backfill missing metrics from stage counters when scanner callback
        # doesn't provide explicit values (legacy emitters).
        if self._total_files_in_scope <= 0:
            self._total_files_in_scope = max(self._total_files_in_scope, ft, scanned)
        if self._files_processed <= 0:
            self._files_processed = max(0, min(self._total_files_in_scope or scanned, scanned))
        self._progress.total_files_in_scope = self._total_files_in_scope
        self._progress.files_processed = min(
            max(0, self._files_processed),
            max(self._total_files_in_scope, self._files_processed),
        )
        self._progress.candidates_found = self._candidates_found
        self._progress.active_hash_algorithm = self._active_hash_algorithm
        self._emit_progress()

    def _emit_progress(self) -> None:
        if self._callback:
            try:
                self._callback(self._progress)
            except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
                pass

    # -- result conversion -----------------------------------------------------

    @staticmethod
    def _convert_groups(
        raw_groups: List[dict],
        cancel_event: Optional[threading.Event] = None,
    ) -> List[DuplicateGroup]:
        results: List[DuplicateGroup] = []
        for idx, g in enumerate(raw_groups):
            if cancel_event is not None and cancel_event.is_set():
                break
            paths: List[str] = g.get("paths", [])
            if len(paths) < 2:
                continue

            files: List[DuplicateFile] = []
            cancelled_mid_group = False
            for p in paths:
                if cancel_event is not None and cancel_event.is_set():
                    cancelled_mid_group = True
                    break
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

            if cancelled_mid_group:
                break

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
