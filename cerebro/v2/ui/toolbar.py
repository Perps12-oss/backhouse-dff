"""
Toolbar Widget

Full Ashisoft-style toolbar:
  [📁 Add Path] [✕ Remove] | [▶ Search Now] [⏹ Stop] | [📋 Auto Mark ▼] [🗑 Delete] [📦 Move To] | [⚙] [?]

"Search Now" is accent-colored; "Stop" is hidden until a scan is running;
"Delete" is danger-colored; "Auto Mark" opens a dropdown menu.
"""

from __future__ import annotations

import tkinter as tk
from typing import Optional, Callable, List
from pathlib import Path

try:
    import customtkinter as ctk
    CTkFrame = ctk.CTkFrame
    CTkButton = ctk.CTkButton
    CTkLabel = ctk.CTkLabel
except ImportError:
    CTkFrame = tk.Frame
    CTkButton = tk.Button
    CTkLabel = tk.Label

from cerebro.v2.core.design_tokens import Spacing, Typography, Dimensions
from cerebro.v2.core.theme_bridge_v2 import theme_color, subscribe_to_theme


# Auto-mark rule labels → rule keys (same keys used by results_panel.apply_selection_rule)
_AUTO_MARK_RULES = [
    ("Select All Duplicates",              "select_all"),
    ("Keep Largest — mark others",         "select_except_largest"),
    ("Keep Smallest — mark others",        "select_except_smallest"),
    ("Keep Newest — mark others",          "select_except_newest"),
    ("Keep Oldest — mark others",          "select_except_oldest"),
    ("Keep First in Group — mark others",  "select_except_first"),
    ("Keep Highest Resolution — mark others", "select_except_highest_resolution"),
    (None, None),  # separator
    ("Select All in Folder…",             "select_in_folder"),
    ("Select by Extension…",              "select_by_extension"),
    (None, None),  # separator
    ("Invert Selection",                   "invert_selection"),
    ("Clear All Selections",               "clear_all"),
]


