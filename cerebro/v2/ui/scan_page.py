"""
ScanPage — full-viewport scan configuration page.

Left (280 px):  folder tree with lazy-loading (off main thread).
Right (rest):   mode bar · config sub-tabs · action bar.
                During scan: sub-tab content is replaced by progress view.
"""
from __future__ import annotations

import logging
import os
import string
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk
from typing import Any, Callable, Dict, List, Optional

_log = logging.getLogger(__name__)

try:
    import customtkinter as ctk
    CTkFrame       = ctk.CTkFrame
    CTkLabel       = ctk.CTkLabel
    CTkButton      = ctk.CTkButton
    CTkProgressBar = ctk.CTkProgressBar
    CTkScrollableFrame = ctk.CTkScrollableFrame
except ImportError:
    CTkFrame       = tk.Frame          # type: ignore[misc,assignment]
    CTkLabel       = tk.Label          # type: ignore[misc,assignment]
    CTkButton      = tk.Button         # type: ignore[misc,assignment]
    CTkProgressBar = None              # type: ignore[misc,assignment]
    CTkScrollableFrame = tk.Frame      # type: ignore[misc,assignment]

from cerebro.engines.base_engine import ScanProgress, ScanState
from cerebro.v2.core.engine_deps import EngineState, probe_mode
from cerebro.v2.ui.theme_applicator import ThemeApplicator
from cerebro.v2.ui.widgets.scan_in_progress_view import ScanInProgressView

# ---------------------------------------------------------------------------
# Design tokens (local — no theme engine dependency)
# ---------------------------------------------------------------------------

_WHITE    = "#FFFFFF"
_NAVY     = "#0B1929"
_NAVY_MID = "#1E3A5F"
_NAVY_BAR = "#2E558E"
_SURFACE  = "#F0F0F0"
_BORDER   = "#E0E0E0"
_GRAY     = "#666666"
_DIMGRAY  = "#AAAAAA"
_RED      = "#E74C3C"
_BLUE_ACT = "#2E75B6"      # sub-tab active indicator
_SEL_BG   = "#E6F0FA"      # tree selected row
_BTN_BORDER = "#DDDDDD"

_SCAN_MODES: List[Dict[str, str]] = [
    {"key": "files",         "icon": "📄", "label": "Files"},
    {"key": "empty_folders", "icon": "📁", "label": "Folders"},
    {"key": "photos",        "icon": "🖼",  "label": "Compare"},
    {"key": "music",         "icon": "🎵", "label": "Music"},
    {"key": "large_files",   "icon": "📊", "label": "Unique"},
]

# ttk.Treeview requires globally-unique item ids. Never reuse the same iid under
# multiple parents — use tags to identify placeholder rows instead.
_DUMMY_TAG = "__tree_dummy__"


# ===========================================================================
# Left panel — folder tree
# ===========================================================================

