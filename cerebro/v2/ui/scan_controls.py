"""
Scan Lifecycle controls — FINAL PLAN v2.0 §9.

Must support: Start, Pause, Resume, Cancel
Cancel always visible.
No UI blocking under any operation.
"""

from __future__ import annotations

import tkinter as tk
from typing import Any, Callable, Dict, Optional

from cerebro.v2.ui.theme_applicator import ThemeApplicator, theme_token

_DANGER   = "#E74C3C"
_BLUE     = "#2980B9"
_ORANGE   = "#F39C12"
_WHITE    = "#FFFFFF"
_PANEL_BG = "#F0F0F0"
_TEXT     = "#111111"
_TEXT_SEC = "#666666"


class ScanControlsBar(tk.Frame):
    """Scan lifecycle controls: Start, Pause, Resume, Cancel (FINAL PLAN §9)."""

    HEIGHT = 40

    def __init__(
        self,
        master,
        on_start: Optional[Callable[[], None]] = None,
        on_pause: Optional[Callable[[], None]] = None,
        on_resume: Optional[Callable[[], None]] = None,
        on_cancel: Optional[Callable[[], None]] = None,
        **kwargs,
    ) -> None:
        self._t = ThemeApplicator.get().build_tokens()
        kwargs.setdefault("bg", self._t.get("bg2", _PANEL_BG))
        super().__init__(master, **kwargs)
        self._on_start = on_start
        self._on_pause = on_pause
        self._on_resume = on_resume
        self._on_cancel = on_cancel
        self._state = "idle"  # idle | scanning | paused | completed
        self._progress_var = tk.DoubleVar(value=0)
        self._build()
        ThemeApplicator.get().register(self._apply_theme)

    def _build(self) -> None:
        t = self._t
        bg = theme_token(t, "bg2", _PANEL_BG)
        fg = theme_token(t, "fg", _TEXT)
        fg2 = theme_token(t, "fg2", _TEXT_SEC)

        inner = tk.Frame(self, bg=bg)
        inner.pack(fill="x", padx=12, pady=6)

        self._start_btn = tk.Button(
            inner, text="Start Scan",
            bg=_BLUE, fg=_WHITE,
            font=("Segoe UI", 10, "bold"),
            relief="flat", cursor="hand2",
            padx=16, pady=4,
            command=self._on_start_click,
        )
        self._start_btn.pack(side="left")

        self._pause_btn = tk.Button(
            inner, text="Pause",
            bg=_ORANGE, fg=_WHITE,
            font=("Segoe UI", 10),
            relief="flat", cursor="hand2",
            padx=12, pady=4,
            command=self._on_pause_click,
        )

        self._resume_btn = tk.Button(
            inner, text="Resume",
            bg=_BLUE, fg=_WHITE,
            font=("Segoe UI", 10),
            relief="flat", cursor="hand2",
            padx=12, pady=4,
            command=self._on_resume_click,
        )

        self._cancel_btn = tk.Button(
            inner, text="Cancel",
            bg=_DANGER, fg=_WHITE,
            font=("Segoe UI", 10),
            relief="flat", cursor="hand2",
            padx=12, pady=4,
            command=self._on_cancel_click,
        )

        self._progress_bar = ttk_progress = tk.Frame(inner, bg=_PANEL_BG, height=6)
        self._progress_fill = tk.Frame(ttk_progress, bg=_BLUE, width=0, height=6)

        self._progress_label = tk.Label(
            inner, text="",
            bg=bg, fg=fg2,
            font=("Segoe UI", 9),
        )

    def set_state(self, state: str, progress: float = 0.0,
                  can_pause: bool = False, can_resume: bool = False) -> None:
        """Update control visibility based on scan state."""
        self._state = state
        t = self._t
        bg = theme_token(t, "bg2", _PANEL_BG)
        fg2 = theme_token(t, "fg2", _TEXT_SEC)

        # Remove all packed buttons
        for btn in (self._start_btn, self._pause_btn,
                    self._resume_btn, self._cancel_btn,
                    self._progress_bar, self._progress_label):
            try:
                btn.pack_forget()
            except (tk.TclError, AttributeError):
                pass
        try:
            self._progress_fill.place_forget()
        except (tk.TclError, AttributeError):
            pass

        if state == "idle":
            self._start_btn.pack(side="left")
        elif state == "scanning":
            self._progress_bar.pack(side="left", fill="x", expand=True, padx=(8, 8))
            self._progress_bar.pack_propagate(False)
            fill_pct = max(0, min(100, progress * 100))
            self._progress_fill.configure(bg=_BLUE)
            self._progress_fill.place(x=0, y=0, relheight=1, width=fill_pct)
            self._progress_label.configure(text=f"{fill_pct:.0f}%")
            self._progress_label.pack(side="left")

            if can_pause:
                self._pause_btn.pack(side="left", padx=(4, 0))
            if can_resume:
                self._resume_btn.pack(side="left", padx=(4, 0))
            self._cancel_btn.pack(side="right")
        elif state == "paused":
            self._progress_bar.pack(side="left", fill="x", expand=True, padx=(8, 8))
            self._progress_bar.pack_propagate(False)
            fill_pct = max(0, min(100, progress * 100))
            self._progress_fill.configure(bg=_ORANGE)
            self._progress_fill.place(x=0, y=0, relheight=1, width=fill_pct)
            self._progress_label.configure(text=f"Paused — {fill_pct:.0f}%")
            self._progress_label.pack(side="left")
            self._resume_btn.pack(side="left", padx=(4, 0))
            self._cancel_btn.pack(side="right")
        elif state == "completed":
            self._start_btn.configure(text="New Scan")
            self._start_btn.pack(side="left")

    def _on_start_click(self) -> None:
        if self._on_start:
            self._on_start()

    def _on_pause_click(self) -> None:
        if self._on_pause:
            self._on_pause()

    def _on_resume_click(self) -> None:
        if self._on_resume:
            self._on_resume()

    def _on_cancel_click(self) -> None:
        if self._on_cancel:
            self._on_cancel()

    def _apply_theme(self, t: dict) -> None:
        self._t = t