class Toolbar(CTkFrame):
    """
    Full-width toolbar matching Ashisoft Duplicate File Finder Pro 8.2.

    Public API (callbacks):
        on_add_path(cb)         — Add Path button
        on_remove_selected(cb)  — Remove button
        on_start_search(cb)     — Search Now button
        on_stop_search(cb)      — Stop button
        on_auto_mark(cb)        — Auto Mark menu item; cb(rule_key: str)
        on_delete_selected(cb)  — Delete button
        on_move_to(cb)          — Move To button
        on_settings(cb)         — Settings button
        on_help(cb)             — Help button

    State methods:
        set_scanning(bool)      — swap Search Now ↔ Stop visibility
        set_has_selection(bool) — enable/disable Delete & Move To
    """

    def __init__(self, master=None, **kwargs):
        super().__init__(master, **kwargs)
        subscribe_to_theme(self, self._apply_theme)

        self._scanning: bool = False
        self._folders: List[Path] = []

        # Callbacks
        self._on_add_path:        Optional[Callable[[], None]] = None
        self._on_remove_selected: Optional[Callable[[], None]] = None
        self._on_start_search:    Optional[Callable[[], None]] = None
        self._on_stop_search:     Optional[Callable[[], None]] = None
        self._on_auto_mark:       Optional[Callable[[str], None]] = None
        self._on_delete_selected: Optional[Callable[[], None]] = None
        self._on_move_to:         Optional[Callable[[], None]] = None
        self._on_settings:        Optional[Callable[[], None]] = None
        self._on_help:            Optional[Callable[[], None]] = None

        # Widgets (set in _build_widgets)
        self._add_path_btn:  Optional[CTkButton] = None
        self._remove_btn:    Optional[CTkButton] = None
        self._sep1:          Optional[CTkLabel]  = None
        self._start_btn:     Optional[CTkButton] = None
        self._stop_btn:      Optional[CTkButton] = None
        self._sep2:          Optional[CTkLabel]  = None
        self._auto_mark_btn: Optional[CTkButton] = None
        self._delete_btn:    Optional[CTkButton] = None
        self._move_to_btn:   Optional[CTkButton] = None
        self._sep3:          Optional[CTkLabel]  = None
        self._settings_btn:  Optional[CTkButton] = None
        self._help_btn:      Optional[CTkButton] = None

        self._build_widgets()
        self._layout_widgets()
        self._bind_shortcuts()

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _build_widgets(self) -> None:
        bg   = theme_color("toolbar.background")
        sec  = theme_color("button.secondary")
        secH = theme_color("button.secondaryHover")
        bdr  = theme_color("toolbar.border")
        acc  = theme_color("button.primary")
        accH = theme_color("button.primaryHover")
        dng  = theme_color("button.danger")
        dngH = theme_color("button.dangerHover")
        rad  = Spacing.BORDER_RADIUS_MD
        h    = Dimensions.BUTTON_HEIGHT_MD
        fw   = Typography.FONT_MD

        self._add_path_btn = CTkButton(
            self, text="📁 Add Path",
            width=110, height=h, font=fw,
            fg_color=sec, hover_color=secH,
            border_width=1, border_color=bdr, corner_radius=rad,
            command=self._trigger_add_path,
        )
        self._remove_btn = CTkButton(
            self, text="✕ Remove",
            width=90, height=h, font=fw,
            fg_color=sec, hover_color=secH,
            border_width=1, border_color=bdr, corner_radius=rad,
            command=self._trigger_remove,
        )
        self._sep1 = CTkLabel(self, text="│", width=20,
                              text_color=bdr, font=Typography.FONT_LG)

        self._start_btn = CTkButton(
            self, text="▶  Search Now",
            width=130, height=h, font=fw,
            fg_color=acc, hover_color=accH,
            border_width=0, corner_radius=rad,
            command=self._trigger_start,
        )
        # Stop is hidden until a scan starts
        self._stop_btn = CTkButton(
            self, text="⏹  Stop",
            width=90, height=h, font=fw,
            fg_color=dng, hover_color=dngH,
            border_width=0, corner_radius=rad,
            command=self._trigger_stop,
        )

        self._sep2 = CTkLabel(self, text="│", width=20,
                              text_color=bdr, font=Typography.FONT_LG)

        self._auto_mark_btn = CTkButton(
            self, text="📋 Auto Mark  ▼",
            width=135, height=h, font=fw,
            fg_color=sec, hover_color=secH,
            border_width=1, border_color=bdr, corner_radius=rad,
            command=self._show_auto_mark_menu,
        )
        self._delete_btn = CTkButton(
            self, text="🗑 Delete",
            width=90, height=h, font=fw,
            fg_color=dng, hover_color=dngH,
            border_width=0, corner_radius=rad,
            state="disabled",
            command=self._trigger_delete,
        )
        self._move_to_btn = CTkButton(
            self, text="📦 Move To",
            width=95, height=h, font=fw,
            fg_color=sec, hover_color=secH,
            border_width=1, border_color=bdr, corner_radius=rad,
            state="disabled",
            command=self._trigger_move_to,
        )

        self._sep3 = CTkLabel(self, text="│", width=20,
                              text_color=bdr, font=Typography.FONT_LG)

        self._settings_btn = CTkButton(
            self, text="⚙",
            width=36, height=h, font=Typography.FONT_LG,
            fg_color="transparent", hover_color=secH,
            border_width=0, corner_radius=rad,
            command=self._trigger_settings,
        )
        self._help_btn = CTkButton(
            self, text="?",
            width=36, height=h, font=Typography.FONT_LG,
            fg_color="transparent", hover_color=secH,
            border_width=0, corner_radius=rad,
            command=self._trigger_help,
        )

    def _layout_widgets(self) -> None:
        self.configure(
            height=Dimensions.TOOLBAR_HEIGHT,
            fg_color=theme_color("toolbar.background"),
        )
        pad = (Spacing.XS, Spacing.XS)

        for btn in (
            self._add_path_btn, self._remove_btn,
            self._sep1,
            self._start_btn,
            # _stop_btn intentionally NOT packed here — shown dynamically
            self._sep2,
            self._auto_mark_btn, self._delete_btn, self._move_to_btn,
            self._sep3,
            self._settings_btn, self._help_btn,
        ):
            btn.pack(side="left", padx=pad, pady=(Spacing.SM, Spacing.SM))

        # Right-side spacer
        CTkLabel(self, text="").pack(side="right", padx=Spacing.MD)

    # ------------------------------------------------------------------
    # Trigger methods
    # ------------------------------------------------------------------

    def _trigger_add_path(self) -> None:
        if self._on_add_path:
            self._on_add_path()

    def _trigger_remove(self) -> None:
        if self._on_remove_selected:
            self._on_remove_selected()

    def _trigger_start(self) -> None:
        if self._on_start_search and not self._scanning:
            self._on_start_search()

    def _trigger_stop(self) -> None:
        if self._on_stop_search and self._scanning:
            self._on_stop_search()

    def _trigger_delete(self) -> None:
        if self._on_delete_selected:
            self._on_delete_selected()

    def _trigger_move_to(self) -> None:
        if self._on_move_to:
            self._on_move_to()

    def _trigger_settings(self) -> None:
        if self._on_settings:
            self._on_settings()

    def _trigger_help(self) -> None:
        if self._on_help:
            self._on_help()

    def _show_auto_mark_menu(self) -> None:
        """Pop up the Auto Mark dropdown menu below the button."""
        menu = tk.Menu(self, tearoff=0)
        for label, rule_key in _AUTO_MARK_RULES:
            if label is None:
                menu.add_separator()
            else:
                menu.add_command(
                    label=label,
                    command=lambda k=rule_key: self._on_auto_mark(k) if self._on_auto_mark else None,
                )
        try:
            x = self._auto_mark_btn.winfo_rootx()
            y = self._auto_mark_btn.winfo_rooty() + self._auto_mark_btn.winfo_height()
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    # ------------------------------------------------------------------
    # State management
    # ------------------------------------------------------------------

    def set_scanning(self, scanning: bool) -> None:
        """Swap Search Now / Stop visibility based on scan state."""
        self._scanning = scanning
        if scanning:
            self._start_btn.pack_forget()
            self._stop_btn.pack(
                side="left",
                padx=(Spacing.XS, Spacing.XS),
                pady=(Spacing.SM, Spacing.SM),
                before=self._sep2,
            )
        else:
            self._stop_btn.pack_forget()
            self._start_btn.pack(
                side="left",
                padx=(Spacing.XS, Spacing.XS),
                pady=(Spacing.SM, Spacing.SM),
                before=self._sep2,
            )

    def set_has_selection(self, has_selection: bool) -> None:
        """Enable or disable Delete / Move To based on whether files are checked."""
        state = "normal" if has_selection else "disabled"
        try:
            self._delete_btn.configure(state=state)
            self._move_to_btn.configure(state=state)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Keyboard shortcuts
    # ------------------------------------------------------------------

    def _bind_shortcuts(self) -> None:
        try:
            root = self.winfo_toplevel()
            root.bind("<Control-o>", lambda e: self._trigger_add_path())
            root.bind("<Control-O>", lambda e: self._trigger_add_path())
            root.bind("<Control-Return>", lambda e: self._trigger_start())
            root.bind("<Control-Enter>",  lambda e: self._trigger_start())
            root.bind("<Escape>",          lambda e: self._trigger_stop())
            root.bind("<Control-comma>",   lambda e: self._trigger_settings())
            root.bind("<Delete>",          lambda e: self._trigger_delete())
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Callback registration (public API)
    # ------------------------------------------------------------------

    def on_add_path(self, cb: Callable[[], None]) -> None:        self._on_add_path = cb
    def on_remove_selected(self, cb: Callable[[], None]) -> None: self._on_remove_selected = cb
    def on_start_search(self, cb: Callable[[], None]) -> None:    self._on_start_search = cb
    def on_stop_search(self, cb: Callable[[], None]) -> None:     self._on_stop_search = cb
    def on_auto_mark(self, cb: Callable[[str], None]) -> None:    self._on_auto_mark = cb
    def on_delete_selected(self, cb: Callable[[], None]) -> None: self._on_delete_selected = cb
    def on_move_to(self, cb: Callable[[], None]) -> None:         self._on_move_to = cb
    def on_settings(self, cb: Callable[[], None]) -> None:        self._on_settings = cb
    def on_help(self, cb: Callable[[], None]) -> None:            self._on_help = cb

    # ------------------------------------------------------------------
    # Folder helpers (kept for backwards compatibility)
    # ------------------------------------------------------------------

    def get_folders(self) -> List[Path]:        return self._folders.copy()
    def add_folder(self, path: Path) -> None:
        if path not in self._folders:
            self._folders.append(path)
    def remove_folder(self, path: Path) -> None:
        if path in self._folders:
            self._folders.remove(path)
    def clear_folders(self) -> None:            self._folders.clear()
    def set_folders_count(self, count: int) -> None: pass  # reserved for badge

    # ------------------------------------------------------------------
    # Theme
    # ------------------------------------------------------------------

    def _apply_theme(self) -> None:
        try: self.configure(fg_color=theme_color("toolbar.background"))
        except Exception: pass

        pairs = [
            (self._add_path_btn,  "button.secondary",  "button.secondaryHover"),
            (self._remove_btn,    "button.secondary",  "button.secondaryHover"),
            (self._start_btn,     "button.primary",    "button.primaryHover"),
            (self._stop_btn,      "button.danger",     "button.dangerHover"),
            (self._auto_mark_btn, "button.secondary",  "button.secondaryHover"),
            (self._delete_btn,    "button.danger",     "button.dangerHover"),
            (self._move_to_btn,   "button.secondary",  "button.secondaryHover"),
        ]
        for btn, fg_slot, hov_slot in pairs:
            try: btn.configure(fg_color=theme_color(fg_slot), hover_color=theme_color(hov_slot))
            except Exception: pass

        for sep in (self._sep1, self._sep2, self._sep3):
            try: sep.configure(text_color=theme_color("toolbar.border"))
            except Exception: pass


logger = __import__('logging').getLogger(__name__)

# Blueprint-compatible alias.
TopActionToolbar = Toolbar
