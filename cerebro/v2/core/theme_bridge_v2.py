# cerebro/v2/core/theme_bridge_v2.py
"""
V2 Theme Bridge — connects ThemeEngineV3 to the CustomTkinter UI.

Provides a simple API for v2 components to get themed colors at runtime
instead of using the static Colors class from design_tokens.py.

Usage in v2 components::

    from cerebro.v2.core.theme_bridge_v2 import theme_color, subscribe_to_theme

    class MyWidget(ctk.CTkFrame):
        def __init__(self, master, **kwargs):
            super().__init__(master, fg_color=theme_color("panel.background"), **kwargs)
            subscribe_to_theme(self, self._apply_theme)
            self._apply_theme()

        def _apply_theme(self):
            self.configure(fg_color=theme_color("panel.background"))
"""

from __future__ import annotations

from typing import Callable, Optional


def theme_color(slot: str, fallback: str = "#7aa2ff") -> str:
    """Get the current theme color for a semantic slot.

    This is the v2 equivalent of the v1 ``token(key)`` function.
    It reads from ThemeEngineV3, which resolves all 80 slots
    via fallback chains and derive functions.

    Args:
        slot: Semantic color slot name (e.g. "base.background", "toolbar.foreground").
        fallback: Hex color returned if the slot cannot be resolved (magenta by default).

    Returns:
        Resolved hex color string (e.g. "#0a0e14").
    """
    try:
        from cerebro.core.theme_engine_v3 import ThemeEngineV3
        return ThemeEngineV3.get().get_color(slot, fallback)
    except Exception:
        return fallback


def theme_colors() -> dict:
    """Get all 80 resolved color slots as a flat dict.

    Useful for bulk operations or components that need many colors at once.
    """
    try:
        from cerebro.core.theme_engine_v3 import ThemeEngineV3
        return ThemeEngineV3.get().get_all_resolved()
    except Exception:
        return {}


def theme_type() -> str:
    """Get the current theme type: 'dark' or 'light'."""
    try:
        from cerebro.core.theme_engine_v3 import ThemeEngineV3
        engine = ThemeEngineV3.get()
        return engine.get_theme_metadata(engine.active_theme_name).get("type", "dark")
    except Exception:
        return "dark"


def is_dark_theme() -> bool:
    """Return True if the current theme is dark."""
    return theme_type() == "dark"


def subscribe_to_theme(widget, apply_fn: Callable[[], None]) -> None:
    """Register a widget for theme change notifications.

    When the theme changes, *apply_fn* will be called. The widget should
    re-read all colors via ``theme_color()`` inside this function.

    Args:
        widget: The CTk widget (unused directly, but stored for reference).
        apply_fn: Callable that re-applies colors to the widget.
    """
    try:
        from cerebro.core.theme_engine_v3 import ThemeEngineV3
        ThemeEngineV3.get().subscribe(apply_fn)
    except Exception:
        pass


def unsubscribe_from_theme(widget, apply_fn: Callable[[], None]) -> None:
    """Unregister a widget from theme change notifications.

    Args:
        widget: The CTk widget (unused, but kept for API consistency).
        apply_fn: The same callable that was passed to subscribe_to_theme.
    """
    try:
        from cerebro.core.theme_engine_v3 import ThemeEngineV3
        ThemeEngineV3.get().unsubscribe(apply_fn)
    except Exception:
        pass


def set_ctk_appearance_mode() -> None:
    """Sync CustomTkinter's appearance mode with the current theme type.

    Call this after setting a theme to ensure CTk renders correctly.
    'Dark' theme → ctk.set_appearance_mode("Dark")
    'Light' theme → ctk.set_appearance_mode("Light")
    """
    try:
        import customtkinter as ctk
        mode = "Dark" if is_dark_theme() else "Light"
        ctk.set_appearance_mode(mode)
    except Exception:
        pass


# =============================================================================
# Convenience aliases — map old Colors constants to semantic slots
# These allow gradual migration: components can switch one alias at a time.
# =============================================================================

# Backgrounds
BG_PRIMARY = lambda: theme_color("base.background")
BG_SECONDARY = lambda: theme_color("base.backgroundSecondary")
BG_TERTIARY = lambda: theme_color("base.backgroundTertiary")
BG_QUATERNARY = lambda: theme_color("base.backgroundElevated")

