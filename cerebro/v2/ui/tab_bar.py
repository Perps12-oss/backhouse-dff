from __future__ import annotations

"""
TabBar — 36 px light tab strip with 6 named tabs.

Active:   white bg, bold text, 3 px #E74C3C underline.
Inactive: #F0F0F0 bg, gray text.
Disabled: #F0F0F0 bg, #BBBBBB text, not clickable.
Badge:    small red pill on the Results tab showing duplicate count.
"""

import tkinter as tk
from typing import Callable, Dict, List, Optional, Tuple

from cerebro.v2.ui.a11y import apply_focus_ring
from cerebro.v2.ui.theme_applicator import ThemeApplicator

_SURFACE     = "#F0F0F0"
_WHITE       = "#FFFFFF"
_BORDER      = "#E0E0E0"
_ACTIVE_FG   = "#111111"
_INACTIVE_FG = "#666666"
_DISABLED_FG = "#BBBBBB"
_ACCENT      = "#E74C3C"
_BADGE_BG    = "#E74C3C"

TABS: List[Tuple[str, str]] = [
    ("welcome",     "Welcome"),
    ("scan",        "Scan"),
    ("results",     "Results"),
    ("review",      "Review"),
    ("history",     "History"),
    ("diagnostics", "Diagnostics"),
]


class _Tab(tk.Frame):
    _INDICATOR_H = 3

    def __init__(
        self,
        master,
        tab_bar: "TabBar",
        key: str,
        label: str,
        on_activate: Callable[[str], None],
        **kwargs,
    ) -> None:
        kwargs.setdefault("bg", _SURFACE)
        super().__init__(master, cursor="hand2", **kwargs)
        self._bar: TabBar    = tab_bar
        self._key            = key
        self._on_activate    = on_activate
        self._active         = False
        self._disabled       = False
        self._t: dict        = {}
        self._a11y_installed = False

        # Inner frame holds label + optional badge side-by-side
        self._inner = tk.Frame(self, bg=_SURFACE)
        self._inner.pack(fill="both", expand=True, padx=12)

        self._lbl = tk.Label(
            self._inner,
            text=label,
            bg=_SURFACE,
            fg=_INACTIVE_FG,
            font=("Segoe UI", 10),
        )
        self._lbl.pack(side="left", fill="y")

        # Badge — hidden until count > 0
        self._badge_text = tk.StringVar(value="")
        self._badge = tk.Label(
            self._inner,
            textvariable=self._badge_text,
            bg=_BADGE_BG,
            fg="#FFFFFF",
            font=("Segoe UI", 8, "bold"),
            padx=4,
            pady=0,
        )

        # 3 px bottom indicator
        self._indicator = tk.Frame(self, height=self._INDICATOR_H, bg=_SURFACE)
        self._indicator.pack(side="bottom", fill="x")

        for w in (self, self._inner, self._lbl, self._indicator):
            w.bind("<Button-1>", self._click)
            w.bind("<Enter>",    self._hover_in)
            w.bind("<Leave>",    self._hover_out)
        self._badge.bind("<Button-1>", self._click)
        self._badge.bind("<Enter>",    self._hover_in)
        self._badge.bind("<Leave>",    self._hover_out)

        # Keyboard: activate + move between tabs (WCAG 2.1.1, 2.4.1)
        self.bind("<Return>",     self._key_activate)
        self.bind("<Key-Return>", self._key_activate)
        self.bind("<space>",      self._key_activate)
        for seq in ("<Left>", "<Right>", "<Home>", "<End>"):
            self.bind(seq, self._key_nav)

    def _install_a11y(self, t: dict) -> None:
        c = t.get("focus_ring", t.get("accent", _ACCENT))
        apply_focus_ring(self, focus_color=c, width=2)
        self._a11y_installed = True

    def _key_activate(self, _e=None) -> None:
        if not self._disabled:
            self._on_activate(self._key)

    def _key_nav(self, e) -> None:
        if self._disabled:
            return
        if e.keysym == "Left":
            self._bar.focus_neighbor(self._key, -1)
        elif e.keysym == "Right":
            self._bar.focus_neighbor(self._key, 1)
        elif e.keysym == "Home":
            self._bar.focus_first()
        elif e.keysym == "End":
            self._bar.focus_last()
        return "break"

    def _click(self, _e=None) -> None:
        if self._disabled:
            return
        self.focus_set()
        self._on_activate(self._key)

    def _hover_in(self, _e=None) -> None:
        if not self._active and not self._disabled:
            self._lbl.configure(fg=self._t.get("fg", _ACTIVE_FG))

    def _hover_out(self, _e=None) -> None:
        if not self._active and not self._disabled:
            self._lbl.configure(fg=self._t.get("tab_inactive_fg", _INACTIVE_FG))

    def set_active(self, active: bool) -> None:
        self._active = active
        t = self._t
        if active:
            bg  = t.get("tab_active_bg", _WHITE)
            fg  = t.get("tab_active_fg", _ACTIVE_FG)
            ind = t.get("tab_indicator", _ACCENT)
            self.configure(bg=bg)
            self._inner.configure(bg=bg)
            self._lbl.configure(bg=bg, fg=fg, font=("Segoe UI", 10, "bold"))
            self._indicator.configure(bg=ind)
        else:
            bg  = t.get("tab_inactive_bg", _SURFACE)
            if self._disabled:
                fg = t.get("fg_muted", _DISABLED_FG)
            else:
                fg = t.get("tab_inactive_fg", _INACTIVE_FG)
            self.configure(bg=bg)
            self._inner.configure(bg=bg)
            self._lbl.configure(bg=bg, fg=fg, font=("Segoe UI", 10))
            self._indicator.configure(bg=bg)

    def apply_theme(self, t: dict) -> None:
        self._t = t
        c = t.get("focus_ring", t.get("accent", _ACCENT))
        if not self._a11y_installed:
            self._install_a11y(t)
        else:
            apply_focus_ring(self, focus_color=c, width=2)
        self.set_active(self._active)

    def set_disabled(self, disabled: bool) -> None:
        self._disabled = disabled
        self.configure(cursor="" if disabled else "hand2")
        try:
            self.configure(takefocus=0 if disabled else 1)
        except tk.TclError:
            pass
        if not self._active:
            self._lbl.configure(fg=_DISABLED_FG if disabled else _INACTIVE_FG)

    def is_disabled(self) -> bool:
        return self._disabled

    def set_badge(self, count: int) -> None:
        if count > 0:
            self._badge_text.set(f" {count} ")
            self._badge.pack(side="left", padx=(4, 0))
        else:
            self._badge_text.set("")
            self._badge.pack_forget()
        self._badge.bind("<Button-1>", self._click)
        self._badge.bind("<Enter>",    self._hover_in)
        self._badge.bind("<Leave>",    self._hover_out)


