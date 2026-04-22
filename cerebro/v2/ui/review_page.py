"""
ReviewPage — full-viewport focus on a single duplicate group.

Left (~55%):  breadcrumb · large preview · action buttons
Right (~45%): copy list (all files in group) · group navigation
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from typing import Callable, List, Optional

try:
    import customtkinter as ctk
    CTkFrame = ctk.CTkFrame
    CTkLabel = ctk.CTkLabel
    CTkButton = ctk.CTkButton
except ImportError:
    CTkFrame  = tk.Frame   # type: ignore[misc,assignment]
    CTkLabel  = tk.Label   # type: ignore[misc,assignment]
    CTkButton = tk.Button  # type: ignore[misc,assignment]

from cerebro.engines.base_engine import DuplicateGroup, DuplicateFile
from cerebro.v2.ui.theme_applicator import ThemeApplicator

# ---------------------------------------------------------------------------
# Tokens
# ---------------------------------------------------------------------------
_WHITE     = "#FFFFFF"
_F8        = "#F8F8F8"
_BORDER    = "#E0E0E0"
_NAVY_MID  = "#1E3A5F"
_RED       = "#E74C3C"
_GREEN     = "#27AE60"
_GRAY      = "#666666"
_DIMGRAY   = "#AAAAAA"
_W70       = "#B0BEC8"   # white 70 % on navy — breadcrumb filename

_IMAGE_EXT = {".jpg",".jpeg",".png",".gif",".bmp",".webp",".tiff",".tif",
              ".heic",".heif",".cr2",".cr3",".nef",".arw",".dng"}
_VIDEO_EXT = {".mp4",".avi",".mkv",".mov",".wmv",".flv",".webm",".m4v"}

# File-type icons (large text fallback)
_TYPE_ICONS = {
    "image":    "🖼",
    "video":    "🎬",
    "audio":    ".🎵",
    "document": "📄",
    "archive":  "📦",
    "other":    "📎",
}


def _file_type(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in _IMAGE_EXT:      return "image"
    if ext in _VIDEO_EXT:      return "video"
    if ext in {".mp3",".flac",".ogg",".wav",".aac",".m4a",".wma"}: return "audio"
    if ext in {".pdf",".doc",".docx",".xls",".xlsx",".txt",".ppt",".pptx"}: return "document"
    if ext in {".zip",".rar",".7z",".tar",".gz",".bz2"}: return "archive"
    return "other"


def _fmt_size(n: int) -> str:
    if n < 1024:       return f"{n} B"
    if n < 1024**2:    return f"{n/1024:.1f} KB"
    if n < 1024**3:    return f"{n/1024**2:.1f} MB"
    return             f"{n/1024**3:.1f} GB"


def _fmt_date(ts: float) -> str:
    if not ts:
        return "—"
    from datetime import datetime
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return "—"


def _open_in_explorer(path: Path) -> None:
    try:
        folder = path.parent if path.is_file() else path
        if sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", str(path)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(folder)])
        else:
            subprocess.Popen(["xdg-open", str(folder)])
    except Exception:
        pass


def _open_default(path: Path) -> None:
    try:
        if sys.platform == "win32":
            os.startfile(str(path))
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except Exception:
        pass


# ===========================================================================
# Breadcrumb bar
# ===========================================================================

class _BreadcrumbBar(tk.Frame):
    H = 32

    def __init__(self, master, on_back: Callable, **kw) -> None:
        kw.setdefault("bg", _NAVY_MID)
        kw.setdefault("height", self.H)
        super().__init__(master, **kw)
        self.pack_propagate(False)
        self._on_back = on_back
        self._build()

    def _build(self) -> None:
        back = tk.Label(self, text="← Back to Results", bg=_NAVY_MID,
                        fg=_WHITE, font=("Segoe UI", 10), cursor="hand2")
        back.pack(side="left", padx=12)
        back.bind("<Button-1>", lambda _e: self._on_back())

        self._group_lbl = tk.Label(self, text="", bg=_NAVY_MID,
                                   fg=_WHITE, font=("Segoe UI", 10))
        self._group_lbl.place(relx=0.5, rely=0.5, anchor="center")

        self._file_lbl = tk.Label(self, text="", bg=_NAVY_MID,
                                  fg=_W70, font=("Segoe UI", 9))
        self._file_lbl.pack(side="right", padx=12)

    def apply_theme(self, t: dict) -> None:
        bg = t.get("nav_bar", _NAVY_MID)
        self.configure(bg=bg)
        for w in self.winfo_children():
            try:
                w.configure(bg=bg)
            except Exception:
                pass

    def update(self, group_idx: int, total: int, filename: str) -> None:
        self._group_lbl.configure(text=f"Group {group_idx + 1} of {total}")
        name = filename if len(filename) <= 35 else "…" + filename[-33:]
        self._file_lbl.configure(text=name)


# ===========================================================================
# Preview area
# ===========================================================================

class _PreviewArea(tk.Frame):

    def __init__(self, master, **kw) -> None:
        kw.setdefault("bg", _WHITE)
        super().__init__(master, **kw)
        self._img_ref = None
        self._t: dict = {}
        self._current_path: Optional[Path] = None
        self._build()

    def _build(self) -> None:
        self._canvas = tk.Canvas(self, bg=_WHITE, highlightthickness=0, cursor="hand2")
        self._canvas.pack(fill="both", expand=True)
        self._canvas.bind("<Button-1>", self._on_click)
        self._canvas.bind("<Configure>", lambda _e: self._redraw())
        self._meta_lbl = tk.Label(self, text="", bg=_WHITE, fg=_GRAY, font=("Segoe UI", 9))
        self._meta_lbl.pack(pady=6)

    def apply_theme(self, t: dict) -> None:
        self._t = t
        bg    = t.get("bg",       _WHITE)
        muted = t.get("fg_muted", _GRAY)
        self.configure(bg=bg)
        self._canvas.configure(bg=bg)
        self._meta_lbl.configure(bg=bg, fg=muted)

    def load(self, f: DuplicateFile) -> None:
        self._current_path = Path(f.path)
        ft = _file_type(self._current_path)
        meta = f"{_fmt_size(f.size)}  ·  {_fmt_date(f.modified)}"
        self._meta_lbl.configure(text=meta)

        if ft == "image":
            threading.Thread(target=self._load_image,
                             args=(self._current_path,), daemon=True).start()
        else:
            icon = _TYPE_ICONS.get(ft, "📎")
            self._show_icon(icon)

    def _load_image(self, path: Path) -> None:
        try:
            from PIL import Image, ImageTk
            img = Image.open(path)
            img.thumbnail((800, 600), Image.LANCZOS)
            photo = ImageTk.PhotoImage(img)
            dims = f"{img.size[0]}×{img.size[1]}"
            self.after(0, lambda p=photo, d=dims: self._show_image(p, d))
        except Exception:
            self.after(0, lambda: self._show_icon("🖼"))

    def _show_image(self, photo, dims: str) -> None:
        self._img_ref = photo
        self._canvas.delete("all")
        w = self._canvas.winfo_width()  or 400
        h = self._canvas.winfo_height() or 300
        self._canvas.create_image(w // 2, h // 2, image=photo, anchor="center")
        cur = self._meta_lbl.cget("text")
        if dims and dims not in cur:
            self._meta_lbl.configure(text=f"{dims}  ·  {cur}")

    def _show_icon(self, icon: str) -> None:
        self._img_ref = None
        self._canvas.delete("all")
        w = self._canvas.winfo_width()  or 400
        h = self._canvas.winfo_height() or 300
        self._canvas.create_text(w // 2, h // 2, text=icon,
                                 font=("Segoe UI", 64),
                                 fill=self._t.get("fg_muted", _DIMGRAY))

    def _redraw(self) -> None:
        if self._img_ref:
            self._show_image(self._img_ref, "")

    def _on_click(self, _e=None) -> None:
        if self._current_path and self._current_path.exists():
            threading.Thread(target=_open_default,
                             args=(self._current_path,), daemon=True).start()

    def clear(self) -> None:
        self._img_ref = None
        self._canvas.delete("all")
        self._meta_lbl.configure(text="")
        self._current_path = None


# ===========================================================================
# Copy list (right panel)
# ===========================================================================

class _CopyCard(tk.Frame):
    """Single file card in the copy list."""

    def __init__(self, master, f: DuplicateFile, is_original: bool,
                 on_select: Callable[[DuplicateFile], None],
                 t: Optional[dict] = None, **kw) -> None:
        t = t or {}
        kw.setdefault("bg", t.get("bg2", _WHITE))
        super().__init__(master, cursor="hand2", **kw)
        self._file      = f
        self._on_select = on_select
        self._build(f, is_original, t)
        self.bind("<Button-1>", lambda _e: on_select(f))

    def _build(self, f: DuplicateFile, is_original: bool, t: dict) -> None:
        bg     = t.get("bg2",      _WHITE)
        fg     = t.get("fg",       "#111111")
        fg2    = t.get("fg2",      _GRAY)
        fg_mut = t.get("fg_muted", _DIMGRAY)
        border = t.get("border",   _BORDER)
        accent = _GREEN if is_original else _RED

        tk.Frame(self, bg=accent, width=3).pack(side="left", fill="y")

        body = tk.Frame(self, bg=bg, padx=8, pady=6)
        body.pack(fill="both", expand=True)
        body.bind("<Button-1>", lambda _e: self._on_select(self._file))

        top = tk.Frame(body, bg=bg)
        top.pack(fill="x")
        tk.Label(top, text=Path(f.path).name, bg=bg, fg=fg,
                 font=("Segoe UI", 11, "bold"), anchor="w").pack(side="left")
        tk.Label(top, text="ORIGINAL" if is_original else "DUPLICATE",
                 bg=accent, fg=_WHITE,
                 font=("Segoe UI", 8, "bold"), padx=4, pady=1).pack(side="right")

        path_str = str(f.path)
        if len(path_str) > 55:
            path_str = "…" + path_str[-53:]
        tk.Label(body, text=path_str, bg=bg, fg=fg2,
                 font=("Segoe UI", 9), anchor="w", justify="left").pack(fill="x")

        tk.Label(body, text=f"{_fmt_size(f.size)}  ·  {_fmt_date(f.modified)}",
                 bg=bg, fg=fg_mut, font=("Segoe UI", 9)).pack(anchor="w")

        tk.Frame(self, bg=border, height=1).pack(fill="x", side="bottom")


class _CopyList(tk.Frame):
    """Scrollable list of all copies in a group."""

    def __init__(self, master, **kw) -> None:
        kw.setdefault("bg", _F8)
        super().__init__(master, **kw)
        self._on_select: Optional[Callable[[DuplicateFile], None]] = None
        self._t: dict = {}
        self._build()

    def _build(self) -> None:
        self._hdr = tk.Label(self, text="All copies — 0 files",
                             bg=_F8, fg="#111111",
                             font=("Segoe UI", 11, "bold"),
                             anchor="w", padx=16, pady=10)
        self._hdr.pack(fill="x")
        self._hdr_sep = tk.Frame(self, bg=_BORDER, height=1)
        self._hdr_sep.pack(fill="x")

        from tkinter import ttk
        canvas = tk.Canvas(self, bg=_WHITE, highlightthickness=0)
        vsb = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(fill="both", expand=True)

        self._inner = tk.Frame(canvas, bg=_WHITE)
        win = canvas.create_window((0, 0), window=self._inner, anchor="nw")

        self._inner.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(win, width=e.width))
        canvas.bind("<MouseWheel>", lambda e: canvas.yview_scroll(-1 * (e.delta // 120), "units"))
        self._canvas = canvas

    def apply_theme(self, t: dict) -> None:
        self._t = t
        bg  = t.get("bg2",    _F8)
        fg  = t.get("fg",     "#111111")
        bg2 = t.get("bg",     _WHITE)
        br  = t.get("border", _BORDER)
        self.configure(bg=bg)
        self._hdr.configure(bg=bg, fg=fg)
        self._hdr_sep.configure(bg=br)
        self._canvas.configure(bg=bg2)
        self._inner.configure(bg=bg2)

    def load(self, group: DuplicateGroup,
             on_select: Callable[[DuplicateFile], None]) -> None:
        self._on_select = on_select
        for w in self._inner.winfo_children():
            w.destroy()
        n = len(group.files)
        self._hdr.configure(text=f"All copies — {n} file{'s' if n != 1 else ''}")
        keeper_idx = group.get_keeper_index()
        for i, f in enumerate(group.files):
            _CopyCard(self._inner, f,
                      is_original=(i == keeper_idx),
                      on_select=on_select,
                      t=self._t).pack(fill="x")


# ===========================================================================
# Group navigation bar
# ===========================================================================

class _GroupNav(tk.Frame):
    H = 44

    def __init__(self, master,
                 on_prev: Callable, on_next: Callable, **kw) -> None:
        kw.setdefault("bg", _WHITE)
        kw.setdefault("height", self.H)
        super().__init__(master, **kw)
        self.pack_propagate(False)
        tk.Frame(self, bg=_BORDER, height=1).pack(side="top", fill="x")

        self._prev_btn = tk.Button(self, text="← Prev group",
                                   bg=_WHITE, fg="#333333",
                                   font=("Segoe UI", 10), relief="flat",
                                   cursor="hand2", padx=14,
                                   command=on_prev)
        self._prev_btn.pack(side="left", fill="y")

        self._nav_lbl = tk.Label(self, text="", bg=_WHITE, fg=_GRAY,
                                 font=("Segoe UI", 10))
        self._nav_lbl.place(relx=0.5, rely=0.5, anchor="center")

        self._next_btn = tk.Button(self, text="Next group →",
                                   bg=_WHITE, fg="#333333",
                                   font=("Segoe UI", 10), relief="flat",
                                   cursor="hand2", padx=14,
                                   command=on_next)
        self._next_btn.pack(side="right", fill="y")

    def apply_theme(self, t: dict) -> None:
        bg    = t.get("bg",       _WHITE)
        fg    = t.get("fg",       "#333333")
        muted = t.get("fg_muted", _GRAY)
        br    = t.get("border",   _BORDER)
        self.configure(bg=bg)
        self._prev_btn.configure(bg=bg, fg=fg, activebackground=bg)
        self._next_btn.configure(bg=bg, fg=fg, activebackground=bg)
        self._nav_lbl.configure(bg=bg, fg=muted)
        for w in self.winfo_children():
            if isinstance(w, tk.Frame):
                try:
                    w.configure(bg=br)
                except tk.TclError:
                    pass

    def update(self, idx: int, total: int) -> None:
        self._nav_lbl.configure(text=f"{idx + 1} / {total}")
        self._prev_btn.configure(state="normal" if idx > 0          else "disabled")
        self._next_btn.configure(state="normal" if idx < total - 1  else "disabled")


# ===========================================================================
# ReviewPage
# ===========================================================================

class ReviewPage(tk.Frame):
    """
    Full-viewport review page.

    Call load_group(groups, group_id) to enter from the Results page.
    """

    def __init__(self, master,
                 on_back: Optional[Callable] = None,
                 on_navigate_results: Optional[Callable[[], None]] = None,
                 **kw) -> None:
        kw.setdefault("bg", _WHITE)
        super().__init__(master, **kw)
        self._on_back     = on_back
        # Called when the empty-state "Go to Results" button is clicked,
        # or the user lands on Review from the top nav with no group loaded.
        self._on_navigate_results = on_navigate_results
        self._groups:     List[DuplicateGroup] = []
        self._group_idx:  int                  = 0
        self._preview_file: Optional[DuplicateFile] = None
        self._t: dict = {}
        self._build()
        self._build_empty_state()
        self._bind_keys()
        self._t = ThemeApplicator.get().build_tokens()
        ThemeApplicator.get().register(self._apply_theme)
        # Show the empty-state overlay at init — it stays visible until the
        # first load_group() call marks the page as "entered with data".
        self._show_empty_state()

    # ------------------------------------------------------------------
    def _build(self) -> None:
        # ── Left column ──────────────────────────────────────────────
        self._left_col = tk.Frame(self, bg=_WHITE)
        self._left_col.place(relx=0, rely=0, relwidth=0.55, relheight=1)

        self._breadcrumb = _BreadcrumbBar(self._left_col, on_back=self._go_back)
        self._breadcrumb.pack(fill="x")

        self._preview = _PreviewArea(self._left_col)
        self._preview.pack(fill="both", expand=True)

        # Action buttons bar — filled, color-coded so the main actions
        # (Keep / Delete / Open) stand out against the white preview pane
        # instead of blending in as ghosted outlines.
        self._acts_bar = tk.Frame(self._left_col, bg=_WHITE, height=60)
        self._acts_bar.pack(fill="x", side="bottom")
        self._acts_bar.pack_propagate(False)
        tk.Frame(self._acts_bar, bg=_BORDER, height=1).pack(side="top", fill="x")
        self._acts_center = tk.Frame(self._acts_bar, bg=_WHITE)
        self._acts_center.pack(anchor="center", expand=True)

        self._act_btn_specs: List[dict] = []

        def _abtn(text, cmd, bg_color, hover_color):
            b = tk.Button(
                self._acts_center, text=text, command=cmd,
                bg=bg_color, fg=_WHITE,
                font=("Segoe UI", 10, "bold"), relief="flat",
                cursor="hand2", padx=18, pady=8,
                activebackground=hover_color, activeforeground=_WHITE,
                borderwidth=0, highlightthickness=0,
            )
            b.pack(side="left", padx=6, pady=10)
            b.bind("<Enter>", lambda _e, w=b, c=hover_color: w.configure(bg=c))
            b.bind("<Leave>", lambda _e, w=b, c=bg_color:   w.configure(bg=c))
            self._act_btn_specs.append({"btn": b, "bg": bg_color, "hover": hover_color})
            return b

        _abtn("\u2713 Keep this one",       self._keep_current,     "#2E8B57", "#3FA56B")
        _abtn("\u2716 Delete as duplicate", self._delete_current,   _RED,      "#C0392B")
        _abtn("\u270E Open in Explorer",    self._open_in_explorer, "#2E75B6", "#3A87CC")

        # ── Right column ─────────────────────────────────────────────
        self._right_col = tk.Frame(self, bg=_F8)
        self._right_col.place(relx=0.55, rely=0, relwidth=0.45, relheight=1)
        tk.Frame(self._right_col, bg=_BORDER, width=1).place(x=0, rely=0, relheight=1)

        self._copy_list = _CopyList(self._right_col)
        self._copy_list.pack(fill="both", expand=True)

        self._group_nav = _GroupNav(self._right_col,
                                    on_prev=self._prev_group,
                                    on_next=self._next_group)
        self._group_nav.pack(fill="x", side="bottom")

    # ------------------------------------------------------------------
    # Empty state — covers the whole page when no group has been loaded.
    # The user reaches this path by clicking the Review tab in the top nav
    # without first picking a group from Results.

    def _build_empty_state(self) -> None:
        self._empty_state = tk.Frame(self, bg=_WHITE)
        center = tk.Frame(self._empty_state, bg=_WHITE)
        center.place(relx=0.5, rely=0.5, anchor="center")

        self._empty_icon = tk.Label(
            center, text="\U0001F50D", bg=_WHITE, fg=_DIMGRAY,
            font=("Segoe UI Emoji", 56),
        )
        self._empty_icon.pack(pady=(0, 12))

        self._empty_title = tk.Label(
            center, text="No group selected", bg=_WHITE, fg="#333333",
            font=("Segoe UI", 16, "bold"),
        )
        self._empty_title.pack(pady=(0, 6))

        self._empty_subtitle = tk.Label(
            center,
            text="Pick a group on the Results page to review its duplicates.",
            bg=_WHITE, fg=_GRAY, font=("Segoe UI", 10),
        )
        self._empty_subtitle.pack(pady=(0, 20))

        self._empty_cta = tk.Button(
            center, text="Go to Results", command=self._navigate_results,
            bg="#2E75B6", fg=_WHITE,
            font=("Segoe UI", 10, "bold"), relief="flat",
            cursor="hand2", padx=22, pady=9,
            activebackground="#3A87CC", activeforeground=_WHITE,
            borderwidth=0, highlightthickness=0,
        )
        self._empty_cta.pack()
        self._empty_cta.bind(
            "<Enter>", lambda _e: self._empty_cta.configure(bg="#3A87CC"))
        self._empty_cta.bind(
            "<Leave>", lambda _e: self._empty_cta.configure(bg="#2E75B6"))

    def _show_empty_state(self) -> None:
        self._empty_state.place(relx=0, rely=0, relwidth=1, relheight=1)
        self._empty_state.lift()

    def _hide_empty_state(self) -> None:
        self._empty_state.place_forget()

    def _navigate_results(self) -> None:
        if self._on_navigate_results:
            self._on_navigate_results()

    def on_show(self) -> None:
        """Called by AppShell when this page becomes the active tab.

        If the user landed here from the top nav without first picking a
        group (i.e. no groups loaded yet), show the empty-state overlay
        instead of the stale "All copies — 0 files" chrome.
        """
        if not self._groups:
            self._show_empty_state()
        else:
            self._hide_empty_state()

    # ------------------------------------------------------------------
    def _apply_theme(self, t: dict) -> None:
        self._t = t
        bg  = t.get("bg",     _WHITE)
        bg2 = t.get("bg2",    _F8)
        fg  = t.get("fg",     "#333333")
        br  = t.get("border", _BORDER)
        self.configure(bg=bg)
        self._left_col.configure(bg=bg)
        self._right_col.configure(bg=bg2)
        self._breadcrumb.apply_theme(t)
        self._preview.apply_theme(t)
        self._acts_bar.configure(bg=bg)
        self._acts_center.configure(bg=bg)
        # Keep the colored Keep/Delete/Open buttons vivid across theme
        # changes: only restyle the container + the thin top separator
        # frame, not the action buttons themselves.
        for w in self._acts_bar.winfo_children():
            try:
                if w is self._acts_center:
                    continue
                if isinstance(w, tk.Frame):
                    w.configure(bg=br)
            except tk.TclError:
                pass
        for spec in self._act_btn_specs:
            try:
                spec["btn"].configure(bg=spec["bg"], fg=_WHITE,
                                       activebackground=spec["hover"],
                                       activeforeground=_WHITE)
            except tk.TclError:
                pass
        self._copy_list.apply_theme(t)
        self._group_nav.apply_theme(t)

        # Empty-state follows the theme for background/title; muted subtitle
        # and the CTA keep their distinct palette so the invitation reads
        # as an action, not as chrome.
        try:
            self._empty_state.configure(bg=bg)
            for child in self._empty_state.winfo_children():
                if isinstance(child, tk.Frame):
                    child.configure(bg=bg)
                    for leaf in child.winfo_children():
                        if isinstance(leaf, tk.Label):
                            leaf.configure(bg=bg)
            self._empty_icon.configure(fg=t.get("fg_muted", _DIMGRAY))
            self._empty_title.configure(fg=fg)
            self._empty_subtitle.configure(fg=t.get("fg_muted", _GRAY))
        except tk.TclError:
            pass

    def _bind_keys(self) -> None:
        self.bind("<Left>",  lambda _e: self._prev_group())
        self.bind("<Right>", lambda _e: self._next_group())

    # ------------------------------------------------------------------
    # Public API

    def load_group(self, groups: List[DuplicateGroup], group_id: int) -> None:
        self._groups = groups
        idx = next((i for i, g in enumerate(groups) if g.group_id == group_id), 0)
        self._group_idx = idx
        self._hide_empty_state()
        self._show_current()

    # ------------------------------------------------------------------
    # Navigation

    def _show_current(self) -> None:
        if not self._groups:
            return
        g = self._groups[self._group_idx]
        self._breadcrumb.update(self._group_idx, len(self._groups),
                                Path(g.files[0].path).name if g.files else "")
        self._group_nav.update(self._group_idx, len(self._groups))
        # Show first file in preview
        if g.files:
            self._preview_file = g.files[0]
            self._preview.load(g.files[0])
        else:
            self._preview.clear()
        self._copy_list.load(g, self._on_copy_selected)
        self.focus_set()

    def _on_copy_selected(self, f: DuplicateFile) -> None:
        self._preview_file = f
        self._preview.load(f)
        # Update breadcrumb filename
        self._breadcrumb.update(self._group_idx, len(self._groups),
                                Path(f.path).name)

    def _prev_group(self) -> None:
        if self._group_idx > 0:
            self._group_idx -= 1
            self._show_current()

    def _next_group(self) -> None:
        if self._group_idx < len(self._groups) - 1:
            self._group_idx += 1
            self._show_current()

    def _go_back(self) -> None:
        if self._on_back:
            self._on_back()

    # ------------------------------------------------------------------
    # Actions

    def _keep_current(self) -> None:
        """Mark current file as keeper (unflagged) — no deletion."""
        if self._preview_file:
            self._preview_file.is_keeper = True

    def _delete_current(self) -> None:
        if not self._preview_file:
            return
        path = Path(self._preview_file.path)
        threading.Thread(target=self._do_delete,
                         args=(path,), daemon=True).start()

    def _do_delete(self, path: Path) -> None:
        try:
            from cerebro.core.deletion import DeletionEngine, DeletionPolicy, DeletionRequest
            engine = DeletionEngine()
            req    = DeletionRequest(policy=DeletionPolicy.TRASH,
                                     metadata={"source": "review_page"})
            engine.delete_one(path, req)
        except Exception:
            try:
                import send2trash
                send2trash.send2trash(str(path))
            except Exception:
                pass
        self.after(0, self._after_delete)

    def _after_delete(self) -> None:
        """Remove deleted file from group and refresh view."""
        if not self._groups or not self._preview_file:
            return
        g = self._groups[self._group_idx]
        g.files = [f for f in g.files
                   if str(f.path) != str(self._preview_file.path)]
        self._preview_file = None
        if not g.files:
            # Remove empty group and navigate
            self._groups.pop(self._group_idx)
            self._group_idx = min(self._group_idx, len(self._groups) - 1)
        self._show_current()

    def _open_in_explorer(self) -> None:
        if self._preview_file:
            threading.Thread(target=_open_in_explorer,
                             args=(Path(self._preview_file.path),),
                             daemon=True).start()
