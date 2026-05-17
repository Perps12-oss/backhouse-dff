"""Flet-base palette preset and legacy theme id migration."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Tuple


@dataclass(frozen=True)
class PalettePreset:
    """Full color spec for one theme preset."""

    id: str
    name: str
    is_dark: bool

    # Surface hierarchy
    bg: str
    bg2: str
    bg3: str

    # Text hierarchy
    fg: str
    fg2: str
    fg_muted: str

    # Semantic
    primary: str
    danger: str
    success: str
    warning: str

    # Structure
    border: str
    nav_bg: str

    # Material 3 seed (matches primary unless noted)
    seed: str


FLET_BASE_PRESET = PalettePreset(
    id="flet_base",
    name="Flet Base",
    is_dark=True,
    bg="#121212",
    bg2="#1e1e1e",
    bg3="#2a2a2a",
    fg="#FFFFFF",
    fg2="#B3B3B3",
    fg_muted="#737373",
    primary="#1DB954",
    danger="#E91429",
    success="#1DB954",
    warning="#F59E0B",
    border="#2a2a2a",
    nav_bg="#1e1e1e",
    seed="#1DB954",
)

PRESET_THEMES: Tuple[PalettePreset, ...] = (FLET_BASE_PRESET,)

# Legacy VS Code-style ids → flet_base (or gradient id where noted).
_LEGACY_PRESET_ALIASES: dict[str, str] = {
    "count_byteula": "flet_base",
    "phantom_noir": "flet_base",
    "atoms_ghost": "flet_base",
    "shibuya_3am": "flet_base",
    "night_shift_survivor": "flet_base",
    "octocats_lair": "flet_base",
    "og_peacock": "flet_base",
    "warm_beige_dad": "flet_base",
    "purple_cat_supremacy": "flet_base",
    "cerebro": "flet_base",
    "blinding_white": "flet_base",
    "alabaster_overachiever": "flet_base",
    "peppermint_incident": "flet_base",
    "arctic": "flet_base",
    "midnight_malware": "gradient_crimson",
    "solarized_sarcasm": "flet_base",
    "high_contrast_hangover": "flet_base",
    "pastel_pandemonium": "flet_base",
    "blue_screen_of_serenity": "flet_base",
    "hackers_hangnail": "gradient_matrix",
    "grayscale_gossip": "gradient_slate",
    "coral_reef_revenge": "gradient_coral",
    "neon_void": "gradient_ocean",
    "glass_day": "flet_base",
}


def resolve_preset_id(preset_id: str) -> str:
    """Map stored settings id to a current gradient or flet_base id."""
    pid = (preset_id or "").strip().lower()
    if not pid:
        return "flet_base"
    return _LEGACY_PRESET_ALIASES.get(pid, pid)


def preset_by_id(preset_id: str) -> PalettePreset | None:
    pid = resolve_preset_id(preset_id)
    for p in PRESET_THEMES:
        if p.id == pid:
            return p
    return None


def default_preset() -> PalettePreset:
    return FLET_BASE_PRESET


def derive_preset_from_base(
    base: PalettePreset,
    *,
    preset_id: str,
    name: str,
    primary: str,
    seed: str | None = None,
) -> PalettePreset:
    """Build a palette from flet_base surfaces with gradient-driven accent."""
    return replace(
        base,
        id=preset_id,
        name=name,
        primary=primary,
        seed=seed or primary,
        success=primary,
    )
