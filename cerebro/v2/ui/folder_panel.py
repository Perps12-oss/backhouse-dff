"""
Folder Panel Widget

Left panel with 2-tab layout:
- Folders tab: scan folders + mode-dependent scan options
- Protect tab: protected folders (excluded from deletion)

Supports post-scan collapse (full-width results) and pre-scan expand.
"""

from __future__ import annotations

import logging
import tkinter as tk
from tkinter import filedialog, messagebox
from typing import Optional, Callable, List, Dict
from pathlib import Path

try:
    import customtkinter as ctk
    CTkFrame = ctk.CTkFrame
    CTkButton = ctk.CTkButton
    CTkLabel = ctk.CTkLabel
    CTkScrollableFrame = ctk.CTkScrollableFrame
    CTkOptionMenu = ctk.CTkOptionMenu
    CTkSlider = ctk.CTkSlider
    CTkCheckBox = ctk.CTkCheckBox
except ImportError:
    CTkFrame = tk.Frame
    CTkButton = tk.Button
    CTkLabel = tk.Label
    CTkScrollableFrame = tk.Frame
    CTkOptionMenu = tk.OptionMenu
    CTkSlider = tk.Scale
    CTkCheckBox = tk.Checkbutton

from cerebro.v2.core.design_tokens import Spacing, Typography, Dimensions
from cerebro.v2.core.theme_bridge_v2 import theme_color, subscribe_to_theme


# ---------------------------------------------------------------------------
# Network / UNC path dialog
# ---------------------------------------------------------------------------

class NetworkPathDialog:
    """Lets the user type a UNC path or network/mapped-drive path.

    Usage::

        dlg = NetworkPathDialog(parent_widget)
        dlg.show()
        if dlg.result:
            # dlg.result is a non-empty string entered by the user
            ...
    """

    def __init__(self, parent: tk.Misc) -> None:
        self.result: Optional[str] = None
        self._parent = parent

    def show(self) -> None:
        """Display the modal dialog and populate ``self.result`` on success."""
        win = tk.Toplevel(self._parent)
        win.title("Add Network Path")
        win.resizable(False, False)
        win.grab_set()  # modal

        # ── Label ──────────────────────────────────────────────────────────
        lbl = tk.Label(
            win,
            text=r"Enter network path  (e.g. \\server\share  or  Z:\)",
            padx=12, pady=8,
        )
        lbl.grid(row=0, column=0, columnspan=3, sticky="w")

        # ── Entry ──────────────────────────────────────────────────────────
        entry_var = tk.StringVar()
        entry = tk.Entry(win, textvariable=entry_var, width=52)
        entry.grid(row=1, column=0, columnspan=2, padx=(12, 4), pady=4, sticky="ew")
        entry.focus_set()

        # ── Browse button ──────────────────────────────────────────────────
        def _browse() -> None:
            chosen = filedialog.askdirectory(
                title="Select network folder",
                parent=win,
            )
            if chosen:
                entry_var.set(chosen)

        btn_browse = tk.Button(win, text="Browse…", command=_browse)
        btn_browse.grid(row=1, column=2, padx=(0, 12), pady=4)

        # ── Warning label (hidden until validation fails) ──────────────────
        warn_var = tk.StringVar()
        warn_lbl = tk.Label(win, textvariable=warn_var, fg="orange",
                            wraplength=380, justify="left", padx=12)
        warn_lbl.grid(row=2, column=0, columnspan=3, sticky="w")

        # ── Add / Cancel buttons ───────────────────────────────────────────
        def _add() -> None:
            raw = entry_var.get().strip()
            if not raw:
                warn_var.set("Please enter a path.")
                return

            from cerebro.utils.paths import validate_scan_path
            ok, reason = validate_scan_path(raw)
            if not ok:
                # Warn but still allow adding (network may be temporarily offline)
                warn_var.set(f"Warning: {reason}\nThe path will still be added.")
                win.after(1500, _commit)  # auto-commit after brief pause
                return
            _commit()

        def _commit() -> None:
            self.result = entry_var.get().strip()
            win.destroy()

        def _cancel() -> None:
            win.destroy()

        btn_frame = tk.Frame(win)
        btn_frame.grid(row=3, column=0, columnspan=3, pady=(4, 10))
        tk.Button(btn_frame, text="Add", width=10, command=_add).pack(
            side="left", padx=6)
        tk.Button(btn_frame, text="Cancel", width=10, command=_cancel).pack(
            side="left", padx=6)

        # Bind Enter key to Add action
        win.bind("<Return>", lambda _e: _add())
        win.bind("<Escape>", lambda _e: _cancel())

        win.wait_window()


