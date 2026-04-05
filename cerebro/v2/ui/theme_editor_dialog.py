"""
Theme Editor Dialog

Allows users to create and edit custom themes by tweaking color slots
visually. Changes are previewed live and saved to ~/.cerebro/themes/.

Opens from Settings → Appearance → [Edit / New Theme].
"""

from __future__ import annotations

import json
import tkinter as tk
from tkinter import colorchooser, messagebox, simpledialog
from pathlib import Path
from typing import Any, Dict, Optional

try:
    import customtkinter as ctk
    CTkToplevel = ctk.CTkToplevel
    CTkFrame   = ctk.CTkFrame
    CTkLabel   = ctk.CTkLabel
    CTkButton  = ctk.CTkButton
    CTkEntry   = ctk.CTkEntry
    CTkScrollableFrame = ctk.CTkScrollableFrame
    CTkOptionMenu = ctk.CTkOptionMenu
    CTkSwitch  = ctk.CTkSwitch
except ImportError:
    CTkToplevel = tk.Toplevel
    CTkFrame   = tk.Frame
    CTkLabel   = tk.Label
    CTkButton  = tk.Button
    CTkEntry   = tk.Entry
    CTkScrollableFrame = tk.Frame
    CTkOptionMenu = tk.OptionMenu
    CTkSwitch  = tk.Checkbutton

from cerebro.v2.core.design_tokens import Spacing, Typography
from cerebro.v2.core.theme_bridge_v2 import theme_color, subscribe_to_theme

# Slots users can edit (subset — most important ones)
_EDITABLE_GROUPS = [
    ("Backgrounds", [
        ("base.background",         "Main Window Background"),
        ("base.backgroundSecondary","Panel / Sidebar"),
        ("base.backgroundTertiary", "Card / Row Alternate"),
        ("base.backgroundElevated", "Dialogs / Tooltips"),
    ]),
    ("Text", [
        ("base.foreground",         "Primary Text"),
        ("base.foregroundSecondary","Secondary Text"),
        ("base.foregroundMuted",    "Disabled / Hint Text"),
    ]),
    ("Accent & Borders", [
        ("base.accent",             "Accent Color"),
        ("base.accentHover",        "Accent Hover"),
        ("base.accentMuted",        "Accent Background Tint"),
        ("base.border",             "Border / Divider"),
    ]),
    ("Buttons", [
        ("button.primary",          "Primary Button"),
        ("button.primaryHover",     "Primary Button Hover"),
        ("button.secondary",        "Secondary Button"),
        ("button.secondaryHover",   "Secondary Button Hover"),
        ("button.danger",           "Danger / Delete Button"),
        ("button.dangerHover",      "Danger Button Hover"),
    ]),
    ("Feedback", [
        ("feedback.success",        "Success"),
        ("feedback.warning",        "Warning"),
        ("feedback.danger",         "Error / Danger"),
        ("feedback.info",           "Info"),
    ]),
]

_USER_THEMES_DIR = Path.home() / ".cerebro" / "themes"


def _load_active_colors() -> Dict[str, str]:
    """Get all resolved colors for the currently active theme."""
    try:
        from cerebro.core.theme_engine_v3 import ThemeEngineV3
        return ThemeEngineV3.get().get_all_resolved()
    except Exception:
        return {}


