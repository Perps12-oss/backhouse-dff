"""
WCAG-oriented helpers for Tkinter: focus visibility and first-focusable discovery.

Full WCAG 2.1 AA (contrast, screen readers) also depends on theme and platform;
this module supports keyboard focus visibility (2.4.7) and a bypass path (2.4.1).
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any, Optional, Union


def apply_focus_ring(
    w: tk.Misc,
    *,
    focus_color: str = "#2563EB",
    width: int = 2,
) -> None:
    """2 px keyboard focus ring (2.4.7 Focus Visible). No-op for unsupported widgets."""
    if not hasattr(w, "winfo_exists") or not w.winfo_exists():
        return
    w._a11y_focus_width = int(width)  # type: ignore[attr-defined]
    if getattr(w, "_a11y_ring_installed", False):  # type: ignore[truthy-bool]
        # Theme refresh: new focus color, same bindings
        try:
            w.configure(  # type: ignore[union-attr]
                highlightcolor=focus_color,
                highlightbackground=focus_color,
            )
        except tk.TclError:
            pass
        return
    w._a11y_ring_installed = True  # type: ignore[attr-defined]
    try:
        w.configure(  # type: ignore[union-attr]
            takefocus=1,
            highlightthickness=0,
            highlightcolor=focus_color,
            highlightbackground=focus_color,
        )
    except tk.TclError:
        return

    def on_in(_e: object) -> None:
        tw = int(getattr(w, "_a11y_focus_width", 2) or 2)  # type: ignore[truthy-bool]
        if hasattr(w, "winfo_exists") and w.winfo_exists():
            try:
                w.configure(highlightthickness=tw)  # type: ignore[union-attr]
            except tk.TclError:
                pass

    def on_out(_e: object) -> None:
        if hasattr(w, "winfo_exists") and w.winfo_exists():
            try:
                w.configure(highlightthickness=0)  # type: ignore[union-attr]
            except tk.TclError:
                pass

    w.bind("<FocusIn>", on_in, add="+")
    w.bind("<FocusOut>", on_out, add="+")


def _is_focusable_control(w: Any) -> bool:
    if isinstance(
        w,
        (
            tk.Button,
            tk.Entry,
            tk.Text,
            tk.Listbox,
            tk.Scale,
            ttk.Button,
            ttk.Entry,
            ttk.Combobox,
        ),
    ):
        return True
    n = type(w).__name__
    if n.startswith("CTk") and any(
        x in n
        for x in ("Button", "Entry", "Textbox", "CheckBox", "Segmented", "Switch")
    ):
        return True
    return False


def _walk(root: Any, depth: int) -> Optional[tk.Misc]:
    if root is None or depth > 30:
        return None
    try:
        if not root.winfo_exists():
            return None
    except tk.TclError:
        return None
    if _is_focusable_control(root):
        return root
    for child in root.winfo_children():
        got = _walk(child, depth + 1)
        if got is not None:
            return got
    return None


def first_focusable_descendant(
    root: Union[tk.Misc, Any],
) -> Optional[tk.Misc]:
    """Return the first depth-first focusable ttk/tk control under ``root``."""
    if root is None:  # type: ignore[truthy-bool]
        return None
    return _walk(root, 0)
