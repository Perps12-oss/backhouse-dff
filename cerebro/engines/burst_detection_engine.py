"""Burst Detection Engine.

Groups images taken in rapid succession (burst mode on cameras) so the user
can keep only the best shot.  Two images are considered part of the same burst
when they:
  1. Live in the **same folder**.
  2. Were captured within ``burst_gap_seconds`` of each other (EXIF
     DateTimeOriginal, or filesystem mtime as fallback).

Keeper selection: image with the highest Laplacian variance (sharpness proxy)
when PIL is available; falls back to the largest file by size.

Registered in ScanOrchestrator as mode ``"burst"``.
"""
from __future__ import annotations

import dataclasses
import logging
import threading
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from cerebro.engines.base_engine import (
    BaseEngine,
    DuplicateFile,
    DuplicateGroup,
    EngineOption,
    ScanProgress,
    ScanState,
)

logger = logging.getLogger(__name__)

IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".jpe", ".png", ".gif", ".bmp",
    ".tiff", ".tif", ".webp", ".heic", ".heif",
    ".cr2", ".cr3", ".nef", ".arw", ".dng", ".orf",
    ".rw2", ".pef", ".raf", ".sr2",
}

_EXIF_DATETIME_TAG = 36867  # DateTimeOriginal


def _normalize_for_safe_convert(img):
    """Avoid Pillow warning for palette transparency stored as bytes."""
    try:
        transparency = img.info.get("transparency")
    except Exception:
        transparency = None
    if img.mode == "P" and isinstance(transparency, (bytes, bytearray)):
        return img.convert("RGBA")
    return img


def _read_exif_timestamp(path: Path) -> Optional[float]:
    """Return EXIF DateTimeOriginal as a Unix timestamp, or None."""
    try:
        from PIL import Image
        with Image.open(path) as img:
            exif = img._getexif()  # type: ignore[attr-defined]
            if exif and _EXIF_DATETIME_TAG in exif:
                raw = exif[_EXIF_DATETIME_TAG]
                import datetime
                dt = datetime.datetime.strptime(raw, "%Y:%m:%d %H:%M:%S")
                return dt.timestamp()
    except Exception:
        pass
    return None


def _laplacian_variance(path: Path) -> float:
    """Sharpness proxy: variance of the Laplacian (higher = sharper)."""
    try:
        from PIL import Image, ImageFilter
        import statistics
        with Image.open(path) as img:
            img = _normalize_for_safe_convert(img)
            gray = img.convert("L").resize((256, 256))
            lap = list(gray.filter(ImageFilter.FIND_EDGES).getdata())
            mean = sum(lap) / len(lap)
            return statistics.variance(lap, mean)
    except Exception:
        return 0.0


