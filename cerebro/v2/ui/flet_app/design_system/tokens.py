"""Named visual constants for futuristic Home / shell surfaces.

Components should consume ThemeTokens from theme.py for colors; use these
for gradients, glow opacities, and layout rhythm that are not on ColorTokens.
"""

from __future__ import annotations

# Neon dark (preset: neon_void)
NEON_BG_BASE = "#0A0E17"
NEON_BG_SURFACE = "#101624"
NEON_BG_ELEVATED = "#182034"
NEON_BORDER_SUBTLE = "#94A3B8"
NEON_BORDER_GLOW = "#06B6D4"
NEON_ACCENT_PRIMARY = "#06B6D4"
NEON_ACCENT_SECONDARY = "#F59E0B"
NEON_TEXT_PRIMARY = "#F1F5F9"
NEON_TEXT_SECONDARY = "#94A3B8"
NEON_TEXT_MUTED = "#64748B"

# Light glass (preset: glass_day)
GLASS_ACCENT_PRIMARY = "#06B6D4"
GLASS_ACCENT_SECONDARY = "#F59E0B"

# Hero / scan CTA gradients
SCAN_GRADIENT_START = "#0891B2"
SCAN_GRADIENT_END = "#06B6D4"

# Shape
CARD_RADIUS = 12
BUTTON_RADIUS = 8
PANEL_RADIUS = 16

# Spacing rhythm (px)
SECTION_PADDING = 24
CARD_PADDING = 16
COMPACT_GAP = 8
SECTION_GAP = 16

# Glass / glow (opacity fractions for ft.Colors.with_opacity)
GLASS_BG_OPACITY = 0.70
GLASS_BORDER_OPACITY = 0.08
GLOW_SHADOW_OPACITY = 0.05
HERO_RADIAL_OPACITY = 0.03

# Motion (ms)
MOTION_FAST = 150
MOTION_NORMAL = 200
MOTION_NAV = 300
MOTION_STAGGER_STEP = 100

# Time keeper
RELATIVE_TIME_INTERVAL_S = 30.0
