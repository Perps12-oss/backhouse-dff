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
from tkinter import filedialog, ttk
from typing import Callable, Dict, List, Optional, Set

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

from cerebro.engines.base_engine import DuplicateGroup
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
        # Two extra cells (Largest duplicate, Biggest group) were added in
        # the Results→Review split: Results is now a pure-overview page, so
        # the stats bar earns a bit more informational weight. "Largest
        # duplicate" = the single biggest file among all duplicate rows;
        # "Biggest group" = how many copies the most-populated group holds
        # (a proxy for "which group is the biggest reclaim target").
        groups = [
            ("files_scanned", self._t.get("fg",        "#111111"), "Files scanned"),
            ("duplicates",    self._t.get("stat_dupes", _RED),     "Duplicates found"),
            ("recoverable",   self._t.get("stat_space", _GREEN),   "Space recoverable"),
            ("largest_dup",   self._t.get("fg",        "#111111"), "Largest duplicate"),
            ("biggest_group", self._t.get("fg",        "#111111"), "Biggest group"),
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
        self._labels["largest_dup"]  .configure(bg=bg, fg=t.get("fg",        "#111111"))
        self._labels["biggest_group"].configure(bg=bg, fg=t.get("fg",        "#111111"))
        files, dupes = self._last_counts
        self._draw_pie(files, dupes)

    def update(
        self,
        files: int,
        dupes: int,
        recoverable: int,
        largest_dup: int = 0,
        biggest_group: int = 0,
    ) -> None:
        self._last_counts = (files, dupes)
        self._labels["files_scanned"].configure(text=f"{files:,}")
        self._labels["duplicates"].configure(text=f"{dupes:,}")
        self._labels["recoverable"].configure(text=_fmt_size(recoverable))
        self._labels["largest_dup"].configure(
            text=_fmt_size(largest_dup) if largest_dup else "—"
        )
        self._labels["biggest_group"].configure(
            text=f"{biggest_group:,} copies" if biggest_group else "—"
        )
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
    """Results action strip — Delete / Move / Copy / Export.

    The Phase-6 "Auto Mark ▼" dropdown and "List / Grid" segmented toggle
    were removed in the Results→Review split: Auto-Mark (now "Smart
    Select") belongs on the Review page where the user has already seen
    thumbnails + file sizes and can make an informed bulk decision; the
    grid view and side-by-side comparison likewise live on Review.
    Results keeps only the per-row checkbox → DELETE path, for users
    who want to hand-curate a subset of the table.
    """
    H = 40

    def __init__(self, master,
                 on_delete: Callable,
                 on_move:   Callable,
                 **kw) -> None:
        t = ThemeApplicator.get().build_tokens()
        kw.setdefault("bg", t.get("bg", _WHITE))
        kw.setdefault("height", self.H)
        super().__init__(master, **kw)
        self.pack_propagate(False)
        self._on_delete    = on_delete
        self._on_move      = on_move
        self._has_sel      = False
        self._t            = t
        self._buttons: List[Dict[str, object]] = []
        self._build()

    def _build(self) -> None:
        bg     = self._t.get("bg",     _WHITE)
        border = self._t.get("border", _BORDER)

        self._bottom_border = tk.Frame(self, bg=border, height=1)
        self._bottom_border.pack(side="bottom", fill="x")
        self._inner = tk.Frame(self, bg=bg)
        self._inner.pack(fill="both", expand=True, padx=8)

        self._del_btn  = self._mk_btn("DELETE",      self._on_delete, role="danger")
        self._mk_btn("MOVE",            self._on_move)
        self._mk_btn("COPY",            self._noop)
        self._mk_btn("Export results",  self._noop)

        # Hint anchor on the right reminding users where the smart-
        # select lives now. Lightweight — plain label, no button.
        tk.Label(
            self._inner,
            text="Smart Select lives on the Review tab \u2192",
            bg=bg, fg=self._t.get("fg_muted", _DIMGRAY),
            font=("Segoe UI", 9, "italic"),
        ).pack(side="right", padx=(0, 4))

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
            for child in self._inner.winfo_children():
                if isinstance(child, tk.Label):
                    child.configure(bg=bg, fg=t.get("fg_muted", _DIMGRAY))
        except (tk.TclError, AttributeError):
            pass
        self.set_has_selection(self._has_sel)

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
    """Results page — scan overview, filter/sort table, batch delete.

    Scope was narrowed after the Phase-6 Results→Review split: preview,
    comparison, and Smart Select moved to the Review page. Results is
    now purely the analytical view: a filterable / sortable table of
    every file in every duplicate group, with manual per-row check-to-
    delete via the Phase-5 ``VirtualFileGrid``.

    Call ``load_results(groups)`` after a scan completes.
    """

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
        self._build()
        self._apply_theme(initial)
        ThemeApplicator.get().register(self._apply_theme)

    # ------------------------------------------------------------------
    def _build(self) -> None:
        self._stats_bar = _StatsBar(self)
        self._stats_bar.pack(fill="x")

        self._toolbar = _ActionToolbar(
            self,
            on_delete=self._delete_checked,
            on_move=self._move_checked,
        )
        self._toolbar.pack(fill="x")

        self._filter_bar = _FilterListBar(self, on_filter=self._apply_filter)
        self._filter_bar.pack(fill="x")

        self._col_hdr = _ColHeader(self, on_sort=self._on_sort)
        self._col_hdr.pack(fill="x")

        self._body = tk.Frame(self, bg=self._t.get("bg", _WHITE))
        self._body.pack(fill="both", expand=True)

        self._grid = VirtualFileGrid(
            self._body,
            on_open_group=self._open_group_by_id,
        )
        self._vsb = ttk.Scrollbar(
            self._body, orient="vertical",
            command=self._grid.yview,
        )
        self._grid.configure(yscrollcommand=self._vsb.set)
        self._vsb.pack(side="right", fill="y")
        self._grid.pack(fill="both", expand=True)
        self._grid.bind("<<CheckChanged>>", self._on_check_changed)

        self._empty_lbl = tk.Label(
            self._body,
            text="No scan results yet.\nRun a scan from the Scan tab.",
            bg=self._t.get("bg", _WHITE),
            fg=self._t.get("fg_muted", _DIMGRAY),
            font=("Segoe UI", 11), justify="center",
        )
        self._empty_lbl.place(relx=0.5, rely=0.4, anchor="center")

    # ------------------------------------------------------------------
    # Theme

    def _apply_theme(self, t: dict) -> None:
        self._t = t
        bg = t.get("bg", _WHITE)
        self.configure(bg=bg)
        try:
            self._body.configure(bg=bg)
        except Exception:
            pass
        try:
            self._empty_lbl.configure(bg=bg, fg=t.get("fg_muted", _DIMGRAY))
        except Exception:
            pass
        self._grid.apply_theme(t)
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

        # Phase-6 part-3 metrics, added when Results became the overview-
        # only page. Computed once per load (scans rarely produce 200K+
        # groups and the walk is O(rows), so inline is fine).
        largest_dup = 0
        biggest_group = 0
        for g in groups:
            copies = len(g.files)
            if copies > biggest_group:
                biggest_group = copies
            for f in g.files:
                size = int(getattr(f, "size", 0) or 0)
                if size > largest_dup:
                    largest_dup = size

        self._stats_bar.update(
            total_files, dupes, recoverable,
            largest_dup=largest_dup,
            biggest_group=biggest_group,
        )

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
        self._grid.load(rows)

    # ------------------------------------------------------------------
    # Sorting

    def _on_sort(self, col: str) -> None:
        self._grid.sort_by(col)

    # ------------------------------------------------------------------
    # Selection / check

    def _on_check_changed(self, _event=None) -> None:
        has = self._grid.get_checked_count() > 0
        self._toolbar.set_has_selection(has)

    # ------------------------------------------------------------------
    # Actions

    def _delete_checked(self) -> None:
        """Run the 4-step delete ceremony on the currently-checked rows.

        All the actual flow lives in ``cerebro.v2.ui.delete_flow`` so the
        Review page's Smart-Select path runs the exact same ceremony.
        """
        checked = self._grid.get_checked_rows()
        if not checked:
            return
        from cerebro.v2.ui.delete_flow import run_delete_ceremony, DeleteItem
        items = [
            DeleteItem(
                path_str=str(r.get("path", "")),
                size=int(r.get("size", 0) or 0),
            )
            for r in checked
        ]
        self._toolbar.set_has_selection(False)
        run_delete_ceremony(
            parent=self,
            items=items,
            scan_mode=self._scan_mode,
            on_remove_paths=self._remove_paths,
            on_navigate_home=self._on_navigate_home,
            on_rescan=self._on_rescan,
            source_tag="results_page",
        )

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