class BurstDetectionEngine(BaseEngine):
    """Detects photo bursts (rapid-fire sequences) in image folders."""

    def get_name(self) -> str:
        return "Burst Detection"

    def get_mode_options(self) -> List[EngineOption]:
        return [
            EngineOption(
                name="burst_gap_seconds",
                display_name="Max Gap Between Shots (seconds)",
                type="int",
                default=3,
                min_value=1,
                max_value=30,
                tooltip=(
                    "Images taken within this many seconds of each other "
                    "in the same folder are treated as a burst."
                ),
            ),
            EngineOption(
                name="min_burst_size",
                display_name="Minimum Burst Size",
                type="int",
                default=3,
                min_value=2,
                max_value=100,
                tooltip="Minimum number of shots to qualify as a burst.",
            ),
            EngineOption(
                name="include_hidden",
                display_name="Include Hidden Files",
                type="bool",
                default=False,
            ),
        ]

    def __init__(self) -> None:
        super().__init__()
        self._results: List[DuplicateGroup] = []
        self._progress = ScanProgress(state=ScanState.IDLE)
        self._cancel_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._callback: Optional[Callable[[ScanProgress], None]] = None

    def configure(self, folders: List[Path], protected: List[Path],
                  options: dict) -> None:
        self._folders = [Path(f) for f in folders]
        self._protected = [Path(p) for p in protected]
        self._options = {
            "burst_gap_seconds": 3,
            "min_burst_size": 3,
            "include_hidden": False,
            **options,
        }

    def start(self, progress_callback: Callable[[ScanProgress], None]) -> None:
        self._cancel_event.clear()
        self._results = []
        self._state = ScanState.SCANNING
        self._progress = ScanProgress(state=ScanState.SCANNING)
        self._callback = progress_callback
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="burst-scan"
        )
        self._thread.start()

    def pause(self) -> None:
        raise NotImplementedError("BurstDetectionEngine does not support pause.")

    def resume(self) -> None:
        raise NotImplementedError("BurstDetectionEngine does not support pause.")

    def cancel(self) -> None:
        self._cancel_event.set()
        self._state = ScanState.CANCELLED

    def get_results(self) -> List[DuplicateGroup]:
        return self._results

    def get_progress(self) -> ScanProgress:
        return self._progress

    # ------------------------------------------------------------------
    # Internal

    def _run(self) -> None:
        try:
            self._do_scan()
        except Exception as exc:
            logger.exception("Burst scan failed: %s", exc)
            self._state = ScanState.ERROR
            self._progress = ScanProgress(state=ScanState.ERROR,
                                          current_file=str(exc))
            if self._callback:
                self._callback(self._progress)

    def _do_scan(self) -> None:
        gap = int(self._options.get("burst_gap_seconds", 3))
        min_size = int(self._options.get("min_burst_size", 3))
        skip_hidden = not bool(self._options.get("include_hidden", False))
        t0 = time.perf_counter()

        # 1. Discover image files
        image_files: List[Path] = []
        for folder in self._folders:
            if self._cancel_event.is_set():
                return
            try:
                for item in folder.rglob("*"):
                    if self._cancel_event.is_set():
                        return
                    if not item.is_file():
                        continue
                    if skip_hidden and item.name.startswith("."):
                        continue
                    if self._protected and any(
                        item.is_relative_to(p) for p in self._protected
                    ):
                        continue
                    if item.suffix.lower() in IMAGE_EXTENSIONS:
                        image_files.append(item)
            except (OSError, PermissionError, TimeoutError) as exc:
                logger.warning("Cannot access folder %s: %s", folder, exc)

        if not image_files:
            self._state = ScanState.COMPLETED
            self._progress = ScanProgress(state=ScanState.COMPLETED)
            if self._callback:
                self._callback(self._progress)
            return

        # 2. Collect timestamps (EXIF first, mtime fallback)
        records: List[Dict] = []
        total = len(image_files)
        for i, path in enumerate(image_files):
            if self._cancel_event.is_set():
                return
            try:
                stat = path.stat()
            except OSError:
                continue
            ts = _read_exif_timestamp(path) or stat.st_mtime
            records.append({
                "path": path,
                "folder": str(path.parent),
                "ts": ts,
                "size": stat.st_size,
                "mtime": stat.st_mtime,
            })
            if i % 25 == 0 and self._callback:
                self._progress = ScanProgress(
                    state=ScanState.SCANNING,
                    files_scanned=i,
                    files_total=total,
                    stage="reading_timestamps",
                )
                self._callback(dataclasses.replace(self._progress))

        # 3. Group by folder, sort by timestamp, split on gaps
        by_folder: Dict[str, List[Dict]] = {}
        for rec in records:
            by_folder.setdefault(rec["folder"], []).append(rec)

        groups: List[DuplicateGroup] = []
        group_id = 0

        for folder_records in by_folder.values():
            folder_records.sort(key=lambda r: r["ts"])
            burst: List[Dict] = [folder_records[0]]
            for rec in folder_records[1:]:
                if rec["ts"] - burst[-1]["ts"] <= gap:
                    burst.append(rec)
                else:
                    if len(burst) >= min_size:
                        g = self._make_group(group_id, burst)
                        if g:
                            groups.append(g)
                            group_id += 1
                    burst = [rec]
            if len(burst) >= min_size:
                g = self._make_group(group_id, burst)
                if g:
                    groups.append(g)
                    group_id += 1

        self._results = groups
        self._state = ScanState.COMPLETED
        logger.info(
            "Burst scan: %.2fs, %d images, %d bursts",
            time.perf_counter() - t0, len(records), len(groups),
        )
        self._progress = ScanProgress(
            state=ScanState.COMPLETED,
            files_scanned=len(records),
            files_total=len(records),
            groups_found=len(groups),
            duplicates_found=sum(len(g.files) - 1 for g in groups),
            bytes_reclaimable=sum(g.reclaimable for g in groups),
        )
        if self._callback:
            self._callback(self._progress)

    def _make_group(self, group_id: int, burst: List[Dict]) -> Optional[DuplicateGroup]:
        if len(burst) < 2:
            return None

        # Pick keeper by sharpness; fall back to largest size
        sharpness: List[Tuple[float, Dict]] = []
        for rec in burst:
            score = _laplacian_variance(rec["path"])
            sharpness.append((score, rec))

        best_score = max(s for s, _ in sharpness)
        if best_score > 0:
            keeper_rec = max(sharpness, key=lambda x: x[0])[1]
        else:
            keeper_rec = max(burst, key=lambda r: r["size"])

        total_size = sum(r["size"] for r in burst)
        reclaimable = total_size - keeper_rec["size"]

        files = [
            DuplicateFile(
                path=rec["path"],
                size=rec["size"],
                modified=rec["mtime"],
                extension=rec["path"].suffix.lower(),
                is_keeper=(rec is keeper_rec),
                similarity=1.0,
            )
            for rec in burst
        ]
        return DuplicateGroup(
            group_id=group_id,
            files=files,
            total_size=total_size,
            reclaimable=reclaimable,
            similarity_type="burst",
        )
