"""
Video Deduplication Engine

Detects duplicate/near-duplicate videos using FFmpeg frame extraction
and perceptual hashing (dHash) on keyframes.

Falls back to metadata-only matching (duration + size) when FFmpeg is
not installed.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
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

# Video file extensions
VIDEO_EXTENSIONS = {
    ".mp4", ".avi", ".mkv", ".mov", ".wmv", ".flv", ".webm",
    ".m4v", ".mpg", ".mpeg", ".3gp", ".ts", ".mts", ".m2ts",
}

# Number of keyframes to extract per video for comparison
KEYFRAME_COUNT = 5

# Maximum hamming distance between dHash pairs to be considered duplicates
DHASH_THRESHOLD = 10  # out of 64 bits


def _ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def _dhash(image_path: Path, size: int = 8) -> Optional[int]:
    """Compute dHash of an image file. Returns None if PIL not available."""
    try:
        from PIL import Image
        img = Image.open(image_path).convert("L").resize(
            (size + 1, size), Image.LANCZOS
        )
        pixels = list(img.getdata())
        bits = []
        for row in range(size):
            for col in range(size):
                bits.append(1 if pixels[row * (size + 1) + col] >
                            pixels[row * (size + 1) + col + 1] else 0)
        h = 0
        for bit in bits:
            h = (h << 1) | bit
        return h
    except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
        return None


def _hamming_distance(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def _extract_keyframes(video_path: Path, n: int, out_dir: Path) -> List[Path]:
    """Use FFmpeg to extract n evenly-spaced frames from a video."""
    frames = []
    try:
        # Get duration first
        result = subprocess.run(
            [
                "ffprobe", "-v", "error", "-show_entries",
                "format=duration", "-of", "default=noprint_wrappers=1:nokey=1",
                str(video_path),
            ],
            capture_output=True, text=True, timeout=10,
        )
        duration = float(result.stdout.strip() or "0")
        if duration <= 0:
            return []

        for i in range(n):
            t = duration * (i + 1) / (n + 1)
            out_file = out_dir / f"frame_{i:02d}.jpg"
            subprocess.run(
                [
                    "ffmpeg", "-ss", str(t), "-i", str(video_path),
                    "-vframes", "1", "-q:v", "5", str(out_file),
                    "-y", "-loglevel", "error",
                ],
                capture_output=True, timeout=15,
            )
            if out_file.exists():
                frames.append(out_file)
    except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
        pass
    return frames


def _video_signature(video_path: Path, use_ffmpeg: bool) -> Optional[Tuple]:
    """
    Compute a video signature for comparison.
    Returns (duration_s, size_bytes, frame_hashes) or None on failure.
    """
    try:
        stat = video_path.stat()
        size = stat.st_size
    except OSError:
        return None

    duration = 0.0
    if use_ffmpeg:
        try:
            result = subprocess.run(
                [
                    "ffprobe", "-v", "error", "-show_entries",
                    "format=duration", "-of",
                    "default=noprint_wrappers=1:nokey=1",
                    str(video_path),
                ],
                capture_output=True, text=True, timeout=10,
            )
            duration = float(result.stdout.strip() or "0")
        except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
            pass

    frame_hashes: List[int] = []
    if use_ffmpeg:
        with tempfile.TemporaryDirectory() as tmp:
            frames = _extract_keyframes(video_path, KEYFRAME_COUNT, Path(tmp))
            for f in frames:
                h = _dhash(f)
                if h is not None:
                    frame_hashes.append(h)

    return (duration, size, tuple(frame_hashes))


def _similarity(sig_a: Tuple, sig_b: Tuple, dur_tol: float = 2.0) -> float:
    """Return similarity 0.0–1.0 between two video signatures."""
    dur_a, size_a, hashes_a = sig_a
    dur_b, size_b, hashes_b = sig_b

    # Duration must be within tolerance (or both 0 if metadata unavailable)
    if abs(dur_a - dur_b) > dur_tol and not (dur_a == 0 and dur_b == 0):
        return 0.0

    # Size within 5% → base similarity
    if size_a == 0 or size_b == 0:
        return 0.0
    size_ratio = min(size_a, size_b) / max(size_a, size_b)
    if size_ratio < 0.5:
        return 0.0

    if hashes_a and hashes_b:
        n = min(len(hashes_a), len(hashes_b))
        matched = sum(
            1 for i in range(n)
            if _hamming_distance(hashes_a[i], hashes_b[i]) <= DHASH_THRESHOLD
        )
        return matched / n

    # Fallback: duration + size only
    dur_sim = 1.0 - min(abs(dur_a - dur_b), dur_tol) / dur_tol if dur_tol > 0 else 1.0
    return (dur_sim + size_ratio) / 2.0


class VideoDedupEngine(BaseEngine):
    """
    Video duplicate detection engine.

    Uses FFmpeg keyframe extraction + perceptual hashing when available.
    Falls back to duration + size comparison otherwise.
    """

    def __init__(self):
        super().__init__()
        self._results: List[DuplicateGroup] = []
        self._progress = ScanProgress(state=ScanState.IDLE)
        self._cancel_event = threading.Event()
        self._pause_event = threading.Event()
        self._ffmpeg = _ffmpeg_available()

    def get_name(self) -> str:
        suffix = "" if self._ffmpeg else " (metadata-only, FFmpeg not found)"
        return f"Video Deduplication{suffix}"

    def get_mode_options(self) -> List[EngineOption]:
        return [
            EngineOption(
                name="similarity_threshold",
                display_name="Similarity Threshold (%)",
                type="int",
                default=85,
                min_value=50,
                max_value=100,
                tooltip="Minimum frame-hash similarity to flag as duplicate",
            ),
            EngineOption(
                name="duration_tolerance",
                display_name="Duration Tolerance (s)",
                type="int",
                default=2,
                min_value=0,
                max_value=30,
                tooltip="Allow this many seconds difference in video duration",
            ),
            EngineOption(
                name="min_size_mb",
                display_name="Minimum Size (MB)",
                type="int",
                default=1,
                min_value=0,
                max_value=10_000,
                tooltip="Skip videos smaller than this size",
            ),
        ]

    def configure(self, folders, protected, options) -> None:
        self._folders = folders
        self._protected = protected
        self._options = options

    def start(self, progress_callback: Callable[[ScanProgress], None]) -> None:
        self._cancel_event.clear()
        self._pause_event.clear()
        self._results = []
        self._state = ScanState.SCANNING
        self._run_scan(progress_callback)

    def _run_scan(self, cb: Callable[[ScanProgress], None]) -> None:
        threshold = self._options.get("similarity_threshold", 85) / 100.0
        dur_tol = float(self._options.get("duration_tolerance", 2))
        min_size = self._options.get("min_size_mb", 1) * 1024 * 1024

        # Collect video files
        video_files: List[Path] = []
        for folder in self._folders:
            for root, _, files in os.walk(folder):
                for fname in files:
                    p = Path(root) / fname
                    if p.suffix.lower() in VIDEO_EXTENSIONS:
                        try:
                            if p.stat().st_size >= min_size:
                                video_files.append(p)
                        except OSError:
                            pass

        total = len(video_files)
        cb(ScanProgress(state=ScanState.SCANNING, files_total=total, current_file="Computing signatures…"))

        # Compute signatures
        signatures: Dict[Path, Tuple] = {}
        for i, vf in enumerate(video_files):
            if self._cancel_event.is_set():
                break
            while self._pause_event.is_set():
                time.sleep(0.1)
            sig = _video_signature(vf, self._ffmpeg)
            if sig:
                signatures[vf] = sig
            cb(ScanProgress(
                state=ScanState.SCANNING,
                files_scanned=i + 1,
                files_total=total,
                current_file=str(vf),
            ))

        if self._cancel_event.is_set():
            self._state = ScanState.CANCELLED
            cb(ScanProgress(state=ScanState.CANCELLED))
            return

        # Compare all pairs
        paths = list(signatures.keys())
        groups: List[List[Path]] = []
        grouped = set()

        for i in range(len(paths)):
            if paths[i] in grouped:
                continue
            group = [paths[i]]
            for j in range(i + 1, len(paths)):
                if paths[j] in grouped:
                    continue
                sim = _similarity(signatures[paths[i]], signatures[paths[j]], dur_tol)
                if sim >= threshold:
                    group.append(paths[j])
            if len(group) > 1:
                for p in group:
                    grouped.add(p)
                groups.append(group)

        # Build DuplicateGroup objects
        for gid, group in enumerate(groups):
            files = []
            for p in group:
                try:
                    stat = p.stat()
                    sig = signatures.get(p)
                    dur = sig[0] if sig else 0.0
                    files.append(DuplicateFile(
                        path=p, size=stat.st_size, modified=stat.st_mtime,
                        extension=p.suffix.lower(), similarity=threshold,
                        metadata={"duration": dur},
                    ))
                except OSError:
                    pass
            if len(files) > 1:
                # Keep largest as default keeper
                files.sort(key=lambda f: f.size, reverse=True)
                files[0].is_keeper = True
                dg = DuplicateGroup(group_id=gid, files=files)
                self._results.append(dg)

        self._state = ScanState.COMPLETED
        cb(ScanProgress(
            state=ScanState.COMPLETED,
            files_scanned=total,
            files_total=total,
            groups_found=len(self._results),
            duplicates_found=sum(len(g.files) - 1 for g in self._results),
            bytes_reclaimable=sum(g.reclaimable for g in self._results),
        ))

    def pause(self) -> None:
        self._pause_event.set()
        self._state = ScanState.PAUSED

    def resume(self) -> None:
        self._pause_event.clear()
        self._state = ScanState.SCANNING

    def cancel(self) -> None:
        self._cancel_event.set()
        self._state = ScanState.CANCELLED

    def get_results(self) -> List[DuplicateGroup]:
        return self._results

    def get_progress(self) -> ScanProgress:
        return self._progress