# ---------------------------------------------------------------------------
# Folder list widgets (reused by both tabs)
# ---------------------------------------------------------------------------

class ScanFolderList(CTkScrollableFrame):
    """Scrollable list of folders with add/remove controls."""

    _add_label: str = "+ Add Folder"
    _add_color_key: str = "button.primary"
    _add_hover_key: str = "button.primaryHover"

    def __init__(self, master=None, **kwargs):
        super().__init__(master, **kwargs)
        self._folders: List[Path] = []
        self._folder_widgets: Dict[Path, Dict[str, tk.Widget]] = {}
        self._on_folder_added: Optional[Callable[[Path], None]] = None
        self._on_folder_removed: Optional[Callable[[Path], None]] = None

        subscribe_to_theme(self, self._apply_theme)
        self._build_ui()

    def _build_ui(self) -> None:
        try:
            self.configure(
                fg_color=theme_color("base.backgroundTertiary"),
                scrollbar_fg_color=theme_color("panel.background"),
                scrollbar_button_color=theme_color("base.backgroundTertiary"),
                scrollbar_button_hover_color=theme_color(self._add_color_key),
            )
        except AttributeError:
            pass

        self._add_btn = CTkButton(
            self,
            text=self._add_label,
            height=Dimensions.BUTTON_HEIGHT_MD,
            font=Typography.FONT_SM,
            fg_color=theme_color(self._add_color_key),
            hover_color=theme_color(self._add_hover_key),
            corner_radius=Spacing.BORDER_RADIUS_SM,
        )
        self._add_btn.pack(fill="x", padx=Spacing.SM, pady=(0, Spacing.XS))
        self._add_btn.configure(command=self._trigger_add)

        self._add_network_btn = CTkButton(
            self,
            text="+ Add Network Path",
            height=Dimensions.BUTTON_HEIGHT_MD,
            font=Typography.FONT_SM,
            fg_color=theme_color("base.backgroundElevated"),
            hover_color=theme_color(self._add_hover_key),
            corner_radius=Spacing.BORDER_RADIUS_SM,
        )
        self._add_network_btn.pack(fill="x", padx=Spacing.SM, pady=(0, Spacing.SM))
        self._add_network_btn.configure(command=self._trigger_add_network)

    def _apply_theme(self) -> None:
        try:
            self.configure(
                fg_color=theme_color("base.backgroundTertiary"),
                scrollbar_fg_color=theme_color("panel.background"),
                scrollbar_button_color=theme_color("base.backgroundTertiary"),
                scrollbar_button_hover_color=theme_color(self._add_color_key),
            )
        except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
            pass
        try:
            self._add_btn.configure(
                fg_color=theme_color(self._add_color_key),
                hover_color=theme_color(self._add_hover_key),
            )
        except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
            pass
        try:
            self._add_network_btn.configure(
                fg_color=theme_color("base.backgroundElevated"),
                hover_color=theme_color(self._add_hover_key),
            )
        except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
            pass
        for widgets in self._folder_widgets.values():
            try:
                widgets["frame"].configure(fg_color=theme_color("base.backgroundElevated"))
                widgets["label"].configure(text_color=theme_color("base.foreground"))
                widgets["button"].configure(
                    fg_color=theme_color("base.foregroundSecondary"),
                    hover_color=theme_color("feedback.danger"),
                )
            except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
                pass

    def _trigger_add(self) -> None:
        path = filedialog.askdirectory(title="Select folder")
        if path:
            self.add_folder(Path(path))

    def _trigger_add_network(self) -> None:
        dlg = NetworkPathDialog(self)
        dlg.show()
        if dlg.result:
            self.add_folder(Path(dlg.result))

    def add_folder(self, path: Path) -> None:
        if path in self._folders:
            return
        self._folders.append(path)

        row = CTkFrame(self, height=Dimensions.ROW_HEIGHT,
                       fg_color=theme_color("base.backgroundElevated"))
        row.pack(fill="x", padx=Spacing.SM, pady=(0, Spacing.XS))

        name = path.name or str(path)
        if len(name) > 28:
            name = name[:25] + "..."

        lbl = CTkLabel(row, text=name, font=Typography.FONT_SM,
                       text_color=theme_color("base.foreground"), anchor="w")
        lbl.pack(side="left", padx=Spacing.SM, fill="x", expand=True)

        btn = CTkButton(row, text="×", width=24, height=24,
                        font=Typography.FONT_LG,
                        fg_color=theme_color("base.foregroundSecondary"),
                        hover_color=theme_color("feedback.danger"),
                        corner_radius=Spacing.BORDER_RADIUS_SM)
        btn.pack(side="right", padx=Spacing.SM)
        btn.configure(command=lambda p=path: self._remove_folder(p))

        self._folder_widgets[path] = {"frame": row, "label": lbl, "button": btn}
        if self._on_folder_added:
            self._on_folder_added(path)

    def _remove_folder(self, path: Path) -> None:
        if path not in self._folders:
            return
        self._folders.remove(path)
        widgets = self._folder_widgets.pop(path, {})
        if widgets:
            widgets["frame"].destroy()
        if self._on_folder_removed:
            self._on_folder_removed(path)

    def clear_folders(self) -> None:
        for path in list(self._folders):
            self._remove_folder(path)

    def get_folders(self) -> List[Path]:
        return self._folders.copy()

    def set_folders(self, folders: List[Path]) -> None:
        self.clear_folders()
        for p in folders:
            self.add_folder(p)

    def on_folder_added(self, cb: Callable[[Path], None]) -> None:
        self._on_folder_added = cb

    def on_folder_removed(self, cb: Callable[[Path], None]) -> None:
        self._on_folder_removed = cb


