"""
ResultsPage — post-scan results with canvas-based virtual file grid.

Stats bar · Action toolbar · Filter list · VirtualFileGrid
"""
from __future__ import annotations

import logging
import os
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any, Callable, Dict, List, Optional, Set

_log = logging.getLogger(__name__)

try:
    import customtkinter as ctk
    CTkFrame    = ctk.CTkFrame
    CTkLabel    = ctk.CTkLabel
    CTkButton   = ctk.CTkButton
except ImportError:
    CTkFrame    = tk.Frame      # type: ignore[misc,assignment]
    CTkLabel    = tk.Label      # type: ignore[misc,assignment]
    CTkButton   = tk.Button     # type: ignore[misc,assignment]

from cerebro.engines.base_engine import DuplicateGroup, DuplicateFile
from cerebro.v2.ui.theme_applicator import ThemeApplicator

# ---------------------------------------------------------------------------
# Tokens
# ---------------------------------------------------------------------------
_WHITE    = "#FFFFFF"
_SURFACE  = "#F0F0F0"
_ROW_ALT  = "#F8F8F8"
_SELECTED = "#1E3A8A"
_SEL_FG   = "#FFFFFF"
_BORDER   = "#E0E0E0"
_BTN_BD   = "#DDDDDD"
_NAVY_MID = "#1E3A5F"
_RED      = "#E74C3C"
_GREEN    = "#27AE60"
_GRAY     = "#666666"
_DIMGRAY  = "#AAAAAA"
_HDR_BG   = "#E8E8E8"

# File-type extension sets for the filter list
_EXT_MUSIC  = {".mp3",".flac",".ogg",".wav",".aac",".m4a",".wma",".opus",".aiff",".ape"}
_EXT_PIC    = {".jpg",".jpeg",".png",".gif",".bmp",".webp",".heic",".tiff",".tif",
               ".cr2",".cr3",".nef",".arw",".dng"}
_EXT_VID    = {".mp4",".avi",".mkv",".mov",".wmv",".flv",".webm",".m4v",".mpg",".mpeg"}
_EXT_DOC    = {".pdf",".doc",".docx",".xls",".xlsx",".ppt",".pptx",".txt",".odt",".rtf"}
_EXT_ARCH   = {".zip",".rar",".7z",".tar",".gz",".bz2",".xz",".iso"}

_FILTER_EXTS: Dict[str, Optional[Set[str]]] = {
    "all": None,
    "music": _EXT_MUSIC,
    "pictures": _EXT_PIC,
    "videos": _EXT_VID,
    "documents": _EXT_DOC,
    "archives": _EXT_ARCH,
}

_EXT_ALL_KNOWN: Set[str] = (
    _EXT_MUSIC | _EXT_PIC | _EXT_VID | _EXT_DOC | _EXT_ARCH
)


def classify_file(ext: str) -> str:
    """Return the Results-filter bucket for a file extension.

    Buckets: ``pictures``, ``music``, ``videos``, ``documents``, ``archives``,
    ``other``. Input is the extension including the leading dot (e.g.
    ``'.jpg'``); comparison is case-insensitive.
    """
    e = (ext or "").lower()
    if e in _EXT_PIC:   return "pictures"
    if e in _EXT_MUSIC: return "music"
    if e in _EXT_VID:   return "videos"
    if e in _EXT_DOC:   return "documents"
    if e in _EXT_ARCH:  return "archives"
    return "other"


def _fmt_size(n: int) -> str:
    if n < 1024:       return f"{n} B"
    if n < 1024**2:    return f"{n/1024:.1f} KB"
    if n < 1024**3:    return f"{n/1024**2:.1f} MB"
    return             f"{n/1024**3:.1f} GB"


def _fmt_date(ts: float) -> str:
    if not ts:
        return "—"
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
    except Exception:
        return "—"


# ---------------------------------------------------------------------------
# Columns definition  (name, fixed_width — 0 = flex)
# ---------------------------------------------------------------------------
COLS = [("☐", 28), ("Name", 260), ("Size", 88), ("Date", 110), ("Folder", 0)]


def _col_x_widths(total_w: int):
    """Return list of (name, x_start, width) for all columns."""
    flex_w = max(0, total_w - sum(w for _, w in COLS if w > 0))
    result, x = [], 0
    for name, w in COLS:
        cw = w if w > 0 else flex_w
        result.append((name, x, cw))
        x += cw
    return result


# ===========================================================================
# VirtualFileGrid
# ===========================================================================

