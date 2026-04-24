"""
Loading States — FINAL PLAN v2.0 §10.

Required: Skeleton loaders, Progressive thumbnails, Real progress indicators.
"""

from __future__ import annotations

import tkinter as tk
from typing import Optional

from cerebro.v2.ui.theme_applicator import ThemeApplicator, theme_token

_SKELETON_BG = "#E0E0E0"
_SKELETON_FG = "#F5F5F5"
_PANEL_BG    = "#F0F0F0"


class SkeletonLoader(tk.Frame):
    """Animated skeleton placeholder (FINAL PLAN §10).

    Renders a shimmer effect for loading states.
    """

    def __init__(
        self,
        master,
        rows: int = 5,
        row_height: int = 26,
        **kwargs,
    ) -> None:
        self._t = ThemeApplicator.get().build_tokens()
        kwargs.setdefault("bg", theme_token(self._t, "bg2", _PANEL_BG))
        super().__init__(master, **kwargs)
        self._rows = rows
        self._row_height = row_height
        self._shimmer_pos = 0
        self._shimmer_after_id: Optional[str] = None
        self._bar_colors: list = []
        self._build()

    def _build(self) -> None:
        t = self._t
        bg = theme_token(t, "bg2", _PANEL_BG)
        skel_bg = theme_token(t, "bg3", _SKELETON_BG)
        skel_fg = theme_token(t, "bg", _SKELETON_FG)

        for i in range(self._rows):
            row = tk.Frame(self, bg=bg, height=self._row_height)
            row.pack(fill="x", pady=2, padx=4)
            row.pack_propagate(False)

            # Text placeholder bar (70-90% width)
            import random
            width_pct = 0.7 + random.random() * 0.2
            bar = tk.Frame(row, bg=skel_bg, height=12)
            bar.place(relx=0.02, rely=0.5, anchor="w",
                      relwidth=width_pct, height=12)
            self._bar_colors.append((row, bar))

    def start_shimmer(self) -> None:
        """Begin the shimmer animation."""
        self._animate_shimmer()

    def stop_shimmer(self) -> None:
        """Stop the shimmer animation."""
        if self._shimmer_after_id is not None:
            try:
                self.after_cancel(self._shimmer_after_id)
            except (tk.TclError, ValueError):
                pass
            self._shimmer_after_id = None

    def _animate_shimmer(self) -> None:
        self._shimmer_pos = (self._shimmer_pos + 1) % len(self._bar_colors)
        for i, (row, bar) in enumerate(self._bar_colors):
            if i == self._shimmer_pos:
                bar.configure(bg=theme_token(self._t, "bg", _SKELETON_FG))
            else:
                bar.configure(bg=theme_token(self._t, "bg3", _SKELETON_BG))
        self._shimmer_after_id = self.after(150, self._animate_shimmer)

    def destroy(self) -> None:
        self.stop_shimmer()
        super().destroy()


class ProgressIndicator(tk.Frame):
    """Real progress indicator with label (FINAL PLAN §10)."""

    HEIGHT = 32

    def __init__(
        self,
        master,
        **kwargs,
    ) -> None:
        self._t = ThemeApplicator.get().build_tokens()
        kwargs.setdefault("bg", theme_token(self._t, "bg2", _PANEL_BG))
        super().__init__(master, **kwargs)
        self._progress = 0.0
        self._build()

    def _build(self) -> None:
        t = self._t
        bg = theme_token(t, "bg2", _PANEL_BG)
        fg = theme_token(t, "fg", "#111111")
        accent = theme_token(t, "accent", "#2980B9")

        self._track = tk.Frame(self, bg=bg, height=6)
        self._track.pack(fill="x", padx=12, pady=(8, 0))
        self._track.pack_propagate(False)

        self._fill = tk.Frame(self._track, bg=accent, width=0, height=6)
        self._fill.place(x=0, y=0, relheight=1, width=0)

        self._label = tk.Label(
            self, text="0%",
            bg=bg, fg=fg,
            font=("Segoe UI", 9),
        )
        self._label.pack(anchor="e", padx=12)

    def set_progress(self, value: float) -> None:
        """Update progress (0.0 to 1.0)."""
        self._progress = max(0.0, min(1.0, value))
        pct = int(self._progress * 100)
        self._label.configure(text=f"{pct}%")
        try:
            track_w = self._track.winfo_width()
            fill_w = int(track_w * self._progress)
            self._fill.place(x=0, y=0, relheight=1, width=fill_w)
        except tk.TclError:
            pass

    def set_label(self, text: str) -> None:
        self._label.configure(text=text)
