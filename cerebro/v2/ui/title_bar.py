"""
TitleBar — 32 px dark-navy bar.

Left:   decorative macOS-style traffic-light dots (non-functional).
Center: "C E R E B R O" wordmark in white.
Right:  "Themes" and "Settings" text links.

``Themes`` is a **single-click quick dropdown** anchored to its label; the
label widget is exposed via :py:meth:`TitleBar.get_themes_anchor` so the
shell can position the popup directly beneath it.
"""
from __future__ import annotations

import tkinter as tk
from typing import Callable, Dict, List, Optional

from cerebro.v2.ui.theme_applicator import ThemeApplicator

_NAVY = "#0B1929"
_LINK = "#7A8FA6"   # white ~30 % blended onto navy background


class TitleBar(tk.Frame):
    HEIGHT = 32

    def __init__(
        self,
        master,
        on_settings: Optional[Callable[[], None]] = None,
        on_themes:   Optional[Callable[[], None]] = None,
        **kwargs,
    ) -> None:
        kwargs.setdefault("bg", _NAVY)
        kwargs.setdefault("height", self.HEIGHT)
        super().__init__(master, **kwargs)
        self.pack_propagate(False)
        self._on_settings = on_settings
        self._on_themes   = on_themes
        self._link_labels: List[tk.Label] = []
        self._named_links: Dict[str, tk.Label] = {}
        self._t = ThemeApplicator.get().build_tokens()
        self._build()
        ThemeApplicator.get().register(self._apply_theme)

    # ------------------------------------------------------------------

    def _build(self) -> None:
        t = self._t
        bg = t.get("title_bar_bg", _NAVY)

        # ── Left: traffic lights ──────────────────────────────────────
        self._left_frame = tk.Frame(self, bg=bg)
        self._left_frame.pack(side="left", padx=(10, 0), fill="y")
        for color in ("#FF5F57", "#FFBD2E", "#28CA41"):
            c = tk.Canvas(self._left_frame, width=12, height=12,
                          bg=bg, highlightthickness=0)
            c.pack(side="left", padx=3, pady=10)
            c.create_oval(1, 1, 11, 11, fill=color, outline="")

        # ── Center: wordmark (placed, not packed, so it stays centred) ─
        self._wordmark_lbl = tk.Label(
            self,
            text="C E R E B R O",
            bg=bg,
            fg=t.get("fg", "#FFFFFF"),
            font=("Segoe UI", 9, "bold"),
        )
        self._wordmark_lbl.place(relx=0.5, rely=0.5, anchor="center")

        # ── Right: text links ─────────────────────────────────────────
        self._right_frame = tk.Frame(self, bg=bg)
        self._right_frame.pack(side="right", padx=(0, 14), fill="y")

        fg2 = t.get("fg2", _LINK)
        fg  = t.get("fg", "#FFFFFF")
        self._link_labels = []
        self._named_links = {}
        # packed right-to-left so Settings appears rightmost
        for key, text, cb_attr in [
            ("settings", "Settings", "_on_settings"),
            ("themes",   "Themes",   "_on_themes"),
        ]:
            lbl = tk.Label(
                self._right_frame, text=text, bg=bg, fg=fg2,
                font=("Segoe UI", 9), cursor="hand2",
            )
            lbl.pack(side="right", padx=6)
            cb = getattr(self, cb_attr)
            if cb:
                lbl.bind("<Button-1>", lambda _e, c=cb, w=lbl: c(w))
            lbl.bind("<Enter>", lambda _e, w=lbl, f=fg:  w.configure(fg=f))
            lbl.bind("<Leave>", lambda _e, w=lbl, f=fg2: w.configure(fg=f))
            self._link_labels.append(lbl)
            self._named_links[key] = lbl

    # ------------------------------------------------------------------

    def _apply_theme(self, t: dict) -> None:
        self._t = t
        bg  = t.get("title_bar_bg", _NAVY)
        fg  = t.get("fg", "#FFFFFF")
        fg2 = t.get("fg2", _LINK)
        self.configure(bg=bg)
        self._left_frame.configure(bg=bg)
        for child in self._left_frame.winfo_children():
            try:
                child.configure(bg=bg)
            except Exception:
                pass
        self._right_frame.configure(bg=bg)
        self._wordmark_lbl.configure(bg=bg, fg=fg)
        for lbl in self._link_labels:
            lbl.configure(bg=bg, fg=fg2)
            lbl.bind("<Enter>", lambda _e, w=lbl, f=fg:  w.configure(fg=f))
            lbl.bind("<Leave>", lambda _e, w=lbl, f=fg2: w.configure(fg=f))

    # ------------------------------------------------------------------
    # Public API

    def set_settings_callback(self, cb: Callable[[], None]) -> None:
        self._on_settings = cb

    def set_themes_callback(self, cb: Callable[[], None]) -> None:
        self._on_themes = cb

    def get_themes_anchor(self) -> Optional[tk.Label]:
        """Return the ``Themes`` label widget so popups can anchor under it."""
        return self._named_links.get("themes")

    def get_settings_anchor(self) -> Optional[tk.Label]:
        """Return the ``Settings`` label widget."""
        return self._named_links.get("settings")
