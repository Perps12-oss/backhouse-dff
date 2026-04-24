"""Shared file-type buckets for Results / Review / Duplicates (extension-based)."""

from __future__ import annotations

from typing import Dict, Optional, Set

# File-type extension sets for the filter list
_EXT_MUSIC = {".mp3", ".flac", ".ogg", ".wav", ".aac", ".m4a", ".wma", ".opus", ".aiff", ".ape"}
_EXT_PIC = {
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".heic", ".tiff", ".tif",
    ".cr2", ".cr3", ".nef", ".arw", ".dng",
}
_EXT_VID = {".mp4", ".avi", ".mkv", ".mov", ".wmv", ".flv", ".webm", ".m4v", ".mpg", ".mpeg"}
_EXT_DOC = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".txt", ".odt", ".rtf"}
_EXT_ARCH = {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".iso"}

_FILTER_EXTS: Dict[str, Optional[Set[str]]] = {
    "all": None,
    "music": _EXT_MUSIC,
    "pictures": _EXT_PIC,
    "videos": _EXT_VID,
    "documents": _EXT_DOC,
    "archives": _EXT_ARCH,
}

_EXT_ALL_KNOWN: Set[str] = _EXT_MUSIC | _EXT_PIC | _EXT_VID | _EXT_DOC | _EXT_ARCH


def classify_file(ext: str) -> str:
    """Bucket: ``pictures`` | ``music`` | ... | ``other``."""
    e = (ext or "").lower()
    if e in _EXT_PIC:
        return "pictures"
    if e in _EXT_MUSIC:
        return "music"
    if e in _EXT_VID:
        return "videos"
    if e in _EXT_DOC:
        return "documents"
    if e in _EXT_ARCH:
        return "archives"
    return "other"
