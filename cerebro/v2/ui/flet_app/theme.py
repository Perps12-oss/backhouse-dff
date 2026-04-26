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

    primary: str = "#2563EB"
    primary_hover: str = "#1D4ED8"
    danger: str = "#EF4444"
    danger_hover: str = "#DC2626"
    success: str = "#10B981"
    warning: str = "#F59E0B"

    bg: str = "#F8FBFF"
    bg2: str = "#EEF4FF"
    bg3: str = "#E7EEFA"

    fg: str = "#0B1220"
    fg2: str = "#24344E"
    fg_muted: str = "#50627F"

    border: str = "#CBD8EE"
    border_strong: str = "#AFC3E5"
    border3: str = "#DDE8FA"

    nav_bg: str = "#0A1929"
    nav_bar: str = "#1E3A5F"

    row_sel: str = "#EFF6FF"
    row_sel_fg: str = "#0F172A"

    glass_bg: str = "#F8FAFC"
    glass_border: str = "#E2E8F0"

    accent: str = "#3B82F6"


@dataclass(frozen=True)
class DarkColorTokens:
    """Dark-mode color palette — Cerebro navy/cyan brand."""

    primary: str = "#35E7FF"        # brighter cyan for standout actions
    primary_hover: str = "#19D7F5"
    danger: str = "#F87171"
    danger_hover: str = "#FCA5A5"
    success: str = "#34D399"
    warning: str = "#FBBF24"

    bg: str = "#060B14"
    bg2: str = "#0B1220"
    bg3: str = "#101A2E"

    fg: str = "#F3F9FF"             # primary text, high contrast
    fg2: str = "#C7D8F4"            # secondary text, still readable
    fg_muted: str = "#8FA7CC"       # muted text with better lift

    border: str = "#2B3A54"
    border_strong: str = "#3A4F73"
    border3: str = "#1C2740"

    nav_bg: str = "#080C11"         # sidebar bg (was #020617)
    nav_bar: str = "#0D1117"        # nav bar (was #0F172A)

    row_sel: str = "#1A2A45"
    row_sel_fg: str = "#F3F9FF"

    glass_bg: str = "#0D1628"
    glass_border: str = "#324765"

    accent: str = "#35E7FF"


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
    size_xs: int = 10
    size_sm: int = 11
    size_base: int = 13
    size_md: int = 14
    size_lg: int = 16
    size_xl: int = 18
    size_xxl: int = 22
    size_xxxl: int = 30


@dataclass
class ThemeTokens:
    """Aggregated theme tokens for one mode."""

    colors: ColorTokens = field(default_factory=ColorTokens)
    spacing: Spacing = field(default_factory=Spacing)
    typography: Typography = field(default_factory=Typography)
    border_radius: int = 8
    border_radius_sm: int = 4
    border_radius_lg: int = 12
    border_radius_xl: int = 20
    shadow_blur: float = 8.0
    shadow_offset_y: float = 2.0
    duration_fast: int = 150
    duration_normal: int = 300
    duration_slow: int = 500


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


def build_flet_theme(mode: str, seed: str | None = None) -> ft.Theme:
    """Build a complete ft.Theme with explicit ColorScheme for correct Material 3 contrast."""
    if mode == "dark":
        c = DarkColorTokens()
        # Dracula-like readability profile: bright, crisp text hierarchy on dark surfaces.
        text_primary = "#F6F8FF"
        text_secondary = "#D8E2FF"
        text_muted = "#AFC1E6"
        scheme = ft.ColorScheme(
            primary=seed or c.primary,
            on_primary="#0A0E14",
            primary_container=ft.Colors.with_opacity(0.18, seed or c.primary),
            on_primary_container=text_primary,
            secondary="#8BE9FD",
            on_secondary="#0A0E14",
            secondary_container=ft.Colors.with_opacity(0.18, "#8BE9FD"),
            on_secondary_container=text_primary,
            surface=c.bg,
            on_surface=text_primary,
            surface_container=c.bg2,
            on_surface_variant=text_secondary,
            outline=c.border,
            outline_variant=c.border_strong,
            error=c.danger,
            on_error="#0A0E14",
            tertiary="#BD93F9",
            on_tertiary="#0A0E14",
            tertiary_container=ft.Colors.with_opacity(0.20, "#BD93F9"),
            on_tertiary_container=text_primary,
            surface_container_high=c.bg3,
            surface_container_low=c.bg2,
            surface_tint=text_muted,
        )
    else:
        c = ColorTokens()
        # Keep light themes vibrant and legible instead of washed out.
        text_primary = "#0E172A"
        text_secondary = "#1F3352"
        text_muted = "#3B5478"
        scheme = ft.ColorScheme(
            primary=seed or c.primary,
            on_primary="#FFFFFF",
            primary_container=ft.Colors.with_opacity(0.12, seed or c.primary),
            on_primary_container=text_primary,
            secondary="#4F46E5",
            on_secondary="#FFFFFF",
            secondary_container=ft.Colors.with_opacity(0.16, "#4F46E5"),
            on_secondary_container=text_primary,
            surface=c.bg,
            on_surface=text_primary,
            surface_container=c.bg2,
            on_surface_variant=text_secondary,
            outline=c.border,
            outline_variant=c.border_strong,
            error=c.danger,
            on_error="#FFFFFF",
            tertiary="#0EA5E9",
            on_tertiary="#FFFFFF",
            tertiary_container=ft.Colors.with_opacity(0.18, "#0EA5E9"),
            on_tertiary_container=text_primary,
            surface_container_high=c.bg3,
            surface_container_low=c.bg2,
            surface_tint=text_muted,
        )
    return ft.Theme(
        color_scheme_seed=None,
        color_scheme=scheme,
        font_family=Typography().family,
        visual_density=ft.VisualDensity.COMFORTABLE,
    )


def glass_container(
    content: ft.Control,
    t: ThemeTokens,
    *,
    padding: int = 16,
    border_radius: int | None = None,
    expand: bool = False,
    blur: int = 0,
) -> ft.Container:
    """Create a glassmorphism-styled container."""
    br = border_radius or t.border_radius
    container_kwargs: dict = dict(
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
    if blur > 0:
        container_kwargs["blur"] = ft.Blur(blur, blur)
    return ft.Container(**container_kwargs)
