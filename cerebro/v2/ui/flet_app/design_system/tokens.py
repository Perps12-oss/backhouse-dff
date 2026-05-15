"""Named visual constants and accent preset maps for Home / shell surfaces."""

from __future__ import annotations

from enum import Enum
from typing import Mapping

# ---------------------------------------------------------------------------
# Accent preset dictionaries (checklist NEON_DARK / light glass)
# ---------------------------------------------------------------------------

NEON_DARK: Mapping[str, str] = {
    "accent_primary": "#06B6D4",
    "accent_primary_glow": "rgba(6,182,212,0.4)",
    "accent_secondary": "#F59E0B",
    "bg_base": "#0A0E17",
    "bg_surface": "rgba(16,22,36,0.7)",
    "bg_elevated": "rgba(24,32,52,0.85)",
    "border_subtle": "rgba(148,163,184,0.08)",
    "border_glow": "rgba(6,182,212,0.3)",
    "text_primary": "#F1F5F9",
    "text_secondary": "#94A3B8",
    "text_muted": "#64748B",
}

GLASS_DAY: Mapping[str, str] = {
    "accent_primary": "#06B6D4",
    "accent_primary_glow": "rgba(6,182,212,0.35)",
    "accent_secondary": "#F59E0B",
    "bg_base": "#F0F9FF",
    "bg_surface": "rgba(224,242,254,0.85)",
    "bg_elevated": "rgba(186,230,253,0.9)",
    "border_subtle": "rgba(148,163,184,0.2)",
    "border_glow": "rgba(6,182,212,0.25)",
    "text_primary": "#0F172A",
    "text_secondary": "#334155",
    "text_muted": "#64748B",
}


class AccentPreset(str, Enum):
    """Maps to ``palette_themes.PalettePreset.id`` values."""

    NEON_DARK = "neon_void"
    GLASS_DAY = "glass_day"


PRESET_ACCENT_MAP: dict[AccentPreset, Mapping[str, str]] = {
    AccentPreset.NEON_DARK: NEON_DARK,
    AccentPreset.GLASS_DAY: GLASS_DAY,
}

# Legacy named constants (hero gradients, motion timing)
NEON_BG_BASE = NEON_DARK["bg_base"]
NEON_BG_SURFACE = "#101624"
NEON_BG_ELEVATED = "#182034"
NEON_BORDER_SUBTLE = "#94A3B8"
NEON_BORDER_GLOW = "#06B6D4"
NEON_ACCENT_PRIMARY = NEON_DARK["accent_primary"]
NEON_ACCENT_SECONDARY = NEON_DARK["accent_secondary"]
NEON_TEXT_PRIMARY = NEON_DARK["text_primary"]
NEON_TEXT_SECONDARY = NEON_DARK["text_secondary"]
NEON_TEXT_MUTED = NEON_DARK["text_muted"]

GLASS_ACCENT_PRIMARY = GLASS_DAY["accent_primary"]
GLASS_ACCENT_SECONDARY = GLASS_DAY["accent_secondary"]

SCAN_GRADIENT_START = "#0891B2"
SCAN_GRADIENT_END = "#06B6D4"

CARD_RADIUS = 12
BUTTON_RADIUS = 8
PANEL_RADIUS = 16

SECTION_PADDING = 24
CARD_PADDING = 16
COMPACT_GAP = 8
SECTION_GAP = 16

GLASS_BG_OPACITY = 0.70
GLASS_BORDER_OPACITY = 0.08
GLOW_SHADOW_OPACITY = 0.05
HERO_RADIAL_OPACITY = 0.03

MOTION_FAST = 150
MOTION_NORMAL = 200
MOTION_NAV = 300
MOTION_STAGGER_STEP = 100

RELATIVE_TIME_INTERVAL_S = 30.0