class _FolderTree(tk.Frame):
    """280 px folder tree with lazy expansion (children loaded off-thread)."""

    WIDTH = 280
    _STYLE = "FolderTree.Treeview"

    def __init__(self, master, **kwargs) -> None:
        t = ThemeApplicator.get().build_tokens()
        kwargs.setdefault("bg", t.get("bg2", _WHITE))
        kwargs.setdefault("width", self.WIDTH)
        super().__init__(master, **kwargs)
        self.pack_propagate(False)
        self._selected_path: Optional[Path] = None
        self._on_activate: Optional[Callable[[Path], None]] = None
        self._t: dict = t
        self._build()
        self.apply_theme(t)
        self.after(0, self._populate_roots)

    def _build(self) -> None:
        t = self._t
        nav_bg = t.get("nav_bar", _NAVY_MID)
        panel  = t.get("bg2",     _WHITE)
        fg     = t.get("fg",      _WHITE)

        # Header bar
        self._hdr = tk.Frame(self, bg=nav_bg, height=32)
        self._hdr.pack(fill="x")
        self._hdr.pack_propagate(False)
        self._hdr_lbl = tk.Label(
            self._hdr, text="This PC", bg=nav_bg, fg=fg,
            font=("Segoe UI", 10),
        )
        self._hdr_lbl.pack(side="left", padx=10)
        self._hdr_btn = tk.Button(
            self._hdr, text="↺", bg=nav_bg, fg=fg,
            activebackground=nav_bg, activeforeground=fg,
            relief="flat", font=("Segoe UI", 11), cursor="hand2",
            command=self._refresh,
        )
        self._hdr_btn.pack(side="right", padx=8)

        # Tree + scrollbar
        self._body = tk.Frame(self, bg=panel)
        self._body.pack(fill="both", expand=True)

        self._apply_tree_style(t)

        vsb = ttk.Scrollbar(self._body, orient="vertical")
        self._tree = ttk.Treeview(self._body, style=self._STYLE,
                                  show="tree", selectmode="browse",
                                  yscrollcommand=vsb.set)
        vsb.configure(command=self._tree.yview)
        vsb.pack(side="right", fill="y")
        self._tree.pack(fill="both", expand=True)

        self._tree.bind("<<TreeviewOpen>>", self._on_open)
        self._tree.bind("<<TreeviewSelect>>", self._on_select)
        self._tree.bind("<Double-Button-1>", self._on_double_click)

    def _apply_tree_style(self, t: dict) -> None:
        panel  = t.get("bg2",        _WHITE)
        fg     = t.get("fg",         "#333333")
        sel_bg = t.get("row_sel",    _SEL_BG)
        sel_fg = t.get("row_sel_fg", "#111111")
        style = ttk.Style()
        style.configure(
            self._STYLE,
            background=panel, fieldbackground=panel,
            foreground=fg, rowheight=24, font=("Segoe UI", 10),
        )
        style.map(
            self._STYLE,
            background=[("selected", sel_bg)],
            foreground=[("selected", sel_fg)],
        )
        style.configure(f"{self._STYLE}.Heading", font=("Segoe UI", 9))

    def apply_theme(self, t: dict) -> None:
        self._t = t
        nav_bg = t.get("nav_bar", _NAVY_MID)
        panel  = t.get("bg2",     _WHITE)
        fg     = t.get("fg",      _WHITE)
        self.configure(bg=panel)
        if hasattr(self, "_hdr"):
            self._hdr.configure(bg=nav_bg)
            self._hdr_lbl.configure(bg=nav_bg, fg=fg)
            self._hdr_btn.configure(
                bg=nav_bg, fg=fg,
                activebackground=nav_bg, activeforeground=fg,
            )
        if hasattr(self, "_body"):
            self._body.configure(bg=panel)
        self._apply_tree_style(t)

    def _populate_roots(self) -> None:
        threading.Thread(target=self._build_roots, daemon=True).start()

    def _build_roots(self) -> None:
        nodes: List[tuple] = []

        # System shortcuts
        home = Path.home()
        for name in ("Desktop", "Documents", "Downloads", "Music", "Pictures", "Videos"):
            p = home / name
            if p.exists():
                nodes.append(("📂 " + name, p))

        # Drive letters (Windows)
        for letter in string.ascii_uppercase:
            drive = Path(f"{letter}:\\")
            if drive.exists():
                nodes.append((f"💾 {letter}:\\", drive))

        self.after(0, lambda n=nodes: self._insert_roots(n))

    def _insert_roots(self, nodes: List[tuple]) -> None:
        self._tree.delete(*self._tree.get_children())
        for label, path in nodes:
            item = self._tree.insert("", "end", text=label,
                                     values=[str(path)])
            self._add_dummy_child(item, text="Loading…")

    def _dummy_tags(self) -> tuple[str, ...]:
        return (_DUMMY_TAG,)

    def _is_dummy_item(self, iid: str) -> bool:
        tags = self._tree.item(iid, "tags") or ()
        return _DUMMY_TAG in tags

    def _add_dummy_child(self, parent: str, *, text: str) -> None:
        """Insert a unique placeholder child so the row shows an expand arrow."""
        self._tree.insert(parent, "end", text=text, tags=self._dummy_tags())

    def _on_open(self, _event=None) -> None:
        item = self._tree.focus()
        children = self._tree.get_children(item)
        if len(children) == 1 and self._is_dummy_item(children[0]):
            path_str = self._tree.item(item, "values")
            if path_str:
                self._tree.delete(children[0])
                threading.Thread(
                    target=self._load_children,
                    args=(item, Path(path_str[0])),
                    daemon=True,
                ).start()

    def _load_children(self, parent: str, path: Path) -> None:
        entries: List[tuple] = []
        try:
            for p in sorted(path.iterdir()):
                if p.is_dir() and not p.name.startswith("."):
                    entries.append(("📂 " + p.name, p))
        except PermissionError:
            pass
        self.after(0, lambda e=entries: self._insert_children(parent, e))

    def _insert_children(self, parent: str, entries: List[tuple]) -> None:
        for label, path in entries:
            child = self._tree.insert(parent, "end", text=label,
                                      values=[str(path)])
            # Add dummy so it shows expand arrow
            self._add_dummy_child(child, text="")

    def _on_select(self, _event=None) -> None:
        item = self._tree.focus()
        vals = self._tree.item(item, "values")
        if vals:
            self._selected_path = Path(vals[0])

    def _refresh(self) -> None:
        self._populate_roots()

    def get_selected(self) -> Optional[Path]:
        return self._selected_path

    def on_activate(self, cb: Callable[[Path], None]) -> None:
        """Register a handler invoked when a tree row is double-clicked."""
        self._on_activate = cb

    def _on_double_click(self, event) -> None:
        # Ignore double-clicks on the disclosure indicator so single-click
        # expand/collapse keeps working; activate only on the row body.
        region = self._tree.identify_region(event.x, event.y)
        if region not in ("tree", "cell"):
            return None
        iid = self._tree.identify_row(event.y)
        if not iid:
            return None
        vals = self._tree.item(iid, "values")
        if not vals or not self._on_activate:
            return None
        try:
            self._on_activate(Path(vals[0]))
        except Exception:
            _log.exception("tree double-click activate handler failed")
        return "break"


# ===========================================================================
# Right panel sub-components
# ===========================================================================

class _ModeButton(tk.Frame):
    """Single 80×48 px scan-mode button."""

    def __init__(self, master, key: str, icon: str, label: str,
                 on_click: Callable[[str], None], **kwargs) -> None:
        t = ThemeApplicator.get().build_tokens()
        kwargs.setdefault("bg", t.get("bg", _WHITE))
        kwargs.setdefault("width", 80)
        kwargs.setdefault("height", 48)
        super().__init__(master, cursor="hand2", **kwargs)
        self.pack_propagate(False)
        self._key      = key
        self._on_click = on_click
        self._active   = False
        self._t        = t

        inner = tk.Frame(self, bg=t.get("bg", _WHITE))
        inner.place(relx=0.5, rely=0.5, anchor="center")

        self._icon_lbl = tk.Label(
            inner, text=icon, bg=t.get("bg", _WHITE),
            fg=t.get("fg2", _GRAY), font=("Segoe UI", 14),
        )
        self._icon_lbl.pack()
        self._text_lbl = tk.Label(
            inner, text=label, bg=t.get("bg", _WHITE),
            fg=t.get("fg2", _GRAY), font=("Segoe UI", 9),
        )
        self._text_lbl.pack()
        self._inner = inner

        for w in (self, inner, self._icon_lbl, self._text_lbl):
            w.bind("<Button-1>", lambda _e: self._on_click(self._key))

        self._apply_style()

    def set_active(self, active: bool) -> None:
        self._active = active
        self._apply_style()

    def apply_theme(self, t: dict) -> None:
        self._t = t
        self._apply_style()

    def _apply_style(self) -> None:
        t = self._t
        active_bg = t.get("accent",  _NAVY_MID)
        active_fg = t.get("row_sel_fg", t.get("bg", _WHITE))
        inactive_bg = t.get("bg",     _WHITE)
        inactive_fg = t.get("fg2",    _GRAY)
        hover_bd    = t.get("border", _BTN_BORDER)
        bg = active_bg if self._active else inactive_bg
        fg = active_fg if self._active else inactive_fg
        hb = active_bg if self._active else hover_bd
        self.configure(bg=bg, highlightbackground=hb, highlightthickness=1)
        self._inner.configure(bg=bg)
        self._icon_lbl.configure(bg=bg, fg=fg)
        self._text_lbl.configure(bg=bg, fg=fg)


