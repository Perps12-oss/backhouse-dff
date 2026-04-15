"""
Music Deduplication Engine

Detects duplicate audio files using ID3/Vorbis tag metadata (title, artist,
album, duration) and fuzzy string matching.

Requires: mutagen (graceful fallback to filename+duration if not installed)
"""

from __future__ import annotations

import os
import re
import threading
import time
from difflib import SequenceMatcher
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

AUDIO_EXTENSIONS = {
    ".mp3", ".flac", ".ogg", ".wav", ".aac", ".m4a", ".wma",
    ".opus", ".ape", ".aiff", ".alac", ".dsf",
}

# Format quality ranking (higher = better quality — prefer to keep)
FORMAT_RANK = {
    ".flac": 10, ".alac": 10, ".ape": 9, ".dsf": 9, ".wav": 8, ".aiff": 8,
    ".ogg": 6, ".opus": 6, ".m4a": 5, ".aac": 5, ".wma": 4, ".mp3": 3,
}


def _normalize(s: str) -> str:
    """Lowercase, strip punctuation and extra whitespace for fuzzy matching."""
    s = s.lower()
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _similarity_ratio(a: str, b: str) -> float:
    if not a and not b:
        return 0.0
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, _normalize(a), _normalize(b)).ratio()


def _extract_tags(path: Path) -> Optional[Dict]:
    """Extract audio metadata. Returns None if file is unreadable."""
    tags: Dict = {
        "title": "", "artist": "", "album": "",
        "duration": 0.0, "bitrate": 0,
    }
    try:
        from mutagen import File as MFile
        audio = MFile(path, easy=True)
        if audio is None:
            return tags
        if hasattr(audio, "info"):
            tags["duration"] = getattr(audio.info, "length", 0.0)
            tags["bitrate"] = getattr(audio.info, "bitrate", 0)
        for key in ("title", "artist", "album"):
            val = audio.get(key) or audio.get(key.capitalize())
            if val:
                tags[key] = str(val[0]) if isinstance(val, list) else str(val)
    except ImportError:
        # mutagen not available — use filename heuristic
        stem = path.stem
        parts = re.split(r"[-–—]", stem, maxsplit=2)
        if len(parts) >= 2:
            tags["artist"] = parts[0].strip()
            tags["title"] = parts[1].strip()
    except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
        pass
    return tags


def _audio_similarity(
    tags_a: Dict, tags_b: Dict,
    title_w: float, artist_w: float, album_w: float,
    dur_tol: float,
) -> float:
    """Return combined similarity score 0.0–1.0."""
    # Duration gate
    dur_a, dur_b = tags_a["duration"], tags_b["duration"]
    if dur_a > 0 and dur_b > 0 and abs(dur_a - dur_b) > dur_tol:
        return 0.0

    title_sim  = _similarity_ratio(tags_a["title"],  tags_b["title"])
    artist_sim = _similarity_ratio(tags_a["artist"], tags_b["artist"])
    album_sim  = _similarity_ratio(tags_a["album"],  tags_b["album"])

    total_w = title_w + artist_w + album_w
    if total_w == 0:
        return 0.0
    return (title_sim * title_w + artist_sim * artist_w + album_sim * album_w) / total_w


def _keeper_score(path: Path, tags: Dict) -> float:
    """Higher = more worth keeping. FLAC > WAV > OGG > MP3, then by bitrate."""
    fmt = FORMAT_RANK.get(path.suffix.lower(), 0)
    bitrate = tags.get("bitrate", 0) or 0
    return fmt * 10_000 + bitrate


