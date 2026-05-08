"""VS Code-accurate palette presets with coy cheeky names."""

from __future__ import annotations

from dataclasses import dataclass
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


PRESET_THEMES: Tuple[PalettePreset, ...] = (
    # ------------------------------------------------------------------ dark
    PalettePreset(
        id="count_byteula",
        name="Count Byteula",                       # Dracula
        is_dark=True,
        bg="#282A36", bg2="#21222C", bg3="#44475A",
        fg="#F8F8F2", fg2="#BFBFBF", fg_muted="#6272A4",
        primary="#BD93F9", danger="#FF5555", success="#50FA7B", warning="#F1FA8C",
        border="#44475A", nav_bg="#21222C",
        seed="#BD93F9",
    ),
    PalettePreset(
        id="phantom_noir",
        name="Phantom Noir",                        # VS Code Dark+
        is_dark=True,
        bg="#1E1E1E", bg2="#252526", bg3="#2D2D30",
        fg="#D4D4D4", fg2="#CCCCCC", fg_muted="#808080",
        primary="#569CD6", danger="#F44747", success="#4EC9B0", warning="#CE9178",
        border="#3C3C3C", nav_bg="#333333",
        seed="#007ACC",
    ),
    PalettePreset(
        id="atoms_ghost",
        name="Atom's Ghost",                        # One Dark Pro
        is_dark=True,
        bg="#282C34", bg2="#21252B", bg3="#2C313A",
        fg="#ABB2BF", fg2="#828997", fg_muted="#5C6370",
        primary="#61AFEF", danger="#E06C75", success="#98C379", warning="#E5C07B",
        border="#3E4452", nav_bg="#21252B",
        seed="#61AFEF",
    ),
    PalettePreset(
        id="shibuya_3am",
        name="Shibuya at 3AM",                      # Tokyo Night
        is_dark=True,
        bg="#1A1B26", bg2="#16161E", bg3="#1F2335",
        fg="#A9B1D6", fg2="#787C99", fg_muted="#565F89",
        primary="#7AA2F7", danger="#F7768E", success="#9ECE6A", warning="#E0AF68",
        border="#292E42", nav_bg="#16161E",
        seed="#7AA2F7",
    ),
    PalettePreset(
        id="night_shift_survivor",
        name="Night Shift Survivor",                # Night Owl
        is_dark=True,
        bg="#011627", bg2="#01111D", bg3="#0B2942",
        fg="#D6DEEB", fg2="#A7B8CC", fg_muted="#637777",
        primary="#82AAFF", danger="#EF5350", success="#ADDB67", warning="#FFCB8B",
        border="#1D3B53", nav_bg="#010E1A",
        seed="#82AAFF",
    ),
    PalettePreset(
        id="octocats_lair",
        name="Octocat's Lair",                      # GitHub Dark
        is_dark=True,
        bg="#0D1117", bg2="#161B22", bg3="#1C2128",
        fg="#C9D1D9", fg2="#8B949E", fg_muted="#6E7681",
        primary="#58A6FF", danger="#F85149", success="#3FB950", warning="#D29922",
        border="#30363D", nav_bg="#010409",
        seed="#58A6FF",
    ),
    PalettePreset(
        id="og_peacock",
        name="The OG Peacock",                      # Monokai
        is_dark=True,
        bg="#272822", bg2="#1E1F1C", bg3="#3E3D32",
        fg="#F8F8F2", fg2="#CFCFC2", fg_muted="#75715E",
        primary="#66D9E8", danger="#F92672", success="#A6E22E", warning="#E6DB74",
        border="#3E3D32", nav_bg="#1E1F1C",
        seed="#A6E22E",
    ),
    PalettePreset(
        id="warm_beige_dad",
        name="Warm Beige Dad",                      # Gruvbox Dark
        is_dark=True,
        bg="#282828", bg2="#1D2021", bg3="#3C3836",
        fg="#EBDBB2", fg2="#D5C4A1", fg_muted="#928374",
        primary="#83A598", danger="#CC241D", success="#98971A", warning="#D79921",
        border="#3C3836", nav_bg="#1D2021",
        seed="#FE8019",
    ),
    PalettePreset(
        id="purple_cat_supremacy",
        name="Purple Cat Supremacy",                # Catppuccin Mocha
        is_dark=True,
        bg="#1E1E2E", bg2="#181825", bg3="#313244",
        fg="#CDD6F4", fg2="#BAC2DE", fg_muted="#6C7086",
        primary="#CBA6F7", danger="#F38BA8", success="#A6E3A1", warning="#F9E2AF",
        border="#45475A", nav_bg="#11111B",
        seed="#CBA6F7",
    ),
    PalettePreset(
        id="cerebro",
        name="Cerebro",                             # original house dark
        is_dark=True,
        bg="#060B14", bg2="#0B1220", bg3="#101A2E",
        fg="#F3F9FF", fg2="#C7D8F4", fg_muted="#8FA7CC",
        primary="#22D3EE", danger="#F87171", success="#34D399", warning="#FBBF24",
        border="#2B3A54", nav_bg="#080C11",
        seed="#22D3EE",
    ),
    # ----------------------------------------------------------------- light
    PalettePreset(
        id="blinding_white",
        name="Blinding White",                      # VS Code Light+
        is_dark=False,
        bg="#FFFFFF", bg2="#F3F3F3", bg3="#E8E8E8",
        fg="#1F1F1F", fg2="#3C3C3C", fg_muted="#717171",
        primary="#0078D4", danger="#E51400", success="#388A34", warning="#BF8803",
        border="#CECECE", nav_bg="#2C2C2C",
        seed="#0078D4",
    ),
    PalettePreset(
        id="alabaster_overachiever",
        name="Alabaster Overachiever",              # GitHub Light
        is_dark=False,
        bg="#FFFFFF", bg2="#F6F8FA", bg3="#EFF2F5",
        fg="#24292F", fg2="#57606A", fg_muted="#8C959F",
        primary="#0969DA", danger="#CF222E", success="#1A7F37", warning="#9A6700",
        border="#D0D7DE", nav_bg="#161B22",
        seed="#0969DA",
    ),
    PalettePreset(
        id="peppermint_incident",
        name="The Peppermint Incident",             # Solarized Light
        is_dark=False,
        bg="#FDF6E3", bg2="#EEE8D5", bg3="#E1D9C2",
        fg="#657B83", fg2="#586E75", fg_muted="#93A1A1",
        primary="#268BD2", danger="#DC322F", success="#859900", warning="#CB4B16",
        border="#D4CCBA", nav_bg="#002B36",
        seed="#268BD2",
    ),
    PalettePreset(
        id="arctic",
        name="Arctic",                              # original house light
        is_dark=False,
        bg="#F8FBFF", bg2="#EEF4FF", bg3="#E7EEFA",
        fg="#0B1220", fg2="#24344E", fg_muted="#50627F",
        primary="#2563EB", danger="#EF4444", success="#10B981", warning="#F59E0B",
        border="#CBD8EE", nav_bg="#0A1929",
        seed="#38BDF8",
    ),
    # ------------------------------------------------------------------ bonus 8
    PalettePreset(
        id="midnight_malware",
        name="Midnight Malware",                    # toxic neon pink on void black
        is_dark=True,
        bg="#080C12", bg2="#0D1318", bg3="#0F141C",
        fg="#D9D9D9", fg2="#C0C0C0", fg_muted="#3A3A4A",
        primary="#FF2C5C", danger="#FF2C5C", success="#00FF88", warning="#FFAA00",
        border="#1A2030", nav_bg="#0D1318",
        seed="#FF2C5C",
    ),
    PalettePreset(
        id="solarized_sarcasm",
        name="Solarized Sarcasm",                   # burnt orange, dry green, ironic warmth
        is_dark=False,
        bg="#FFF2E0", bg2="#EEE8D5", bg3="#F5EFE0",
        fg="#4A3B2C", fg2="#657B83", fg_muted="#C5AD8E",
        primary="#D14A2A", danger="#DC322F", success="#859900", warning="#CB4B16",
        border="#C5AD8E", nav_bg="#002B36",
        seed="#D14A2A",
    ),
    PalettePreset(
        id="high_contrast_hangover",
        name="High Contrast Hangover",              # yellow on black, throbbing headache
        is_dark=True,
        bg="#000000", bg2="#000000", bg3="#111111",
        fg="#FFFF00", fg2="#CCCCCC", fg_muted="#888888",
        primary="#FFFF00", danger="#FF0000", success="#00FF00", warning="#FF8800",
        border="#FFFF00", nav_bg="#000000",
        seed="#FFFF00",
    ),
    PalettePreset(
        id="pastel_pandemonium",
        name="Pastel Pandemonium",                  # terracotta + sage + lilac, cute chaos
        is_dark=False,
        bg="#FFFAF2", bg2="#F0EBE0", bg3="#F9F4E8",
        fg="#5A4C3E", fg2="#7A6C5E", fg_muted="#C0B0A0",
        primary="#E07A5F", danger="#E07A5F", success="#6A9C89", warning="#F4A261",
        border="#DDD0C0", nav_bg="#5A4C3E",
        seed="#E07A5F",
    ),
    PalettePreset(
        id="blue_screen_of_serenity",
        name="Blue Screen of Serenity",             # corporate navy shell, pale editor
        is_dark=False,
        bg="#F5F8FA", bg2="#EDF2F8", bg3="#E0EBF5",
        fg="#1A1A2E", fg2="#354A60", fg_muted="#A0B8D0",
        primary="#007ACC", danger="#FF0000", success="#2EA043", warning="#F5B800",
        border="#2A3C54", nav_bg="#1A2535",
        seed="#007ACC",
    ),
    PalettePreset(
        id="hackers_hangnail",
        name="Hacker's Hangnail",                   # matrix green on near-black
        is_dark=True,
        bg="#0D0D0D", bg2="#0A0A0A", bg3="#111111",
        fg="#33FF33", fg2="#22CC22", fg_muted="#1A4A1A",
        primary="#33FF33", danger="#FF3333", success="#00FF99", warning="#FFAA00",
        border="#1A3A1A", nav_bg="#0A0A0A",
        seed="#33FF33",
    ),
    PalettePreset(
        id="grayscale_gossip",
        name="Grayscale Gossip",                    # no colour, only contrast and weight
        is_dark=True,
        bg="#1E1E1E", bg2="#181818", bg3="#2D2D2D",
        fg="#D4D4D4", fg2="#B8B8B8", fg_muted="#505050",
        primary="#007ACC", danger="#FF4444", success="#888888", warning="#CCAA00",
        border="#333333", nav_bg="#181818",
        seed="#007ACC",
    ),
    PalettePreset(
        id="coral_reef_revenge",
        name="Coral Reef Revenge",                  # warm coral + deep teal, reef strikes back
        is_dark=False,
        bg="#FFF5EE", bg2="#EDE8E0", bg3="#F5F0E8",
        fg="#2C3E50", fg2="#4A5C6E", fg_muted="#B8A898",
        primary="#E76F51", danger="#E74C3C", success="#2A9D8F", warning="#E67E22",
        border="#C8BEB0", nav_bg="#2C3E50",
        seed="#E76F51",
    ),
)


def preset_by_id(preset_id: str) -> PalettePreset | None:
    pid = (preset_id or "").strip().lower()
    for p in PRESET_THEMES:
        if p.id == pid:
            return p
    return None


def default_preset() -> PalettePreset:
    return PRESET_THEMES[0]  # Count Byteula
