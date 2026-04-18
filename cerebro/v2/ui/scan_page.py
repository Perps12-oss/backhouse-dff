"""
ScanPage — full-viewport scan configuration page.

Left (280 px):  folder tree with lazy-loading (off main thread).
Right (rest):   mode bar · config sub-tabs · action bar.
                During scan: sub-tab content is replaced by progress view.
"""
from __future__ import annotations

import os
import string
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk
from typing import Any, Callable, Dict, List, Optional

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
from cerebro.v2.ui.theme_applicator import ThemeApplicator

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
    """Scrollable list of folders added to the scan."""

    def __init__(self, master, **kwargs) -> None:
        t = ThemeApplicator.get().build_tokens()
        kwargs.setdefault("bg", t.get("bg", _WHITE))
        super().__init__(master, **kwargs)
        self._folders: List[Path] = []
        self._on_changed: Optional[Callable[[List[Path]], None]] = None
        self._t = t
        self._rows: List[Dict[str, tk.Widget]] = []
        self._build()

    def _build(self) -> None:
        bg = self._t.get("bg", _WHITE)
        self._canvas = tk.Canvas(self, bg=bg, highlightthickness=0)
        vsb = ttk.Scrollbar(self, orient="vertical", command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self._canvas.pack(fill="both", expand=True)

        self._inner = tk.Frame(self._canvas, bg=bg)
        self._win = self._canvas.create_window((0, 0), window=self._inner,
                                               anchor="nw")
        self._inner.bind("<Configure>", self._on_inner_configure)
        self._canvas.bind("<Configure>", self._on_canvas_configure)
        self._canvas.bind("<MouseWheel>",
                          lambda e: self._canvas.yview_scroll(-1 * (e.delta // 120), "units"))

        self._empty_lbl = tk.Label(
            self._inner,
            text="No folders added yet.\nSelect from the tree or use Add Folders below.",
            bg=bg, fg=self._t.get("fg_muted", _DIMGRAY),
            font=("Segoe UI", 10), justify="center",
        )
        self._empty_lbl.pack(expand=True, pady=40)

    def apply_theme(self, t: dict) -> None:
        self._t = t
        bg = t.get("bg", _WHITE)
        self.configure(bg=bg)
        self._canvas.configure(bg=bg)
        self._inner.configure(bg=bg)
        self._empty_lbl.configure(bg=bg, fg=t.get("fg_muted", _DIMGRAY))
        for r in self._rows:
            self._paint_row(r)

    def _paint_row(self, r: Dict[str, tk.Widget]) -> None:
        t = self._t
        bg  = t.get("bg",     _WHITE)
        fg  = t.get("fg",     "#333333")
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
        self._empty_lbl.pack_forget()
        self._render_row(path)
        if self._on_changed:
            self._on_changed(list(self._folders))

    def _render_row(self, path: Path) -> None:
        t = self._t
        bg = t.get("bg", _WHITE)
        row = tk.Frame(self._inner, bg=bg)
        row.pack(fill="x", padx=8, pady=2)

        icon = tk.Label(row, text="📁", bg=bg, fg="#F0A500",
                        font=("Segoe UI", 12))
        icon.pack(side="left", padx=(0, 6))
        path_lbl = tk.Label(row, text=str(path), bg=bg,
                            fg=t.get("fg", "#333333"),
                            font=("Segoe UI", 10), anchor="w")
        path_lbl.pack(side="left", fill="x", expand=True)
        x_btn = tk.Button(row, text="×", bg=bg, fg=t.get("danger", _RED),
                          activebackground=bg, activeforeground=t.get("danger", _RED),
                          font=("Segoe UI", 12, "bold"),
                          relief="flat", cursor="hand2",
                          command=lambda p=path: self._remove(p))
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
        if not self._folders:
            self._empty_lbl.pack(expand=True, pady=40)
        if self._on_changed:
            self._on_changed(list(self._folders))

    def clear_all(self) -> None:
        self._folders.clear()
        for r in self._rows:
            r["row"].destroy()
        self._rows.clear()
        self._empty_lbl.pack(expand=True, pady=40)
        if self._on_changed:
            self._on_changed([])

    def paste_path(self) -> None:
        try:
            raw = self.clipboard_get()
            p = Path(raw.strip())
            if p.is_dir():
                self.add(p)
        except Exception:
            pass

    def get_folders(self) -> List[Path]:
        return list(self._folders)

    def on_changed(self, cb: Callable[[List[Path]], None]) -> None:
        self._on_changed = cb


class _ActionBar(tk.Frame):
    """40 px navy action bar: ADD FOLDERS | PASTE PATH | CLEAR ALL | OPEN | SAVE."""

    def __init__(self, master, folders_list: _SearchFoldersList,
                 tree: _FolderTree, **kwargs) -> None:
        kwargs.setdefault("bg", _NAVY_BAR)
        kwargs.setdefault("height", 40)
        super().__init__(master, **kwargs)
        self.pack_propagate(False)
        self._folders_list = folders_list
        self._tree         = tree
        self._build()

    def _build(self) -> None:
        def _btn(text: str, cmd) -> tk.Button:
            b = tk.Button(
                self, text=text, bg=_NAVY_BAR, fg=_WHITE,
                font=("Segoe UI", 9), relief="flat",
                padx=10, pady=0, cursor="hand2",
                activebackground="#3A6BAE", activeforeground=_WHITE,
                command=cmd,
            )
            b.pack(side="left", fill="y", padx=1)
            b.bind("<Enter>", lambda _e: b.configure(bg="#3A6BAE"))
            b.bind("<Leave>", lambda _e: b.configure(bg=_NAVY_BAR))
            return b

        _btn("ADD FOLDERS", self._add_folders)
        _btn("PASTE PATH",  self._paste_path)
        _btn("CLEAR ALL",   self._clear_all)

        # Right side
        tk.Label(self, text="+ Send suggestions", bg=_NAVY_BAR,
                 fg="#7A9EC0", font=("Segoe UI", 9)).pack(side="right", padx=12)

    def apply_theme(self, t: dict) -> None:
        nav = t.get("nav_bar", _NAVY_BAR)
        acc = t.get("accent", _NAVY_MID)
        self.configure(bg=nav)
        for w in self.winfo_children():
            try:
                if isinstance(w, tk.Button):
                    w.configure(bg=nav, activebackground=acc)
                elif isinstance(w, tk.Frame):
                    w.configure(bg=nav)
                elif isinstance(w, tk.Label):
                    w.configure(bg=nav)
            except Exception:
                pass

    def _add_folders(self) -> None:
        sel = self._tree.get_selected()
        if sel:
            self._folders_list.add(sel)
        else:
            path = filedialog.askdirectory(title="Select folder to scan")
            if path:
                self._folders_list.add(Path(path))

    def _paste_path(self) -> None:
        self._folders_list.paste_path()

    def _clear_all(self) -> None:
        self._folders_list.clear_all()


class _ScanProgressView(tk.Frame):
    """Shown in the config area while a scan is running."""

    def __init__(self, master, **kwargs) -> None:
        t = ThemeApplicator.get().build_tokens()
        kwargs.setdefault("bg", t.get("bg", _WHITE))
        super().__init__(master, **kwargs)
        self._t = t
        self._build()

    def _build(self) -> None:
        bg = self._t.get("bg", _WHITE)
        self._outer = tk.Frame(self, bg=bg)
        self._outer.place(relx=0.5, rely=0.4, anchor="center")

        # Progress bar
        if CTkProgressBar is not None:
            self._pbar = CTkProgressBar(
                self._outer, width=400, height=12,
                progress_color=self._t.get("accent", _NAVY_MID),
            )
            self._pbar.pack(pady=(0, 16))
            self._pbar.set(0)
            self._use_ctk = True
        else:
            canvas = tk.Canvas(
                self._outer, width=400, height=12,
                bg=self._t.get("border", "#E0E0E0"), highlightthickness=0,
            )
            canvas.pack(pady=(0, 16))
            self._pbar_canvas = canvas
            self._use_ctk = False

        self._status_lbl = tk.Label(
            self._outer, text="Preparing scan…",
            bg=bg, fg=self._t.get("fg", "#333333"), font=("Segoe UI", 12),
        )
        self._status_lbl.pack()

        self._file_lbl = tk.Label(
            self._outer, text="", bg=bg,
            fg=self._t.get("fg_muted", _DIMGRAY), font=("Segoe UI", 9),
            wraplength=420,
        )
        self._file_lbl.pack(pady=(4, 0))

        self._elapsed_lbl = tk.Label(
            self._outer, text="", bg=bg,
            fg=self._t.get("fg_muted", _DIMGRAY), font=("Segoe UI", 9),
        )
        self._elapsed_lbl.pack(pady=(2, 0))

    def apply_theme(self, t: dict) -> None:
        self._t = t
        bg     = t.get("bg",        _WHITE)
        fg     = t.get("fg",        "#333333")
        muted  = t.get("fg_muted",  _DIMGRAY)
        accent = t.get("accent",    _NAVY_MID)
        border = t.get("border",    "#E0E0E0")
        self.configure(bg=bg)
        self._outer.configure(bg=bg)
        self._status_lbl.configure(bg=bg, fg=fg)
        self._file_lbl.configure(bg=bg, fg=muted)
        self._elapsed_lbl.configure(bg=bg, fg=muted)
        if self._use_ctk:
            try:
                self._pbar.configure(progress_color=accent)
            except Exception:
                pass
        else:
            try:
                self._pbar_canvas.configure(bg=border)
            except Exception:
                pass

    def update(self, files_scanned: int, files_total: int,
               stage: str, elapsed: float, current_file: str = "") -> None:
        pct = (files_scanned / files_total) if files_total > 0 else 0.0
        pct = min(1.0, max(0.0, pct))

        if self._use_ctk:
            self._pbar.set(pct)
        else:
            w = self._pbar_canvas.winfo_width() or 400
            self._pbar_canvas.delete("all")
            self._pbar_canvas.create_rectangle(
                0, 0, int(w * pct), 12,
                fill=self._t.get("accent", _NAVY_MID), outline="")

        if files_total > 0:
            self._status_lbl.configure(
                text=f"Scanning… {files_scanned:,} / {files_total:,} files")
        else:
            self._status_lbl.configure(text=stage or "Scanning…")

        if current_file:
            self._file_lbl.configure(
                text=Path(current_file).name[:60])

        mins, secs = divmod(int(elapsed), 60)
        self._elapsed_lbl.configure(
            text=f"Elapsed: {mins}m {secs:02d}s" if mins else f"Elapsed: {secs}s")

    def reset(self) -> None:
        if self._use_ctk:
            self._pbar.set(0)
        self._status_lbl.configure(text="Preparing scan…")
        self._file_lbl.configure(text="")
        self._elapsed_lbl.configure(text="")


# ===========================================================================
# ScanPage
# ===========================================================================

class ScanPage(tk.Frame):
    """
    Full scan configuration page.

    on_scan_complete(results) is called after a successful scan.
    """

    def __init__(
        self,
        master,
        orchestrator: Any,
        on_scan_complete: Optional[Callable[[list], None]] = None,
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

        # Content area — sub-tab frames stacked
        self._content = tk.Frame(self._right_col, bg=_WHITE)
        self._content.pack(fill="both", expand=True)

        self._folders_list = _SearchFoldersList(self._content)
        self._folders_list.place(relwidth=1, relheight=1)

        self._progress_view = _ScanProgressView(self._content)

        # Action bar (pinned to bottom of right column)
        self._action_bar = _ActionBar(self._right_col, self._folders_list, self._tree)
        self._action_bar.pack(side="bottom", fill="x")

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
        # Only Search Folders has real content; others are stubs for now
        if key == "search_folders":
            self._progress_view.place_forget()
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

    def _on_progress(self, progress: ScanProgress) -> None:
        """Called from engine thread — marshal to main thread."""
        self.after(0, lambda p=progress: self._handle_progress(p))

    def _handle_progress(self, progress: ScanProgress) -> None:
        elapsed = time.time() - self._scan_start_time
        self._progress_view.update(
            files_scanned=progress.files_scanned,
            files_total=progress.files_total,
            stage=progress.stage or "",
            elapsed=elapsed,
            current_file=progress.current_file or "",
        )
        if progress.state in (ScanState.COMPLETED, ScanState.CANCELLED, ScanState.ERROR):
            self.after(0, lambda s=progress.state: self._finish_scan(s))

    def _finish_scan(self, state: ScanState) -> None:
        self._scanning = False
        self._mode_bar.set_scanning(False)
        self._hide_progress()

        if state == ScanState.COMPLETED and self._on_scan_complete:
            results = self._orchestrator.get_results()
            self._on_scan_complete(results)

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
            self._action_bar.apply_theme(t)
        except tk.TclError:
            pass

    # ------------------------------------------------------------------
    # Public API

    def add_folder(self, path: Path) -> None:
        self._folders_list.add(path)

    def get_folders(self) -> List[Path]:
        return self._folders_list.get_folders()
