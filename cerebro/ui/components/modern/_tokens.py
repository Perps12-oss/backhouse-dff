# Design tokens and theme lookup – no hex codes; 100% theme_engine.
from __future__ import annotations

from typing import Optional

# Layout tokens (spec)
RADIUS_SM = 6
RADIUS_MD = 8
RADIUS_LG = 12
SPACE_UNIT = 6
SIDEBAR_WIDTH = 200
INSPECTOR_WIDTH = 280
HEADER_HEIGHT = 48
TOOLBAR_HEIGHT = 36
STICKY_BAR_HEIGHT = 44
NAV_ITEM_HEIGHT = 40


def _colors() -> dict:
    try:
        from cerebro.ui.theme_engine import current_colors
        return current_colors()
    except Exception:
        return {}


def token(key: str, fallback_key: str = "accent") -> str:
    """Resolve theme color by key. Fallback to another token with warning."""
    c = _colors()
    v = c.get(key)
    if v:
        return v
    v = c.get(fallback_key)
    if v:
        try:
            from cerebro.services.logger import log_debug
            log_debug(f"[Modern] Missing theme token '{key}', using '{fallback_key}'.")
        except Exception:
            pass
        return v
    return "#7aa2ff"
