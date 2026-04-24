"""Centralized theme tokens for the Flet UI.

Provides light and dark color palettes, spacing constants, and typography
tokens. All page/component modules should consume colors from this module
rather than hard-coding hex values.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict

import flet as ft


@dataclass(frozen=True)
class ColorTokens:
    """Immutable color palette."""

    primary: str = "#3B82F6"
    primary_hover: str = "#2563EB"
    danger: str = "#EF4444"
    danger_hover: str = "#DC2626"
    success: str = "#10B981"
    warning: str = "#F59E0B"

    bg: str = "#FFFFFF"
    bg2: str = "#F8FAFC"
    bg3: str = "#F1F5F9"

    fg: str = "#0F172A"
    fg2: str = "#475569"
    fg_muted: str = "#94A3B8"

    border: str = "#E2E8F0"
    border_strong: str = "#CBD5E1"

    nav_bg: str = "#0A1929"
    nav_bar: str = "#1E3A5F"

    row_sel: str = "#EFF6FF"
    row_sel_fg: str = "#0F172A"

    glass_bg: str = "#F8FAFC"
    glass_border: str = "#E2E8F0"

    accent: str = "#3B82F6"


@dataclass(frozen=True)
class DarkColorTokens:
    """Dark-mode color palette."""

    primary: str = "#60A5FA"
    primary_hover: str = "#93C5FD"
    danger: str = "#F87171"
    danger_hover: str = "#FCA5A5"
    success: str = "#34D399"
    warning: str = "#FBBF24"

    bg: str = "#0F172A"
    bg2: str = "#1E293B"
    bg3: str = "#334155"

    fg: str = "#F1F5F9"
    fg2: str = "#CBD5E1"
    fg_muted: str = "#64748B"

    border: str = "#334155"
    border_strong: str = "#475569"

    nav_bg: str = "#020617"
    nav_bar: str = "#0F172A"

    row_sel: str = "#1E3A5F"
    row_sel_fg: str = "#F1F5F9"

    glass_bg: str = "#1E293B"
    glass_border: str = "#334155"

    accent: str = "#60A5FA"


@dataclass(frozen=True)
class Spacing:
    """Spacing scale in pixels."""

    xs: int = 4
    sm: int = 8
    md: int = 12
    lg: int = 16
    xl: int = 24
    xxl: int = 32
    xxxl: int = 48


@dataclass(frozen=True)
class Typography:
    """Font configuration."""

    family: str = "Segoe UI"
    size_xs: int = 9
    size_sm: int = 10
    size_base: int = 11
    size_md: int = 12
    size_lg: int = 14
    size_xl: int = 16
    size_xxl: int = 18
    size_xxxl: int = 24


@dataclass
class ThemeTokens:
    """Aggregated theme tokens for one mode."""

    colors: ColorTokens = field(default_factory=ColorTokens)
    spacing: Spacing = field(default_factory=Spacing)
    typography: Typography = field(default_factory=Typography)
    border_radius: int = 8
    shadow_blur: float = 8.0
    shadow_offset_y: float = 2.0


def light_theme() -> ThemeTokens:
    return ThemeTokens(colors=ColorTokens())


def dark_theme() -> ThemeTokens:
    return ThemeTokens(colors=DarkColorTokens())


def theme_for_mode(mode: str) -> ThemeTokens:
    """Return theme tokens for the given mode string.

    Args:
        mode: "light", "dark", or "system".
    """
    if mode == "dark":
        return dark_theme()
    return light_theme()


# Well-known scan-mode definitions (icons are Unicode for cross-platform).
SCAN_MODES: list[Dict[str, str]] = [
    {"key": "files", "icon": "description", "label": "Files"},
    {"key": "empty_folders", "icon": "folder", "label": "Folders"},
    {"key": "photos", "icon": "image", "label": "Compare"},
    {"key": "music", "icon": "music_note", "label": "Music"},
    {"key": "large_files", "icon": "bar_chart", "label": "Unique"},
]

# Extension filter buckets used by results and review pages.
FILTER_EXTS: Dict[str, set[str]] = {
    "pictures": {
        ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".tif",
        ".webp", ".svg", ".ico", ".heic", ".heif", ".raw", ".cr2",
    },
    "music": {
        ".mp3", ".wav", ".flac", ".aac", ".ogg", ".wma", ".m4a",
        ".opus", ".aiff",
    },
    "videos": {
        ".mp4", ".avi", ".mkv", ".mov", ".wmv", ".flv", ".webm",
        ".m4v", ".mpg", ".mpeg", ".3gp",
    },
    "documents": {
        ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
        ".txt", ".rtf", ".odt", ".ods", ".odp", ".csv",
    },
    "archives": {
        ".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz",
        ".cab", ".iso", ".dmg",
    },
}

EXT_ALL_KNOWN: set[str] = set()
for _exts in FILTER_EXTS.values():
    EXT_ALL_KNOWN |= _exts


def classify_file(extension: str) -> str:
    """Return the filter bucket for a file extension (lowercase, with dot)."""
    ext = (extension or "").lower()
    for bucket, exts in FILTER_EXTS.items():
        if ext in exts:
            return bucket
    if ext:
        return "other"
    return "other"


def fmt_size(n: int) -> str:
    """Human-readable file size."""
    if n < 1024:
        return f"{n} B"
    if n < 1024 ** 2:
        return f"{n / 1024:.1f} KB"
    if n < 1024 ** 3:
        return f"{n / 1024 ** 2:.1f} MB"
    return f"{n / 1024 ** 3:.1f} GB"


def glass_container(
    content: ft.Control,
    t: ThemeTokens,
    *,
    padding: int = 16,
    border_radius: int | None = None,
    expand: bool = False,
) -> ft.Container:
    """Create a glassmorphism-styled container."""
    br = border_radius or t.border_radius
    return ft.Container(
        content=content,
        padding=padding,
        border_radius=br,
        bgcolor=t.colors.glass_bg,
        border=ft.border.all(1, t.colors.glass_border),
        shadow=ft.BoxShadow(
            spread_radius=0,
            blur_radius=t.shadow_blur,
            offset=ft.Offset(0, t.shadow_offset_y),
            color="#00000015",
        ),
        expand=expand,
    )