class TabBar(tk.Frame):
    HEIGHT = 36

    def __init__(
        self,
        master,
        on_tab_changed: Optional[Callable[[str], None]] = None,
        **kwargs,
    ) -> None:
        kwargs.setdefault("bg", _SURFACE)
        kwargs.setdefault("height", self.HEIGHT)
        super().__init__(master, **kwargs)
        self.pack_propagate(False)

        self._on_tab_changed = on_tab_changed
        self._tabs: Dict[str, _Tab] = {}
        self._active_key: str = "welcome"
        self._t = ThemeApplicator.get().build_tokens()

        self._build()
        # Bottom border drawn as a child frame
        self._bottom_border = tk.Frame(self, bg=_BORDER, height=1)
        self._bottom_border.pack(side="bottom", fill="x")
        ThemeApplicator.get().register(self._apply_theme)

    def _build(self) -> None:
        self._inner_frame = tk.Frame(self, bg=self._t.get("tab_bg", _SURFACE))
        self._inner_frame.pack(side="left", fill="y")
        for key, label in TABS:
            tab = _Tab(
                self._inner_frame,
                tab_bar=self,
                key=key,
                label=label,
                on_activate=self._on_tab_activated,
            )
            tab.pack(side="left", fill="y")
            self._tabs[key] = tab
        self._tabs["welcome"].set_active(True)
        self._tabs["review"].set_disabled(True)
        for tab in self._tabs.values():
            tab.apply_theme(self._t)

    def _apply_theme(self, t: dict) -> None:
        self._t = t
        bg     = t.get("tab_bg", _SURFACE)
        border = t.get("border", _BORDER)
        self.configure(bg=bg)
        self._inner_frame.configure(bg=bg)
        self._bottom_border.configure(bg=border)
        for tab in self._tabs.values():
            tab.apply_theme(t)

    def _on_tab_activated(self, key: str) -> None:
        if key == self._active_key:
            return
        if self._tabs[key].is_disabled():
            return
        if self._on_tab_changed:
            self._on_tab_changed(key)

    def _navigable_keys(self) -> List[str]:
        return [k for k, _ in TABS if not self._tabs[k].is_disabled()]

    def focus_neighbor(self, from_key: str, delta: int) -> None:
        keys = self._navigable_keys()
        if not keys or from_key not in keys:
            return
        i = keys.index(from_key) + delta
        if i < 0:
            i = len(keys) - 1
        elif i >= len(keys):
            i = 0
        self._tabs[keys[i]].focus_set()

    def focus_first(self) -> None:
        keys = self._navigable_keys()
        if keys:
            self._tabs[keys[0]].focus_set()

    def focus_last(self) -> None:
        keys = self._navigable_keys()
        if keys:
            self._tabs[keys[-1]].focus_set()

    def focus_active_tab(self) -> None:
        if self._active_key in self._tabs and not self._tabs[self._active_key].is_disabled():
            self._tabs[self._active_key].focus_set()

    # ------------------------------------------------------------------
    # Public API

    def set_active_key(self, key: str) -> None:
        """Paint the strip for ``key`` only — used after store state updates (no callback)."""
        if key not in self._tabs:
            return
        if key == self._active_key:
            return
        if self._tabs[key].is_disabled():
            return
        self._tabs[self._active_key].set_active(False)
        self._active_key = key
        self._tabs[key].set_active(True)

    def switch_to(self, key: str) -> None:
        """Legacy alias: prefer :meth:`set_active_key` for store-driven UIs."""
        self.set_active_key(key)

    def get_active(self) -> str:
        return self._active_key

    def on_tab_changed(self, cb: Callable[[str], None]) -> None:
        self._on_tab_changed = cb

    def set_results_badge(self, count: int) -> None:
        self._tabs["results"].set_badge(count)

    def enable_review(self) -> None:
        self._tabs["review"].set_disabled(False)

    def disable_review(self) -> None:
        self._tabs["review"].set_disabled(True)
