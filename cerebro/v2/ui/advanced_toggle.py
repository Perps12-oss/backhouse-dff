"""
Global Advanced Toggle — FINAL PLAN v2.0 §1.2.

Default OFF, instant toggle (no reload), affects visibility only.
Persists per session. State-bound via dispatch.
"""

from __future__ import annotations

import tkinter as tk
from typing import Optional

from cerebro.v2.ui.theme_applicator import ThemeApplicator, theme_token


class AdvancedToggle(tk.Frame):
    """Checkbox-style toggle for global advanced mode."""

    HEIGHT = 28

    def __init__(
        self,
        master,
        on_toggle: Optional[object] = None,
        **kwargs,
    ) -> None:
        self._t = ThemeApplicator.get().build_tokens()
        kwargs.setdefault("bg", self._t.get("tab_bg", "#F0F0F0"))
        super().__init__(master, **kwargs)
        self._on_toggle = on_toggle
        self._advanced = False
        self._build()
        ThemeApplicator.get().register(self._apply_theme)

    def _build(self) -> None:
        t = self._t
        fg = theme_token(t, "tab_inactive_fg", "#666666")
        bg = theme_token(t, "tab_bg", "#F0F0F0")

        self._var = tk.BooleanVar(value=False)
        self._cb = tk.Checkbutton(
            self,
            text="Advanced",
            variable=self._var,
            bg=bg,
            fg=fg,
            selectcolor=bg,
            activebackground=bg,
            activeforeground=fg,
            font=("Segoe UI", 9),
            relief="flat",
            bd=0,
            cursor="hand2",
            command=self._on_change,
        )
        self._cb.pack(side="right", padx=(0, 14), pady=2)

    def _on_change(self) -> None:
        self._advanced = self._var.get()
        if self._on_toggle:
            self._on_toggle(self._advanced)

    def _apply_theme(self, t: dict) -> None:
        self._t = t
        fg = theme_token(t, "tab_inactive_fg", "#666666")
        bg = theme_token(t, "tab_bg", "#F0F0F0")
        try:
            self.configure(bg=bg)
            self._cb.configure(
                bg=bg,
                fg=fg,
                selectcolor=bg,
                activebackground=bg,
                activeforeground=fg,
            )
        except tk.TclError:
            pass

    def set_value(self, value: bool) -> None:
        """Set toggle state without firing callback."""
        self._advanced = value
        self._var.set(value)

    def get_value(self) -> bool:
        return self._advanced
