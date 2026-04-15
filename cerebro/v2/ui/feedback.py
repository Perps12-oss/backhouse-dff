"""
Lightweight CTk-native feedback helpers for v2 flows.
"""

from __future__ import annotations

import logging
from typing import Protocol

import tkinter as tk

try:
    import customtkinter as ctk
except ImportError:  # pragma: no cover - fallback only
    ctk = None

logger = logging.getLogger(__name__)


class CTkMessageInterface(Protocol):
    """Interface marker for windows exposing v2 feedback helpers."""

    def show_error(self, title: str, message: str) -> None: ...
    def show_info(self, title: str, message: str) -> None: ...
    def confirm_action(self, title: str, message: str) -> bool: ...


class FeedbackPanel:
    """Simple modal message panel using CTk if available."""

    def __init__(self, parent, title: str, message: str, type: str = "info"):
        self._win = tk.Toplevel(parent)
        self._win.title(title)
        self._win.transient(parent)
        self._win.grab_set()
        self._win.resizable(False, False)

        frame_cls = ctk.CTkFrame if ctk else tk.Frame
        label_cls = ctk.CTkLabel if ctk else tk.Label
        btn_cls = ctk.CTkButton if ctk else tk.Button

        frame = frame_cls(self._win)
        frame.pack(fill="both", expand=True, padx=16, pady=16)

        color = "#f39c12" if type == "warning" else ("#e74c3c" if type == "error" else "#2e86de")
        label_cls(frame, text=title, font=("Segoe UI", 13, "bold"), text_color=color if ctk else None).pack(anchor="w")
        label_cls(frame, text=message, justify="left", wraplength=500).pack(anchor="w", pady=(8, 12))
        btn_cls(frame, text="OK", command=self._win.destroy).pack(anchor="e")

        self._win.update_idletasks()
        self._center(parent)
        self._win.wait_window()

    def _center(self, parent) -> None:
        x = parent.winfo_rootx() + (parent.winfo_width() // 2) - (self._win.winfo_width() // 2)
        y = parent.winfo_rooty() + (parent.winfo_height() // 2) - (self._win.winfo_height() // 2)
        self._win.geometry(f"+{max(0, x)}+{max(0, y)}")


def confirm_yes_no(parent, title: str, message: str) -> bool:
    """Return True when user confirms."""
    result = {"value": False}

    win = tk.Toplevel(parent)
    win.title(title)
    win.transient(parent)
    win.grab_set()
    win.resizable(False, False)

    frame_cls = ctk.CTkFrame if ctk else tk.Frame
    label_cls = ctk.CTkLabel if ctk else tk.Label
    btn_cls = ctk.CTkButton if ctk else tk.Button

    frame = frame_cls(win)
    frame.pack(fill="both", expand=True, padx=16, pady=16)
    label_cls(frame, text=message, justify="left", wraplength=520).pack(anchor="w", pady=(0, 12))

    btn_row = frame_cls(frame)
    btn_row.pack(fill="x")
    btn_cls(btn_row, text="Cancel", command=win.destroy).pack(side="right", padx=(8, 0))

    def _yes() -> None:
        result["value"] = True
        win.destroy()

    btn_cls(btn_row, text="Yes", command=_yes).pack(side="right")
    win.wait_window()
    return result["value"]


def show_text_panel(parent, title: str, message: str) -> None:
    """Convenience helper for informational copy."""
    FeedbackPanel(parent, title=title, message=message, type="info")