class VirtualFileGrid(tk.Canvas):
    """Canvas-based virtual file list — smooth at 5 000+ rows."""

    ROW_H = 24

    def __init__(self, parent, on_open_group: Optional[Callable[[int], None]] = None,
                 **kw) -> None:
        kw.setdefault("bg", _WHITE)
        kw.setdefault("highlightthickness", 0)
        # Captured up-front so ttk.Scrollbar can drive us via configure().
        # See configure() + _render() — we fire this ourselves because
        # native Canvas scrolling is bypassed by our own _scroll_y model.
        self._yscrollcommand: Optional[Callable[[str, str], None]] = kw.pop(
            "yscrollcommand", None
        )
        super().__init__(parent, **kw)
        self._rows:         List[Dict]     = []
        self._checked:      Set[int]       = set()       # row indices
        self._selected_idx: Optional[int]  = None
        self._scroll_y:     int            = 0
        self._sort_col:     str            = "Name"
        self._sort_asc:     bool           = True
        self._on_open_group = on_open_group
        self._total_h:      int            = 0

        self.bind("<MouseWheel>",    self._on_scroll)           # Win / macOS
        self.bind("<Button-4>",      self._on_scroll_linux)     # Linux up
        self.bind("<Button-5>",      self._on_scroll_linux)     # Linux down
        self.bind("<Button-1>",      self._on_click)
        self.bind("<Double-Button-1>", self._on_dbl)
        self.bind("<Configure>",     lambda _e: self._render())
        self.bind("<space>",         self._on_space)
        self.bind("<Up>",            lambda _e: self._move_sel(-1))
        self.bind("<Down>",          lambda _e: self._move_sel(1))
        self.bind("<Prior>",         lambda _e: self._move_sel(-self._page_size()))
        self.bind("<Next>",          lambda _e: self._move_sel( self._page_size()))
        self.bind("<Home>",          self._on_home)
        self.bind("<End>",           self._on_end)
        self.bind("<Return>",        lambda _e: self._open_selected())
        self.bind("<Control-a>",     lambda _e: self._check_all())
        self.bind("<Control-A>",     lambda _e: self._check_all())
        self.bind("<Delete>",        lambda _e: self._mark_selected_delete())

    # ------------------------------------------------------------------
    # Scroll model — unified for scrollbar + mouse wheel + keyboard.
    #
    # Canvas's native yview is bypassed: our _render draws row items at
    # y = i*ROW_H - self._scroll_y, so the only thing that matters is
    # _scroll_y. Both ttk.Scrollbar drags AND mouse-wheel events route
    # through _scroll_to / _scroll_by; _render then pushes the current
    # fractional view back to the scrollbar via _yscrollcommand so the
    # thumb tracks correctly regardless of input channel.

    def configure(self, cnf=None, **kw):  # type: ignore[override]
        merged: Dict = dict(cnf) if isinstance(cnf, dict) else {}
        merged.update(kw)
        if "yscrollcommand" in merged:
            self._yscrollcommand = merged.pop("yscrollcommand")
        if not merged:
            return super().configure()
        return super().configure(**merged)

    config = configure  # Tk alias

    def yview(self, *args):  # type: ignore[override]
        if not args:
            return self._yview_fractions()
        op = args[0]
        if op == "moveto" and len(args) >= 2:
            try:
                fraction = float(args[1])
            except (TypeError, ValueError):
                return None
            self._scroll_to(int(fraction * self._total_h))
        elif op == "scroll" and len(args) >= 3:
            try:
                number = int(args[1])
            except (TypeError, ValueError):
                return None
            what = str(args[2])
            if what.startswith("page"):
                self._scroll_by_page(number)
            else:
                self._scroll_by(number * self.ROW_H)
        return None

    def _yview_fractions(self) -> tuple:
        if self._total_h <= 0:
            return (0.0, 1.0)
        h = self.winfo_height() or 400
        top = max(0.0, min(1.0, self._scroll_y / self._total_h))
        bot = max(0.0, min(1.0, (self._scroll_y + h) / self._total_h))
        return (top, bot)

    def _scroll_to(self, y_px: int) -> None:
        h = self.winfo_height() or 400
        max_y = max(0, self._total_h - h)
        self._scroll_y = max(0, min(max_y, int(y_px)))
        self._render()

    def _scroll_by(self, delta_px: int) -> None:
        self._scroll_to(self._scroll_y + int(delta_px))

    def _scroll_by_page(self, pages: int) -> None:
        h = self.winfo_height() or 400
        page_px = max(self.ROW_H, h - self.ROW_H)
        self._scroll_by(int(pages) * page_px)

    def _page_size(self) -> int:
        h = self.winfo_height() or 400
        return max(1, h // self.ROW_H - 1)

    def _on_home(self, _event=None) -> str:
        if self._rows:
            self._selected_idx = 0
        self._scroll_to(0)
        return "break"

    def _on_end(self, _event=None) -> str:
        if self._rows:
            self._selected_idx = len(self._rows) - 1
        self._scroll_to(self._total_h)
        return "break"

    # ------------------------------------------------------------------
    # Data

    def load(self, rows: List[Dict]) -> None:
        self._rows = rows
        self._checked.clear()
        self._selected_idx = None
        self._scroll_y = 0
        self._total_h = len(rows) * self.ROW_H
        self._render()

    def get_checked_rows(self) -> List[Dict]:
        return [self._rows[i] for i in sorted(self._checked) if i < len(self._rows)]

    def get_checked_count(self) -> int:
        return len(self._checked)

    # ------------------------------------------------------------------
    # Rendering

    def _visible_range(self):
        h = self.winfo_height() or 400
        first = max(0, self._scroll_y // self.ROW_H)
        last  = min(len(self._rows), first + h // self.ROW_H + 2)
        return first, last

    def apply_theme(self, t: dict) -> None:
        self._t = t
        self.configure(bg=t.get("bg", _WHITE))
        self._render()

    def _render(self) -> None:
        t        = getattr(self, "_t", {})
        _bg      = t.get("bg",      _WHITE)
        _row_alt = t.get("row_alt", _ROW_ALT)
        _sel     = t.get("row_sel", _SELECTED)
        _sel_fg  = t.get("row_sel_fg", _SEL_FG)
        _fg_base = t.get("fg",      "#333333")

        self.delete("row")
        if not self._rows:
            self.create_text(self.winfo_width() // 2 or 200, 80,
                             text="No results to display.",
                             fill=_DIMGRAY, font=("Segoe UI", 11), tags="row")
            return

        w = self.winfo_width() or 800
        cols = _col_x_widths(w)
        first, last = self._visible_range()

        for i in range(first, last):
            row  = self._rows[i]
            y    = i * self.ROW_H - self._scroll_y
            is_sel = (i == self._selected_idx)
            is_chk = (i in self._checked)

            # Row background
            if is_sel:
                bg = _sel
            elif row.get("_group_shade"):
                bg = _row_alt
            else:
                bg = _bg
            fg = _sel_fg if is_sel else _fg_base

            self.create_rectangle(0, y, w, y + self.ROW_H,
                                  fill=bg, outline="", tags="row")

            for col_name, cx, cw in cols:
                if cw <= 0:
                    continue
                if col_name == "☐":
                    chk = "☑" if is_chk else "☐"
                    self.create_text(cx + cw // 2, y + self.ROW_H // 2,
                                     text=chk, fill=fg, anchor="center",
                                     font=("Segoe UI", 10), tags="row")
                elif col_name == "Name":
                    name = row.get("name", "")
                    if len(name) > 38:
                        name = name[:36] + "…"
                    self.create_text(cx + 4, y + self.ROW_H // 2,
                                     text=name, fill=fg, anchor="w",
                                     font=("Segoe UI", 10), tags="row")
                elif col_name == "Size":
                    self.create_text(cx + cw - 4, y + self.ROW_H // 2,
                                     text=row.get("size_str", ""),
                                     fill=fg, anchor="e",
                                     font=("Segoe UI", 10), tags="row")
                elif col_name == "Date":
                    self.create_text(cx + 4, y + self.ROW_H // 2,
                                     text=row.get("date", ""),
                                     fill=fg, anchor="w",
                                     font=("Segoe UI", 10), tags="row")
                elif col_name == "Folder":
                    folder = row.get("folder", "")
                    max_chars = max(0, cw // 7)
                    if len(folder) > max_chars:
                        folder = "…" + folder[-(max_chars - 1):]
                    self.create_text(cx + 4, y + self.ROW_H // 2,
                                     text=folder, fill=fg, anchor="w",
                                     font=("Segoe UI", 10), tags="row")

        # Keep Tk's native scrollregion clamped to the viewport so native
        # Canvas scrolling (which we intentionally bypass) can never drift
        # away from the drawn row range. All scrolling now flows through
        # yview() / _scroll_to / _scroll_by on our _scroll_y model.
        h = self.winfo_height() or 400
        super().configure(scrollregion=(0, 0, w, h))

        # Push current fractional view to the scrollbar so the thumb
        # tracks mouse-wheel and keyboard-driven scrolling, not only
        # scrollbar drags.
        if self._yscrollcommand is not None:
            top, bot = self._yview_fractions()
            try:
                self._yscrollcommand(f"{top}", f"{bot}")
            except tk.TclError:
                pass

    # ------------------------------------------------------------------
    # Interaction

    def _on_scroll(self, event) -> None:
        # Windows: event.delta is a multiple of 120 per notch.
        # macOS:   event.delta is a small signed integer per notch.
        # Scroll 3 rows per notch either way for a snappy feel.
        if abs(event.delta) >= 120:
            notches = -event.delta // 120
        else:
            notches = -1 if event.delta > 0 else 1
        self._scroll_by(notches * self.ROW_H * 3)

    def _on_scroll_linux(self, event) -> None:
        # X11: <Button-4>/<Button-5> deliver wheel events with delta=0.
        direction = -1 if getattr(event, "num", 0) == 4 else 1
        self._scroll_by(direction * self.ROW_H * 3)

    def _row_at_y(self, y: int) -> Optional[int]:
        idx = (y + self._scroll_y) // self.ROW_H
        return idx if 0 <= idx < len(self._rows) else None

    def _on_click(self, event) -> None:
        self.focus_set()
        idx = self._row_at_y(event.y)
        if idx is None:
            return
        w = self.winfo_width() or 800
        cols = _col_x_widths(w)
        chk_end = cols[0][1] + cols[0][2]  # end of checkbox column
        if event.x <= chk_end:
            if idx in self._checked:
                self._checked.discard(idx)
            else:
                self._checked.add(idx)
        else:
            self._selected_idx = idx
        self._render()
        self._fire_check_change()

    def _on_dbl(self, event) -> None:
        idx = self._row_at_y(event.y)
        if idx is not None:
            self._selected_idx = idx
            self._open_selected()

    def _open_selected(self) -> None:
        if self._selected_idx is not None and self._on_open_group:
            row = self._rows[self._selected_idx]
            self._on_open_group(row.get("group_id", 0))

    def _on_space(self, _event) -> None:
        if self._selected_idx is not None:
            if self._selected_idx in self._checked:
                self._checked.discard(self._selected_idx)
            else:
                self._checked.add(self._selected_idx)
            self._render()
            self._fire_check_change()

    def _move_sel(self, delta: int) -> None:
        if not self._rows:
            return
        cur = self._selected_idx or 0
        nxt = max(0, min(len(self._rows) - 1, cur + delta))
        self._selected_idx = nxt
        # Auto-scroll
        visible_start = self._scroll_y // self.ROW_H
        visible_end   = visible_start + self.winfo_height() // self.ROW_H - 1
        if nxt < visible_start:
            self._scroll_y = nxt * self.ROW_H
        elif nxt > visible_end:
            self._scroll_y = (nxt - visible_end + visible_start) * self.ROW_H
        self._render()

    def _check_all(self) -> None:
        if len(self._checked) == len(self._rows):
            self._checked.clear()
        else:
            self._checked = set(range(len(self._rows)))
        self._render()
        self._fire_check_change()

    def _mark_selected_delete(self) -> None:
        if self._selected_idx is not None:
            self._checked.add(self._selected_idx)
            self._render()
            self._fire_check_change()

    def _fire_check_change(self) -> None:
        self.event_generate("<<CheckChanged>>")

    # ------------------------------------------------------------------
    # Sorting

    def sort_by(self, col: str) -> None:
        if col == self._sort_col:
            self._sort_asc = not self._sort_asc
        else:
            self._sort_col = col
            self._sort_asc = True
        key_map = {
            "Name": lambda r: r.get("name", "").lower(),
            "Size": lambda r: r.get("size", 0),
            "Date": lambda r: r.get("date", ""),
            "Folder": lambda r: r.get("folder", "").lower(),
        }
        key = key_map.get(col, lambda r: r.get("name", ""))
        self._rows.sort(key=key, reverse=not self._sort_asc)
        self._checked.clear()
        self._selected_idx = None
        self._render()
        self._fire_check_change()


# ===========================================================================
# Column header
# ===========================================================================

class _ColHeader(tk.Canvas):
    H = 28

    def __init__(self, parent, on_sort: Callable[[str], None], **kw) -> None:
        t = ThemeApplicator.get().build_tokens()
        kw.setdefault("bg", t.get("bg2", _HDR_BG))
        kw.setdefault("height", self.H)
        kw.setdefault("highlightthickness", 0)
        super().__init__(parent, **kw)
        self._on_sort   = on_sort
        self._sort_col  = "Name"
        self._sort_asc  = True
        self._t         = t
        self.bind("<Configure>", lambda _e: self._render())
        self.bind("<Button-1>",  self._on_click)

    def apply_theme(self, t: dict) -> None:
        self._t = t
        self.configure(bg=t.get("bg2", _HDR_BG))
        self._render()

    def _render(self) -> None:
        self.delete("all")
        w = self.winfo_width() or 800
        cols = _col_x_widths(w)
        fg     = self._t.get("fg2",    "#555555")
        border = self._t.get("border", _BORDER)
        for col_name, cx, cw in cols:
            if cw <= 0:
                continue
            label = col_name
            if col_name == self._sort_col and col_name not in ("☐",):
                label += " ▲" if self._sort_asc else " ▼"
            self.create_text(cx + 4, self.H // 2, text=label,
                             fill=fg, anchor="w",
                             font=("Segoe UI", 9, "bold"))
            # column divider
            self.create_line(cx + cw - 1, 4, cx + cw - 1, self.H - 4,
                             fill=border)

    def _on_click(self, event) -> None:
        w = self.winfo_width() or 800
        cols = _col_x_widths(w)
        for col_name, cx, cw in cols:
            if col_name in ("☐",):
                continue
            if cx <= event.x < cx + cw:
                self._sort_col = col_name
                self._sort_asc = not self._sort_asc if col_name == self._sort_col else True
                self._render()
                self._on_sort(col_name)
                break

    def set_sort(self, col: str, asc: bool) -> None:
        self._sort_col = col
        self._sort_asc = asc
        self._render()


# ===========================================================================
# Stats bar
# ===========================================================================

class _StatsBar(tk.Frame):
    H = 48

    def __init__(self, master, **kw) -> None:
        t = ThemeApplicator.get().build_tokens()
        kw.setdefault("bg", t.get("bg", _WHITE))
        kw.setdefault("height", self.H)
        super().__init__(master, **kw)
        self.pack_propagate(False)
        self._t = t
        self._last_counts = (0, 0)
        self._build()

    def _build(self) -> None:
        bg     = self._t.get("bg",     _WHITE)
        border = self._t.get("border", _BORDER)

        self._bottom_border = tk.Frame(self, bg=border, height=1)
        self._bottom_border.pack(side="bottom", fill="x")

        self._inner = tk.Frame(self, bg=bg)
        self._inner.pack(fill="both", expand=True, padx=16)

        self._pie = tk.Canvas(self._inner, width=24, height=24,
                              bg=bg, highlightthickness=0)
        self._pie.pack(side="left", padx=(0, 12))

        self._labels: Dict[str, tk.Label] = {}
        self._caption_labels: List[tk.Label] = []
        self._columns: List[tk.Frame] = []
        self._separators: List[tk.Frame] = []
        groups = [
            ("files_scanned",  self._t.get("fg",        "#111111"), "Files scanned"),
            ("duplicates",     self._t.get("stat_dupes", _RED),     "Duplicates found"),
            ("recoverable",    self._t.get("stat_space", _GREEN),   "Space recoverable"),
        ]
        for i, (key, fg, lbl_text) in enumerate(groups):
            if i:
                sep = tk.Frame(self._inner, bg=border, width=1)
                sep.pack(side="left", fill="y", padx=20, pady=8)
                self._separators.append(sep)
            col = tk.Frame(self._inner, bg=bg)
            col.pack(side="left")
            self._columns.append(col)
            val_lbl = tk.Label(col, text="0", bg=bg, fg=fg,
                               font=("Segoe UI", 18, "bold"))
            val_lbl.pack()
            cap = tk.Label(col, text=lbl_text, bg=bg,
                           fg=self._t.get("fg2", _GRAY),
                           font=("Segoe UI", 9))
            cap.pack()
            self._labels[key] = val_lbl
            self._caption_labels.append(cap)

    def apply_theme(self, t: dict) -> None:
        self._t = t
        bg     = t.get("bg",     _WHITE)
        border = t.get("border", _BORDER)
        muted  = t.get("fg2",    _GRAY)
        self.configure(bg=bg)
        self._bottom_border.configure(bg=border)
        self._inner.configure(bg=bg)
        self._pie.configure(bg=bg)
        for col in self._columns:
            col.configure(bg=bg)
        for sep in self._separators:
            sep.configure(bg=border)
        for cap in self._caption_labels:
            cap.configure(bg=bg, fg=muted)
        self._labels["files_scanned"].configure(bg=bg, fg=t.get("fg",        "#111111"))
        self._labels["duplicates"]   .configure(bg=bg, fg=t.get("stat_dupes", _RED))
        self._labels["recoverable"]  .configure(bg=bg, fg=t.get("stat_space", _GREEN))
        files, dupes = self._last_counts
        self._draw_pie(files, dupes)

    def update(self, files: int, dupes: int, recoverable: int) -> None:
        self._last_counts = (files, dupes)
        self._labels["files_scanned"].configure(text=f"{files:,}")
        self._labels["duplicates"].configure(text=f"{dupes:,}")
        self._labels["recoverable"].configure(text=_fmt_size(recoverable))
        self._draw_pie(files, dupes)

    def _draw_pie(self, files: int, dupes: int) -> None:
        c = self._pie
        c.delete("all")
        pie_bg = self._t.get("bg3",    _SURFACE)
        border = self._t.get("border", _BORDER)
        danger = self._t.get("stat_dupes", _RED)
        c.create_oval(2, 2, 22, 22, fill=pie_bg, outline=border)
        if files > 0:
            pct = min(1.0, dupes / files)
            extent = pct * 360
            if extent > 0:
                c.create_arc(2, 2, 22, 22, start=90,
                             extent=-extent, fill=danger, outline="")


# ===========================================================================
# Action toolbar
# ===========================================================================

class _ActionToolbar(tk.Frame):
    H = 40

    def __init__(self, master,
                 on_delete: Callable,
                 on_move:   Callable,
                 on_auto_mark: Callable[[str], None],
                 on_view_mode: Optional[Callable[[str], None]] = None,
                 initial_view_mode: str = "list",
                 **kw) -> None:
        t = ThemeApplicator.get().build_tokens()
        kw.setdefault("bg", t.get("bg", _WHITE))
        kw.setdefault("height", self.H)
        super().__init__(master, **kw)
        self.pack_propagate(False)
        self._on_delete    = on_delete
        self._on_move      = on_move
        self._on_auto_mark = on_auto_mark
        # Phase 6: List/Grid view toggle. ResultsPage owns the actual view
        # swap + persistence; this widget just emits the user's pick.
        self._on_view_mode = on_view_mode
        self._view_mode    = initial_view_mode if initial_view_mode in ("list", "grid") else "list"
        self._has_sel      = False
        self._t            = t
        self._buttons: List[Dict[str, object]] = []
        self._view_btns: Dict[str, tk.Button] = {}
        self._build()

    def _build(self) -> None:
        bg     = self._t.get("bg",     _WHITE)
        border = self._t.get("border", _BORDER)

        self._bottom_border = tk.Frame(self, bg=border, height=1)
        self._bottom_border.pack(side="bottom", fill="x")
        self._inner = tk.Frame(self, bg=bg)
        self._inner.pack(fill="both", expand=True, padx=8)

        self._auto_btn = self._mk_btn("Auto Mark ▼", self._show_auto_mark)
        self._del_btn  = self._mk_btn("DELETE",      self._on_delete, role="danger")
        self._mk_btn("MOVE",            self._on_move)
        self._mk_btn("COPY",            self._noop)
        self._mk_btn("Export results",  self._noop)

        # ── View toggle (right-aligned) ─────────────────────────────
        # Two-segment pill: the active mode is filled navy, the
        # inactive one is ghosted. Kept visually distinct from the
        # left-side action buttons so the user reads it as "mode",
        # not "action".
        self._view_strip = tk.Frame(self._inner, bg=bg)
        self._view_strip.pack(side="right", padx=(8, 0))
        tk.Label(
            self._view_strip, text="View:", bg=bg,
            fg=self._t.get("fg_muted", _DIMGRAY),
            font=("Segoe UI", 9),
        ).pack(side="left", padx=(0, 6))
        self._view_btns["list"] = self._mk_view_btn("\u2630 List", "list")
        self._view_btns["grid"] = self._mk_view_btn("\u25A6 Grid", "grid")
        self._paint_view_toggle()

    def _mk_view_btn(self, text: str, mode: str) -> tk.Button:
        b = tk.Button(
            self._view_strip, text=text,
            command=lambda m=mode: self._pick_view(m),
            font=("Segoe UI", 9, "bold"), relief="flat",
            cursor="hand2", padx=10, pady=3,
            borderwidth=0, highlightthickness=0,
        )
        b.pack(side="left", padx=(0, 4))
        return b

    def _pick_view(self, mode: str) -> None:
        if mode not in ("list", "grid") or mode == self._view_mode:
            return
        self._view_mode = mode
        self._paint_view_toggle()
        if self._on_view_mode:
            try:
                self._on_view_mode(mode)
            except Exception:   # pylint: disable=broad-except
                _log.exception("on_view_mode callback raised")

    def _paint_view_toggle(self) -> None:
        t = self._t
        active_bg   = t.get("sel_bg", _SELECTED)
        active_fg   = t.get("sel_fg", _SEL_FG)
        inactive_bg = t.get("bg3",    _SURFACE)
        inactive_fg = t.get("fg",     "#333333")
        for mode, btn in self._view_btns.items():
            if mode == self._view_mode:
                btn.configure(bg=active_bg, fg=active_fg,
                              activebackground=active_bg,
                              activeforeground=active_fg)
            else:
                btn.configure(bg=inactive_bg, fg=inactive_fg,
                              activebackground=t.get("bg2", _ROW_ALT),
                              activeforeground=inactive_fg)

    def set_view_mode(self, mode: str) -> None:
        """Programmatically reflect the active view without firing the
        callback (used by ResultsPage at init when hydrating from
        persisted Settings)."""
        if mode in ("list", "grid"):
            self._view_mode = mode
            if self._view_btns:
                self._paint_view_toggle()

    def _mk_btn(self, text: str, cmd, *, role: str = "default") -> tk.Button:
        t   = self._t
        bg  = t.get("bg",  _WHITE)
        fg  = t.get("danger", _RED) if role == "danger" else t.get("fg", "#333333")
        bd  = t.get("border", _BTN_BD)
        b = tk.Button(
            self._inner,
            text=text, command=cmd,
            bg=bg, fg=fg,
            activebackground=t.get("bg3", _SURFACE),
            activeforeground=fg,
            font=("Segoe UI", 10), relief="flat",
            cursor="hand2", padx=10, pady=4,
            highlightbackground=bd, highlightthickness=1,
        )
        b.pack(side="left", padx=3)
        entry = {"btn": b, "role": role}
        self._buttons.append(entry)
        b.bind("<Enter>", lambda _e, en=entry: self._hover(en, True))
        b.bind("<Leave>", lambda _e, en=entry: self._hover(en, False))
        return b

    def _hover(self, entry: Dict[str, object], inside: bool) -> None:
        t = self._t
        base = t.get("bg", _WHITE)
        hover = t.get("bg3", _SURFACE)
        btn = entry["btn"]  # type: ignore[assignment]
        btn.configure(bg=hover if inside else base)  # type: ignore[union-attr]

    def apply_theme(self, t: dict) -> None:
        self._t = t
        bg     = t.get("bg",     _WHITE)
        border = t.get("border", _BORDER)
        fg     = t.get("fg",     "#333333")
        danger = t.get("danger", _RED)
        hover  = t.get("bg3",    _SURFACE)
        self.configure(bg=bg)
        self._inner.configure(bg=bg)
        self._bottom_border.configure(bg=border)
        for entry in self._buttons:
            btn = entry["btn"]  # type: ignore[assignment]
            role = entry["role"]
            btn_fg = danger if role == "danger" else fg  # type: ignore[assignment]
            btn.configure(  # type: ignore[union-attr]
                bg=bg, fg=btn_fg,
                activebackground=hover, activeforeground=btn_fg,
                highlightbackground=border,
            )
        try:
            self._view_strip.configure(bg=bg)
            for child in self._view_strip.winfo_children():
                if isinstance(child, tk.Label):
                    child.configure(bg=bg, fg=t.get("fg_muted", _DIMGRAY))
        except (tk.TclError, AttributeError):
            pass
        self._paint_view_toggle()
        self.set_has_selection(self._has_sel)

    # Five-option rule list shared with the button label "Auto Mark ▼".
    # Order: newer-keep, older-keep, first-keep, last-keep, path-contains.
    # ``select_in_folder`` falls through to ``select_except_first`` in the
    # current ``ResultsPage._auto_mark`` implementation — that is pre-existing
    # behaviour preserved verbatim; a proper path-prompt dialog is a future
    # enhancement.
    _AUTO_MARK_OPTS = [
        ("Mark newer in each group",    "select_except_oldest"),
        ("Mark older in each group",    "select_except_newest"),
        ("Mark all except first",       "select_except_first"),
        ("Mark all except last",        "select_except_last"),
        ("Mark by path contains…",      "select_in_folder"),
    ]

    def _show_auto_mark(self) -> None:
        """Open a native dropdown menu anchored below the Auto Mark button.

        Replaces the previous ``CTkToplevel`` modal (regression introduced in
        145b855 when the legacy MainWindow toolbar's ``tk.Menu`` dropdown
        was not migrated to the new ResultsPage toolbar). Uses the same
        ``tk_popup`` pattern as ``cerebro/v2/ui/toolbar.py::_show_auto_mark_menu``.
        """
        menu = tk.Menu(self, tearoff=0)
        for label, rule in self._AUTO_MARK_OPTS:
            menu.add_command(
                label=label,
                command=lambda r=rule: self._on_auto_mark(r),
            )
        try:
            x = self._auto_btn.winfo_rootx()
            y = self._auto_btn.winfo_rooty() + self._auto_btn.winfo_height()
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def set_has_selection(self, has: bool) -> None:
        self._has_sel = has
        t = self._t
        border = t.get("border", _BTN_BD)
        danger = t.get("danger", _RED)
        self._del_btn.configure(
            highlightbackground=danger if has else border,
            highlightthickness=2 if has else 1,
        )

    def _noop(self) -> None:
        pass


# ===========================================================================
# Filter list (plain row — matches virtual list, no block/tab chrome)
# ===========================================================================

class _FilterListBar(tk.Frame):
    """File-type filter as a single horizontal list of labels (no boxes or tab fills).

    Each tab label includes a live count, e.g. ``Pictures (3,412)``.
    Tabs whose count is zero are visually muted and non-clickable; the
    ``All`` tab is always clickable regardless of count.
    """

    H = 28
    TABS = [
        ("all", "All"),
        ("pictures", "Pictures"),
        ("music", "Music"),
        ("videos", "Videos"),
        ("documents", "Documents"),
        ("archives", "Archives"),
        ("other", "Other"),
    ]

    def __init__(self, master, on_filter: Callable[[str], None], **kw) -> None:
        kw.setdefault("bg", _WHITE)
        kw.setdefault("height", self.H)
        super().__init__(master, **kw)
        self.pack_propagate(False)
        self._on_filter = on_filter
        self._active = "all"
        self._lbls: Dict[str, tk.Label] = {}
        self._seps: List[tk.Label] = []
        self._counts: Dict[str, int] = {k: 0 for k, _ in self.TABS}
        self._disabled: Set[str] = set()
        self._t_theme: dict = {}
        self._build()

    def _build(self) -> None:
        self._bottom_border = tk.Frame(self, bg=_BORDER, height=1)
        self._bottom_border.pack(side="bottom", fill="x")
        self._inner = tk.Frame(self, bg=_WHITE)
        self._inner.pack(side="left", fill="y")

        for i, (key, text) in enumerate(self.TABS):
            if i:
                sep = tk.Label(
                    self._inner,
                    text="·",
                    bg=_WHITE,
                    fg=_DIMGRAY,
                    font=("Segoe UI", 10),
                )
                sep.pack(side="left")
                self._seps.append(sep)
            pad_l = 12 if i == 0 else 6
            lbl = tk.Label(
                self._inner,
                text=text,
                bg=_WHITE,
                fg=_GRAY,
                font=("Segoe UI", 10),
                cursor="hand2",
            )
            lbl.pack(side="left", padx=(pad_l, 6))
            lbl.bind("<Button-1>", lambda _e, k=key: self._click(k))
            lbl.bind("<Enter>", lambda _e, k=key: self._hover(k, True))
            lbl.bind("<Leave>", lambda _e, k=key: self._hover(k, False))
            self._lbls[key] = lbl
        self._set_active("all")

    def apply_theme(self, t: dict) -> None:
        self._t_theme = t
        bg = t.get("bg", _WHITE)
        br = t.get("border", _BORDER)
        self.configure(bg=bg)
        self._inner.configure(bg=bg)
        self._bottom_border.configure(bg=br)
        for sep in self._seps:
            sep.configure(bg=bg, fg=br)
        self._set_active(self._active)

    def set_counts(self, counts: Dict[str, int]) -> None:
        """Update per-bucket counts and re-render tab labels.

        Zero-count tabs (except ``all``) become muted and unclickable.
        """
        for key, _ in self.TABS:
            self._counts[key] = int(counts.get(key, 0))
        self._disabled = {
            k for k, _ in self.TABS
            if k != "all" and self._counts.get(k, 0) == 0
        }
        for key, _ in self.TABS:
            self._lbls[key].configure(
                text=self._label_text(key),
                cursor="arrow" if key in self._disabled else "hand2",
            )
        self._set_active(self._active)

    def _label_text(self, key: str) -> str:
        base = next(t for k, t in self.TABS if k == key)
        count = self._counts.get(key, 0)
        return f"{base} ({count:,})"

    def _click(self, key: str) -> None:
        if key in self._disabled:
            return
        self._set_active(key)
        self._on_filter(key)

    def _hover(self, key: str, inside: bool) -> None:
        if key in self._disabled or key == self._active:
            return
        t = self._t_theme
        bg = t.get("bg", _WHITE)
        fg2 = t.get("fg2", _GRAY)
        fg = t.get("fg", "#333333")
        self._lbls[key].configure(
            bg=bg,
            fg=fg if inside else fg2,
        )

    def _set_active(self, key: str) -> None:
        self._active = key
        t = self._t_theme
        bg = t.get("bg", _WHITE)
        acc = t.get("accent", _NAVY_MID)
        fg2 = t.get("fg2", _GRAY)
        fg_mute = t.get("fg_muted", _DIMGRAY)
        for k, w in self._lbls.items():
            disabled = k in self._disabled
            on = (k == key) and not disabled
            if disabled:
                fg = fg_mute
            elif on:
                fg = acc
            else:
                fg = fg2
            w.configure(
                bg=bg,
                fg=fg,
                font=("Segoe UI", 10, "bold") if on else ("Segoe UI", 10),
            )


# ===========================================================================
# ResultsPage
# ===========================================================================

class ResultsPage(tk.Frame):
    """Full results page. Call load_results(groups) after a scan completes."""

    def __init__(self, master,
                 on_open_group: Optional[Callable[[int, List[DuplicateGroup]], None]] = None,
                 on_navigate_home: Optional[Callable[[], None]] = None,
                 on_rescan: Optional[Callable[[], None]] = None,
                 **kw) -> None:
        initial = ThemeApplicator.get().build_tokens()
        kw.setdefault("bg", initial.get("bg", _WHITE))
        super().__init__(master, **kw)
        self._on_open_group = on_open_group
        # Delete-flow navigation hooks owned by AppShell: after the celebration
        # overlay and when the user picks "Rescan" in the summary dialog.
        self._on_navigate_home = on_navigate_home
        self._on_rescan        = on_rescan
        self._groups:   List[DuplicateGroup] = []
        self._all_rows: List[Dict]           = []  # flat, unfiltered
        self._filter    = "all"
        self._scan_mode: str = "files"  # set by load_results; feeds the
                                        # delete ceremony's media-noun labels
        self._t: dict = initial
        # Phase 6: view-mode state. Hydrated from Settings on first build;
        # saved back whenever the toolbar toggle fires.
        self._view_mode: str = self._load_view_mode_pref()
        self._build()
        # Initial view follows the persisted preference; do it after
        # _build so both child widgets exist.
        self._activate_view(self._view_mode, fire_callback=False)
        self._apply_theme(initial)
        ThemeApplicator.get().register(self._apply_theme)

    # ------------------------------------------------------------------
    # Persisted view-mode preference (Phase 6)
    #
    # Kept deliberately tolerant: if Settings can't be loaded for any
    # reason (corrupt JSON, missing file, import failure) we fall back
    # to "list" silently — the toggle button still works, it just
    # won't persist. Same pattern for saving.

    def _load_view_mode_pref(self) -> str:
        try:
            from cerebro.v2.ui.settings_dialog import Settings, get_settings_path
            s = Settings.load(get_settings_path())
            mode = str(s.ui.get("results_view_mode", "list"))
            return mode if mode in ("list", "grid") else "list"
        except Exception:   # pylint: disable=broad-except
            _log.debug("Could not load view-mode pref; defaulting to list",
                       exc_info=True)
            return "list"

    def _save_view_mode_pref(self, mode: str) -> None:
        try:
            from cerebro.v2.ui.settings_dialog import Settings, get_settings_path
            path = get_settings_path()
            s = Settings.load(path)
            s.ui["results_view_mode"] = mode
            s.save(path)
        except Exception:   # pylint: disable=broad-except
            _log.debug("Could not persist view-mode pref", exc_info=True)

    # ------------------------------------------------------------------
    def _build(self) -> None:
        self._stats_bar = _StatsBar(self)
        self._stats_bar.pack(fill="x")

        self._toolbar = _ActionToolbar(
            self,
            on_delete=self._delete_checked,
            on_move=self._move_checked,
            on_auto_mark=self._auto_mark,
            on_view_mode=self._on_view_mode_changed,
            initial_view_mode=self._view_mode,
        )
        self._toolbar.pack(fill="x")

        self._filter_bar = _FilterListBar(self, on_filter=self._apply_filter)
        self._filter_bar.pack(fill="x")

        self._col_hdr = _ColHeader(self, on_sort=self._on_sort)
        self._col_hdr.pack(fill="x")

        # Body: hosts three interchangeable views — list, grid, and the
        # side-by-side comparison takeover. Only one is packed at a time.
        self._body = tk.Frame(self, bg=self._t.get("bg", _WHITE))
        self._body.pack(fill="both", expand=True)

        # ── List view (existing Phase-5 VirtualFileGrid) ───────────
        self._list_frame = tk.Frame(self._body, bg=self._t.get("bg", _WHITE))
        self._list_grid = VirtualFileGrid(
            self._list_frame,
            on_open_group=self._open_group_by_id,
        )
        self._list_vsb = ttk.Scrollbar(
            self._list_frame, orient="vertical",
            command=self._list_grid.yview,
        )
        self._list_grid.configure(yscrollcommand=self._list_vsb.set)
        self._list_vsb.pack(side="right", fill="y")
        self._list_grid.pack(fill="both", expand=True)
        self._list_grid.bind("<<CheckChanged>>", self._on_check_changed)

        # ── Grid view (Phase 6 VirtualThumbGrid) ───────────────────
        from cerebro.v2.ui.widgets.virtual_thumb_grid import VirtualThumbGrid
        self._thumb_frame = tk.Frame(self._body, bg=self._t.get("bg", _WHITE))
        self._thumb_grid = VirtualThumbGrid(
            self._thumb_frame,
            on_open_file=self._on_thumb_dbl_click,
        )
        self._thumb_vsb = ttk.Scrollbar(
            self._thumb_frame, orient="vertical",
            command=self._thumb_grid.yview,
        )
        self._thumb_grid.configure(yscrollcommand=self._thumb_vsb.set)
        self._thumb_vsb.pack(side="right", fill="y")
        self._thumb_grid.pack(fill="both", expand=True)
        self._thumb_grid.bind("<<CheckChanged>>", self._on_check_changed)

        # ── Comparison view (revived legacy PreviewPanel) ─────────
        # Built lazily on first image double-click to keep cold start
        # fast and avoid pulling PIL/ZoomCanvas into the import graph
        # when the user never uses grid mode.
        self._cmp_frame: Optional[tk.Frame] = None
        self._cmp_panel: Any = None

        # Active grid pointer — re-bound on view-mode swap so existing
        # handlers (_auto_mark, _delete_checked, _remove_paths,
        # _apply_filter, sort) keep working through self._grid.
        self._grid = self._list_grid

        # Empty state
        self._empty_lbl = tk.Label(
            self._body,
            text="No scan results yet.\nRun a scan from the Scan tab.",
            bg=self._t.get("bg", _WHITE),
            fg=self._t.get("fg_muted", _DIMGRAY),
            font=("Segoe UI", 11), justify="center",
        )
        self._empty_lbl.place(relx=0.5, rely=0.4, anchor="center")

    # ------------------------------------------------------------------
    # View-mode management (Phase 6)

    def _activate_view(self, mode: str, *, fire_callback: bool = True) -> None:
        """Pack the requested view (``list`` or ``grid``) and hide the other.

        Leaves the comparison takeover intact if it's currently packed —
        exiting comparison is the user's explicit Back action, not a
        side-effect of toggling the segmented control.
        """
        if mode not in ("list", "grid"):
            return
        self._view_mode = mode
        # Unpack both list+grid frames before re-packing the chosen one
        # so ordering is deterministic regardless of previous state.
        for frame in (self._list_frame, self._thumb_frame):
            try:
                frame.pack_forget()
            except tk.TclError:
                pass
        target_frame = self._thumb_frame if mode == "grid" else self._list_frame
        target_frame.pack(fill="both", expand=True)
        # Re-point _grid so the legacy helpers (_auto_mark, _delete_checked,
        # sort, _remove_paths) operate on the active widget.
        self._grid = self._thumb_grid if mode == "grid" else self._list_grid
        # Show/hide the column header — it's a list-mode affordance only.
        try:
            if mode == "list":
                self._col_hdr.pack_configure(fill="x")
                # If col header got pack_forget'd before, repack it above body
                if not self._col_hdr.winfo_ismapped():
                    self._col_hdr.pack(fill="x", before=self._body)
            else:
                self._col_hdr.pack_forget()
        except tk.TclError:
            pass
        self._toolbar.set_view_mode(mode)
        if fire_callback:
            self._save_view_mode_pref(mode)

    def _on_view_mode_changed(self, mode: str) -> None:
        # User-initiated toggle from the toolbar. Before swapping, bring
        # the active grid's check set across so marks are preserved.
        self._sync_checked_to(mode)
        self._activate_view(mode, fire_callback=True)
        # Re-render the newly-active grid now that it owns the checks
        # and current visibility state.
        try:
            self._grid._render()   # pylint: disable=protected-access
        except Exception:          # pylint: disable=broad-except
            pass

    def _sync_checked_to(self, target_mode: str) -> None:
        """Copy ``_checked`` from the currently-active grid into the one
        that's about to become active.

        Both grids hold the same row-list in the same order (they're fed
        from ``_apply_filter`` together), so the integer indices map
        one-to-one.
        """
        src = self._thumb_grid if self._view_mode == "grid" else self._list_grid
        dst = self._thumb_grid if target_mode == "grid" else self._list_grid
        if src is dst:
            return
        dst._checked = set(src._checked)   # pylint: disable=protected-access

    # ------------------------------------------------------------------
    # Comparison takeover (revived legacy PreviewPanel — Phase 6)
    #
    # Entered by double-clicking an image tile in grid mode. Left via
    # the Back button in its own chrome. While this view is packed the
    # list/grid are pack_forgotten; the toolbar stays visible so the
    # user can still hit DELETE/MOVE on whichever check set they had.

    def _ensure_comparison_view(self) -> None:
        if self._cmp_frame is not None:
            return
        try:
            from cerebro.v2.ui.preview_panel import PreviewPanel
        except ImportError:
            _log.exception("PreviewPanel import failed — side-by-side disabled")
            return

        self._cmp_frame = tk.Frame(self._body, bg=self._t.get("bg", _WHITE))
        # Top bar: Back button + title.
        bar = tk.Frame(self._cmp_frame, bg=self._t.get("bg", _WHITE), height=38)
        bar.pack(fill="x")
        bar.pack_propagate(False)
        tk.Button(
            bar, text="\u2190  Back to grid", command=self._exit_comparison,
            bg="#2E75B6", fg=_WHITE,
            activebackground="#3A87CC", activeforeground=_WHITE,
            font=("Segoe UI", 9, "bold"), relief="flat",
            cursor="hand2", padx=14, pady=5,
            borderwidth=0, highlightthickness=0,
        ).pack(side="left", padx=10, pady=6)
        self._cmp_title = tk.Label(
            bar, text="", bg=self._t.get("bg", _WHITE),
            fg=self._t.get("fg", "#333333"),
            font=("Segoe UI", 10, "bold"),
        )
        self._cmp_title.pack(side="left", padx=10)

        # The PreviewPanel itself. set_layout_mode("ashisoft") drops the
        # collapsible header so it fills the takeover region.
        self._cmp_panel = PreviewPanel(self._cmp_frame)
        self._cmp_panel.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        try:
            self._cmp_panel.set_layout_mode("compact")
        except Exception:   # pylint: disable=broad-except
            pass

    def _enter_comparison(self, row: Dict) -> None:
        """Open side-by-side comparison for an image row (A) vs its
        group peer (B). Non-image rows never reach this path — the
        grid's double-click handler routes them to Review instead."""
        self._ensure_comparison_view()
        if self._cmp_panel is None:
            # PreviewPanel unavailable (e.g. missing PIL) — fall back
            # to Review so the double-click doesn't no-op.
            self._open_group_by_id(int(row.get("group_id", -1)))
            return

        # Resolve the DuplicateFile for file A and a peer B from the
        # same group.
        gid = int(row.get("group_id", -1))
        target_path = str(row.get("path", ""))
        file_a = None
        file_b = None
        for g in self._groups:
            if g.group_id != gid:
                continue
            for f in g.files:
                if str(f.path) == target_path:
                    file_a = f
                    break
            if file_a is not None:
                # Prefer the first *other* file in the group.
                for f in g.files:
                    if str(f.path) != target_path:
                        file_b = f
                        break
            break

        try:
            self._cmp_panel.load_comparison(file_a, file_b)
        except Exception:   # pylint: disable=broad-except
            _log.exception("PreviewPanel.load_comparison failed")
            return
        # Title: "filename.jpg  ↔  peer.jpg  (group 3, 5 copies)"
        try:
            name_a = Path(str(getattr(file_a, "path", "") or "")).name or "(A)"
            name_b = Path(str(getattr(file_b, "path", "") or "")).name if file_b else "(none)"
            count = len(self._thumb_grid._group_counts) and \
                self._thumb_grid._group_counts.get(gid, 0)  # pylint: disable=protected-access
            self._cmp_title.configure(
                text=f"{name_a}  \u2194  {name_b}   ·   group {gid}, {count} copies"
            )
        except tk.TclError:
            pass

        # Pack the takeover, hide the grid view.
        for frame in (self._list_frame, self._thumb_frame):
            try:
                frame.pack_forget()
            except tk.TclError:
                pass
        self._cmp_frame.pack(fill="both", expand=True)

    def _exit_comparison(self) -> None:
        if self._cmp_frame is None:
            return
        try:
            self._cmp_frame.pack_forget()
        except tk.TclError:
            pass
        # Restore whichever view was active before the takeover.
        self._activate_view(self._view_mode, fire_callback=False)

    def _on_thumb_dbl_click(self, row: Dict) -> None:
        """Route a grid-tile double-click:
         - image → side-by-side comparison takeover
         - non-image (incl. video, for now) → Review page

        Keeps the list-mode double-click behavior (`on_open_group`)
        untouched so the PreviewPanel stays hidden outside grid mode
        per the Phase 6 rule.
        """
        from cerebro.v2.ui.widgets.virtual_thumb_grid import is_image_row
        if is_image_row(row):
            self._enter_comparison(row)
        else:
            self._open_group_by_id(int(row.get("group_id", -1)))

    # ------------------------------------------------------------------
    # Theme

    def _apply_theme(self, t: dict) -> None:
        self._t = t
        bg = t.get("bg", _WHITE)
        self.configure(bg=bg)
        try:
            self._body.configure(bg=bg)
            self._list_frame.configure(bg=bg)
            self._thumb_frame.configure(bg=bg)
            if self._cmp_frame is not None:
                self._cmp_frame.configure(bg=bg)
                self._cmp_title.configure(bg=bg, fg=t.get("fg", "#333333"))
        except Exception:
            pass
        try:
            self._empty_lbl.configure(bg=bg, fg=t.get("fg_muted", _DIMGRAY))
        except Exception:
            pass
        self._list_grid.apply_theme(t)
        self._thumb_grid.apply_theme(t)
        for child in (
            getattr(self, "_stats_bar",  None),
            getattr(self, "_toolbar",    None),
            getattr(self, "_filter_bar", None),
            getattr(self, "_col_hdr",    None),
        ):
            if child is None:
                continue
            try:
                child.apply_theme(t)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Public API

    def load_results(self, groups: List[DuplicateGroup], mode: str = "files") -> None:
        self._groups = groups
        self._scan_mode = mode or "files"
        self._empty_lbl.place_forget()
        self._all_rows = self._build_rows(groups)
        self._refresh_type_counts()
        self._apply_filter(self._filter)

        total_files = sum(len(g.files) for g in groups)
        dupes       = sum(max(0, len(g.files) - 1) for g in groups)
        recoverable = sum(g.reclaimable for g in groups)
        self._stats_bar.update(total_files, dupes, recoverable)

    def _refresh_type_counts(self) -> None:
        """Recompute per-bucket file counts and push to the filter bar.

        If the currently-active filter has dropped to zero (e.g. after a delete
        removed the last Pictures file), fall back to ``all`` so the user is
        never stranded on a muted, non-clickable tab.
        """
        counts: Dict[str, int] = {
            "all": len(self._all_rows),
            "pictures": 0, "music": 0, "videos": 0,
            "documents": 0, "archives": 0, "other": 0,
        }
        for r in self._all_rows:
            counts[classify_file(r.get("extension", ""))] += 1
        self._filter_bar.set_counts(counts)
        if self._filter != "all" and counts.get(self._filter, 0) == 0:
            self._filter = "all"
            self._filter_bar._set_active("all")

    def _build_rows(self, groups: List[DuplicateGroup]) -> List[Dict]:
        rows = []
        for shade, g in enumerate(groups):
            for fi, f in enumerate(g.files):
                rows.append({
                    "group_id":    g.group_id,
                    "file_idx":    fi,
                    "name":        Path(f.path).name,
                    "size":        f.size,
                    "size_str":    _fmt_size(f.size),
                    "date":        _fmt_date(f.modified),
                    "folder":      str(Path(f.path).parent),
                    "path":        str(f.path),
                    "extension":   getattr(f, "extension", Path(f.path).suffix.lower()),
                    "_group_shade": shade % 2 == 1,
                })
        return rows

    # ------------------------------------------------------------------
    # Filtering

    def _apply_filter(self, key: str) -> None:
        self._filter = key
        if key == "other":
            rows = [
                r for r in self._all_rows
                if (r.get("extension", "") or "").lower() not in _EXT_ALL_KNOWN
            ]
        else:
            exts = _FILTER_EXTS.get(key)
            if exts is None:
                rows = self._all_rows
            else:
                rows = [
                    r for r in self._all_rows
                    if (r.get("extension", "") or "").lower() in exts
                ]
        # Feed BOTH views from the same filtered-row list so their row
        # indices stay aligned. Without this, toggling from list to grid
        # would show stale data (or the grid would render only on first
        # activation, not when the filter changes while it's hidden).
        self._list_grid.load(list(rows))
        self._thumb_grid.load(list(rows))

    # ------------------------------------------------------------------
    # Sorting

    def _on_sort(self, col: str) -> None:
        # Sort BOTH views with the same column and direction. We can't
        # sort only the list view: the check-set is a set of integer
        # indices into the loaded row list, and those indices must
        # point at the same rows across the two widgets, or toggling
        # views would silently re-target the user's marks.
        #
        # We let the list's own toggle logic compute the direction
        # (it flips when col is unchanged), then mirror the post-sort
        # row order straight onto the grid's row list and have the
        # grid just re-render — avoids fighting two independent
        # toggle state machines.
        self._list_grid.sort_by(col)
        self._thumb_grid._rows = list(self._list_grid._rows)  # pylint: disable=protected-access
        self._thumb_grid._selected_idx = 0 if self._thumb_grid._rows else None  # type: ignore[attr-defined]
        self._thumb_grid._scroll_y = 0                       # type: ignore[attr-defined]
        self._thumb_grid._recount_groups()                   # type: ignore[attr-defined]
        self._thumb_grid._update_total_h()                   # type: ignore[attr-defined]
        self._thumb_grid._render()                           # type: ignore[attr-defined]

    # ------------------------------------------------------------------
    # Selection / check

    def _on_check_changed(self, event=None) -> None:
        # Mirror the change across both grids so toggling views never
        # loses marks. The originating widget is ``event.widget`` —
        # treat it as the source of truth; copy its ``_checked`` onto
        # the other widget but do NOT fire its render to avoid an
        # infinite <<CheckChanged>> ping-pong (copying the set doesn't
        # generate an event anyway, but being explicit here keeps the
        # invariant obvious).
        src = event.widget if event is not None else self._grid
        other = self._thumb_grid if src is self._list_grid else self._list_grid
        if src is not other:
            other._checked = set(src._checked)   # pylint: disable=protected-access
            try:
                other._render()                  # pylint: disable=protected-access
            except Exception:                    # pylint: disable=broad-except
                pass
        has = self._grid.get_checked_count() > 0
        self._toolbar.set_has_selection(has)

    # ------------------------------------------------------------------
    # Actions

    def _auto_mark(self, rule: str) -> None:
        """Apply simple auto-mark rules client-side."""
        if not self._groups:
            return
        rows = self._grid._rows
        group_map: Dict[int, List[int]] = {}
        for idx, row in enumerate(rows):
            gid = row["group_id"]
            group_map.setdefault(gid, []).append(idx)

        new_checked: Set[int] = set()
        for gid, idxs in group_map.items():
            if rule in ("select_except_oldest", "select_except_newest"):
                dated = sorted(idxs, key=lambda i: rows[i].get("date", ""))
                keep = dated[0] if rule == "select_except_oldest" else dated[-1]
                new_checked.update(i for i in idxs if i != keep)
            elif rule == "select_except_first":
                new_checked.update(idxs[1:])
            elif rule == "select_except_last":
                new_checked.update(idxs[:-1])
            else:
                new_checked.update(idxs[1:])

        self._grid._checked = new_checked
        self._grid._render()
        self._grid._fire_check_change()

    def _delete_checked(self) -> None:
        """Run the 4-step delete ceremony on the currently-checked rows.

        Faithful port of the legacy ``MainWindow._on_delete_selected`` flow
        (introduced in 8496839; docstring there: *"4-step modal confirmation
        + celebration flow"*):

            Step 1 — `_DeleteDialog`  "Are you sure?"      Cancel / Confirm
            Step 2 — `_DeleteDialog`  breakdown + Recycle  Cancel / Allow
            Step 3 — `_DeleteProgressDialog` (non-closeable during worker)
            Step 4 — `_DeleteSummaryDialog`                Rescan / OK
            Step 5 — `_DeleteCelebration` 7s overlay → on_navigate_home()

        When 145b855 built the new ResultsPage toolbar and 39a332c retired
        MainWindow, the ceremony was abandoned — this call used to be a
        bare threaded loop over ``DeletionEngine.delete_one``. We now reuse
        the shipped dialog classes via lazy import (startup path still
        never touches ``main_window``).
        """
        checked = self._grid.get_checked_rows()
        if not checked:
            return

        try:
            from cerebro.v2.ui.main_window import (
                _DeleteDialog, _DeleteProgressDialog, _DeleteSummaryDialog,
                _DeleteCelebration, _delete_media_label, _delete_breakdown,
            )
            from cerebro.v2.core.deletion_history_db import log_deletion_event
        except ImportError:
            _log.exception("Delete ceremony unavailable — legacy dialog import failed")
            return

        try:
            from cerebro.utils.formatting import format_bytes
        except ImportError:
            format_bytes = None  # type: ignore[assignment]

        count = len(checked)
        mode  = self._scan_mode
        noun  = _delete_media_label(mode)

        # -- Step 1 ---------------------------------------------------------
        d1 = _DeleteDialog(
            self,
            title="Confirm Deletion",
            icon="🗑",
            headline=f"Delete the selected {noun}?",
            body=(
                f"You have marked {count} {noun} for deletion.\n"
                "They will be moved to the Recycle Bin and can be restored "
                "if needed."
            ),
            btn_cancel="Cancel",
            btn_confirm="Confirm",
            confirm_dangerous=True,
        )
        if not d1.result:
            return

        # -- Step 2 ---------------------------------------------------------
        breakdown   = _delete_breakdown(checked, mode)
        reclaimable = sum(int(r.get("size", 0)) for r in checked)
        reclaimable_str = (
            format_bytes(reclaimable, decimals=1) if format_bytes
            else _fmt_size(reclaimable)
        )

        d2 = _DeleteDialog(
            self,
            title="Move to Recycle Bin",
            icon="♻",
            headline="Moving to Recycle Bin",
            body=(
                f"{breakdown} will be moved to the Recycle Bin.\n\n"
                f"Estimated space freed: {reclaimable_str}"
            ),
            btn_cancel="Cancel",
            btn_confirm="Allow",
            confirm_dangerous=False,
        )
        if not d2.result:
            return

        # -- Step 3 --- modal progress + background worker -----------------
        prog = _DeleteProgressDialog(self, total=count)
        # deleted_row_keys tracks the ORIGINAL row["path"] strings that the
        # grid and _all_rows use as identity — so _remove_paths() drops the
        # right rows on Windows where Path.resolve() may change slash style
        # or letter case.
        success_count:    List[int]    = [0]
        deleted_row_keys: List[str]    = []
        recovered_bytes:  List[int]    = [0]
        failed_files:     List[tuple]  = []

        def _worker() -> None:
            try:
                from cerebro.core.deletion import (
                    DeletionEngine, DeletionPolicy, DeletionRequest,
                )
            except ImportError:
                DeletionEngine = None  # type: ignore[assignment]
                DeletionPolicy = None  # type: ignore[assignment]
                DeletionRequest = None  # type: ignore[assignment]

            engine  = DeletionEngine() if DeletionEngine else None
            request = (
                DeletionRequest(
                    policy=DeletionPolicy.TRASH,
                    metadata={"source": "results_page", "mode": "trash"},
                )
                if (DeletionRequest and DeletionPolicy) else None
            )
            try:
                import send2trash  # fallback path if engine is unavailable
            except ImportError:
                send2trash = None  # type: ignore[assignment]

            for i, row in enumerate(checked):
                row_key = str(row.get("path", ""))
                size    = int(row.get("size", 0) or 0)
                try:
                    fp = Path(row_key).resolve()
                except (OSError, ValueError):
                    fp = Path(row_key)

                def _mark_ok() -> None:
                    success_count[0] += 1
                    deleted_row_keys.append(row_key)
                    recovered_bytes[0] += size
                    try:
                        log_deletion_event(str(fp), size, mode)
                    except (OSError, ValueError, RuntimeError):
                        _log.exception("log_deletion_event failed for %s", fp)

                try:
                    if engine and request:
                        res = engine.delete_one(fp, request)
                        if getattr(res, "success", False):
                            _mark_ok()
                        else:
                            failed_files.append(
                                (str(fp),
                                 getattr(res, "error", None) or "Unknown error")
                            )
                    elif send2trash is not None:
                        send2trash.send2trash(str(fp))
                        _mark_ok()
                    else:
                        failed_files.append(
                            (str(fp), "deletion backend unavailable")
                        )
                except (OSError, ValueError, RuntimeError, AttributeError,
                        TypeError, KeyError, ImportError) as exc:
                    failed_files.append((str(fp), str(exc)))

                self.after(0, lambda done=i + 1: prog.set_progress(done))

            self.after(0, prog.close)

        threading.Thread(target=_worker, daemon=True, name="delete-ceremony").start()
        prog.wait()  # nested event loop — exits when worker calls prog.close()

        # -- Apply model changes before summary ----------------------------
        self._toolbar.set_has_selection(False)
        if deleted_row_keys:
            self._remove_paths(set(deleted_row_keys))
            # Phase 6 piggyback: surface the floating Undo toast that
            # the legacy MainWindow showed after every successful batch
            # delete. Lazy-imported from the same module the delete
            # dialogs came from — no additional startup cost.
            try:
                from cerebro.v2.ui.main_window import _UndoToast
                size_str = (format_bytes(recovered_bytes[0], decimals=1)
                            if format_bytes else f"{recovered_bytes[0]} bytes")
                _UndoToast(
                    self.winfo_toplevel(),
                    count=len(deleted_row_keys),
                    size_str=size_str,
                    deleted_paths=list(deleted_row_keys),
                )
            except Exception:   # pylint: disable=broad-except
                _log.debug("Undo toast unavailable — skipping", exc_info=True)

        # Partial failure — skip summary/celebration, surface errors only.
        if failed_files:
            head = "\n".join(
                f"  • {Path(f).name}: {e}" for f, e in failed_files[:5]
            )
            more = (
                f"\n  … and {len(failed_files) - 5} more"
                if len(failed_files) > 5 else ""
            )
            messagebox.showwarning(
                "Deletion Partial",
                f"Deleted {success_count[0]} of {count} {noun}.\n\n"
                f"Failed:\n{head}{more}",
                parent=self,
            )
            return

        # -- Step 4 --- summary --------------------------------------------
        d4 = _DeleteSummaryDialog(
            self, noun=noun, count=success_count[0], recovered=recovered_bytes[0]
        )

        if d4.result == "rescan":
            if self._on_rescan:
                try:
                    self._on_rescan()
                except Exception:
                    _log.exception("on_rescan callback failed")
            return

        # -- Step 5 --- celebration overlay --------------------------------
        def _done() -> None:
            if self._on_navigate_home:
                try:
                    self._on_navigate_home()
                except Exception:
                    _log.exception("on_navigate_home callback failed")

        _DeleteCelebration(self, noun=noun, on_done=_done)

    def _remove_paths(self, paths: Set[str]) -> None:
        self._all_rows = [r for r in self._all_rows if r["path"] not in paths]
        self._grid._checked.clear()
        # Recount first; may auto-revert active filter to "all" if the current
        # bucket just dropped to zero, so the user isn't stranded on a muted
        # tab. Re-apply the (possibly updated) active filter to repopulate the
        # grid from the pruned _all_rows.
        self._refresh_type_counts()
        self._apply_filter(self._filter)
        self._grid._fire_check_change()

    def _move_checked(self) -> None:
        dest = filedialog.askdirectory(title="Move files to…")
        if not dest:
            return
        checked = self._grid.get_checked_rows()
        if not checked:
            return
        dest_path = Path(dest)
        threading.Thread(
            target=self._move_worker,
            args=(list(checked), dest_path),
            daemon=True,
        ).start()

    def _move_worker(self, rows: List[Dict], dest: Path) -> None:
        import shutil
        moved = set()
        for row in rows:
            src = Path(row["path"])
            try:
                shutil.move(str(src), str(dest / src.name))
                moved.add(row["path"])
            except Exception:
                pass
        self.after(0, lambda: self._remove_paths(moved))

    # ------------------------------------------------------------------
    # Open group in Review

    def _open_group_by_id(self, group_id: int) -> None:
        if self._on_open_group:
            self._on_open_group(group_id, self._groups)

    def get_groups(self) -> List[DuplicateGroup]:
        return self._groups