class ThemeEditorDialog:
    """
    Full-featured theme editor.

    Usage::

        ThemeEditorDialog.show(parent, base_theme_name="dark_navy_cyan")
        ThemeEditorDialog.show(parent)          # start from active theme
    """

    @classmethod
    def show(cls, parent: tk.Misc,
             base_theme_name: Optional[str] = None) -> None:
        cls(parent, base_theme_name)

    # ------------------------------------------------------------------

    def __init__(self, parent: tk.Misc,
                 base_theme_name: Optional[str] = None) -> None:
        self._parent   = parent
        self._colors: Dict[str, str] = _load_active_colors()
        self._swatches: Dict[str, tk.Label] = {}
        self._hex_vars: Dict[str, tk.StringVar] = {}
        self._dirty    = False
        self._theme_name = ""

        self._win = CTkToplevel(parent)
        self._win.title("Theme Editor")
        self._win.geometry("620x620")
        self._win.transient(parent)
        self._win.grab_set()
        self._win.protocol("WM_DELETE_WINDOW", self._on_close)
        subscribe_to_theme(self._win, self._apply_theme)
        self._build()

        # Pre-populate with base theme
        if base_theme_name:
            self._load_base_theme(base_theme_name)

    # ------------------------------------------------------------------
    # Build UI
    # ------------------------------------------------------------------

    def _build(self) -> None:
        self._win.configure(fg_color=theme_color("base.background"))

        # ── Header ────────────────────────────────────────────────────
        header = CTkFrame(self._win, fg_color=theme_color("toolbar.background"), height=52)
        header.pack(fill="x")
        header.pack_propagate(False)

        CTkLabel(
            header, text="Theme Editor",
            font=("", 15, "bold"),
            text_color=theme_color("base.foreground"),
        ).pack(side="left", padx=Spacing.LG, pady=Spacing.SM)

        # Theme name entry
        CTkLabel(header, text="Name:", font=Typography.FONT_SM,
                 text_color=theme_color("base.foregroundSecondary"),
                 ).pack(side="left", padx=(Spacing.LG, Spacing.XS))
        self._name_var = tk.StringVar(value="my_theme")
        name_entry = CTkEntry(header, textvariable=self._name_var,
                              width=160, height=32, font=Typography.FONT_SM)
        name_entry.pack(side="left")

        # Light / Dark toggle
        CTkLabel(header, text="Type:", font=Typography.FONT_SM,
                 text_color=theme_color("base.foregroundSecondary"),
                 ).pack(side="left", padx=(Spacing.MD, Spacing.XS))
        self._type_var = tk.StringVar(value="dark")
        type_menu = CTkOptionMenu(
            header, values=["dark", "light"],
            variable=self._type_var,
            width=80, height=32, font=Typography.FONT_SM,
        )
        type_menu.pack(side="left")

        # ── Color scroll area ─────────────────────────────────────────
        scroll = CTkScrollableFrame(
            self._win,
            fg_color=theme_color("base.background"),
            label_text="",
        )
        scroll.pack(fill="both", expand=True, padx=Spacing.MD, pady=Spacing.SM)

        for group_label, slots in _EDITABLE_GROUPS:
            # Group heading
            CTkLabel(
                scroll, text=group_label.upper(),
                font=("", 10, "bold"),
                text_color=theme_color("base.foregroundMuted"),
                anchor="w",
            ).pack(fill="x", padx=Spacing.SM, pady=(Spacing.MD, 2))

            for slot, display in slots:
                row = CTkFrame(scroll, fg_color="transparent", height=36)
                row.pack(fill="x", padx=Spacing.SM, pady=1)

                # Label
                CTkLabel(row, text=display, font=Typography.FONT_SM,
                         text_color=theme_color("base.foreground"),
                         anchor="w", width=200,
                         ).pack(side="left")

                # Colour swatch (click to open picker)
                current_hex = self._colors.get(slot, "#888888")
                swatch = tk.Label(row, bg=current_hex, width=4,
                                  relief="solid", bd=1, cursor="hand2")
                swatch.pack(side="left", padx=(0, Spacing.XS), ipady=8)
                swatch.bind("<Button-1>",
                            lambda e, s=slot, sw=swatch: self._pick_color(s, sw))
                self._swatches[slot] = swatch

                # Hex entry
                var = tk.StringVar(value=current_hex)
                var.trace_add("write",
                              lambda *_, s=slot, v=var: self._on_hex_typed(s, v))
                self._hex_vars[slot] = var
                entry = CTkEntry(row, textvariable=var, width=90,
                                 height=28, font=Typography.FONT_SM)
                entry.pack(side="left")

        # ── Footer ────────────────────────────────────────────────────
        footer = CTkFrame(self._win, fg_color=theme_color("toolbar.background"), height=48)
        footer.pack(fill="x", side="bottom")
        footer.pack_propagate(False)

        for text, cmd, col, hov in [
            ("Preview",     self._preview,  "button.secondary",  "button.secondaryHover"),
            ("Save Theme",  self._save,     "button.primary",    "button.primaryHover"),
            ("Cancel",      self._on_close, "button.secondary",  "button.secondaryHover"),
        ]:
            CTkButton(
                footer, text=text, width=110, height=32,
                font=Typography.FONT_SM,
                fg_color=theme_color(col), hover_color=theme_color(hov),
                corner_radius=Spacing.BORDER_RADIUS_SM,
                command=cmd,
            ).pack(side="left", padx=Spacing.SM, pady=Spacing.SM)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _pick_color(self, slot: str, swatch: tk.Label) -> None:
        current = self._colors.get(slot, "#888888")
        result = colorchooser.askcolor(color=current, title=f"Choose color: {slot}",
                                        parent=self._win)
        if result and result[1]:
            hex_color = result[1].upper()
            self._colors[slot] = hex_color
            swatch.configure(bg=hex_color)
            self._hex_vars[slot].set(hex_color)
            self._dirty = True

    def _on_hex_typed(self, slot: str, var: tk.StringVar) -> None:
        val = var.get().strip()
        if not val.startswith("#"):
            val = f"#{val}"
        if len(val) in (4, 7) and all(c in "0123456789abcdefABCDEF" for c in val[1:]):
            self._colors[slot] = val.upper()
            swatch = self._swatches.get(slot)
            if swatch:
                try:
                    swatch.configure(bg=val)
                except Exception:
                    pass
            self._dirty = True

    def _load_base_theme(self, name: str) -> None:
        """Populate editor from an existing theme JSON."""
        try:
            from cerebro.core.theme_engine_v3 import ThemeEngineV3
            engine = ThemeEngineV3.get()
            if name in engine.all_theme_names():
                engine.set_theme(name)
                resolved = engine.get_all_resolved()
                for slot, swatch in self._swatches.items():
                    c = resolved.get(slot, "#888888")
                    self._colors[slot] = c
                    swatch.configure(bg=c)
                    self._hex_vars[slot].set(c)
                theme_meta = engine.get_theme_metadata(name)
                self._type_var.set(theme_meta.get("type", "dark"))
                self._name_var.set(f"{name}_copy")
        except Exception:
            pass

    def _preview(self) -> None:
        """Apply the current editor colors live to the UI."""
        self._apply_to_engine(preview=True)

    def _save(self) -> None:
        """Save the theme to ~/.cerebro/themes/ and apply it."""
        name = self._name_var.get().strip().replace(" ", "_")
        if not name:
            messagebox.showerror("Save Theme", "Please enter a theme name.",
                                 parent=self._win)
            return
        theme_data = {
            "name":         name,
            "display_name": name.replace("_", " ").title(),
            "type":         self._type_var.get(),
            "author":       "User",
            "colors":       {k: v for k, v in self._colors.items()},
        }
        _USER_THEMES_DIR.mkdir(parents=True, exist_ok=True)
        out = _USER_THEMES_DIR / f"{name}.json"
        try:
            out.write_text(json.dumps(theme_data, indent=2))
        except Exception as exc:
            messagebox.showerror("Save Theme", f"Could not save:\n{exc}", parent=self._win)
            return

        self._apply_to_engine(preview=False)
        self._dirty = False
        messagebox.showinfo("Theme Saved",
                            f"Theme '{name}' saved and applied.\n"
                            f"Location: {out}", parent=self._win)
        self._win.destroy()

    def _apply_to_engine(self, preview: bool = False) -> None:
        name = self._name_var.get().strip() or "_preview"
        try:
            from cerebro.core.theme_engine_v3 import ThemeEngineV3
            engine = ThemeEngineV3.get()
            # Inject the raw theme dict directly
            engine.load_theme_from_dict({
                "name": name,
                "type": self._type_var.get(),
                "colors": dict(self._colors),
            })
            engine.set_theme(name)
            from cerebro.v2.core.theme_bridge_v2 import set_ctk_appearance_mode
            set_ctk_appearance_mode()
        except Exception:
            pass

    def _on_close(self) -> None:
        if self._dirty:
            if not messagebox.askyesno("Discard Changes",
                                       "Discard unsaved theme changes?",
                                       parent=self._win):
                return
        self._win.destroy()

    def _apply_theme(self) -> None:
        try:
            self._win.configure(fg_color=theme_color("base.background"))
        except Exception:
            pass
