"""
ThemeApplicator — single global entry point for applying the active theme.

Every page registers its themed widgets here. When the theme changes,
ThemeApplicator.apply(theme_name) drives:

  1. ThemeEngineV3.set_theme(name)   — updates all engine subscribers
                                       (CTk widgets outside AppShell pages).
  2. set_ctk_appearance_mode()       — syncs CTk dark/light mode.
  3. _dispatch(tokens)               — fires shell page hooks (new AppShell).

Using ``apply()`` from every call-site (top-bar dropdown, Settings dialog,
initial AppShell bootstrap) guarantees that both notification channels run
together, so theme changes propagate everywhere consistently.
"""
from __future__ import annotations

import logging
import tkinter as tk
from typing import Callable, List, Optional

_log = logging.getLogger(__name__)


def _tc(slot: str) -> str:
    """Read a color slot from the active theme."""
    from cerebro.v2.core.theme_bridge_v2 import theme_color
    return theme_color(slot)


def theme_token(t: dict, key: str, default: str) -> str:
    """Safe token lookup with a static-constant fallback.

    Shared by page modules so they don't each duplicate this helper.
    """
    value = t.get(key) if isinstance(t, dict) else None
    return value if isinstance(value, str) and value else default


class ThemeApplicator:
    """Singleton theme applicator for the new shell."""

    _instance: "ThemeApplicator | None" = None

    @classmethod
    def get(cls) -> "ThemeApplicator":
        if cls._instance is None:
            cls._instance = ThemeApplicator()
        return cls._instance

    def __init__(self) -> None:
        self._hooks: List[Callable[[dict], None]] = []
        self._current: str = "Cerebro Dark"
        self._root: Optional[tk.Misc] = None

    def register(self, hook: Callable[[dict], None]) -> None:
        """Register a callback that receives the full theme token dict.

        The hook is NOT invoked immediately; callers are expected to either
        consume ``build_tokens()`` during their own construction, or wait for
        the next ``apply()`` / ``refresh()`` dispatch.
        """
        if hook not in self._hooks:
            self._hooks.append(hook)

    def unregister(self, hook: Callable[[dict], None]) -> None:
        """Remove a previously registered hook (no-op if absent)."""
        try:
            self._hooks.remove(hook)
        except ValueError:
            pass

    @property
    def current_theme(self) -> str:
        return self._current

    def set_root(self, root: tk.Misc) -> None:
        """Remember the app root so callers don't have to pass it every time."""
        self._root = root

    def apply(self, theme_name: str, root: Optional[tk.Misc] = None) -> None:
        """Switch to a new theme globally and notify every listener.

        - Updates ThemeEngineV3 (legacy engine subscribers refresh).
        - Syncs CTk appearance mode (Dark/Light).
        - Dispatches token dict to shell hooks via ``after_idle``.
        """
        engine_ok = False
        try:
            from cerebro.core.theme_engine_v3 import ThemeEngineV3
            engine_ok = ThemeEngineV3.get().set_theme(theme_name)
            if engine_ok:
                self._current = theme_name
        except Exception:
            pass

        try:
            from cerebro.v2.core.theme_bridge_v2 import set_ctk_appearance_mode
            set_ctk_appearance_mode()
        except Exception:
            pass

        if root is not None:
            self._root = root

        tokens = self.build_tokens()
        target = self._root
        if target is not None:
            try:
                target.after_idle(lambda: self._dispatch(tokens))
                return
            except Exception:
                pass
        # Fallback: dispatch synchronously if we can't schedule idle work.
        self._dispatch(tokens)

    def refresh(self) -> None:
        """Re-dispatch the currently active theme to all listeners (no engine change)."""
        tokens = self.build_tokens()
        target = self._root
        if target is not None:
            try:
                target.after_idle(lambda: self._dispatch(tokens))
                return
            except Exception:
                pass
        self._dispatch(tokens)

    def build_tokens(self) -> dict:
        """Build a flat token dict from the currently active theme."""
        return {
            # Base
            "bg":              _tc("base.background"),
            "bg2":             _tc("base.backgroundSecondary"),
            "bg3":             _tc("base.backgroundTertiary"),
            "fg":              _tc("base.foreground"),
            "fg2":             _tc("base.foregroundSecondary"),
            "fg_muted":        _tc("base.foregroundMuted"),
            "border":          _tc("base.border"),
            # Shell
            "title_bar_bg":    _tc("shell.titleBarBackground"),
            "accent":          _tc("shell.accentPrimary"),
            "accent2":         _tc("shell.accentSecondary"),
            # Keyboard focus ring (2.4.7) — use primary accent; must contrast with tab bg
            "focus_ring":      _tc("shell.accentPrimary"),
            "danger":          _tc("shell.accentDanger"),
            "success":         _tc("shell.accentSuccess"),
            "nav_bar":         _tc("shell.navyBar"),
            "row_alt":         _tc("shell.rowAlt"),
            "row_sel":         _tc("shell.rowSelected"),
            "row_sel_fg":      _tc("shell.rowSelectedText"),
            "tree_sel":        _tc("shell.treeSelected"),
            "stat_dupes":      _tc("shell.statDuplicates"),
            "stat_space":      _tc("shell.statSpace"),
            # Tabs
            "tab_bg":          _tc("tabs.background"),
            "tab_active_bg":   _tc("tabs.activeBackground"),
            "tab_active_fg":   _tc("tabs.activeForeground"),
            "tab_indicator":   _tc("tabs.activeBorder"),
            "tab_inactive_bg": _tc("tabs.inactiveBackground"),
            "tab_inactive_fg": _tc("tabs.inactiveForeground"),
            "tab_hover_bg":    _tc("tabs.inactiveBackgroundHover"),
            # Theme name for reference
            "_name":           self._current,
        }

    def _dispatch(self, tokens: dict) -> None:
        for hook in self._hooks:
            try:
                hook(tokens)
            except Exception as e:
                _log.warning("[ThemeApplicator] hook error: %s", e)


__all__ = ["ThemeApplicator", "theme_token"]