class _ScanModeBar(tk.Frame):
    """48 px row of 5 mode buttons + START/STOP SCAN."""

    def __init__(self, master, on_mode: Callable[[str], None],
                 on_start: Callable[[], None], on_stop: Callable[[], None],
                 **kwargs) -> None:
        kwargs.setdefault("bg", _WHITE)
        kwargs.setdefault("height", 48)
        super().__init__(master, **kwargs)
        self.pack_propagate(False)
        self._on_mode  = on_mode
        self._on_start = on_start
        self._on_stop  = on_stop
        self._active_key = "files"
        self._btns: Dict[str, _ModeButton] = {}
        self._scanning = False
        self._build()

    def _build(self) -> None:
        self._bottom_border = tk.Frame(self, bg=_BORDER, height=1)
        self._bottom_border.pack(side="bottom", fill="x")

        self._left = tk.Frame(self, bg=_WHITE)
        self._left.pack(side="left", fill="y")

        for m in _SCAN_MODES:
            btn = _ModeButton(self._left, m["key"], m["icon"], m["label"],
                              on_click=self._mode_clicked)
            btn.pack(side="left", padx=2, pady=4)
            self._btns[m["key"]] = btn
        self._btns["files"].set_active(True)

        self._right = tk.Frame(self, bg=_WHITE)
        self._right.pack(side="right", padx=12, fill="y")

        self._action_btn = tk.Button(
            self._right, text="START SCAN",
            bg=_NAVY_MID, fg=_WHITE,
            font=("Segoe UI", 11, "bold"),
            relief="flat", cursor="hand2",
            padx=24, pady=10,
            command=self._action_clicked,
        )
        self._action_btn.pack(side="right")

    def _mode_clicked(self, key: str) -> None:
        if self._scanning:
            return
        self._btns[self._active_key].set_active(False)
        self._active_key = key
        self._btns[key].set_active(True)
        self._on_mode(key)

    def _action_clicked(self) -> None:
        if self._scanning:
            self._on_stop()
        else:
            self._on_start()

    def set_scanning(self, scanning: bool) -> None:
        self._scanning = scanning
        if scanning:
            self._action_btn.configure(text="STOP SCAN", bg=_RED)
        else:
            self._action_btn.configure(text="START SCAN", bg=_NAVY_MID)

    def apply_theme(self, t: dict) -> None:
        bg     = t.get("bg",     _WHITE)
        border = t.get("border", _BORDER)
        btn_fg = t.get("row_sel_fg", t.get("bg", _WHITE))
        self.configure(bg=bg)
        self._left.configure(bg=bg)
        self._right.configure(bg=bg)
        self._bottom_border.configure(bg=border)
        for btn in self._btns.values():
            btn.apply_theme(t)
        if self._scanning:
            self._action_btn.configure(bg=t.get("danger", _RED), fg=btn_fg)
        else:
            self._action_btn.configure(
                bg=t.get("accent", _NAVY_MID),
                fg=btn_fg,
            )

    def get_mode(self) -> str:
        return self._active_key


class _SubTab(tk.Frame):
    """Single config sub-tab."""

    def __init__(self, master, key: str, label: str,
                 on_click: Callable[[str], None], **kwargs) -> None:
        t = ThemeApplicator.get().build_tokens()
        kwargs.setdefault("bg", t.get("bg2", _SURFACE))
        super().__init__(master, cursor="hand2", **kwargs)
        self._key      = key
        self._on_click = on_click
        self._active   = False
        self._t        = t

        self._lbl = tk.Label(
            self, text=label, bg=t.get("bg2", _SURFACE),
            fg=t.get("fg2", _GRAY), font=("Segoe UI", 10), padx=12,
        )
        self._lbl.pack(fill="both", expand=True)

        self._ind = tk.Frame(self, height=2, bg=t.get("bg2", _SURFACE))
        self._ind.pack(side="bottom", fill="x")

        for w in (self, self._lbl):
            w.bind("<Button-1>", lambda _e: self._on_click(self._key))

    def set_active(self, active: bool) -> None:
        self._active = active
        self._paint()

    def apply_theme(self, t: dict) -> None:
        self._t = t
        self._paint()

    def _paint(self) -> None:
        t = self._t
        panel = t.get("bg2",   _SURFACE)
        muted = t.get("fg2",   _GRAY)
        fg    = t.get("fg",    "#111111")
        acc   = t.get("accent", _BLUE_ACT)
        self.configure(bg=panel)
        if self._active:
            self._lbl.configure(bg=panel, fg=fg, font=("Segoe UI", 10, "bold"))
            self._ind.configure(bg=acc)
        else:
            self._lbl.configure(bg=panel, fg=muted, font=("Segoe UI", 10))
            self._ind.configure(bg=panel)


