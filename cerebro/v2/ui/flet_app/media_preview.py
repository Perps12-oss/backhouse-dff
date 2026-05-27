"""Media-type icons and preview eligibility for review thumbnails."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Literal

import flet as ft

from cerebro.v2.ui.flet_app.theme import classify_file

PreviewKind = Literal["image", "text", "video", "icon"]

_TEXT_SUFFIXES = {
    ".txt", ".md", ".markdown", ".json", ".jsonl", ".xml", ".yaml", ".yml",
    ".csv", ".log", ".ini", ".cfg", ".conf", ".py", ".pyw", ".js", ".ts",
    ".jsx", ".tsx", ".html", ".htm", ".css", ".scss", ".java", ".c", ".cpp",
    ".h", ".hpp", ".cs", ".go", ".rs", ".rb", ".php", ".sh", ".bat", ".ps1",
    ".sql", ".toml", ".env", ".rtf",
}

_VIDEO_SUFFIXES = {
    ".mp4", ".avi", ".mkv", ".mov", ".wmv", ".flv", ".webm", ".m4v",
    ".mpg", ".mpeg", ".3gp",
}

_IMAGE_SUFFIXES = {
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tif", ".tiff",
    ".ico", ".heic", ".heif",
}


def _ext(path: Path) -> str:
    return path.suffix.lower()


def media_bucket_for_path(path: Path | str) -> str:
    p = Path(path)
    ext = _ext(p)
    if ext and not ext.startswith("."):
        ext = f".{ext}"
    return classify_file(ext)


def preview_kind_for_path(path: Path | str) -> PreviewKind:
    p = Path(path)
    ext = _ext(p)
    if ext in _IMAGE_SUFFIXES:
        return "image"
    if ext in _TEXT_SUFFIXES:
        return "text"
    if ext in _VIDEO_SUFFIXES and shutil.which("ffmpeg"):
        return "video"
    return "icon"


def is_previewable_path(path: Path | str) -> bool:
    return preview_kind_for_path(path) != "icon"


def flet_icon_for_bucket(bucket: str) -> str:
    return {
        "pictures": ft.icons.Icons.IMAGE_OUTLINED,
        "videos": ft.icons.Icons.MOVIE_OUTLINED,
        "music": ft.icons.Icons.AUDIOTRACK_OUTLINED,
        "documents": ft.icons.Icons.DESCRIPTION_OUTLINED,
        "archives": ft.icons.Icons.FOLDER_ZIP_OUTLINED,
        "other": ft.icons.Icons.INSERT_DRIVE_FILE_OUTLINED,
    }.get(bucket, ft.icons.Icons.INSERT_DRIVE_FILE_OUTLINED)


def flet_icon_for_path(path: Path | str) -> str:
    return flet_icon_for_bucket(media_bucket_for_path(path))


def build_media_placeholder(
    path: Path | str,
    edge: int,
    *,
    color: str,
    bucket: str | None = None,
) -> ft.Icon:
    """Standard Material icon tile when no decoded thumbnail is available."""
    icon_size = max(16, min(edge, int(edge * 0.55)))
    b = bucket if bucket is not None else media_bucket_for_path(path)
    return ft.Icon(flet_icon_for_bucket(b), size=icon_size, color=color)