class ProtectFolderList(ScanFolderList):
    """Protected-folder variant — warning accent."""
    _add_label = "+ Add Protected Folder"
    _add_color_key = "feedback.warning"
    _add_hover_key = "feedback.warning"


# ---------------------------------------------------------------------------
# Scan options panel (mode-dependent)
# ---------------------------------------------------------------------------

class ScanOptionsPanel(CTkScrollableFrame):
    """Dynamic panel for scan-mode options; swaps content on mode change."""

    def __init__(self, master=None, **kwargs):
        super().__init__(master, **kwargs)
        self._current_mode: str = "files"
        self._option_widgets: Dict[str, tk.Widget] = {}
        self._on_options_changed: Optional[Callable[[Dict], None]] = None

        subscribe_to_theme(self, self._apply_theme)

        try:
            self.configure(fg_color=theme_color("base.backgroundTertiary"))
        except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
            pass

        self._options_container = CTkFrame(self, fg_color="transparent")
        self._options_container.pack(fill="both", expand=True)

        self._set_mode_options("files")

    def _apply_theme(self) -> None:
        try:
            self.configure(fg_color=theme_color("base.backgroundTertiary"))
        except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
            pass
        self._set_mode_options(self._current_mode)

    def _clear(self) -> None:
        for w in self._option_widgets.values():
            try:
                w.destroy()
            except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
                pass
        self._option_widgets.clear()
        # Also destroy any bare labels in container
        for child in list(self._options_container.winfo_children()):
            try:
                child.destroy()
            except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
                pass

    def _set_mode_options(self, mode: str) -> None:
        self._current_mode = mode
        self._clear()
        builder = {
            "files": self._build_files_options,
            "photos": self._build_photos_options,
            "videos": self._build_videos_options,
            "music": self._build_music_options,
            "empty_folders": self._build_empty_folders_options,
            "large_files": self._build_large_files_options,
        }.get(mode)
        if builder:
            builder()

    # ---- option builders --------------------------------------------------

    def _lbl(self, text: str) -> None:
        CTkLabel(self._options_container, text=text, font=Typography.FONT_XS,
                 text_color=theme_color("base.foregroundSecondary"),
                 anchor="w").pack(fill="x", padx=Spacing.SM, pady=(Spacing.SM, 0))

    def _menu(self, key: str, values: List[str], default: str) -> None:
        m = CTkOptionMenu(self._options_container, values=values,
                          font=Typography.FONT_SM,
                          fg_color=theme_color("base.backgroundElevated"),
                          button_color=theme_color("base.backgroundElevated"),
                          dropdown_fg_color=theme_color("base.backgroundElevated"))
        m.set(default)
        m.pack(fill="x", padx=Spacing.SM, pady=(Spacing.XS, 0))
        self._option_widgets[key] = m

    def _slider(self, key: str, mn: float, mx: float, default: float) -> None:
        s = CTkSlider(self._options_container, from_=mn, to=mx,
                      number_of_steps=int(mx - mn))
        s.set(default)
        s.pack(fill="x", padx=Spacing.SM, pady=(Spacing.XS, 0))
        self._option_widgets[key] = s

    def _check(self, key: str, text: str, default: bool) -> None:
        cb = CTkCheckBox(self._options_container, text=text, font=Typography.FONT_SM)
        if default:
            cb.select()
        cb.pack(anchor="w", padx=Spacing.SM, pady=(Spacing.XS, 0))
        self._option_widgets[key] = cb

    def _build_files_options(self) -> None:
        self._lbl("Comparison Method")
        self._menu("hash_algo", ["SHA256 (Recommended)", "Blake3 (Fastest)", "MD5 (Quick)"], "SHA256 (Recommended)")
        self._lbl("Ignore files smaller than (MB)")
        self._slider("min_size", 0, 1024, 0)
        self._lbl("Ignore files larger than (MB, 0 = no limit)")
        self._slider("max_size", 0, 10240, 0)

    def _build_photos_options(self) -> None:
        self._lbl("Similarity sensitivity — perceptual (lower = stricter)")
        self._slider("phash_threshold", 0, 64, 8)
        self._lbl("Similarity sensitivity — detail (lower = stricter)")
        self._slider("dhash_threshold", 0, 64, 10)
        self._lbl("Include Formats")
        self._check("format_jpg", "JPG / JPEG", True)
        self._check("format_png", "PNG", True)
        self._check("format_webp", "WEBP", True)
        self._check("format_heic", "HEIC", False)
        self._check("format_raw", "RAW (CR2, NEF, DNG…)", False)

    def _build_videos_options(self) -> None:
        self._lbl("Allow duration difference of (seconds)")
        self._slider("duration_tolerance", 0, 30, 3)
        self._lbl("Scan depth")
        self._menu("keyframe_count", ["3 (Fast)", "5 (Thorough)"], "3 (Fast)")

    def _build_music_options(self) -> None:
        self._lbl("Match Fields")
        self._check("match_artist", "Artist", True)
        self._check("match_title", "Title", True)
        self._check("match_album", "Album", False)
        self._check("match_duration", "Duration", True)
        self._lbl("Similarity Threshold (%)")
        self._slider("similarity_threshold", 50, 100, 85)

    def _build_empty_folders_options(self) -> None:
        self._lbl("Minimum Depth")
        self._slider("min_depth", 0, 10, 0)

    def _build_large_files_options(self) -> None:
        self._lbl("Show top N largest files")
        self._slider("top_n", 10, 500, 100)
        self._lbl("Show files larger than (MB)")
        self._slider("min_size_mb", 0, 1024, 100)
        self._check("group_by_type", "Group by File Type", True)

    # ---- public API -------------------------------------------------------

    def set_mode(self, mode: str) -> None:
        self._set_mode_options(mode)

    def set_slider_value(self, key: str, value: int) -> None:
        widget = self._option_widgets.get(key)
        if isinstance(widget, CTkSlider):
            widget.set(float(value))

    # Friendly-name → internal-value mapping for the Comparison Method menu.
    _HASH_DISPLAY_MAP = {
        "SHA256 (Recommended)": "SHA256",
        "Blake3 (Fastest)":     "Blake3",
        "MD5 (Quick)":          "MD5",
    }

    def get_options(self) -> Dict:
        options: Dict[str, object] = {"mode": self._current_mode}
        for key, widget in self._option_widgets.items():
            if isinstance(widget, CTkSlider):
                options[key] = int(float(widget.get()))
            elif isinstance(widget, CTkCheckBox):
                try:
                    options[key] = bool(widget.get())
                except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
                    options[key] = False
            elif isinstance(widget, CTkOptionMenu):
                try:
                    raw = widget.get()
                    # Strip friendly suffixes so engines receive the bare algorithm name.
                    options[key] = self._HASH_DISPLAY_MAP.get(raw, raw)
                except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
                    options[key] = ""
        return options

    def on_options_changed(self, cb: Callable[[Dict], None]) -> None:
        self._on_options_changed = cb


