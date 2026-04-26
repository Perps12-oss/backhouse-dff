"""Named Material 3 color seeds for the Flet UI (Appearance theme picker)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple


@dataclass(frozen=True)
class PalettePreset:
    """One preset row in the theme grid."""

    id: str
    name: str
    """Hex seed passed to ``ft.Theme(color_scheme_seed=...)``."""
    seed: str
    is_dark: bool
    """If true, ``ThemeMode.DARK`` and dark glass tokens are used."""


# Fourteen curated presets (name + seed + light/dark shell).
PRESET_THEMES: Tuple[PalettePreset, ...] = (
    PalettePreset("cerebro", "Cerebro", "#22D3EE", True),
    PalettePreset("arctic", "Arctic", "#38BDF8", False),
    PalettePreset("blossom", "Blossom", "#F472B6", False),
    PalettePreset("dracula", "Dracula", "#BD93F9", True),
    PalettePreset("forest", "Forest", "#22C55E", False),
    PalettePreset("indigo", "Indigo", "#6366F1", False),
    PalettePreset("lavender", "Lavender", "#A78BFA", False),
    PalettePreset("midnight", "Midnight", "#1E3A8A", True),
    PalettePreset("ocean", "Ocean", "#0EA5E9", False),
    PalettePreset("rose", "Rose", "#FB7185", False),
    PalettePreset("slate", "Slate", "#64748B", True),
    PalettePreset("sunflower", "Sunflower", "#EAB308", False),
    PalettePreset("teal", "Teal", "#14B8A6", False),
    PalettePreset("ember", "Ember", "#F97316", False),
)


def preset_by_id(preset_id: str) -> PalettePreset | None:
    pid = (preset_id or "").strip().lower()
    for p in PRESET_THEMES:
        if p.id == pid:
            return p
    return None


def default_preset() -> PalettePreset:
    return PRESET_THEMES[0]