class MusicDedupEngine(BaseEngine):
    """
    Music duplicate detection via ID3 tag fuzzy matching.

    Groups files whose title+artist+album similarity exceeds the threshold
    and whose durations are within tolerance.
    """

    def __init__(self):
        super().__init__()
        self._results: List[DuplicateGroup] = []
        self._progress = ScanProgress(state=ScanState.IDLE)
        self._cancel_event = threading.Event()
        self._pause_event = threading.Event()

    def get_name(self) -> str:
        return "Music Deduplication"

    def get_mode_options(self) -> List[EngineOption]:
        return [
            EngineOption(
                name="similarity_threshold",
                display_name="Tag Similarity (%)",
                type="int", default=85, min_value=50, max_value=100,
                tooltip="Minimum combined title+artist+album similarity",
            ),
            EngineOption(
                name="duration_tolerance",
                display_name="Duration Tolerance (s)",
                type="int", default=2, min_value=0, max_value=30,
                tooltip="Allow this many seconds difference in track length",
            ),
            EngineOption(
                name="title_weight",
                display_name="Title Weight",
                type="int", default=50, min_value=0, max_value=100,
                tooltip="How much to weight title similarity (0-100)",
            ),
            EngineOption(
                name="artist_weight",
                display_name="Artist Weight",
                type="int", default=30, min_value=0, max_value=100,
                tooltip="How much to weight artist similarity (0-100)",
            ),
            EngineOption(
                name="album_weight",
                display_name="Album Weight",
                type="int", default=20, min_value=0, max_value=100,
                tooltip="How much to weight album similarity (0-100)",
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
        threshold  = self._options.get("similarity_threshold", 85) / 100.0
        dur_tol    = float(self._options.get("duration_tolerance", 2))
        title_w    = self._options.get("title_weight", 50)
        artist_w   = self._options.get("artist_weight", 30)
        album_w    = self._options.get("album_weight", 20)

        # Collect audio files
        audio_files: List[Path] = []
        for folder in self._folders:
            for root, _, files in os.walk(folder):
                for fname in files:
                    p = Path(root) / fname
                    if p.suffix.lower() in AUDIO_EXTENSIONS:
                        audio_files.append(p)

        total = len(audio_files)
        cb(ScanProgress(state=ScanState.SCANNING, files_total=total))

        # Extract tags
        tags_map: Dict[Path, Dict] = {}
        for i, af in enumerate(audio_files):
            if self._cancel_event.is_set():
                break
            while self._pause_event.is_set():
                time.sleep(0.1)
            t = _extract_tags(af)
            if t is not None:
                tags_map[af] = t
            cb(ScanProgress(
                state=ScanState.SCANNING,
                files_scanned=i + 1, files_total=total, current_file=str(af),
            ))

        if self._cancel_event.is_set():
            self._state = ScanState.CANCELLED
            cb(ScanProgress(state=ScanState.CANCELLED))
            return

        # O(n²) comparison — acceptable for music libraries up to ~10k files
        paths = list(tags_map.keys())
        grouped: set = set()
        groups: List[List[Path]] = []

        for i in range(len(paths)):
            if paths[i] in grouped:
                continue
            group = [paths[i]]
            for j in range(i + 1, len(paths)):
                if paths[j] in grouped:
                    continue
                sim = _audio_similarity(
                    tags_map[paths[i]], tags_map[paths[j]],
                    title_w, artist_w, album_w, dur_tol,
                )
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
                    t = tags_map.get(p, {})
                    files.append(DuplicateFile(
                        path=p, size=stat.st_size, modified=stat.st_mtime,
                        extension=p.suffix.lower(), similarity=threshold,
                        metadata={"duration": t.get("duration", 0),
                                  "bitrate": t.get("bitrate", 0),
                                  "title": t.get("title", ""),
                                  "artist": t.get("artist", ""),
                                  "album": t.get("album", "")},
                    ))
                except OSError:
                    pass
            if len(files) > 1:
                # Best quality file = keeper
                files.sort(key=lambda f: _keeper_score(f.path, tags_map.get(f.path, {})), reverse=True)
                files[0].is_keeper = True
                self._results.append(DuplicateGroup(group_id=gid, files=files))

        self._state = ScanState.COMPLETED
        cb(ScanProgress(
            state=ScanState.COMPLETED,
            files_scanned=total, files_total=total,
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
