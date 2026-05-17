"""Centralized theme tokens for the Flet UI.

Provides VS Code-accurate color palettes, spacing constants, and typography
tokens. All page/component modules should consume colors from this module
rather than hard-coding hex values.

Call ``set_active_preset()`` (done by ``StateBridge.apply_preset_theme``)
before building any page so that ``theme_for_mode`` returns preset-accurate
colors instead of the built-in fallbacks.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Dict, Optional

import flet as ft

if TYPE_CHECKING:
    from cerebro.v2.ui.flet_app.palette_themes import PalettePreset


# ---------------------------------------------------------------------------
# Module-level active preset — set by apply_preset_theme via state_bridge
# ---------------------------------------------------------------------------

_active_preset: Optional["PalettePreset"] = None


def set_active_preset(preset: "PalettePreset") -> None:
    global _active_preset
    _active_preset = preset


def get_active_preset() -> Optional["PalettePreset"]:
    return _active_preset


# ---------------------------------------------------------------------------
# UI font scale (Settings → Appearance slider). Flet Page has no text_scale in
# current builds; we scale Typography tokens consumed by all pages.
# ---------------------------------------------------------------------------

_UI_FONT_BASE_PX: int = 13
_ui_font_scale: float = 1.0


def set_ui_font_size_px(size: int) -> None:
    """Map slider px (10–18) to a scale factor relative to base 13px body size."""
    global _ui_font_scale
    clamped = max(10, min(18, int(round(size))))
    _ui_font_scale = round(clamped / float(_UI_FONT_BASE_PX), 3)


def get_ui_font_scale() -> float:
    return _ui_font_scale


def _scaled_typography(base: Typography) -> Typography:
    s = _ui_font_scale
    if abs(s - 1.0) < 1e-6:
        return base

    def sc(n: int) -> int:
        return max(6, min(56, int(round(int(n) * s))))

    return Typography(
        family=base.family,
        size_xs=sc(base.size_xs),
        size_sm=sc(base.size_sm),
        size_base=sc(base.size_base),
        size_md=sc(base.size_md),
        size_lg=sc(base.size_lg),
        size_xl=sc(base.size_xl),
        size_xxl=sc(base.size_xxl),
        size_xxxl=sc(base.size_xxxl),
    )


def _with_scaled_typography(tokens: ThemeTokens) -> ThemeTokens:
    new_ty = _scaled_typography(tokens.typography)
    if new_ty is tokens.typography:
        return tokens
    return replace(tokens, typography=new_ty)


# ---------------------------------------------------------------------------
# Token dataclasses
# ---------------------------------------------------------------------------

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
    """Dark-mode color palette fallback (used when no preset is active)."""

    primary: str = "#35E7FF"
    primary_hover: str = "#19D7F5"
    danger: str = "#F87171"
    danger_hover: str = "#FCA5A5"
    success: str = "#34D399"
    warning: str = "#FBBF24"

    bg: str = "#060B14"
    bg2: str = "#0B1220"
    bg3: str = "#101A2E"

    fg: str = "#F3F9FF"
    fg2: str = "#C7D8F4"
    fg_muted: str = "#8FA7CC"

    border: str = "#2B3A54"
    border_strong: str = "#3A4F73"
    border3: str = "#1C2740"

    nav_bg: str = "#080C11"
    nav_bar: str = "#0D1117"

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


# ---------------------------------------------------------------------------
# Token builders
# ---------------------------------------------------------------------------

def _tokens_from_preset(preset: "PalettePreset") -> ColorTokens:
    """Build ColorTokens from a full PalettePreset (VS Code-accurate colors)."""
    import colorsys

    def _darken(hex_color: str, factor: float = 0.85) -> str:
        """Return a slightly darkened version of hex_color for hover states."""
        h = hex_color.lstrip("#")
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        r2 = min(255, int(r * factor))
        g2 = min(255, int(g * factor))
        b2 = min(255, int(b * factor))
        return f"#{r2:02X}{g2:02X}{b2:02X}"

    def _lighten(hex_color: str, factor: float = 1.15) -> str:
        h = hex_color.lstrip("#")
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        r2 = min(255, int(r * factor))
        g2 = min(255, int(g * factor))
        b2 = min(255, int(b * factor))
        return f"#{r2:02X}{g2:02X}{b2:02X}"

    hover = _darken(preset.primary) if preset.is_dark else _lighten(preset.primary)
    danger_hover = _darken(preset.danger) if preset.is_dark else _lighten(preset.danger)

    # Derive border_strong and border3 from the base border
    bh = preset.border.lstrip("#")
    br, bg_, bb = int(bh[0:2], 16), int(bh[2:4], 16), int(bh[4:6], 16)
    if preset.is_dark:
        border_strong = f"#{min(255,br+20):02X}{min(255,bg_+20):02X}{min(255,bb+20):02X}"
        border3 = f"#{max(0,br-12):02X}{max(0,bg_-12):02X}{max(0,bb-12):02X}"
    else:
        border_strong = f"#{max(0,br-20):02X}{max(0,bg_-20):02X}{max(0,bb-20):02X}"
        border3 = f"#{min(255,br+16):02X}{min(255,bg_+16):02X}{min(255,bb+16):02X}"

    # row_sel: tinted bg3 + primary hint
    ph = preset.primary.lstrip("#")
    pr, pg, pb = int(ph[0:2], 16), int(ph[2:4], 16), int(ph[4:6], 16)
    bgh = preset.bg3.lstrip("#")
    bgr, bgg, bgb = int(bgh[0:2], 16), int(bgh[2:4], 16), int(bgh[4:6], 16)
    row_sel = f"#{(bgr+pr)//2:02X}{(bgg+pg)//2:02X}{(bgb+pb)//2:02X}"

    return ColorTokens(
        primary=preset.primary,
        primary_hover=hover,
        danger=preset.danger,
        danger_hover=danger_hover,
        success=preset.success,
        warning=preset.warning,
        bg=preset.bg,
        bg2=preset.bg2,
        bg3=preset.bg3,
        fg=preset.fg,
        fg2=preset.fg2,
        fg_muted=preset.fg_muted,
        border=preset.border,
        border_strong=border_strong,
        border3=border3,
        nav_bg=preset.nav_bg,
        nav_bar=preset.nav_bg,
        row_sel=row_sel,
        row_sel_fg=preset.fg,
        glass_bg=preset.bg2,
        glass_border=preset.border,
        accent=preset.primary,
    )


def light_theme() -> ThemeTokens:
    p = _active_preset
    if p is not None and not p.is_dark:
        return ThemeTokens(colors=_tokens_from_preset(p))
    return ThemeTokens(colors=ColorTokens())


def dark_theme() -> ThemeTokens:
    p = _active_preset
    if p is not None and p.is_dark:
        return ThemeTokens(colors=_tokens_from_preset(p))
    return ThemeTokens(colors=DarkColorTokens())


def theme_for_mode(mode: str, preset_id: str | None = None) -> ThemeTokens:
    """Return theme tokens for the given mode string and optional palette preset id."""
    if preset_id:
        from cerebro.v2.ui.flet_app.palette_themes import preset_by_id

        found = preset_by_id(preset_id)
        if found is not None:
            set_active_preset(found)
    p = _active_preset
    if p is not None:
        tokens = ThemeTokens(colors=_tokens_from_preset(p))
    elif mode == "dark":
        tokens = dark_theme()
    else:
        tokens = light_theme()
    return _with_scaled_typography(tokens)


# ---------------------------------------------------------------------------
# Flet Theme builder
# ---------------------------------------------------------------------------

def build_flet_theme(mode: str, seed: str | None = None) -> ft.Theme:
    """Build a complete ft.Theme with a VS Code-accurate ColorScheme."""
    p = _active_preset

    if p is not None:
        # Use exact preset colors — bypass Material 3 seed generation.
        is_dark = p.is_dark
        primary = p.primary
        on_primary = p.bg if is_dark else "#FFFFFF"
        surface = p.bg
        on_surface = p.fg
        surface_var = p.fg2
        error = p.danger
        on_error = p.bg if is_dark else "#FFFFFF"
        outline = p.border

        bg2 = p.bg2
        bg3 = p.bg3

        scheme = ft.ColorScheme(
            primary=primary,
            on_primary=on_primary,
            primary_container=ft.Colors.with_opacity(0.18, primary),
            on_primary_container=on_surface,
            secondary=p.success,
            on_secondary=on_primary,
            secondary_container=ft.Colors.with_opacity(0.18, p.success),
            on_secondary_container=on_surface,
            surface=surface,
            on_surface=on_surface,
            surface_container=bg2,
            on_surface_variant=surface_var,
            outline=outline,
            outline_variant=ft.Colors.with_opacity(0.6, outline),
            error=error,
            on_error=on_error,
            tertiary=p.warning,
            on_tertiary=on_primary,
            tertiary_container=ft.Colors.with_opacity(0.20, p.warning),
            on_tertiary_container=on_surface,
            surface_container_high=bg3,
            surface_container_low=bg2,
            surface_tint=ft.Colors.with_opacity(0.05, primary),
        )
    elif mode == "dark":
        c = DarkColorTokens()
        text_primary = "#F6F8FF"
        text_secondary = "#D8E2FF"
        text_muted = "#AFC1E6"
        effective_seed = seed or c.primary
        scheme = ft.ColorScheme(
            primary=effective_seed,
            on_primary="#0A0E14",
            primary_container=ft.Colors.with_opacity(0.18, effective_seed),
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
        text_primary = "#0E172A"
        text_secondary = "#1F3352"
        text_muted = "#3B5478"
        effective_seed = seed or c.primary
        scheme = ft.ColorScheme(
            primary=effective_seed,
            on_primary="#FFFFFF",
            primary_container=ft.Colors.with_opacity(0.12, effective_seed),
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


# ---------------------------------------------------------------------------
# Glass surface helpers (theme-aware; avoids light cards on dark shell)
# ---------------------------------------------------------------------------

def _hex_channel(hex_color: str, start: int) -> int:
    h = (hex_color or "#000000").lstrip("#")
    if len(h) > 6:
        h = h[-6:]
    return int(h[start : start + 2], 16)


def is_dark_theme(t: ThemeTokens) -> bool:
    """True when the active palette base background reads as dark."""
    bg = t.colors.bg
    lum = (
        0.299 * _hex_channel(bg, 0)
        + 0.587 * _hex_channel(bg, 2)
        + 0.114 * _hex_channel(bg, 4)
    )
    return lum < 140


def glass_surface_bg(t: ThemeTokens) -> str:
    """Semi-opaque surface aligned with preset bg hierarchy."""
    if is_dark_theme(t):
        return ft.Colors.with_opacity(0.82, t.colors.bg2)
    return ft.Colors.with_opacity(0.96, t.colors.bg2)


def apply_glass_style(container: ft.Container, t: ThemeTokens) -> None:
    """Repaint container as flat flet-base surface (legacy name)."""
    from cerebro.v2.ui.flet_app.design_system.cards import apply_flat_style

    apply_flat_style(container, t)


# ---------------------------------------------------------------------------
# Utility: glass container
# ---------------------------------------------------------------------------

def glass_container(
    content: ft.Control,
    t: ThemeTokens,
    *,
    padding: int | ft.Padding | float = 16,
    border_radius: int | None = None,
    expand: bool | int = False,
    blur: int = 0,
    **kwargs
) -> ft.Container:
    """Flat flet-base card (legacy name)."""
    from cerebro.v2.ui.flet_app.design_system.cards import flat_card

    _ = blur
    return flat_card(
        content,
        t,
        padding=padding,
        border_radius=border_radius or 12,
        expand=expand,
        **kwargs,
    )

# ---------------------------------------------------------------------------
# Static data unchanged from original
# ---------------------------------------------------------------------------

SCAN_MODES: list[Dict[str, str]] = [
    {"key": "files",  "icon": "description", "label": "Full Scan",    "desc": "All duplicate files",    "group": "General category"},
    {"key": "photos", "icon": "image",        "label": "Scan Pictures","desc": "Exact image matches",    "group": "Image category"},
    {"key": "videos", "icon": "videocam",     "label": "Scan Videos",  "desc": "Duplicate video files",  "group": "Audio/Video category"},
    {"key": "music",  "icon": "music_note",   "label": "Scan Audio",   "desc": "Duplicate audio files",  "group": "Audio/Video category"},
]

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
