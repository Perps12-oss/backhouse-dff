# cerebro/core/theme_engine_v3.py
"""
Theme Engine v3 — central theme manager for Cerebro v2.

Framework-agnostic (no Qt, no Tkinter imports). Loads JSON themes,
resolves all 80 semantic slots via fallback chains, persists the active
theme, and notifies listeners on change.

This is the SINGLE SOURCE OF TRUTH for theme state. Both the v1 (PySide6)
and v2 (CustomTkinter) UIs read from this engine via their respective bridges.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .color_utils import (
    apply_derive,
    normalize_hex,
    validate_hex,
    darken,
    lighten,
)
from .theme_schema import (
    DEFAULT_DARK,
    DEFAULT_FEEDBACK,
    DEFAULT_LIGHT,
    HARDCODED_DEFAULTS,
    REQUIRED_SLOTS,
    SLOT_REGISTRY,
    ColorSlot,
    total_slots,
    validate_slot_key,
)


# =============================================================================
# Paths
# =============================================================================

def _builtin_dir() -> Path:
    """Directory containing built-in theme JSON files."""
    return Path(__file__).resolve().parent.parent / "themes" / "builtin"


def _user_themes_dir() -> Path:
    """Directory for user-created/imported themes."""
    from pathlib import Path as P
    # Cross-platform: ~/.cerebro/themes/
    base = P.home() / ".cerebro" / "themes"
    base.mkdir(parents=True, exist_ok=True)
    return base


# =============================================================================
# Theme Loader — validate, load, save JSON themes
# =============================================================================

class ThemeLoadError(Exception):
    """Raised when a theme JSON fails validation."""


def validate_theme(data: Dict[str, Any]) -> List[str]:
    """Validate a theme dict. Returns a list of error strings (empty = valid)."""
    errors: List[str] = []

    if not isinstance(data.get("name"), str) or not data["name"].strip():
        errors.append("Missing or empty 'name' field")

    theme_type = data.get("type")
    if theme_type not in ("dark", "light"):
        errors.append(f"Invalid 'type': must be 'dark' or 'light', got '{theme_type}'")

    colors = data.get("colors")
    if not isinstance(colors, dict) or len(colors) == 0:
        errors.append("Missing or empty 'colors' object")
    else:
        # Check required slots
        for slot in REQUIRED_SLOTS:
            if slot not in colors:
                errors.append(f"Missing required color slot: '{slot}'")

        # Validate all color values (allow 'transparent' as a special value)
        for key, value in colors.items():
            if isinstance(value, str) and value.strip().lower() == "transparent":
                continue  # valid special value
            if not isinstance(value, str) or not validate_hex(value):
                errors.append(f"Invalid hex color for '{key}': '{value}'")
            elif not validate_slot_key(key):
                pass  # unknown slots are silently ignored

    return errors


def load_theme_json(path: Path) -> Dict[str, Any]:
    """Load and validate a theme JSON file. Raises ThemeLoadError on failure."""
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (json.JSONDecodeError, OSError) as e:
        raise ThemeLoadError(f"Failed to read {path}: {e}")

    if not isinstance(data, dict):
        raise ThemeLoadError(f"Theme file {path} does not contain a JSON object")

    errors = validate_theme(data)
    if errors:
        raise ThemeLoadError(f"Theme '{data.get('name', '?')}' has errors:\n" +
                             "\n".join(f"  - {e}" for e in errors))

    # Normalize all color values
    colors = data.get("colors", {})
    for key in list(colors.keys()):
        if validate_slot_key(key):
            colors[key] = normalize_hex(colors[key])

    return data


# =============================================================================
# Theme Engine v3
# =============================================================================

class ThemeEngineV3:
    """Central theme manager. Singleton.

    Usage::

        engine = ThemeEngineV3.get()
        engine.set_theme("Cerebro Dark")
        bg = engine.get_color("base.background")
        engine.subscribe(my_widget_refresh)
    """

    _instance: Optional[ThemeEngineV3] = None

    def __init__(self) -> None:
        self._themes: Dict[str, Dict[str, Any]] = {}
        self._active: str = ""
        self._resolved: Dict[str, str] = {}
        self._listeners: List[Callable[[], None]] = []

        # Ensure directories exist
        _builtin_dir().mkdir(parents=True, exist_ok=True)
        _user_themes_dir().mkdir(parents=True, exist_ok=True)

        # Load all themes
        self._load_all()

        # Restore persisted theme or default
        saved = self._load_from_config()
        if saved and saved in self._themes:
            self._active = saved
        else:
            self._active = self._all_names()[0] if self._all_names() else ""

        self._resolve_all()

    # ------------------------------------------------------------------
    # Singleton
    # ------------------------------------------------------------------

    @classmethod
    def get(cls) -> ThemeEngineV3:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset singleton (useful for testing)."""
        cls._instance = None

    # ------------------------------------------------------------------
    # Theme loading
    # ------------------------------------------------------------------

    def _load_all(self) -> None:
        """Load built-in and user themes."""
        self._themes.clear()

        # Built-in themes
        for path in _builtin_dir().glob("*.json"):
            try:
                data = load_theme_json(path)
                name = data.get("name", path.stem)
                self._themes[name] = data
            except ThemeLoadError:
                pass  # skip invalid built-in themes

        # User themes (can override built-ins by name)
        for path in _user_themes_dir().glob("*.json"):
            try:
                data = load_theme_json(path)
                name = data.get("name", path.stem)
                self._themes[name] = data
            except ThemeLoadError:
                pass  # skip invalid user themes

    def reload(self) -> None:
        """Reload all themes from disk (picks up new user themes)."""
        self._load_all()
        if self._active not in self._themes:
            self._active = self._all_names()[0] if self._all_names() else ""
        self._resolve_all()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_theme(self, name: str) -> bool:
        """Switch to a theme by name. Resolves all 80 slots and notifies listeners."""
        if name not in self._themes:
            return False
        self._active = name
        self._resolve_all()
        self._save_to_config(name)
        self._notify_listeners()
        return True

    def get_color(self, slot: str, fallback: str = "#FF00FF") -> str:
        """Get the resolved hex color for a semantic slot.

        Returns *fallback* (magenta by default) if the slot is unknown.
        """
        if slot in self._resolved:
            return self._resolved[slot]
        return fallback

    def get_all_resolved(self) -> Dict[str, str]:
        """Return a copy of all 80 resolved color slots."""
        return dict(self._resolved)

    @property
    def active_theme_name(self) -> str:
        return self._active

    def get_theme_data(self, name: str) -> Optional[Dict[str, Any]]:
        """Return the raw theme data dict for a theme."""
        return self._themes.get(name)

    def get_theme_metadata(self, name: str) -> Dict[str, Any]:
        """Return metadata (name, type, description) for a theme."""
        data = self._themes.get(name)
        if data is None:
            return {}
        return {
            "name": data.get("name", name),
            "type": data.get("type", "dark"),
            "description": data.get("description", ""),
            "author": data.get("author", ""),
            "version": data.get("version", ""),
        }

    def all_theme_names(self) -> List[str]:
        """Return sorted list of all available theme names."""
        return sorted(self._themes.keys())

    def _all_names(self) -> List[str]:
        return list(self._themes.keys())

    # ------------------------------------------------------------------
    # Slot resolution
    # ------------------------------------------------------------------

    def _resolve_all(self) -> None:
        """Resolve all 80 slots from the active theme."""
        self._resolved.clear()

        theme = self._themes.get(self._active)
        if theme is None:
            return

        theme_colors: Dict[str, str] = theme.get("colors", {})
        theme_type: str = theme.get("type", "dark")
        defaults = DEFAULT_DARK if theme_type == "dark" else DEFAULT_LIGHT

        # Phase 0: seed feedback defaults so fallback chains can reach them
        for key, value in DEFAULT_FEEDBACK.items():
            self._resolved[key] = value

        # Phase 0b: seed hardcoded defaults
        for key, value in HARDCODED_DEFAULTS.items():
            self._resolved[key] = value

        # Phase 1: resolve all slots (explicit → fallback → derive → default)
        for key, slot in SLOT_REGISTRY.items():
            self._resolve_slot(key, slot, theme_colors, defaults)

    def _resolve_slot(self, key: str, slot: ColorSlot,
                      theme_colors: Dict[str, str],
                      defaults: Dict[str, str]) -> None:
        """Resolve a single slot: explicit → fallback → derive → default."""
        # 1. Explicit value in theme JSON
        if key in theme_colors:
            self._resolved[key] = theme_colors[key]
            return

        # 2. Follow fallback chain (recursive via _resolved cache)
        if slot.fallback is not None:
            # Check if fallback is already resolved
            if slot.fallback in self._resolved:
                base = self._resolved[slot.fallback]
                if slot.derive_fn:
                    self._resolved[key] = apply_derive(base, slot.derive_fn)
                else:
                    self._resolved[key] = base
                return

            # Follow the fallback's fallback first
            fallback_slot = SLOT_REGISTRY.get(slot.fallback)
            if fallback_slot is not None:
                self._resolve_slot(slot.fallback, fallback_slot,
                                  theme_colors, defaults)
                if slot.fallback in self._resolved:
                    base = self._resolved[slot.fallback]
                    if slot.derive_fn:
                        self._resolved[key] = apply_derive(base, slot.derive_fn)
                    else:
                        self._resolved[key] = base
                    return

        # 3. Derive-only (no fallback, but has derive_fn)
        if slot.derive_fn is not None:
            # Try to derive from the group's base slot
            group_base = f"{slot.group}.{['background', 'foreground'][0]}"
            if group_base in self._resolved:
                self._resolved[key] = apply_derive(self._resolved[group_base],
                                                    slot.derive_fn)
                return

        # 4. Type-based default
        if key in defaults:
            self._resolved[key] = defaults[key]

    # ------------------------------------------------------------------
    # Listener management (pub/sub)
    # ------------------------------------------------------------------

    def subscribe(self, callback: Callable[[], None]) -> None:
        """Register a callback to be called when the theme changes."""
        if callback not in self._listeners:
            self._listeners.append(callback)

    def unsubscribe(self, callback: Callable[[], None]) -> None:
        """Unregister a callback."""
        try:
            self._listeners.remove(callback)
        except ValueError:
            pass

    def _notify_listeners(self) -> None:
        """Call all registered callbacks. Catches errors per-listener."""
        for cb in self._listeners:
            try:
                cb()
            except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
                pass

    # ------------------------------------------------------------------
    # Import / Export
    # ------------------------------------------------------------------

    def import_theme(self, path: Path) -> str:
        """Import a theme JSON file. Returns the theme name.

        Raises ThemeLoadError if the file is invalid.
        """
        data = load_theme_json(path)
        name = data["name"]

        # Save to user themes directory
        dest = _user_themes_dir() / f"{_slugify(name)}.json"
        dest.write_text(json.dumps(data, indent=2), encoding="utf-8")

        # Reload and switch
        self.reload()
        return name

    def export_theme(self, name: str, path: Path) -> bool:
        """Export the resolved colors for a theme to a JSON file."""
        if name not in self._themes:
            return False

        # Save current active as a snapshot with all 80 resolved slots
        was_active = self._active
        if self._active != name:
            self.set_theme(name)

        export_data = {
            "name": name,
            "type": self._themes[name].get("type", "dark"),
            "description": f"Exported from Cerebro v2",
            "colors": dict(self._resolved),
        }

        path.write_text(json.dumps(export_data, indent=2), encoding="utf-8")

        # Restore previous active
        if was_active != name and was_active in self._themes:
            self.set_theme(was_active)

        return True

    # ------------------------------------------------------------------
    # Config persistence
    # ------------------------------------------------------------------

    def _load_from_config(self) -> Optional[str]:
        """Load the saved theme name from Cerebro config."""
        try:
            from cerebro.services.config import load_config
            cfg = load_config()
            ui = getattr(cfg, "ui", None)
            if ui is not None:
                theme = getattr(ui, "theme", None)
                if isinstance(theme, str) and theme.strip():
                    return theme.strip()
        except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
            pass
        return None

    def _save_to_config(self, name: str) -> None:
        """Persist the active theme name to Cerebro config."""
        try:
            from cerebro.services.config import load_config, save_config
            cfg = load_config()
            ui = getattr(cfg, "ui", None)
            if ui is not None and hasattr(ui, "theme"):
                ui.theme = name
                save_config(cfg)
        except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
            pass

    # ------------------------------------------------------------------
    # Debug / Introspection
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (f"ThemeEngineV3(active='{self._active}', "
                f"themes={len(self._themes)}, "
                f"resolved={len(self._resolved)}, "
                f"listeners={len(self._listeners)})")


# =============================================================================
# Utilities
# =============================================================================

def _slugify(name: str) -> str:
    """Convert a theme name to a filesystem-safe slug."""
    import re
    s = name.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    s = s.strip("_")
    return s or "untitled"


__all__ = [
    "ThemeEngineV3",
    "ThemeLoadError",
    "validate_theme",
    "load_theme_json",
]