# ---------------------------------------------------------------------------
# FolderPanel — 2-tab layout with collapse support
# ---------------------------------------------------------------------------

class FolderPanel(CTkFrame):
    """
    Left panel with 2-tab layout.

    Tab "Folders":  scan folder list  +  mode-dependent scan options below
    Tab "Protect":  protected folders list

    Collapse/expand: call set_collapsed(True) after scan starts, False before.
    When collapsed the frame width drops to a narrow toggle strip that the
    parent paned window can read via get_collapsed_width().
    """

    COLLAPSED_WIDTH = 28  # px — just enough for the toggle arrow

    def __init__(self, master=None, **kwargs):
        super().__init__(master, **kwargs)

        self._active_tab: str = "folders"   # "folders" | "protect"
        self._collapsed: bool = False

        # Public-API callbacks
        self._on_folders_changed: Optional[Callable[[List[Path]], None]] = None
        self._on_protected_changed: Optional[Callable[[List[Path]], None]] = None
        self._on_options_changed: Optional[Callable[[str, Dict], None]] = None
        self._on_collapse_toggled: Optional[Callable[[bool], None]] = None

        subscribe_to_theme(self, self._apply_theme)
        self._build_ui()

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self.configure(fg_color=theme_color("panel.background"))

        # ── Collapse strip (always visible, left edge) ──────────────
        self._strip = CTkFrame(self, width=self.COLLAPSED_WIDTH,
                               fg_color=theme_color("base.backgroundTertiary"))
        self._strip.pack(side="left", fill="y")
        self._strip.pack_propagate(False)

        self._toggle_btn = CTkButton(
            self._strip, text="◀", width=self.COLLAPSED_WIDTH, height=36,
            font=Typography.FONT_SM,
            fg_color="transparent",
            hover_color=theme_color("base.backgroundElevated"),
            border_width=0, corner_radius=0,
        )
        self._toggle_btn.pack(side="top", pady=(Spacing.MD, 0))
        self._toggle_btn.configure(command=self._toggle_collapse)

        # ── Main content (hidden when collapsed) ─────────────────────
        self._content = CTkFrame(self, fg_color=theme_color("panel.background"))
        self._content.pack(side="left", fill="both", expand=True)

        # Tab bar
        self._tab_bar = CTkFrame(self._content, height=36,
                                 fg_color=theme_color("base.backgroundTertiary"))
        self._tab_bar.pack(fill="x")

        self._tab_folders_btn = self._make_tab_btn("Folders", "folders")
        self._tab_protect_btn = self._make_tab_btn("🛡 Protect", "protect")

        # Tab pages (swapped)
        self._page_folders = CTkFrame(self._content,
                                      fg_color=theme_color("panel.background"))
        self._page_protect = CTkFrame(self._content,
                                      fg_color=theme_color("panel.background"))

        # Build folder page content
        self._scan_list = ScanFolderList(self._page_folders)
        self._scan_list.pack(fill="both", expand=True, padx=Spacing.XS, pady=Spacing.XS)
        self._scan_list.on_folder_added(self._on_scan_added)
        self._scan_list.on_folder_removed(self._on_scan_removed)

        # Divider
        CTkFrame(self._page_folders, height=1,
                 fg_color=theme_color("base.backgroundElevated")).pack(
            fill="x", padx=Spacing.SM, pady=(Spacing.XS, 0))

        # Options section header
        self._options_header = CTkLabel(
            self._page_folders, text="Scan Options",
            font=Typography.FONT_XS,
            text_color=theme_color("base.foregroundSecondary"),
            anchor="w")
        self._options_header.pack(fill="x", padx=Spacing.MD, pady=(Spacing.SM, 0))

        self._options_panel = ScanOptionsPanel(self._page_folders, height=200)
        self._options_panel.pack(fill="x", padx=Spacing.XS)

        # Build protect page content
        self._protect_list = ProtectFolderList(self._page_protect)
        self._protect_list.pack(fill="both", expand=True,
                                padx=Spacing.XS, pady=Spacing.XS)
        self._protect_list.on_folder_added(self._on_protect_added)
        self._protect_list.on_folder_removed(self._on_protect_removed)

        # Show folders tab by default
        self._switch_tab("folders")

    def _make_tab_btn(self, label: str, tab_id: str) -> CTkButton:
        btn = CTkButton(
            self._tab_bar, text=label,
            height=32, font=Typography.FONT_SM,
            fg_color=theme_color("base.backgroundTertiary"),
            hover_color=theme_color("base.backgroundElevated"),
            text_color=theme_color("base.foreground"),
            border_width=0, corner_radius=0,
        )
        btn.pack(side="left", fill="x", expand=True)
        btn.configure(command=lambda t=tab_id: self._switch_tab(t))
        return btn

    # ------------------------------------------------------------------
    # Tab switching
    # ------------------------------------------------------------------

    def _switch_tab(self, tab_id: str) -> None:
        self._active_tab = tab_id

        # Update tab button appearance
        active_fg = theme_color("button.primary")
        inactive_fg = theme_color("base.backgroundTertiary")

        self._tab_folders_btn.configure(
            fg_color=active_fg if tab_id == "folders" else inactive_fg)
        self._tab_protect_btn.configure(
            fg_color=active_fg if tab_id == "protect" else inactive_fg)

        # Swap pages
        self._page_folders.pack_forget()
        self._page_protect.pack_forget()

        if tab_id == "folders":
            self._page_folders.pack(fill="both", expand=True)
        else:
            self._page_protect.pack(fill="both", expand=True)

    # ------------------------------------------------------------------
    # Collapse / expand
    # ------------------------------------------------------------------

    def _toggle_collapse(self) -> None:
        self.set_collapsed(not self._collapsed)

    def set_collapsed(self, collapsed: bool) -> None:
        """Collapse or expand the panel. Call from the scan host after scan."""
        if self._collapsed == collapsed:
            return
        self._collapsed = collapsed

        if collapsed:
            self._content.pack_forget()
            self._toggle_btn.configure(text="▶")
        else:
            self._content.pack(side="left", fill="both", expand=True)
            self._toggle_btn.configure(text="◀")

        if self._on_collapse_toggled:
            self._on_collapse_toggled(collapsed)

    def is_collapsed(self) -> bool:
        return self._collapsed

    # ------------------------------------------------------------------
    # Internal callbacks
    # ------------------------------------------------------------------

    def _on_scan_added(self, path: Path) -> None:
        if self._on_folders_changed:
            self._on_folders_changed(self._scan_list.get_folders())

    def _on_scan_removed(self, path: Path) -> None:
        if self._on_folders_changed:
            self._on_folders_changed(self._scan_list.get_folders())

    def _on_protect_added(self, path: Path) -> None:
        if self._on_protected_changed:
            self._on_protected_changed(self._protect_list.get_folders())

    def _on_protect_removed(self, path: Path) -> None:
        if self._on_protected_changed:
            self._on_protected_changed(self._protect_list.get_folders())

    # ------------------------------------------------------------------
    # Theme
    # ------------------------------------------------------------------

    def _apply_theme(self) -> None:
        try:
            self.configure(fg_color=theme_color("panel.background"))
            self._strip.configure(fg_color=theme_color("base.backgroundTertiary"))
            self._content.configure(fg_color=theme_color("panel.background"))
            self._tab_bar.configure(fg_color=theme_color("base.backgroundTertiary"))
            self._toggle_btn.configure(hover_color=theme_color("base.backgroundElevated"))
        except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
            pass
        # Re-apply active tab highlight
        self._switch_tab(self._active_tab)

    # ------------------------------------------------------------------
    # Public API (unchanged contract for ScanPage / folder host)
    # ------------------------------------------------------------------

    def set_scan_mode(self, mode: str) -> None:
        """Update options panel when scan mode changes."""
        self._options_panel.set_mode(mode)
        # Update header label
        mode_labels = {
            "files": "Scan Options — Files",
            "photos": "Scan Options — Photos",
            "videos": "Scan Options — Videos",
            "music": "Scan Options — Music",
            "empty_folders": "Scan Options — Empty Folders",
            "large_files": "Scan Options — Large Files",
        }
        try:
            self._options_header.configure(
                text=mode_labels.get(mode, "Scan Options"))
        except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
            pass

    def set_photo_phash_dhash_defaults(self, phash_threshold: int, dhash_threshold: int) -> None:
        """Apply persisted image threshold defaults to the photos options panel."""
        self.set_scan_mode("photos")
        self._options_panel.set_slider_value("phash_threshold", phash_threshold)
        self._options_panel.set_slider_value("dhash_threshold", dhash_threshold)

    def get_scan_folders(self) -> List[Path]:
        return self._scan_list.get_folders()

    def get_protected_folders(self) -> List[Path]:
        return self._protect_list.get_folders()

    def get_options(self) -> Dict:
        return self._options_panel.get_options()

    def set_scan_folders(self, folders: List[Path]) -> None:
        self._scan_list.set_folders(folders)

    def set_protected_folders(self, folders: List[Path]) -> None:
        self._protect_list.set_folders(folders)

    def on_folders_changed(self, cb: Callable[[List[Path]], None]) -> None:
        self._on_folders_changed = cb

    def on_protected_changed(self, cb: Callable[[List[Path]], None]) -> None:
        self._on_protected_changed = cb

    def on_options_changed(self, cb: Callable[[str, Dict], None]) -> None:
        self._on_options_changed = cb

    def on_collapse_toggled(self, cb: Callable[[bool], None]) -> None:
        """Notify when user toggles collapse; used by the scan host to resize the paned window."""
        self._on_collapse_toggled = cb


logger = __import__('logging').getLogger(__name__)