# Foregrounds
TEXT_PRIMARY = lambda: theme_color("base.foreground")
TEXT_SECONDARY = lambda: theme_color("base.foregroundSecondary")
TEXT_MUTED = lambda: theme_color("base.foregroundMuted")
TEXT_DISABLED = lambda: theme_color("base.foregroundMuted")

# Borders
BORDER = lambda: theme_color("base.border")
BORDER_LIGHT = lambda: theme_color("base.borderActive")
BORDER_DIM = lambda: theme_color("base.border")

# Accents
ACCENT = lambda: theme_color("base.accent")
ACCENT_HOVER = lambda: theme_color("base.accentHover")
ACCENT_DIM = lambda: theme_color("base.accentMuted")

# Semantic
DANGER = lambda: theme_color("feedback.danger")
DANGER_HOVER = lambda: theme_color("feedback.danger")
SUCCESS = lambda: theme_color("feedback.success")
SUCCESS_HOVER = lambda: theme_color("feedback.success")
WARNING = lambda: theme_color("feedback.warning")
WARNING_HOVER = lambda: theme_color("feedback.warning")
INFO = lambda: theme_color("feedback.info")

# CTk-compatible string getters (drop-in replacement for static constants)
CTK_BG_PRIMARY = property(lambda self: theme_color("base.background"))
CTK_BG_SECONDARY = property(lambda self: theme_color("base.backgroundSecondary"))
CTK_BG_TERTIARY = property(lambda self: theme_color("base.backgroundTertiary"))
CTK_ACCENT = property(lambda self: theme_color("base.accent"))
CTK_ACCENT_HOVER = property(lambda self: theme_color("base.accentHover"))
CTK_TEXT_PRIMARY = property(lambda self: theme_color("base.foreground"))
CTK_TEXT_SECONDARY = property(lambda self: theme_color("base.foregroundSecondary"))
CTK_DANGER = property(lambda self: theme_color("feedback.danger"))
CTK_SUCCESS = property(lambda self: theme_color("feedback.success"))
CTK_WARNING = property(lambda self: theme_color("feedback.warning"))


# =============================================================================
# Slot mapping — old Colors constant name → semantic slot
# Used by migration tooling and for documentation.
# =============================================================================

COLORS_TO_SLOTS = {
    "BG_PRIMARY": "base.background",
    "BG_SECONDARY": "base.backgroundSecondary",
    "BG_TERTIARY": "base.backgroundTertiary",
    "BG_QUATERNARY": "base.backgroundElevated",
    "ACCENT": "base.accent",
    "ACCENT_HOVER": "base.accentHover",
    "ACCENT_DIM": "base.accentMuted",
    "TEXT_PRIMARY": "base.foreground",
    "TEXT_SECONDARY": "base.foregroundSecondary",
    "TEXT_MUTED": "base.foregroundMuted",
    "TEXT_DISABLED": "base.foregroundMuted",
    "BORDER": "base.border",
    "BORDER_LIGHT": "base.borderActive",
    "BORDER_DIM": "base.border",
    "DANGER": "feedback.danger",
    "DANGER_HOVER": "feedback.danger",
    "SUCCESS": "feedback.success",
    "SUCCESS_HOVER": "feedback.success",
    "WARNING": "feedback.warning",
    "WARNING_HOVER": "feedback.warning",
    "INFO": "feedback.info",
    "CTK_BG_PRIMARY": "base.background",
    "CTK_BG_SECONDARY": "base.backgroundSecondary",
    "CTK_BG_TERTIARY": "base.backgroundTertiary",
    "CTK_ACCENT": "base.accent",
    "CTK_ACCENT_HOVER": "base.accentHover",
    "CTK_TEXT_PRIMARY": "base.foreground",
    "CTK_TEXT_SECONDARY": "base.foregroundSecondary",
    "CTK_DANGER": "feedback.danger",
    "CTK_SUCCESS": "feedback.success",
    "CTK_WARNING": "feedback.warning",
}


__all__ = [
    "theme_color",
    "theme_colors",
    "theme_type",
    "is_dark_theme",
    "subscribe_to_theme",
    "unsubscribe_from_theme",
    "set_ctk_appearance_mode",
    "COLORS_TO_SLOTS",
]
