# Design tokens and theme lookup — unified v3 engine with legacy fallback.
from __future__ import annotations

from typing import Dict, Optional

# Layout tokens (spec)
RADIUS_SM = 6
RADIUS_MD = 8
RADIUS_LG = 12
SPACE_UNIT = 8
SIDEBAR_WIDTH = 240
INSPECTOR_WIDTH = 320
HEADER_HEIGHT = 64
TOOLBAR_HEIGHT = 48
STICKY_BAR_HEIGHT = 56
NAV_ITEM_HEIGHT = 48


def _colors() -> Dict[str, str]:
    """Resolve theme colors from ThemeEngineV3 (preferred) or legacy engine.

    Returns a dict with BOTH semantic keys (e.g. "base.background") and
    legacy keys (e.g. "bg", "panel", "accent") so all existing token()
    calls keep working without changes.
    """
    # ---- Try ThemeEngineV3 first ----
    try:
        from cerebro.core.theme_engine_v3 import ThemeEngineV3
        engine = ThemeEngineV3.get()
        if engine and engine.active_theme_name:
            from cerebro.ui.theme_bridge_v1 import build_legacy_colors
            return build_legacy_colors(engine)
    except Exception:
        pass

    # ---- Fallback to legacy ThemeEngine ----
    try:
        from cerebro.ui.theme_engine import current_colors
        return current_colors()
    except Exception:
        pass

    return {}


def token(key: str, fallback_key: str = "accent") -> str:
    """Resolve theme color by key with fallback chain.

    Supports both legacy keys ("bg", "panel", "accent") and semantic
    keys ("base.background", "toolbar.foreground", etc.).

    Resolution order:
      1. Look up *key* directly in colors dict
      2. Look up *fallback_key* in colors dict
      3. Try resolving *key* through LEGACY_KEY_MAP (semantic mapping)
      4. Hardcoded fallback "#7aa2ff"
    """
    c = _colors()
    v = c.get(key)
    if v:
        return v

    # Try fallback key
    v = c.get(fallback_key)
    if v:
        _log_missing(key, fallback_key)
        return v

    # Try legacy key mapping
    try:
        from cerebro.ui.theme_bridge_v1 import LEGACY_KEY_MAP
        semantic = LEGACY_KEY_MAP.get(key)
        if semantic:
            v = c.get(semantic)
            if v:
                _log_missing(key, semantic)
                return v
    except Exception:
        pass

    return "#7aa2ff"


def _log_missing(key: str, resolved_via: str) -> None:
    """Log a debug message about a missing token (non-fatal)."""
    try:
        from cerebro.services.logger import log_debug
        log_debug(f"[Modern] Missing theme token '{key}', resolved via '{resolved_via}'.")
    except Exception:
        pass
