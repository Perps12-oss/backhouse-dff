"""Thirty-five multigradient shell themes (vertical gradient + dot grid)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple


@dataclass(frozen=True)
class GradientTheme:
    id: str
    name: str
    gradient_top: str
    gradient_bottom: str
    accent: str
    dot_color: str

    @property
    def stops(self) -> tuple[str, str]:
        return (self.gradient_top, self.gradient_bottom)


GRADIENT_THEMES: Tuple[GradientTheme, ...] = (
    GradientTheme("flet_base", "Flet Base", "#1a2228", "#121212", "#1DB954", "#9CA3AF"),
    GradientTheme("gradient_emerald", "Emerald Mist", "#142820", "#121212", "#1DB954", "#6EE7B7"),
    GradientTheme("gradient_forest", "Forest Depth", "#152218", "#121212", "#22C55E", "#86EFAC"),
    GradientTheme("gradient_mint", "Mint Veil", "#132622", "#121212", "#10B981", "#6EE7B7"),
    GradientTheme("gradient_sage", "Sage Haze", "#1a2420", "#121212", "#84CC16", "#BEF264"),
    GradientTheme("gradient_ocean", "Ocean Drift", "#141e28", "#121212", "#06B6D4", "#67E8F9"),
    GradientTheme("gradient_azure", "Azure Tide", "#121e2a", "#121212", "#0EA5E9", "#7DD3FC"),
    GradientTheme("gradient_cobalt", "Cobalt Night", "#151a2e", "#121212", "#3B82F6", "#93C5FD"),
    GradientTheme("gradient_indigo", "Indigo Bloom", "#181528", "#121212", "#6366F1", "#A5B4FC"),
    GradientTheme("gradient_violet", "Violet Dusk", "#1c1528", "#121212", "#8B5CF6", "#C4B5FD"),
    GradientTheme("gradient_plum", "Plum Shadow", "#221428", "#121212", "#A855F7", "#D8B4FE"),
    GradientTheme("gradient_royal", "Royal Pulse", "#1a1830", "#121212", "#7C3AED", "#C4B5FD"),
    GradientTheme("gradient_rose", "Rose Ember", "#241820", "#121212", "#F43F5E", "#FDA4AF"),
    GradientTheme("gradient_coral", "Coral Reef", "#241a18", "#121212", "#FB7185", "#FECDD3"),
    GradientTheme("gradient_sunset", "Sunset Glow", "#281c14", "#121212", "#F97316", "#FDBA74"),
    GradientTheme("gradient_amber", "Amber Field", "#241e14", "#121212", "#F59E0B", "#FCD34D"),
    GradientTheme("gradient_gold", "Golden Hour", "#262014", "#121212", "#EAB308", "#FDE047"),
    GradientTheme("gradient_crimson", "Crimson Veil", "#281418", "#121212", "#EF4444", "#FCA5A5"),
    GradientTheme("gradient_ruby", "Ruby Night", "#2a1418", "#121212", "#DC2626", "#F87171"),
    GradientTheme("gradient_cherry", "Cherry Smoke", "#261618", "#121212", "#E11D48", "#FDA4AF"),
    GradientTheme("gradient_slate", "Slate Calm", "#1a1e24", "#121212", "#64748B", "#94A3B8"),
    GradientTheme("gradient_steel", "Steel Horizon", "#181c22", "#121212", "#475569", "#CBD5E1"),
    GradientTheme("gradient_graphite", "Graphite", "#1c1c1c", "#121212", "#A3A3A3", "#D4D4D4"),
    GradientTheme("gradient_ash", "Ash Fade", "#1e1e1e", "#121212", "#737373", "#A3A3A3"),
    GradientTheme("gradient_teal", "Teal Aurora", "#122428", "#121212", "#14B8A6", "#5EEAD4"),
    GradientTheme("gradient_cyan", "Cyan Pulse", "#122228", "#121212", "#22D3EE", "#67E8F9"),
    GradientTheme("gradient_sky", "Skyline", "#141e26", "#121212", "#38BDF8", "#BAE6FD"),
    GradientTheme("gradient_lagoon", "Lagoon", "#142428", "#121212", "#2DD4BF", "#99F6E4"),
    GradientTheme("gradient_arctic", "Arctic Blue", "#161e28", "#121212", "#60A5FA", "#BFDBFE"),
    GradientTheme("gradient_frost", "Frost", "#1a2028", "#121212", "#94A3B8", "#E2E8F0"),
    GradientTheme("gradient_lilac", "Lilac Dream", "#1e1828", "#121212", "#C084FC", "#E9D5FF"),
    GradientTheme("gradient_peach", "Peach Soft", "#241c18", "#121212", "#FB923C", "#FED7AA"),
    GradientTheme("gradient_mauve", "Mauve Mist", "#201a24", "#121212", "#D946EF", "#F0ABFC"),
    GradientTheme("gradient_matrix", "Matrix", "#0f1a12", "#121212", "#33FF33", "#4ADE80"),
    GradientTheme("gradient_midnight", "Midnight", "#14141e", "#121212", "#818CF8", "#C7D2FE"),
)


def gradient_by_id(theme_id: str) -> GradientTheme | None:
    tid = (theme_id or "").strip().lower()
    for g in GRADIENT_THEMES:
        if g.id == tid:
            return g
    return None


def default_gradient() -> GradientTheme:
    return GRADIENT_THEMES[0]
