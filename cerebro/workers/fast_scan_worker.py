# cerebro/workers/fast_scan_worker.py
from __future__ import annotations

import sys
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from PySide6.QtCore import QThread, Signal, QObject

from collections import defaultdict

from cerebro.core.fast_pipeline import FastPipeline
from cerebro.core.models import ScanProgress


def _allowed_extensions_for_media_type(media_type: str) -> Optional[List[str]]:
    media_type = (media_type or "all").lower()
    mapping = {
        "images": [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff"],
        "video": [".mp4", ".mkv", ".avi", ".mov", ".wmv", ".webm"],
        "music": [".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a"],
        "documents": [".pdf", ".doc", ".docx", ".txt", ".rtf"],
    }
    return mapping.get(media_type)


def _meta_path(meta: Any) -> str:
    """Path from scanner result (dict or object)."""
    if hasattr(meta, "path"):
        return str(meta.path)
    return str(meta.get("path", "")) if isinstance(meta, dict) else ""


def _meta_size(meta: Any) -> int:
    """Size from scanner result (dict or object)."""
    if hasattr(meta, "size"):
        return int(meta.size)
    return int(meta.get("size", 0)) if isinstance(meta, dict) else 0


def _meta_hash(meta: Any) -> Any:
    """Hash from scanner result (dict or object)."""
    if hasattr(meta, "hash"):
        return meta.hash
    return meta.get("hash") if isinstance(meta, dict) else None


@dataclass(frozen=True, slots=True)
class FastScanConfig:
    root: str
    min_size_bytes: int = 1024
    include_hidden: bool = False
    follow_symlinks: bool = False
    allowed_extensions: Optional[List[str]] = None
    exclude_dirs: Optional[List[str]] = None
    max_workers: int = 0  # 0 = auto
    cache_path: Optional[str] = None
    scan_name: Optional[str] = None
    media_type: str = "all"
    engine: str = "simple"
    scanner_tier: str = "turbo"  # NEW: turbo/ultra/quantum

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "FastScanConfig":
        if "root" not in d:
            raise ValueError("FastScanConfig requires 'root'")
        allowed = d.get("allowed_extensions") or d.get("file_types")
        media_type = str(d.get("media_type", "all")).lower()
        if not allowed and media_type and media_type != "all":
            allowed = _allowed_extensions_for_media_type(media_type)
        if allowed is not None:
            allowed = [e if e.startswith(".") else f".{e}" for e in (allowed or [])]
        return cls(
            root=str(d["root"]),
            min_size_bytes=int(d.get("min_size_bytes", 1024)),
            include_hidden=bool(d.get("include_hidden", False)),
            follow_symlinks=bool(d.get("follow_symlinks", False)),
            allowed_extensions=allowed or None,
            exclude_dirs=list(d.get("exclude_dirs") or []) or None,
            max_workers=int(d.get("max_workers", 0)),
            cache_path=d.get("cache_path"),
            scan_name=d.get("scan_name"),
            media_type=media_type,
            engine=str(d.get("engine", "simple")).lower(),
            scanner_tier=str(d.get("scanner_tier", "turbo")).lower(),  # NEW
        )


class FastScanWorker(QThread):
    """
    PySide6-only.
    Emits semantic scan signals consumed by LiveScanController.

    Signals:
      - progress_updated(ScanProgress)
      - phase_changed(str)
      - file_changed(str)
      - group_discovered(int)      # delta (typically +1)
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
        self._cfg = FastScanConfig.from_dict(config)
        self._pipeline: Optional[FastPipeline] = None
        self._cancelled = False

        self._start_ts = 0.0
        self._last_groups = 0

    def cancel(self) -> None:
        self._cancelled = True
        if self._pipeline is not None:
            try:
                self._pipeline.cancel()
            except Exception:
                pass

    def run(self) -> None:
        self._start_ts = time.perf_counter()
        self._last_groups = 0

        try:
            root = str(self._cfg.root)
            
            # Check if using optimized scanner tiers
            if self._cfg.scanner_tier in ("turbo", "ultra", "quantum"):
                self._run_optimized_scan()
                return
            
            # Fall back to legacy FastPipeline
            self._pipeline = FastPipeline(
                max_workers=self._cfg.max_workers,
                cache_path=self._cfg.cache_path,
                engine=self._cfg.engine,
            )

            def progress_cb(percent: int, message: str, stats: Dict[str, Any]) -> None:
                if self._cancelled:
                    return

                phase = str(stats.get("phase") or "")
                if phase:
                    self.phase_changed.emit(phase)

                current_path = str(stats.get("current_path") or stats.get("current_file") or "")
                if current_path:
                    self.file_changed.emit(current_path)

                groups_found = stats.get("groups_found")
                if groups_found is not None:
                    try:
                        g = int(groups_found)
                        delta = g - self._last_groups
                        if delta > 0:
                            self.group_discovered.emit(delta)
                        self._last_groups = g
                    except Exception:
                        pass

                warn = stats.get("warning")
                if warn:
                    self.warning_raised.emit(current_path, str(warn))

                elapsed = max(0.0, time.perf_counter() - self._start_ts)
                prog = ScanProgress(
                    phase=phase,
                    message=str(message or ""),
                    percent=float(percent),
                    scanned_files=int(stats.get("scanned_files", stats.get("files_scanned", 0)) or 0),
                    scanned_bytes=int(stats.get("scanned_bytes", stats.get("bytes_scanned", 0)) or 0),
                    elapsed_seconds=float(stats.get("elapsed_seconds", stats.get("elapsed", elapsed)) or elapsed),
                    estimated_total_files=stats.get("estimated_total_files", stats.get("total_files")),
                    estimated_total_bytes=stats.get("estimated_total_bytes", stats.get("total_bytes")),
                    current_path=current_path or None,
                )
                self.progress_updated.emit(prog)

            result = self._pipeline.run_fast_scan(
                root,
                min_size=self._cfg.min_size_bytes,
                include_hidden=self._cfg.include_hidden,
                follow_symlinks=self._cfg.follow_symlinks,
                allowed_extensions=self._cfg.allowed_extensions,
                exclude_dirs=self._cfg.exclude_dirs,
                progress_cb=progress_cb,
            )

            if self._cancelled or bool(result.get("cancelled", False)):
                self.cancelled.emit()
                return

            # Normalize payload fields for UI
            payload = dict(result or {})
            payload.setdefault("scan_root", root)
            payload.setdefault("scan_name", self._cfg.scan_name or f"Scan of {root}")
            payload.setdefault("groups", payload.get("groups") or [])
            payload.setdefault("file_count", int(payload.get("file_count", 0) or 0))
            payload.setdefault("total_size", int(payload.get("total_size", 0) or 0))
            payload.setdefault("scan_duration", float(payload.get("scan_duration", 0.0) or 0.0))

            self.finished.emit(payload)

        except Exception as e:
            msg = f"{e}"
            tb = traceback.format_exc()
            self.error_occurred.emit(msg)
            self.failed.emit(tb)
    
    def _run_optimized_scan(self) -> None:
        """Run scan using optimized scanner tiers (Turbo/Ultra/Quantum)."""
        try:
            root = Path(self._cfg.root)
            tier = self._cfg.scanner_tier
            
            # Phase: Setup
            self.phase_changed.emit("Initializing scanner...")
            
            # Initialize the appropriate scanner
            scanner = None
            scanner_name = "Unknown"
            
            if tier == "turbo":
                try:
                    from cerebro.core.scanner_adapter import create_optimized_scanner
                    scanner = create_optimized_scanner()
                    scanner_name = "TurboScanner"
                    self.phase_changed.emit("TurboScanner initialized (12x faster)")
                except ImportError as e:
                    self.failed.emit(f"TurboScanner not available: {e}")
                    return
            
            elif tier == "ultra":
                try:
                    from cerebro.core.scanners.ultra_scanner import UltraScanner, UltraScanConfig
                    
                    config = UltraScanConfig(
                        min_size=self._cfg.min_size_bytes,
                        skip_hidden=not self._cfg.include_hidden,
                        exclude_dirs=set(self._cfg.exclude_dirs or []),
                        use_bloom_filter=True,
                        use_simd_hash=True,
                        use_everything_sdk=(sys.platform == 'win32'),
                        dir_workers=min(64, self._cfg.max_workers * 4) if self._cfg.max_workers else 64,
                        hash_workers=min(128, self._cfg.max_workers * 8) if self._cfg.max_workers else 128,
                    )
                    
                    scanner = UltraScanner(config)
                    scanner_name = "UltraScanner"
                    self.phase_changed.emit("UltraScanner initialized (60x faster)")
                except ImportError as e:
                    self.failed.emit(f"UltraScanner not available: {e}\nInstall: pip install xxhash mmh3 numpy")
                    return
            
            elif tier == "quantum":
                try:
                    from cerebro.core.scanners.quantum_scanner import QuantumScanner, QuantumScanConfig
                    
                    config = QuantumScanConfig(
                        use_gpu=True,
                        gpu_device="cuda",
                        use_neural_predictor=True,
                        use_async_io=True,
                    )
                    
                    scanner = QuantumScanner(config)
                    scanner_name = "QuantumScanner"
                    self.phase_changed.emit("QuantumScanner initialized (180x+ faster)")
                except ImportError as e:
                    self.failed.emit(f"QuantumScanner not available: {e}\nInstall: pip install cupy-cuda12x torch pyzmq")
                    return
            
            if not scanner:
                self.failed.emit(f"Unknown scanner tier: {tier}")
                return
            
            # Phase: Discovery
            self.phase_changed.emit(f"{scanner_name}: Discovering files...")
            
            files_found = []
            groups_found = {}
            processed_count = 0
            total_size = 0
            
            # Scan files (file_meta can be dict or object with path/hash/size)
            for file_meta in scanner.scan([root]):
                if self._cancelled:
                    self.cancelled.emit()
                    return
                
                processed_count += 1
                total_size += _meta_size(file_meta)
                
                # Update progress every 100 files
                if processed_count % 100 == 0:
                    elapsed = time.perf_counter() - self._start_ts
                    progress = ScanProgress(
                        phase=f"Scanning with {scanner_name}",
                        message=f"Processed {processed_count:,} files",
                        percent=0.0,  # Unknown total
                        scanned_files=processed_count,
                        scanned_bytes=total_size,
                        elapsed_seconds=elapsed,
                        current_path=_meta_path(file_meta),
                    )
                    self.progress_updated.emit(progress)
                    self.file_changed.emit(_meta_path(file_meta))
                
                files_found.append(file_meta)
            
            # Phase: Complete
            elapsed = time.perf_counter() - self._start_ts
            self.phase_changed.emit(f"{scanner_name}: Completed")
            
            # Build result: use scanner's last_groups so Review page has duplicate groups
            groups_list = getattr(scanner, "last_groups", None) or []
            if not groups_list and hasattr(scanner, "scanner"):
                groups_list = getattr(scanner.scanner, "last_groups", None) or []
            # Quantum/Ultra return flat file list: build duplicate groups by hash for Review
            if not groups_list and files_found:
                by_hash = defaultdict(list)
                for meta in files_found:
                    h = _meta_hash(meta)
                    if h is not None:
                        by_hash[h].append(meta)
                for h, metas in by_hash.items():
                    if len(metas) < 2:
                        continue
                    paths = [_meta_path(m) for m in metas]
                    sizes = [_meta_size(m) for m in metas]
                    groups_list.append({
                        "paths": paths,
                        "hash": str(h),
                        "count": len(paths),
                        "recoverable_bytes": sum(sizes),
                    })
            result = {
                "scan_root": str(root),
                "scan_name": self._cfg.scan_name or f"Scan of {root}",
                "file_count": processed_count,
                "total_size": total_size,
                "scan_duration": elapsed,
                "scanner_tier": tier,
                "scanner_name": scanner_name,
                "groups": groups_list,
                "group_count": len(groups_list),
                "duplicate_count": sum(g.get("count", len(g.get("paths", []))) for g in groups_list),
                "cancelled": False,
            }
            
            # Final progress
            progress = ScanProgress(
                phase="Complete",
                message=f"Scanned {processed_count:,} files in {elapsed:.1f}s",
                percent=100.0,
                scanned_files=processed_count,
                scanned_bytes=total_size,
                elapsed_seconds=elapsed,
            )
            self.progress_updated.emit(progress)
            
            self.finished.emit(result)
            
        except Exception as e:
            msg = f"{e}"
            tb = traceback.format_exc()
            self.error_occurred.emit(msg)
            self.failed.emit(tb)
