"""
SettingsPage — FINAL PLAN v2.0 §8.

Minimal:
  §8.1 General: Theme, Default scan location
  §8.2 Scanning: Include subfolders, Min file size
  §8.3 Deletion & Safety: Recycle bin ON

Advanced:
  §8.2 Scanning: Profiles, Ignore rules, File types
  §8.3 Deletion: Permanent delete, Retention, Dry-run default
  §8.4 Performance: CPU limit, I/O throttle, Cache
  §8.5 Advanced: Logging, Debug, Experimental
"""

from __future__ import annotations

import tkinter as tk
from tkinter import filedialog
from typing import Any, Callable, Dict, Optional

from cerebro.v2.ui.theme_applicator import ThemeApplicator, theme_token

_PANEL_BG = "#F0F0F0"
_CARD_BG  = "#FFFFFF"
_BORDER   = "#E0E0E0"
_TEXT     = "#111111"
_TEXT_SEC = "#666666"
_ACCENT   = "#2980B9"


class SettingsPage(tk.Frame):
    """Settings page with minimal/advanced modes (FINAL PLAN §8)."""

    def __init__(
        self,
        master,
        store: Optional[object] = None,
        coordinator: Optional[object] = None,
        **kwargs,
    ) -> None:
        kwargs.setdefault("bg", _PANEL_BG)
        super().__init__(master, **kwargs)
        self._store = store
        self._coordinator = coordinator
        self._advanced = False
        self._t: Dict[str, Any] = {}
        self._build()
        self._t = ThemeApplicator.get().build_tokens()
        ThemeApplicator.get().register(self._apply_theme)

    def _apply_theme(self, t: dict) -> None:
        self._t = t
        for w in self.winfo_children():
            w.destroy()
        self._build()

    def _build(self) -> None:
        canvas = tk.Canvas(self, bg=theme_token(self._t, "bg", _PANEL_BG),
                           highlightthickness=0)
        scrollbar = tk.Scrollbar(self, orient="vertical", command=canvas.yview)
        self._scroll_frame = tk.Frame(
            canvas,
            bg=theme_token(self._t, "bg", _PANEL_BG),
        )
        self._scroll_frame.bind(
            "<Configure>",
            lambda _e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.create_window((0, 0), window=self._scroll_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        canvas.bind("<Configure>", lambda e: canvas.itemconfig(
            canvas.find_all()[0] if canvas.find_all() else 0,
            width=e.width,
        ))
        canvas.bind(
            "<MouseWheel>",
            lambda e: canvas.yview_scroll(-1 * (e.delta // 120), "units"),
        )

        self._build_section_general(self._scroll_frame)
        self._build_section_scanning(self._scroll_frame)
        self._build_section_deletion(self._scroll_frame)
        if self._advanced:
            self._build_section_performance(self._scroll_frame)
            self._build_section_advanced(self._scroll_frame)

    def _section_card(self, parent: tk.Frame, title: str) -> tk.Frame:
        t = self._t
        bg = theme_token(t, "bg", _CARD_BG)
        fg = theme_token(t, "fg", _TEXT)
        fg2 = theme_token(t, "fg2", _TEXT_SEC)
        border = theme_token(t, "border", _BORDER)

        outer = tk.Frame(parent, bg=bg, bd=1, relief="solid",
                         highlightbackground=border, highlightthickness=1)
        outer.pack(fill="x", padx=24, pady=(12, 0))

        header = tk.Frame(outer, bg=bg)
        header.pack(fill="x", padx=16, pady=(12, 4))
        tk.Label(header, text=title, bg=bg, fg=fg,
                 font=("Segoe UI", 12, "bold")).pack(side="left")

        body = tk.Frame(outer, bg=bg)
        body.pack(fill="x", padx=16, pady=(0, 16))

        return body

    def _setting_row(self, parent: tk.Frame, label: str) -> tk.Frame:
        bg = theme_token(self._t, "bg", _CARD_BG)
        fg = theme_token(self._t, "fg", _TEXT)
        fg2 = theme_token(self._t, "fg2", _TEXT_SEC)

        row = tk.Frame(parent, bg=bg)
        row.pack(fill="x", pady=4)

        tk.Label(row, text=label, bg=bg, fg=fg,
                 font=("Segoe UI", 10)).pack(side="left")
        return row

    def _build_section_general(self, parent: tk.Frame) -> None:
        card = self._section_card(parent, "General")

        row = self._setting_row(card, "Theme")
        self._theme_var = tk.StringVar(value="system")
        for val, lbl in [("light", "Light"), ("dark", "Dark"), ("system", "System")]:
            bg = theme_token(self._t, "bg", _CARD_BG)
            fg = theme_token(self._t, "fg2", _TEXT_SEC)
            tk.Radiobutton(
                row, text=lbl, variable=self._theme_var, value=val,
                bg=bg, fg=fg, selectcolor=bg,
                activebackground=bg, activeforeground=fg,
                font=("Segoe UI", 9),
                command=self._on_theme_change,
            ).pack(side="left", padx=(0, 8))

        row2 = self._setting_row(card, "Default scan location")
        bg = theme_token(self._t, "bg", _CARD_BG)
        fg2 = theme_token(self._t, "fg2", _TEXT_SEC)
        self._scan_path_var = tk.StringVar(value="~")
        tk.Entry(row2, textvariable=self._scan_path_var, width=30,
                 font=("Segoe UI", 9), relief="flat").pack(side="left", padx=(0, 4))
        tk.Button(
            row2, text="Browse", bg=bg, fg=fg2,
            font=("Segoe UI", 9), relief="flat", cursor="hand2",
            command=self._browse_scan_path,
        ).pack(side="left")

    def _build_section_scanning(self, parent: tk.Frame) -> None:
        card = self._section_card(parent, "Scanning")

        row1 = self._setting_row(card, "Include subfolders")
        self._subfolders_var = tk.BooleanVar(value=True)
        bg = theme_token(self._t, "bg", _CARD_BG)
        fg2 = theme_token(self._t, "fg2", _TEXT_SEC)
        tk.Checkbutton(
            row1, variable=self._subfolders_var,
            bg=bg, fg=fg2, selectcolor=bg,
            activebackground=bg, activeforeground=fg2,
            font=("Segoe UI", 9),
        ).pack(side="left")

        row2 = self._setting_row(card, "Minimum file size")
        self._min_size_var = tk.StringVar(value="0")
        tk.Entry(row2, textvariable=self._min_size_var, width=10,
                 font=("Segoe UI", 9), relief="flat").pack(side="left", padx=(0, 4))
        tk.Label(row2, text="KB", bg=bg, fg=fg2,
                 font=("Segoe UI", 9)).pack(side="left")

        if self._advanced:
            tk.Frame(card, bg=theme_token(self._t, "border", _BORDER),
                     height=1).pack(fill="x", pady=8)

            row3 = self._setting_row(card, "Scan profiles")
            tk.Button(
                row3, text="Manage profiles", bg=bg, fg=fg2,
                font=("Segoe UI", 9), relief="flat", cursor="hand2",
            ).pack(side="left")

            row4 = self._setting_row(card, "Ignore rules")
            tk.Button(
                row4, text="Edit ignore list", bg=bg, fg=fg2,
                font=("Segoe UI", 9), relief="flat", cursor="hand2",
            ).pack(side="left")

            row5 = self._setting_row(card, "File types")
            tk.Button(
                row5, text="Configure types", bg=bg, fg=fg2,
                font=("Segoe UI", 9), relief="flat", cursor="hand2",
            ).pack(side="left")

    def _build_section_deletion(self, parent: tk.Frame) -> None:
        card = self._section_card(parent, "Deletion & Safety")

        row1 = self._setting_row(card, "Move to recycle bin")
        self._recycle_var = tk.BooleanVar(value=True)
        bg = theme_token(self._t, "bg", _CARD_BG)
        fg2 = theme_token(self._t, "fg2", _TEXT_SEC)
        tk.Checkbutton(
            row1, variable=self._recycle_var,
            bg=bg, fg=fg2, selectcolor=bg,
            activebackground=bg, activeforeground=fg2,
            font=("Segoe UI", 9),
        ).pack(side="left")

        if self._advanced:
            tk.Frame(card, bg=theme_token(self._t, "border", _BORDER),
                     height=1).pack(fill="x", pady=8)

            row2 = self._setting_row(card, "Permanent delete")
            self._permanent_var = tk.BooleanVar(value=False)
            tk.Checkbutton(
                row2, variable=self._permanent_var,
                bg=bg, fg=fg2, selectcolor=bg,
                activebackground=bg, activeforeground=fg2,
                font=("Segoe UI", 9),
            ).pack(side="left")

            row3 = self._setting_row(card, "Retention period")
            self._retention_var = tk.StringVar(value="30")
            tk.Entry(row3, textvariable=self._retention_var, width=10,
                     font=("Segoe UI", 9), relief="flat").pack(side="left", padx=(0, 4))
            tk.Label(row3, text="days", bg=bg, fg=fg2,
                     font=("Segoe UI", 9)).pack(side="left")

            row4 = self._setting_row(card, "Dry-run default")
            self._dry_run_default_var = tk.BooleanVar(value=False)
            tk.Checkbutton(
                row4, variable=self._dry_run_default_var,
                bg=bg, fg=fg2, selectcolor=bg,
                activebackground=bg, activeforeground=fg2,
                font=("Segoe UI", 9),
            ).pack(side="left")

    def _build_section_performance(self, parent: tk.Frame) -> None:
        card = self._section_card(parent, "Performance")
        bg = theme_token(self._t, "bg", _CARD_BG)
        fg2 = theme_token(self._t, "fg2", _TEXT_SEC)

        row1 = self._setting_row(card, "CPU limit")
        self._cpu_var = tk.IntVar(value=100)
        tk.Scale(row1, from_=10, to=100, orient="horizontal",
                 variable=self._cpu_var, bg=bg, fg=fg2,
                 troughcolor=bg, highlightthickness=0,
                 font=("Segoe UI", 8)).pack(side="left", fill="x", expand=True)

        row2 = self._setting_row(card, "I/O throttle")
        self._io_var = tk.IntVar(value=0)
        tk.Scale(row2, from_=0, to=100, orient="horizontal",
                 variable=self._io_var, bg=bg, fg=fg2,
                 troughcolor=bg, highlightthickness=0,
                 font=("Segoe UI", 8)).pack(side="left", fill="x", expand=True)

        row3 = self._setting_row(card, "Cache")
        tk.Button(
            row3, text="Clear cache", bg=bg, fg=fg2,
            font=("Segoe UI", 9), relief="flat", cursor="hand2",
        ).pack(side="left")

    def _build_section_advanced(self, parent: tk.Frame) -> None:
        card = self._section_card(parent, "Advanced")
        bg = theme_token(self._t, "bg", _CARD_BG)
        fg2 = theme_token(self._t, "fg2", _TEXT_SEC)

        row1 = self._setting_row(card, "Logging level")
        self._log_var = tk.StringVar(value="WARNING")
        tk.OptionMenu(row1, self._log_var, "DEBUG", "INFO", "WARNING", "ERROR").pack(
            side="left")

        row2 = self._setting_row(card, "Debug mode")
        self._debug_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            row2, variable=self._debug_var,
            bg=bg, fg=fg2, selectcolor=bg,
            activebackground=bg, activeforeground=fg2,
            font=("Segoe UI", 9),
        ).pack(side="left")

        row3 = self._setting_row(card, "Experimental features")
        self._experimental_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            row3, variable=self._experimental_var,
            bg=bg, fg=fg2, selectcolor=bg,
            activebackground=bg, activeforeground=fg2,
            font=("Segoe UI", 9),
        ).pack(side="left")

    def _on_theme_change(self) -> None:
        pass

    def _browse_scan_path(self) -> None:
        path = filedialog.askdirectory()
        if path:
            self._scan_path_var.set(path)

    def set_advanced(self, value: bool) -> None:
        self._advanced = value
        for w in self.winfo_children():
            w.destroy()
        self._build()

    def on_show(self) -> None:
        pass
