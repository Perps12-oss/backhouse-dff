# cerebro/core/theme_schema.py
"""
Theme Schema — 80 semantic color slot definitions with fallback chains.

Every themeable UI element has a semantic name (e.g. ``toolbar.background``).
A theme defines colors for these slots. If a slot is omitted, the engine
derives it via the fallback chain and derive function defined here.

Slot naming convention: ``area.element[.modifier][.state]``
  - ``area``      = UI zone (base, toolbar, panel, results, …)
  - ``element``   = specific widget or surface
  - ``modifier``  = variant (secondary, primary, hover)
  - ``state``     = interaction state (active, focus, selected)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass(frozen=True, slots=True)
class ColorSlot:
    """Definition of a single themeable color slot."""

    key: str                     # e.g. "toolbar.background"
    group: str                   # e.g. "toolbar"
    description: str             # Human-readable (for theme editor UI)
    fallback: Optional[str] = None   # Slot to fall back to if undefined
    derive_fn: Optional[str] = None  # e.g. "lighten:8", "darken:10", "alpha:50"


# =============================================================================
# Slot Registry — 80 slots across 12 groups
# =============================================================================

SLOT_REGISTRY: Dict[str, ColorSlot] = {}

def _s(key: str, group: str, desc: str,
        fallback: Optional[str] = None,
        derive: Optional[str] = None) -> ColorSlot:
    """Shorthand for creating a ColorSlot and registering it."""
    slot = ColorSlot(key=key, group=group, description=desc,
                    fallback=fallback, derive_fn=derive)
    SLOT_REGISTRY[key] = slot
    return slot


# ---- Base (12 slots) ----

_s("base.background",          "base", "Main window background")
_s("base.backgroundSecondary", "base", "Panel/sidebar backgrounds",
   fallback="base.background", derive="lighten:4")
_s("base.backgroundTertiary",  "base", "Card/row alternate backgrounds",
   fallback="base.backgroundSecondary", derive="lighten:4")
_s("base.backgroundElevated",  "base", "Elevated surfaces (dialogs, tooltips)",
   fallback="base.backgroundTertiary", derive="lighten:4")
_s("base.foreground",          "base", "Primary text color")
_s("base.foregroundSecondary", "base", "Secondary/muted text",
   fallback="base.foreground", derive="alpha:60")
_s("base.foregroundMuted",     "base", "Disabled/hint text",
   fallback="base.foreground", derive="alpha:35")
_s("base.border",              "base", "Default borders and dividers")
_s("base.borderActive",        "base", "Focused/active element border",
   fallback="base.accent")
_s("base.accent",              "base", "Primary accent color")
_s("base.accentHover",         "base", "Accent on hover/press",
   fallback="base.accent", derive="darken:10")
_s("base.accentMuted",         "base", "Subtle accent tint for backgrounds",
   fallback="base.accent", derive="alpha:20")

# ---- Toolbar (5 slots) ----

_s("toolbar.background",       "toolbar", "Toolbar strip background",
   fallback="base.backgroundSecondary")
_s("toolbar.foreground",       "toolbar", "Toolbar text and icons",
   fallback="base.foreground")
_s("toolbar.border",           "toolbar", "Bottom border of toolbar",
   fallback="base.border")
_s("toolbar.buttonHover",      "toolbar", "Button hover background",
   fallback="base.backgroundTertiary")
_s("toolbar.separator",        "toolbar", "Vertical separator between button groups",
   fallback="base.border", derive="alpha:50")

# ---- Tabs (6 slots) ----

_s("tabs.background",          "tabs", "Tab strip background",
   fallback="base.background")
_s("tabs.foreground",          "tabs", "Inactive tab text",
   fallback="base.foregroundSecondary")
_s("tabs.activeBackground",    "tabs", "Active/selected tab fill",
   fallback="base.accent")
_s("tabs.activeForeground",    "tabs", "Active tab text",
   fallback="base.background")
_s("tabs.hoverBackground",     "tabs", "Tab hover background",
   fallback="base.backgroundTertiary")
_s("tabs.border",              "tabs", "Tab strip bottom border",
   fallback="base.border")

# ---- Panel — Left sidebar (6 slots) ----

_s("panel.background",         "panel", "Left panel background",
   fallback="base.backgroundSecondary")
_s("panel.foreground",         "panel", "Left panel text",
   fallback="base.foreground")
_s("panel.border",             "panel", "Panel right border",
   fallback="base.border")
_s("panel.sectionHeader",      "panel", "Collapsible section header background",
   fallback="base.backgroundTertiary")
_s("panel.sectionHeaderText",  "panel", "Section header text",
   fallback="base.foregroundSecondary")
_s("panel.itemHover",          "panel", "Folder list row hover",
   fallback="base.backgroundTertiary")

# ---- Results — Center treeview (10 slots) ----

_s("results.background",       "results", "Treeview background",
   fallback="base.background")
_s("results.foreground",       "results", "Default row text",
   fallback="base.foreground")
_s("results.headerBackground", "results", "Duplicate group header row background",
   fallback="base.backgroundElevated")
_s("results.headerForeground", "results", "Group header text",
   fallback="base.accent")
_s("results.rowEven",          "results", "Even row background",
   fallback="base.background")
_s("results.rowOdd",           "results", "Odd row background",
   fallback="base.backgroundSecondary")
_s("results.rowHover",         "results", "Row mouse hover background",
   fallback="base.backgroundTertiary")
_s("results.rowSelected",      "results", "Selected row background",
   fallback="base.accentMuted")
_s("results.checkboxActive",   "results", "Checked checkbox color",
   fallback="base.accent")
_s("results.checkboxInactive", "results", "Unchecked checkbox color",
   fallback="base.foregroundMuted")

# ---- Preview — Bottom panel (5 slots) ----

_s("preview.background",       "preview", "Preview panel background",
   fallback="base.backgroundSecondary")
_s("preview.foreground",       "preview", "Preview text",
   fallback="base.foreground")
_s("preview.border",           "preview", "Preview panel top border",
   fallback="base.border")
_s("preview.metadataLabel",    "preview", 'Metadata labels ("Resolution:", "Size:")',
   fallback="base.foregroundSecondary")
_s("preview.metadataValue",    "preview", "Metadata values",
   fallback="base.foreground")

# ---- Selection Bar (4 slots) ----

_s("selection.background",     "selection", "Selection bar background",
   fallback="base.backgroundTertiary")
_s("selection.foreground",     "selection", "Selection bar text",
   fallback="base.foreground")
_s("selection.border",         "selection", "Top/bottom borders",
   fallback="base.border")
_s("selection.counter",        "selection", '"12 of 47" counter color',
   fallback="base.accent")

# ---- Status Bar (5 slots) ----

_s("status.background",        "status", "Status bar background",
   fallback="base.backgroundSecondary")
_s("status.foreground",        "status", "Status bar text",
   fallback="base.foregroundSecondary")
_s("status.border",            "status", "Status bar top border",
   fallback="base.border")
_s("status.progressBar",       "status", "Progress bar fill",
   fallback="base.accent")
_s("status.progressTrack",     "status", "Progress bar track",
   fallback="base.border")

# ---- Buttons (9 slots) ----

_s("button.primary",           "button", "Primary button bg (Start Search)",
   fallback="base.accent")
_s("button.primaryForeground", "button", "Primary button text",
   fallback="base.background")
_s("button.primaryHover",      "button", "Primary button hover",
   fallback="base.accentHover")
_s("button.secondary",         "button", "Secondary button background")
_s("button.secondaryForeground","button", "Secondary button text",
   fallback="base.foreground")
_s("button.secondaryBorder",   "button", "Secondary button border",
   fallback="base.border")
_s("button.secondaryHover",    "button", "Secondary button hover background",
   fallback="base.backgroundTertiary")
_s("button.danger",            "button", "Danger button bg (Delete)",
   fallback="feedback.danger")
_s("button.dangerForeground",  "button", "Danger button text")

# ---- Inputs (6 slots) ----

_s("input.background",         "input", "Text input / dropdown background",
   fallback="base.backgroundSecondary")
_s("input.foreground",         "input", "Input text",
   fallback="base.foreground")
_s("input.border",             "input", "Input border",
   fallback="base.border")
_s("input.borderFocus",        "input", "Input border when focused",
   fallback="base.accent")
_s("input.placeholder",        "input", "Placeholder text",
   fallback="base.foregroundMuted")
_s("input.sliderTrack",        "input", "Slider track color",
   fallback="base.border")

# ---- Dialogs (4 slots) ----

_s("dialog.background",        "dialog", "Dialog/popup background",
   fallback="base.backgroundElevated")
_s("dialog.foreground",        "dialog", "Dialog text",
   fallback="base.foreground")
_s("dialog.border",            "dialog", "Dialog border",
   fallback="base.border")
_s("dialog.overlay",           "dialog", "Semi-transparent backdrop")

# ---- Feedback / Semantic (8 slots) ----

_s("feedback.success",          "feedback", "Success text/icon (scan complete)")
_s("feedback.successBackground","feedback", "Success background tint")
_s("feedback.warning",          "feedback", "Warning text/icon (protected folder)")
_s("feedback.warningBackground","feedback", "Warning background tint")
_s("feedback.danger",           "feedback", "Error text/icon (read failure)")
_s("feedback.dangerBackground", "feedback", "Error background tint")
_s("feedback.info",             "feedback", "Info text/icon (scan hint)")
_s("feedback.infoBackground",   "feedback", "Info background tint")


# =============================================================================
# Slot Groups — convenient access by area
# =============================================================================

SLOT_GROUPS: Dict[str, List[str]] = {
    "base":       sorted(k for k, v in SLOT_REGISTRY.items() if v.group == "base"),
    "toolbar":    sorted(k for k, v in SLOT_REGISTRY.items() if v.group == "toolbar"),
    "tabs":       sorted(k for k, v in SLOT_REGISTRY.items() if v.group == "tabs"),
    "panel":      sorted(k for k, v in SLOT_REGISTRY.items() if v.group == "panel"),
    "results":    sorted(k for k, v in SLOT_REGISTRY.items() if v.group == "results"),
    "preview":    sorted(k for k, v in SLOT_REGISTRY.items() if v.group == "preview"),
    "selection":  sorted(k for k, v in SLOT_REGISTRY.items() if v.group == "selection"),
    "status":     sorted(k for k, v in SLOT_REGISTRY.items() if v.group == "status"),
    "button":     sorted(k for k, v in SLOT_REGISTRY.items() if v.group == "button"),
    "input":      sorted(k for k, v in SLOT_REGISTRY.items() if v.group == "input"),
    "dialog":     sorted(k for k, v in SLOT_REGISTRY.items() if v.group == "dialog"),
    "feedback":   sorted(k for k, v in SLOT_REGISTRY.items() if v.group == "feedback"),
}

# =============================================================================
# Required slots for a minimal valid theme (the 12 base.* slots)
# =============================================================================

REQUIRED_SLOTS: List[str] = sorted(
    k for k, v in SLOT_REGISTRY.items() if v.group == "base"
)

# =============================================================================
# Default semantic colors (hardcoded fallbacks when nothing else resolves)
# =============================================================================

# These are used as absolute last-resort values when even the theme type
# default cannot be computed.

DEFAULT_DARK: Dict[str, str] = {
    "base.background":          "#1E1E1E",
    "base.backgroundSecondary": "#252526",
    "base.backgroundTertiary":  "#2D2D2D",
    "base.backgroundElevated":  "#383838",
    "base.foreground":          "#D4D4D4",
    "base.foregroundSecondary": "#808080",
    "base.foregroundMuted":     "#5A5A5A",
    "base.border":              "#3C3C3C",
    "base.borderActive":        "#007ACC",
    "base.accent":              "#007ACC",
    "base.accentHover":         "#1C97EA",
    "base.accentMuted":         "#1E3A5F",
}

DEFAULT_LIGHT: Dict[str, str] = {
    "base.background":          "#FFFFFF",
    "base.backgroundSecondary": "#F3F3F3",
    "base.backgroundTertiary":  "#E8E8E8",
    "base.backgroundElevated":  "#E0E0E0",
    "base.foreground":          "#1E1E1E",
    "base.foregroundSecondary": "#616161",
    "base.foregroundMuted":     "#9E9E9E",
    "base.border":              "#C8C8C8",
    "base.borderActive":        "#0066B8",
    "base.accent":              "#0066B8",
    "base.accentHover":         "#005BA4",
    "base.accentMuted":         "#CCE4F7",
}

DEFAULT_FEEDBACK: Dict[str, str] = {
    "feedback.success":           "#3FB950",
    "feedback.successBackground": "#0D2818",
    "feedback.warning":           "#D29922",
    "feedback.warningBackground": "#2D1F05",
    "feedback.danger":            "#F85149",
    "feedback.dangerBackground":  "#2D0709",
    "feedback.info":              "#58A6FF",
    "feedback.infoBackground":    "#0D1D30",
}

# Default values for slots that have no derive_fn and no fallback
# (these are the hardcoded constants in the schema)
HARDCODED_DEFAULTS: Dict[str, str] = {
    "button.secondary":          "#1E2533",   # subtle elevated bg; never transparent
    "button.dangerForeground":   "#FFFFFF",
    "dialog.overlay":            "#000000",
}


# =============================================================================
# Validation
# =============================================================================

def validate_slot_key(key: str) -> bool:
    """Return True if *key* is a recognized slot name."""
    return key in SLOT_REGISTRY


def get_slot(key: str) -> Optional[ColorSlot]:
    """Get a ColorSlot by key, or None if unknown."""
    return SLOT_REGISTRY.get(key)


def total_slots() -> int:
    """Return total number of registered slots."""
    return len(SLOT_REGISTRY)


def check_fallback_cycles() -> List[List[str]]:
    """Detect any circular fallback chains. Returns list of cycles (empty if OK)."""
    visited: Dict[str, Optional[str]] = {}  # key → parent that led here
    cycles: List[List[str]] = []

    def _walk(key: str, path: List[str]) -> None:
        slot = SLOT_REGISTRY.get(key)
        if slot is None or slot.fallback is None:
            return
        if slot.fallback in path:
            cycle_start = path.index(slot.fallback)
            cycles.append(path[cycle_start:] + [slot.fallback])
            return
        path.append(slot.fallback)
        _walk(slot.fallback, path)
        path.pop()

    for key in SLOT_REGISTRY:
        _walk(key, [key])

    return cycles


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    "ColorSlot",
    "SLOT_REGISTRY",
    "SLOT_GROUPS",
    "REQUIRED_SLOTS",
    "DEFAULT_DARK",
    "DEFAULT_LIGHT",
    "DEFAULT_FEEDBACK",
    "HARDCODED_DEFAULTS",
    "validate_slot_key",
    "get_slot",
    "total_slots",
    "check_fallback_cycles",
]
