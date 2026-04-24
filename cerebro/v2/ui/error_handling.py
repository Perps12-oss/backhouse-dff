"""
Error Handling — FINAL PLAN v2.0 §11.

Must cover: Permission denied, File locked, Disk full
Errors must be: visible, human-readable, actionable
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox
from typing import Callable, Dict, List, Optional

from cerebro.v2.ui.theme_applicator import ThemeApplicator, theme_token

_DANGER   = "#E74C3C"
_WARNING  = "#F39C12"
_BLUE     = "#2980B9"
_WHITE    = "#FFFFFF"
_PANEL_BG = "#F0F0F0"
_TEXT     = "#111111"
_TEXT_SEC = "#666666"


class ErrorBanner(tk.Frame):
    """Visible, human-readable, actionable error banner (FINAL PLAN §11)."""

    HEIGHT = 48

    def __init__(self, master, **kwargs) -> None:
        self._t = ThemeApplicator.get().build_tokens()
        kwargs.setdefault("bg", _DANGER)
        super().__init__(master, **kwargs)
        self._build()
        ThemeApplicator.get().register(self._apply_theme)

    def _build(self) -> None:
        self._inner = tk.Frame(self, bg=_DANGER)
        self._inner.pack(fill="x", padx=12, pady=8)

        self._icon_label = tk.Label(
            self._inner, text="\u26A0",
            bg=_DANGER, fg=_WHITE,
            font=("Segoe UI", 14),
        )
        self._icon_label.pack(side="left", padx=(0, 8))

        self._msg_label = tk.Label(
            self._inner, text="",
            bg=_DANGER, fg=_WHITE,
            font=("Segoe UI", 10, "bold"),
            wraplength=600,
            justify="left",
        )
        self._msg_label.pack(side="left", fill="x", expand=True)

        self._action_btn = tk.Button(
            self._inner, text="",
            bg=_WHITE, fg=_DANGER,
            font=("Segoe UI", 9, "bold"),
            relief="flat", cursor="hand2",
            padx=12, pady=2,
        )

        self._dismiss_btn = tk.Button(
            self._inner, text="\u2715",
            bg=_DANGER, fg=_WHITE,
            font=("Segoe UI", 10),
            relief="flat", cursor="hand2",
            padx=4, pady=0,
            command=self.hide,
        )
        self._dismiss_btn.pack(side="right", padx=(4, 0))

    def show_error(self, message: str, action_label: str = "",
                   on_action: Optional[Callable[[], None]] = None) -> None:
        """Show an error with optional action button."""
        self._msg_label.configure(text=message)
        try:
            self._dismiss_btn.pack(side="right", padx=(4, 0))
        except (tk.TclError, AttributeError):
            pass

        if action_label and on_action:
            self._action_btn.configure(
                text=action_label,
                command=lambda: (on_action(), self.hide()),
            )
            self._action_btn.pack(side="right", padx=(4, 0))
        else:
            try:
                self._action_btn.pack_forget()
            except (tk.TclError, AttributeError):
                pass

        self.pack(fill="x")

    def show_warning(self, message: str, action_label: str = "",
                     on_action: Optional[Callable[[], None]] = None) -> None:
        """Show a warning with optional action button."""
        self._msg_label.configure(text=message)
        self.configure(bg=_WARNING)
        self._inner.configure(bg=_WARNING)
        self._icon_label.configure(bg=_WARNING)
        self._msg_label.configure(bg=_WARNING)
        self._dismiss_btn.configure(bg=_WARNING)
        try:
            self._dismiss_btn.pack(side="right", padx=(4, 0))
        except (tk.TclError, AttributeError):
            pass

        if action_label and on_action:
            self._action_btn.configure(
                text=action_label,
                bg=_WHITE, fg=_WARNING,
                command=lambda: (on_action(), self.hide()),
            )
            self._action_btn.pack(side="right", padx=(4, 0))

        self.pack(fill="x")

    def hide(self) -> None:
        """Hide the banner."""
        self.pack_forget()

    def _apply_theme(self, t: dict) -> None:
        self._t = t


# ---------------------------------------------------------------------------
# Specific error types (FINAL PLAN §11)
# ---------------------------------------------------------------------------

def show_permission_denied(parent: tk.Widget, path: str = "",
                           error_banner: Optional[ErrorBanner] = None) -> None:
    """Handle permission denied errors."""
    msg = f"Permission denied: {path}" if path else "Permission denied. You may need administrator privileges."
    if error_banner:
        error_banner.show_error(msg, "Run as admin", lambda: None)
    else:
        messagebox.showerror("Permission Denied", msg, parent=parent)


def show_file_locked(parent: tk.Widget, path: str = "",
                     error_banner: Optional[ErrorBanner] = None) -> None:
    """Handle file locked errors."""
    msg = f"File is locked: {path}" if path else "File is locked by another process. Close the file and try again."
    if error_banner:
        error_banner.show_warning(msg, "Retry", lambda: None)
    else:
        messagebox.showwarning("File Locked", msg, parent=parent)


def show_disk_full(parent: tk.Widget, error_banner: Optional[ErrorBanner] = None) -> None:
    """Handle disk full errors."""
    msg = "Disk is full. Free up space or choose a different location."
    if error_banner:
        error_banner.show_error(msg)
    else:
        messagebox.showerror("Disk Full", msg, parent=parent)