class _SearchFoldersList(tk.Frame):
    """Scrollable list of folders added to the scan, with inline action strip and drop zone."""

    def __init__(self, master, tree: Optional["_FolderTree"] = None, **kwargs) -> None:
        t = ThemeApplicator.get().build_tokens()
        kwargs.setdefault("bg", t.get("bg", _WHITE))
        super().__init__(master, **kwargs)
        self._tree = tree
        self._folders: List[Path] = []
        self._on_changed: Optional[Callable[[List[Path]], None]] = None
        self._t = t
        self._rows: List[Dict[str, tk.Widget]] = []
        self._build()

    def _build(self) -> None:
        bg  = self._t.get("bg",      _WHITE)
        nav = self._t.get("nav_bar", _NAVY_BAR)

        # --- Scrollable area fills the whole panel ---
        self._canvas = tk.Canvas(self, bg=bg, highlightthickness=0)
        vsb = ttk.Scrollbar(self, orient="vertical", command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self._canvas.pack(fill="both", expand=True)

        self._inner = tk.Frame(self._canvas, bg=bg)
        self._win = self._canvas.create_window((0, 0), window=self._inner, anchor="nw")
        self._inner.bind("<Configure>", self._on_inner_configure)
        self._canvas.bind("<Configure>", self._on_canvas_configure)
        self._canvas.bind(
            "<MouseWheel>",
            lambda e: self._canvas.yview_scroll(-1 * (e.delta // 120), "units"),
        )

        # Drop zone — always visible, sits centered in the panel.
        self._drop_zone = _DropZone(self._inner, t=self._t, on_add=self._browse)
        self._drop_zone.pack(expand=True, fill="both", pady=(8, 0))
        self._drop_zone.try_register_dnd(self._on_dnd_drop)

        # Centered action strip directly under the drop zone (not pinned
        # to the panel bottom). Rows get packed above the drop zone via
        # `before=self._drop_zone`, so the buttons stay with it at the
        # visual middle of the panel and never get crowded by rows.
        self._action_strip = tk.Frame(self._inner, bg=bg)
        self._action_strip.pack(fill="x", pady=(8, 16))
        self._action_center = tk.Frame(self._action_strip, bg=bg)
        self._action_center.pack(anchor="center")
        self._strip_btns: List[tk.Button] = []
        for text, cmd in [
            ("BROWSE\u2026",  self._browse),
            ("PASTE PATH",    self.paste_path),
            ("CLEAR ALL",     self.clear_all),
        ]:
            b = tk.Button(
                self._action_center, text=text, bg=nav,
                fg=_WHITE, font=("Segoe UI", 9, "bold"), relief="flat",
                padx=16, pady=6, cursor="hand2",
                activebackground="#3A6BAE", activeforeground=_WHITE,
                command=cmd,
            )
            b.pack(side="left", padx=4)
            b.bind("<Enter>", lambda _e, w=b: w.configure(bg="#3A6BAE"))
            b.bind("<Leave>", lambda _e, w=b, n=nav: w.configure(bg=n))
            self._strip_btns.append(b)

    def _on_dnd_drop(self, data: str) -> None:
        """Parse tkinterdnd2 brace-wrapped paths and add any valid directories."""
        raw = data.strip()
        tokens = raw.split("} {") if "} {" in raw else [raw]
        for token in tokens:
            p = Path(token.strip().strip("{}"))
            if p.is_dir():
                self.add(p)

    def _browse(self) -> None:
        """Open the native Explorer folder-picker and add the chosen folder."""
        path = filedialog.askdirectory(title="Select folder to scan")
        if path:
            self.add(Path(path))

    def apply_theme(self, t: dict) -> None:
        self._t = t
        bg  = t.get("bg",      _WHITE)
        nav = t.get("nav_bar", _NAVY_BAR)
        acc = t.get("accent",  "#3A6BAE")
        self.configure(bg=bg)
        self._canvas.configure(bg=bg)
        self._inner.configure(bg=bg)
        self._action_strip.configure(bg=bg)
        self._action_center.configure(bg=bg)
        for b in self._strip_btns:
            b.configure(bg=nav, fg=_WHITE, activebackground=acc)
            b.bind("<Enter>", lambda _e, w=b, a=acc: w.configure(bg=a))
            b.bind("<Leave>", lambda _e, w=b, n=nav: w.configure(bg=n))
        self._drop_zone.apply_theme(t)
        for r in self._rows:
            self._paint_row(r)

    def _paint_row(self, r: Dict[str, tk.Widget]) -> None:
        t      = self._t
        bg     = t.get("bg",     _WHITE)
        fg     = t.get("fg",     "#333333")
        danger = t.get("danger", _RED)
        r["row"].configure(bg=bg)
        r["icon"].configure(bg=bg)
        r["path"].configure(bg=bg, fg=fg)
        r["x"].configure(bg=bg, fg=danger,
                         activebackground=bg, activeforeground=danger)

    def _on_inner_configure(self, _e=None) -> None:
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _on_canvas_configure(self, e) -> None:
        self._canvas.itemconfig(self._win, width=e.width)

    def add(self, path: Path) -> None:
        if path in self._folders:
            return
        self._folders.append(path)
        self._render_row(path)
        if self._on_changed:
            self._on_changed(list(self._folders))

    def _render_row(self, path: Path) -> None:
        t  = self._t
        bg = t.get("bg", _WHITE)
        row = tk.Frame(self._inner, bg=bg)
        # Rows stack above the drop zone so the drop zone + action buttons
        # remain together in the visual middle of the panel.
        row.pack(fill="x", padx=8, pady=2, before=self._drop_zone)

        icon = tk.Label(row, text="📁", bg=bg, fg="#F0A500",
                        font=("Segoe UI", 12))
        icon.pack(side="left", padx=(0, 6))
        path_lbl = tk.Label(row, text=str(path), bg=bg,
                            fg=t.get("fg", "#333333"),
                            font=("Segoe UI", 10), anchor="w")
        path_lbl.pack(side="left", fill="x", expand=True)
        x_btn = tk.Button(
            row, text="×", bg=bg, fg=t.get("danger", _RED),
            activebackground=bg, activeforeground=t.get("danger", _RED),
            font=("Segoe UI", 12, "bold"), relief="flat", cursor="hand2",
            command=lambda p=path: self._remove(p),
        )
        x_btn.pack(side="right")
        entry = {"path_obj": path, "row": row, "icon": icon,
                 "path": path_lbl, "x": x_btn}
        self._rows.append(entry)
        self._paint_row(entry)

    def _remove(self, path: Path) -> None:
        if path in self._folders:
            self._folders.remove(path)
        for r in list(self._rows):
            if r["path_obj"] == path:
                r["row"].destroy()
                self._rows.remove(r)
                break
        if self._on_changed:
            self._on_changed(list(self._folders))

    def clear_all(self) -> None:
        self._folders.clear()
        for r in self._rows:
            r["row"].destroy()
        self._rows.clear()
        if self._on_changed:
            self._on_changed([])

    def paste_path(self) -> None:
        """Paste one or more folder paths from the clipboard.

        Handles the real-world shapes users actually copy:
          - Windows "Copy as path" wraps the path in double quotes.
          - Multi-select "Copy as path" produces one quoted path per line.
          - Users sometimes paste a file path; we add its parent folder.
        Shows a short info popup if nothing usable was found, instead of
        silently doing nothing.
        """
        try:
            raw = self.clipboard_get()
        except tk.TclError:
            raw = ""
        if not raw:
            try:
                from tkinter import messagebox
                messagebox.showinfo(
                    "Paste Path",
                    "Clipboard is empty or does not contain text.",
                )
            except tk.TclError:
                pass
            return

        added = 0
        seen: set = set()
        for line in raw.splitlines():
            candidate = line.strip().strip('"').strip("'").strip()
            if not candidate or candidate in seen:
                continue
            seen.add(candidate)
            try:
                p = Path(candidate)
            except (OSError, ValueError):
                continue
            target: Optional[Path] = None
            try:
                if p.is_dir():
                    target = p
                elif p.is_file():
                    target = p.parent
            except OSError:
                target = None
            if target is not None:
                before = len(self._folders)
                self.add(target)
                if len(self._folders) > before:
                    added += 1

        if added == 0:
            try:
                from tkinter import messagebox
                messagebox.showinfo(
                    "Paste Path",
                    "Clipboard does not contain a valid folder or file path.\n\n"
                    "Tip: in Windows Explorer, right-click a folder and choose "
                    "\u201cCopy as path\u201d, then try again.",
                )
            except tk.TclError:
                pass

    def get_folders(self) -> List[Path]:
        return list(self._folders)

    def on_changed(self, cb: Callable[[List[Path]], None]) -> None:
        self._on_changed = cb


class _DropZone(tk.Frame):
    """Dashed-border drop zone displayed in the folder list when it is empty."""

    def __init__(self, master, t: dict, on_add: Callable, **kwargs) -> None:
        bg = t.get("bg", _WHITE)
        kwargs.setdefault("bg", bg)
        super().__init__(master, **kwargs)
        self._t     = t
        self._on_add = on_add
        self._build()

    def _build(self) -> None:
        self._canvas = tk.Canvas(
            self, bg=self._t.get("bg", _WHITE),
            highlightthickness=0, bd=0,
            width=260, height=150,
        )
        self._canvas.pack(pady=24, padx=24)
        self._canvas.bind("<Configure>", lambda _e: self._draw())
        self._canvas.bind("<Button-1>", lambda _e: self._on_add())
        self._canvas.configure(cursor="hand2")
        self._draw()

    def _draw(self) -> None:
        c = self._canvas
        c.delete("all")
        w = c.winfo_width() or 260
        h = c.winfo_height() or 150
        t       = self._t
        bg      = t.get("bg",       _WHITE)
        border  = t.get("border",   _BORDER)
        fg_mute = t.get("fg_muted", _DIMGRAY)
        fg      = t.get("fg",       "#333333")
        c.configure(bg=bg)
        pad = 10
        c.create_rectangle(
            pad, pad, w - pad, h - pad,
            outline=border, dash=(6, 4), width=2,
        )
        cx, cy = w // 2, h // 2 - 14
        c.create_text(cx, cy, text="📂",
                      font=("Segoe UI", 24), fill=fg_mute)
        c.create_text(cx, cy + 34, text="Drop folders here",
                      font=("Segoe UI", 10, "bold"), fill=fg)
        c.create_text(cx, cy + 50, text="or click to browse",
                      font=("Segoe UI", 9), fill=fg_mute)

    def apply_theme(self, t: dict) -> None:
        self._t = t
        self.configure(bg=t.get("bg", _WHITE))
        self._draw()

    def try_register_dnd(self, on_drop: Callable[[str], None]) -> None:
        """Register as DnD drop target if tkinterdnd2 is available; logs at debug otherwise.

        Requires `TkinterDnD._require(root)` to have been called during app
        startup (see AppShell._bootstrap_tkdnd); otherwise the underlying
        tkdnd Tcl commands are not loaded and registration will fail.
        """
        try:
            import tkinterdnd2 as _dnd  # type: ignore[import]
            self._canvas.drop_target_register(_dnd.DND_FILES)  # type: ignore[attr-defined]
            self._canvas.dnd_bind("<<Drop>>", lambda e: on_drop(e.data))  # type: ignore[attr-defined]
        except (ImportError, AttributeError, tk.TclError) as e:
            _log.debug("drop-zone DnD registration failed: %s", e)


class _SuggestionsFooter(tk.Frame):
    """Slim 24 px footer showing only '+ Send suggestions'. No action buttons."""

    HEIGHT = 24

    def __init__(self, master, **kwargs) -> None:
        t = ThemeApplicator.get().build_tokens()
        kwargs.setdefault("bg",     t.get("nav_bar", _NAVY_BAR))
        kwargs.setdefault("height", self.HEIGHT)
        super().__init__(master, **kwargs)
        self.pack_propagate(False)
        self._t = t
        self._build()

    def _build(self) -> None:
        nav = self._t.get("nav_bar", _NAVY_BAR)
        self._top_border = tk.Frame(self, bg=self._t.get("border", _BORDER), height=1)
        self._top_border.pack(side="top", fill="x")
        self._lbl = tk.Label(
            self, text="+ Send suggestions",
            bg=nav, fg="#7A9EC0",
            font=("Segoe UI", 9), cursor="hand2",
        )
        self._lbl.pack(side="right", padx=12)

    def apply_theme(self, t: dict) -> None:
        self._t = t
        nav = t.get("nav_bar", _NAVY_BAR)
        self.configure(bg=nav)
        self._top_border.configure(bg=t.get("border", _BORDER))
        self._lbl.configure(bg=nav, fg=t.get("fg_muted", _DIMGRAY))


# ===========================================================================
# ScanPage
#
# The in-page scan progress view is the shared ScanInProgressView widget
# (cerebro/v2/ui/widgets/scan_in_progress_view.py). The previous local
# _ScanProgressView class was retired during the post-v1 audit in favour of
# the richer styled view also used by ResultsPanel.
# ===========================================================================

class _EngineWarningBanner(tk.Frame):
    """Slim yellow banner shown above the scan area when the selected
    mode's engine is in a non-AVAILABLE state.

    Visible states surfaced here:

    * ``MISSING_DEPS``  — "Install <pip_hint> to enable this mode"
    * ``DEGRADED``      — "Scan will run with reduced quality because …"
    * ``RUNTIME_ERROR`` — "This engine failed to load — see Diagnostics"
    * ``NOT_IMPLEMENTED`` — purely informational; the mode shouldn't even
      appear in ``_SCAN_MODES`` today, but we handle the case defensively.

    The banner also exposes a "Copy install command" button when a
    ``pip_hint`` is available, so the user can paste it into a terminal
    without retyping.
    """

    _BG     = "#FFF8DC"  # soft yellow (cornsilk) — visible but not alarming
    _FG     = "#5A4A00"
    _BORDER = "#E0C860"

    def __init__(self, parent: tk.Widget) -> None:
        super().__init__(parent, bg=self._BG, highlightthickness=1,
                         highlightbackground=self._BORDER)
        self._pip_hint: Optional[str] = None
        self._icon_lbl = tk.Label(
            self, text="⚠", bg=self._BG, fg=self._FG,
            font=("Segoe UI", 14, "bold"),
        )
        self._icon_lbl.pack(side="left", padx=(14, 6), pady=6)
        self._text_lbl = tk.Label(
            self, text="", bg=self._BG, fg=self._FG,
            font=("Segoe UI", 11), anchor="w", justify="left",
        )
        self._text_lbl.pack(side="left", padx=(0, 10), pady=6, fill="x", expand=True)
        self._copy_btn = tk.Button(
            self, text="Copy install command", command=self._copy_hint,
            bg="#FFFFFF", fg=self._FG, activebackground="#F5E8B5",
            activeforeground=self._FG, relief="flat",
            font=("Segoe UI", 10), cursor="hand2", padx=10, pady=3,
            borderwidth=1,
        )
        # Copy button packed conditionally in ``show``.

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def show(self, message: str, pip_hint: Optional[str]) -> None:
        self._text_lbl.configure(text=message)
        self._pip_hint = pip_hint
        self._copy_btn.pack_forget()
        if pip_hint:
            self._copy_btn.pack(side="right", padx=(0, 12), pady=6)

    def hide(self) -> None:
        self._text_lbl.configure(text="")
        self._pip_hint = None
        self._copy_btn.pack_forget()

    def apply_theme(self, _t: dict) -> None:
        # The banner is intentionally theme-invariant: yellow warning
        # colouring is meaningful regardless of light/dark theme, and
        # mirrors the Diagnostics page's 'warning' dot.
        return

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _copy_hint(self) -> None:
        if not self._pip_hint:
            return
        try:
            self.clipboard_clear()
            self.clipboard_append(self._pip_hint)
            self.update_idletasks()
        except tk.TclError:
            _log.exception("ScanPage banner: failed to copy to clipboard")
            return
        prev = self._copy_btn.cget("text")
        self._copy_btn.configure(text="Copied!")
        self.after(1200, lambda: self._restore_copy_label(prev))

    def _restore_copy_label(self, text: str) -> None:
        try:
            self._copy_btn.configure(text=text)
        except tk.TclError:
            pass


class ScanPage(tk.Frame):
    """
    Full scan configuration page.

    on_scan_complete(results, mode) is called after a successful scan.
    ``mode`` is the scan mode key (``"files"`` / ``"photos"`` / ``"videos"``
    / ``"music"`` / ``"empty_folders"`` / ``"large_files"``) — consumed
    downstream by ResultsPage to label the delete ceremony's media noun.
    """

    def __init__(
        self,
        master,
        orchestrator: Any,
        on_scan_complete: Optional[Callable[[list, str], None]] = None,
        **kwargs,
    ) -> None:
        initial = ThemeApplicator.get().build_tokens()
        kwargs.setdefault("bg", initial.get("bg", _WHITE))
        super().__init__(master, **kwargs)
        self._orchestrator     = orchestrator
        self._on_scan_complete = on_scan_complete
        self._scanning         = False
        self._scan_start_time  = 0.0
        self._current_mode     = "files"
        self._t: dict = initial
        self._build()
        self._apply_theme(initial)
        ThemeApplicator.get().register(self._apply_theme)

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _build(self) -> None:
        # ── Left: folder tree ────────────────────────────────────────
        self._tree = _FolderTree(self)
        self._tree.pack(side="left", fill="y")

        # 1 px vertical divider
        self._v_divider = tk.Frame(self, bg=_BORDER, width=1)
        self._v_divider.pack(side="left", fill="y")

        # ── Right: config area ───────────────────────────────────────
        self._right_col = tk.Frame(self, bg=_WHITE)
        self._right_col.pack(side="left", fill="both", expand=True)

        # Mode bar
        self._mode_bar = _ScanModeBar(
            self._right_col,
            on_mode=self._on_mode_changed,
            on_start=self._start_scan,
            on_stop=self._stop_scan,
        )
        self._mode_bar.pack(fill="x")

        # Config sub-tabs strip
        self._sub_tab_bar = self._build_sub_tab_bar(self._right_col)
        self._sub_tab_bar.pack(fill="x")
        self._sub_tab_border = tk.Frame(self._right_col, bg=_BORDER, height=1)
        self._sub_tab_border.pack(fill="x")

        # Engine-status warning banner (Phase 7). Hidden by default; shown
        # when the currently selected mode's engine is not AVAILABLE.
        self._engine_banner = _EngineWarningBanner(self._right_col)
        # Evaluate once for the default mode so the banner state is correct
        # before the user even interacts with the mode bar.
        self._refresh_engine_banner(self._current_mode)

        # Content area — sub-tab frames stacked
        self._content = tk.Frame(self._right_col, bg=_WHITE)
        self._content.pack(fill="both", expand=True)

        self._folders_list = _SearchFoldersList(self._content, tree=self._tree)
        self._folders_list.place(relwidth=1, relheight=1)
        self._tree.on_activate(self._folders_list.add)

        self._progress_view = ScanInProgressView(
            self._content, on_cancel=self._stop_scan
        )

        # Slim footer (pinned to bottom of right column) — suggestions link only
        self._suggestions_footer = _SuggestionsFooter(self._right_col)
        self._suggestions_footer.pack(side="bottom", fill="x")

    def _build_sub_tab_bar(self, parent: tk.Frame) -> tk.Frame:
        bar = tk.Frame(parent, bg=_SURFACE, height=32)
        bar.pack_propagate(False)
        self._sub_tabs: Dict[str, _SubTab] = {}
        self._active_sub = "search_folders"
        for key, lbl in [("search_folders", "Search Folders"),
                          ("exclude",        "Exclude"),
                          ("protect",        "Protect"),
                          ("filters",        "Filters")]:
            tab = _SubTab(bar, key, lbl, on_click=self._on_sub_tab)
            tab.pack(side="left", fill="y")
            self._sub_tabs[key] = tab
        self._sub_tabs["search_folders"].set_active(True)
        return bar

    # ------------------------------------------------------------------
    # Sub-tab switching
    # ------------------------------------------------------------------

    def _on_sub_tab(self, key: str) -> None:
        if key == self._active_sub:
            return
        self._sub_tabs[self._active_sub].set_active(False)
        self._active_sub = key
        self._sub_tabs[key].set_active(True)
        self._folders_list.place_forget()
        self._progress_view.place_forget()
        if key == "search_folders" and not self._scanning:
            self._folders_list.place(relwidth=1, relheight=1)

    # ------------------------------------------------------------------
    # Mode
    # ------------------------------------------------------------------

    def _on_mode_changed(self, key: str) -> None:
        self._current_mode = key
        try:
            self._orchestrator.set_mode(key)
        except (ValueError, AttributeError):
            pass
        self._refresh_engine_banner(key)

    # ------------------------------------------------------------------
    # Engine banner / pre-scan check (Phase 7)
    # ------------------------------------------------------------------

    def _refresh_engine_banner(self, mode_key: str) -> None:
        """Probe the engine backing ``mode_key`` and show/hide the warning
        banner. Safe to call before ``_content`` exists (during _build)."""
        banner = getattr(self, "_engine_banner", None)
        if banner is None:
            return
        try:
            probe = probe_mode(mode_key)
        except Exception:
            _log.exception("Engine probe raised for mode %s", mode_key)
            probe = None

        if probe is None or probe.state is EngineState.AVAILABLE:
            banner.hide()
            try:
                banner.pack_forget()
            except tk.TclError:
                pass
            return

        message = self._compose_banner_message(probe.state, probe.detail)
        banner.show(message, probe.pip_hint)
        # Insert the banner between the sub-tab border and the content area.
        try:
            content = getattr(self, "_content", None)
            if content is not None:
                banner.pack(fill="x", before=content)
            else:
                banner.pack(fill="x")
        except tk.TclError:
            pass

    @staticmethod
    def _compose_banner_message(state: EngineState, detail: str) -> str:
        if state is EngineState.MISSING_DEPS:
            return f"This scan mode needs a package that isn't installed: {detail}"
        if state is EngineState.DEGRADED:
            return f"This scan mode will run with reduced capability — {detail}"
        if state is EngineState.RUNTIME_ERROR:
            return f"This scan mode failed to load: {detail}. See Diagnostics for details."
        if state is EngineState.NOT_IMPLEMENTED:
            return "This scan mode is planned for a future release."
        return detail

    # ------------------------------------------------------------------
    # Scan lifecycle
    # ------------------------------------------------------------------

    def _start_scan(self) -> None:
        folders = self._folders_list.get_folders()
        if not folders:
            # Fall back to file dialog if no folders added
            path = filedialog.askdirectory(title="Select folder to scan")
            if not path:
                return
            folders = [Path(path)]
            self._folders_list.add(folders[0])

        # Phase-7 pre-scan gate: if the selected mode's engine is in a
        # non-AVAILABLE state, ask the user to confirm before proceeding.
        # DEGRADED means "will run, but worse" — surface the detail.
        # MISSING_DEPS / RUNTIME_ERROR / NOT_IMPLEMENTED means "will likely
        # fail or produce no results" — we still let the user proceed
        # (they might want to confirm the failure for themselves).
        if not self._confirm_non_available_engine():
            return

        self._scanning = True
        self._scan_start_time = time.time()
        self._mode_bar.set_scanning(True)
        self._show_progress()

        try:
            self._orchestrator.set_mode(self._current_mode)
            self._orchestrator.start_scan(
                folders=folders,
                protected=[],
                options={},
                progress_callback=self._on_progress,
            )
        except Exception:
            self._finish_scan(ScanState.ERROR)

    def _stop_scan(self) -> None:
        try:
            self._orchestrator.cancel()
        except Exception:
            pass

    def _confirm_non_available_engine(self) -> bool:
        """Return True if the user wants to proceed despite a
        non-AVAILABLE engine state (or if the engine is AVAILABLE)."""
        try:
            probe = probe_mode(self._current_mode)
        except Exception:
            _log.exception("Pre-scan probe raised for %s", self._current_mode)
            return True
        if probe is None or probe.state is EngineState.AVAILABLE:
            return True

        from tkinter import messagebox
        title_map = {
            EngineState.MISSING_DEPS:    "Scan engine missing dependencies",
            EngineState.DEGRADED:        "Scan engine running degraded",
            EngineState.RUNTIME_ERROR:   "Scan engine failed to load",
            EngineState.NOT_IMPLEMENTED: "Scan engine not implemented",
        }
        title = title_map.get(probe.state, "Scan engine issue")
        body = self._compose_banner_message(probe.state, probe.detail)
        body += "\n\nProceed with the scan anyway?"
        try:
            return bool(messagebox.askokcancel(title, body, parent=self))
        except tk.TclError:
            return True

    def _on_progress(self, progress: ScanProgress) -> None:
        """Called from engine thread — marshal to main thread."""
        self.after(0, lambda p=progress: self._handle_progress(p))

    def _handle_progress(self, progress: ScanProgress) -> None:
        elapsed = time.time() - self._scan_start_time
        self._progress_view.update_progress(
            stage=progress.stage or "",
            files_scanned=progress.files_scanned,
            files_total=progress.files_total,
            elapsed_seconds=elapsed,
            current_file=progress.current_file or "",
        )
        if progress.state in (ScanState.COMPLETED, ScanState.CANCELLED, ScanState.ERROR):
            self.after(0, lambda s=progress.state: self._finish_scan(s))

    def _finish_scan(self, state: ScanState) -> None:
        self._scanning = False
        self._mode_bar.set_scanning(False)
        self._hide_progress()

        if state == ScanState.COMPLETED:
            results = self._orchestrator.get_results()
            # Bug: scan counter stuck at 49. Investigation
            # (docs/bug-investigations/phase3_guard_order.log) correctly
            # diagnosed the INSERT never firing; the log's canonical-chokepoint
            # line was HistoryRecorder on the old single-window host; AppShell uses scan_page hooks
            # in 39a332c and the AppShell/ScanPage path was left with no
            # history recording at all. Broad catch + logger.exception so any
            # future failure surfaces once instead of being swallowed.
            try:
                from cerebro.v2.ui.scan_history_dialog import record_scan

                folders = self._folders_list.get_folders()
                record_scan(
                    mode=self._current_mode,
                    folders=[str(f) for f in folders],
                    groups_found=len(results),
                    files_found=sum(len(g.files) for g in results),
                    bytes_reclaimable=sum(g.reclaimable for g in results),
                    duration_seconds=max(0.0, time.time() - self._scan_start_time),
                )
            except Exception:
                _log.exception("Failed to record scan history entry")

            if self._on_scan_complete:
                self._on_scan_complete(results, self._current_mode)

    def _show_progress(self) -> None:
        self._folders_list.place_forget()
        self._progress_view.reset()
        self._progress_view.place(relwidth=1, relheight=1)

    def _hide_progress(self) -> None:
        self._progress_view.place_forget()
        self._folders_list.place(relwidth=1, relheight=1)

    # ------------------------------------------------------------------
    # Theme

    def _apply_theme(self, t: dict) -> None:
        self._t = t
        bg      = t.get("bg",     _WHITE)
        bg2     = t.get("bg2",    _SURFACE)
        border  = t.get("border", _BORDER)
        self.configure(bg=bg)
        try:
            self._right_col.configure(bg=bg)
        except tk.TclError:
            pass
        try:
            self._v_divider.configure(bg=border)
        except tk.TclError:
            pass
        try:
            self._sub_tab_bar.configure(bg=bg2)
        except tk.TclError:
            pass
        try:
            self._sub_tab_border.configure(bg=border)
        except tk.TclError:
            pass
        try:
            self._content.configure(bg=bg)
        except tk.TclError:
            pass
        try:
            self._tree.apply_theme(t)
        except tk.TclError:
            pass
        try:
            self._mode_bar.apply_theme(t)
        except tk.TclError:
            pass
        for tab in getattr(self, "_sub_tabs", {}).values():
            try:
                tab.apply_theme(t)
            except tk.TclError:
                pass
        try:
            self._folders_list.apply_theme(t)
        except tk.TclError:
            pass
        try:
            self._progress_view.apply_theme(t)
        except tk.TclError:
            pass
        try:
            self._suggestions_footer.apply_theme(t)
        except tk.TclError:
            pass
        try:
            self._engine_banner.apply_theme(t)
        except tk.TclError:
            pass

    # ------------------------------------------------------------------
    # Public API

    def add_folder(self, path: Path) -> None:
        self._folders_list.add(path)

    def get_folders(self) -> List[Path]:
        return self._folders_list.get_folders()
