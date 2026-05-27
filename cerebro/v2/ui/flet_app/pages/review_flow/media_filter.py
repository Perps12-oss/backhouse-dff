"""Media-type scoping for review deletion marks (pictures, music, videos, …)."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, List, Set

from cerebro.engines.base_engine import DuplicateFile
from cerebro.v2.ui.flet_app.theme import classify_file

SELECTION_MEDIA_TYPES: tuple[tuple[str, str], ...] = (
    ("pictures", "Pictures"),
    ("music", "Music"),
    ("videos", "Videos"),
    ("documents", "Documents"),
    ("archives", "Archives"),
    ("other", "Other"),
)

_SELECTION_MEDIA_KEYS = {k for k, _ in SELECTION_MEDIA_TYPES}


def normalized_media_type(value: str) -> str:
    key = (value or "").strip().lower()
    return key if key in _SELECTION_MEDIA_KEYS else "pictures"


def file_media_bucket(f: DuplicateFile) -> str:
    ext = (f.extension or Path(str(f.path)).suffix or "").lower()
    if ext and not ext.startswith("."):
        ext = f".{ext}"
    return classify_file(ext)


def files_in_media_bucket(files: Iterable[DuplicateFile], media_type: str) -> List[DuplicateFile]:
    bucket = normalized_media_type(media_type)
    return [f for f in files if file_media_bucket(f) == bucket]


def filter_paths_for_media_scope(
    files: Iterable[DuplicateFile],
    paths: Iterable[str],
    *,
    enabled: bool,
    media_type: str,
) -> Set[str]:
    """Return paths that may be marked for deletion under an active media filter."""
    path_set = {str(p) for p in paths}
    if not enabled:
        return path_set
    bucket = normalized_media_type(media_type)
    allowed = {str(f.path) for f in files if file_media_bucket(f) == bucket}
    return path_set & allowed
