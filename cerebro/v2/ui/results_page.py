"""
ResultsPage — post-scan Duplicates view (grouped grid + preview, Sprint 2–3).

Stats bar · Action toolbar · Filter list · :class:`DuplicatesView` (DataGrid)
"""
from __future__ import annotations

import logging
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, ttk
from typing import Callable, Dict, List, Optional, Set, TYPE_CHECKING, Tuple

if TYPE_CHECKING:
    from cerebro.v2.coordinator import CerebroCoordinator

from cerebro.v2.state import StateStore
from cerebro.v2.state.actions import (
    ResultsFilesRemoved,
    ResultsViewFilterChanged,
    ResultsViewTextFilterChanged,
    ScanCompleted,
    SetDryRun,
)
from cerebro.v2.ui.widgets.treemap import TreemapWidget
from cerebro.v2.state.app_state import AppState

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
from cerebro.v2.ui.delete_flow import DeleteItem, run_delete_ceremony
from cerebro.v2.ui.duplicates_view import DuplicatesView
from cerebro.v2.ui.file_type_filters import _EXT_ALL_KNOWN, _FILTER_EXTS, classify_file
from cerebro.v2.ui.theme_applicator import ThemeApplicator
from cerebro.v2.state.groups_prune import prune_paths_from_groups

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


def _row_sort_key(col: str) -> Callable[[Dict], object]:
    key_map: Dict[str, Callable[[Dict], object]] = {
        "Name":     lambda r: r.get("name", "").lower(),
        "Size":     lambda r: r.get("size", 0),
        "Date":     lambda r: r.get("date", ""),
        "Folder":   lambda r: r.get("folder", "").lower(),
    }
    return key_map.get(col, lambda r: r.get("name", "").lower())


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

    def set_sort_state(self, col: str, asc: bool) -> None:
        """Row order is already from state; only sync sort metadata (no re-sort)."""
        self._sort_col = col
        self._sort_asc = asc

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
        key = _row_sort_key(col)
        self._rows.sort(key=key, reverse=not self._sort_asc)
        self._checked.clear()
        self._selected_idx = None
        self._render()
        self._fire_check_change()


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
    """Results action strip — Smart Select, Delete, Move, Copy, Export, dry-run."""

    H = 40

    def __init__(self, master,
                 on_delete: Callable,
                 on_move:   Callable,
                 dry_run_var: Optional[tk.BooleanVar] = None,
                 on_dry_run: Optional[Callable] = None,
                 on_smart_menu: Optional[Callable[[tk.Misc], None]] = None,
                 **kw) -> None:
        t = ThemeApplicator.get().build_tokens()
        kw.setdefault("bg", t.get("bg", _WHITE))
        kw.setdefault("height", self.H)
        super().__init__(master, **kw)
        self.pack_propagate(False)
        self._on_delete    = on_delete
        self._on_move      = on_move
        self._dry_run_var  = dry_run_var
        self._on_dry_run   = on_dry_run
        self._on_smart_menu = on_smart_menu
        self._smart_btn: Optional[tk.Button] = None
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
        if self._on_smart_menu is not None:
            self._smart_btn = tk.Button(
                self._inner,
                text="Smart Select \u25BC",
                command=lambda: self._on_smart_menu(self._smart_btn),  # type: ignore[misc]
                bg="#8E44AD", fg="#FFFFFF",
                activebackground="#A255C5", activeforeground="#FFFFFF",
                font=("Segoe UI", 9, "bold"), relief="flat",
                cursor="hand2", padx=12, pady=4,
                borderwidth=0, highlightthickness=0,
            )
            self._smart_btn.pack(side="left", padx=(8, 3))
        self._mk_btn("MOVE",            self._on_move)
        self._mk_btn("COPY",            self._noop)
        self._mk_btn("Export results",  self._noop)

        if self._dry_run_var is not None and self._on_dry_run is not None:
            self._dry_chk = tk.Checkbutton(
                self._inner,
                text="Dry run",
                variable=self._dry_run_var,
                command=self._on_dry_run,
                bg=bg,
                fg=self._t.get("fg2", _GRAY),
                activebackground=bg,
                font=("Segoe UI", 9),
                cursor="hand2",
            )
            self._dry_chk.pack(side="right", padx=(6, 6))

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
        if self._smart_btn is not None:
            self._smart_btn.configure(
                bg="#8E44AD", fg="#FFFFFF",
                activebackground="#A255C5", activeforeground="#FFFFFF",
            )
        try:
            for child in self._inner.winfo_children():
                if isinstance(child, tk.Label):
                    child.configure(bg=bg, fg=t.get("fg_muted", _DIMGRAY))
                if isinstance(child, tk.Checkbutton):
                    child.configure(
                        bg=bg,
                        fg=t.get("fg2", _GRAY),
                        activebackground=bg,
                        selectcolor=t.get("bg3", _SURFACE),
                    )
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

    def __init__(
        self,
        master,
        on_filter: Callable[[str], None],
        *,
        state_driven: bool = False,
        **kw,
    ) -> None:
        kw.setdefault("bg", _WHITE)
        kw.setdefault("height", self.H)
        super().__init__(master, **kw)
        self.pack_propagate(False)
        self._on_filter = on_filter
        self._state_driven = state_driven
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
        if not self._state_driven:
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
# Smart Select rules (same semantics as former Review page)
# ===========================================================================

SMART_SELECT_RULES: List[Tuple[str, str]] = [
    ("Mark all except the oldest in each group", "select_except_oldest"),
    ("Mark all except the newest in each group", "select_except_newest"),
    ("Mark all except the first listed", "select_except_first"),
    ("Mark all except the last listed", "select_except_last"),
    ("Mark all except the largest in each group", "select_except_largest"),
]


# ===========================================================================
# ResultsPage
# ===========================================================================

class ResultsPage(tk.Frame):
    """Post-scan Duplicates: grouped grid, preview, filter-aware Smart Select.

    One row per duplicate group (expand for files). Sort and filter are driven
    from :class:`AppState` via :class:`DuplicatesView` and the coordinator.
    """

    def __init__(
        self,
        master: tk.Misc,
        on_open_group: Optional[
            Callable[[int, List[DuplicateGroup]], None]
        ] = None,
        on_navigate_home: Optional[Callable[[], None]] = None,
        on_rescan: Optional[Callable[[], None]] = None,
        store: Optional[StateStore] = None,
        coordinator: Optional["CerebroCoordinator"] = None,
        **kw,
    ) -> None:
        initial = ThemeApplicator.get().build_tokens()
        kw.setdefault("bg", initial.get("bg", _WHITE))
        super().__init__(master, **kw)
        self._on_open_group = on_open_group
        self._on_navigate_home = on_navigate_home
        self._on_rescan = on_rescan
        self._store = store
        self._coordinator = coordinator
        self._use_state_for_view = store is not None and coordinator is not None
        self._groups: List[DuplicateGroup] = []
        self._filter = "all"
        self._local_text_filter: str = ""
        self._search_after: Optional[str] = None
        self._dry_run_var = tk.BooleanVar(
            value=(store.get_state().dry_run if store is not None else False)
        )
        self._scan_mode: str = "files"
        self._t: dict = initial
        self._dupes: Optional[DuplicatesView] = None
        self._build()
        self._apply_theme(initial)
        ThemeApplicator.get().register(self._apply_theme)
        if self._store is not None:
            self._store.subscribe(self._on_store)

    def _build(self) -> None:
        self._stats_bar = _StatsBar(self)
        self._stats_bar.pack(fill="x")

        self._treemap_pane = tk.Frame(self, bg=self._t.get("bg", _WHITE), height=120)
        self._treemap_pane.pack(fill="x")
        self._treemap_pane.pack_propagate(False)
        self._treemap = TreemapWidget(
            self._treemap_pane,
            on_group_select=self._on_treemap_select,
        )
        self._treemap.pack(fill="both", expand=True)

        self._search_row = tk.Frame(self, bg=self._t.get("bg", _WHITE))
        self._search_row.pack(fill="x", padx=8, pady=(4, 0))
        tk.Label(
            self._search_row,
            text="Search",
            bg=self._t.get("bg", _WHITE),
            fg=self._t.get("fg2", _GRAY),
            font=("Segoe UI", 9),
        ).pack(side="left", padx=(0, 6))
        self._search_entry = tk.Entry(
            self._search_row,
            width=48,
            font=("Segoe UI", 10),
        )
        self._search_entry.pack(side="left", fill="x", expand=True)
        self._search_entry.bind("<KeyRelease>", self._on_search_key)
        if self._use_state_for_view and self._store is not None:
            self._search_entry.insert(0, self._store.get_state().results_text_filter)

        smart = (
            self._show_smart_select_menu
            if self._use_state_for_view
            else None
        )
        self._toolbar = _ActionToolbar(
            self,
            on_delete=self._delete_selected_files,
            on_move=self._move_selected_files,
            dry_run_var=self._dry_run_var if self._use_state_for_view else None,
            on_dry_run=self._on_dry_run_toggled if self._use_state_for_view else None,
            on_smart_menu=smart,
        )
        self._toolbar.pack(fill="x")

        self._filter_bar = _FilterListBar(
            self,
            on_filter=self._on_filter_key,
            state_driven=self._use_state_for_view,
        )
        self._filter_bar.pack(fill="x")

        self._body = tk.Frame(self, bg=self._t.get("bg", _WHITE))
        self._body.pack(fill="both", expand=True)

        if (
            self._use_state_for_view
            and self._store is not None
            and self._coordinator is not None
        ):

            def _emit_open(gid: int, grps: List[DuplicateGroup]) -> None:
                if self._on_open_group is not None:
                    self._on_open_group(gid, grps)

            self._dupes = DuplicatesView(
                self._body,
                store=self._store,
                coordinator=self._coordinator,
                on_open_group=_emit_open,
                on_remove_paths=self._remove_paths,
                on_navigate_home=self._on_navigate_home,
                on_rescan=self._on_rescan,
                get_scan_mode=lambda: self._scan_mode,
                on_file_selection_changed=self._on_dupes_file_selection,
            )
            self._dupes.pack(fill="both", expand=True)
        else:
            tk.Label(
                self._body,
                text="Results grid requires app state (store + coordinator).",
                bg=self._t.get("bg", _WHITE),
                fg=self._t.get("fg_muted", _DIMGRAY),
                font=("Segoe UI", 10),
            ).pack(expand=True)

        self._empty_lbl = tk.Label(
            self._body,
            text="No scan results yet.\nRun a scan from the Scan tab.",
            bg=self._t.get("bg", _WHITE),
            fg=self._t.get("fg_muted", _DIMGRAY),
            font=("Segoe UI", 11),
            justify="center",
        )

    def _on_dry_run_toggled(self) -> None:
        if self._use_state_for_view and self._coordinator is not None:
            self._coordinator.set_dry_run(bool(self._dry_run_var.get()))

    def _on_search_key(self, _event: object = None) -> None:
        if self._use_state_for_view and self._coordinator is not None:
            if self._search_after is not None:
                self.after_cancel(self._search_after)
            self._search_after = self.after(200, self._flush_search_to_state)
        else:
            self._local_text_filter = self._search_entry.get()
            if self._dupes is not None:
                self._dupes.refresh_from_state()

    def _flush_search_to_state(self) -> None:
        self._search_after = None
        if self._coordinator is not None:
            self._coordinator.results_set_text_filter(self._search_entry.get())

    def _on_store(self, s: AppState, old: AppState, action: object) -> None:
        if not self._use_state_for_view:
            return
        if isinstance(action, SetDryRun) or (
            old is not None and s.dry_run != old.dry_run
        ):
            self._dry_run_var.set(s.dry_run)
        if isinstance(action, ResultsViewTextFilterChanged):
            tx = s.results_text_filter
            if self._search_entry.get() != tx:
                self._search_entry.delete(0, tk.END)
                self._search_entry.insert(0, tx)
        if isinstance(action, ResultsViewFilterChanged):
            self._filter = s.results_file_filter
            self._filter_bar._set_active(s.results_file_filter)
        if isinstance(action, ScanCompleted):
            self._groups = list(action.groups)
            self._treemap.load(self._groups)
        if isinstance(action, ResultsFilesRemoved):
            self._groups = list(s.groups)
            self._treemap.load(self._groups)

    def _on_treemap_select(self, group_id: int) -> None:
        if self._dupes is not None and hasattr(self._dupes, "scroll_to_group"):
            self._dupes.scroll_to_group(group_id)

    def _on_filter_key(self, key: str) -> None:
        if self._use_state_for_view and self._coordinator is not None:
            self._coordinator.results_set_filter(key)
        else:
            self._filter = key
            self._filter_bar._set_active(key)
            if self._dupes is not None:
                self._dupes.refresh_from_state()

    def _apply_theme(self, t: dict) -> None:
        self._t = t
        bg = t.get("bg", _WHITE)
        self.configure(bg=bg)
        try:
            self._search_row.configure(bg=bg)
            for c in self._search_row.winfo_children():
                if isinstance(c, (tk.Label, tk.Entry)):
                    c.configure(
                        bg=bg,
                        fg=t.get("fg2", _GRAY)
                        if isinstance(c, tk.Label)
                        else t.get("fg", "#111"),
                    )
        except (tk.TclError, AttributeError):
            pass
        try:
            self._body.configure(bg=bg)
        except (tk.TclError, AttributeError):
            pass
        try:
            self._empty_lbl.configure(bg=bg, fg=t.get("fg_muted", _DIMGRAY))
        except (tk.TclError, AttributeError):
            pass
        if self._dupes is not None:
            self._dupes.apply_theme(t)
        try:
            self._treemap_pane.configure(bg=bg)
            self._treemap.apply_theme(t)
        except (tk.TclError, AttributeError):
            pass
        for child in (
            getattr(self, "_stats_bar", None),
            getattr(self, "_toolbar", None),
            getattr(self, "_filter_bar", None),
        ):
            if child is None:
                continue
            try:
                child.apply_theme(t)
            except (tk.TclError, AttributeError):
                pass

    def _on_dupes_file_selection(self, n_files: int) -> None:
        self._toolbar.set_has_selection(n_files > 0)

    def _show_smart_select_menu(self, anchor: tk.Misc) -> None:
        if not self._groups or self._dupes is None:
            return
        menu = tk.Menu(self, tearoff=0)
        for label, rule in SMART_SELECT_RULES:
            menu.add_command(
                label=label,
                command=lambda r=rule: self._dupes.run_smart_select(r),  # type: ignore[union-attr]
            )
        try:
            x = anchor.winfo_rootx()
            y = anchor.winfo_rooty() + anchor.winfo_height()
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def load_results(self, groups: List[DuplicateGroup], mode: str = "files") -> None:
        self._groups = list(groups)
        self._scan_mode = mode or "files"
        if not groups:
            self._empty_lbl.place(relx=0.5, rely=0.4, anchor="center")
            self._empty_lbl.lift()
        else:
            self._empty_lbl.place_forget()
        self._refresh_type_counts()
        if self._dupes is not None:
            self._dupes.set_groups(self._groups)
        if self._use_state_for_view and self._store is not None:
            s = self._store.get_state()
            self._filter = s.results_file_filter
            self._filter_bar._set_active(s.results_file_filter)

        total_files = sum(len(g.files) for g in groups)
        dupes = sum(max(0, len(g.files) - 1) for g in groups)
        recoverable = sum(g.reclaimable for g in groups)
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
            total_files,
            dupes,
            recoverable,
            largest_dup=largest_dup,
            biggest_group=biggest_group,
        )
        self._treemap.load(self._groups)

    def _refresh_type_counts(self) -> None:
        counts: Dict[str, int] = {
            "all": 0,
            "pictures": 0,
            "music": 0,
            "videos": 0,
            "documents": 0,
            "archives": 0,
            "other": 0,
        }
        for g in self._groups:
            for f in g.files:
                counts["all"] += 1
                ext = getattr(f, "extension", None) or Path(f.path).suffix
                counts[classify_file(ext)] += 1
        self._filter_bar.set_counts(counts)
        if self._filter != "all" and counts.get(self._filter, 0) == 0:
            if self._use_state_for_view and self._coordinator is not None:
                self._coordinator.results_set_filter("all")
            else:
                self._filter = "all"
                self._filter_bar._set_active("all")

    def _delete_selected_files(self) -> None:
        if self._dupes is None:
            return
        paths = self._dupes.get_selected_file_paths()
        if not paths:
            group_ids = self._dupes.get_selected_group_ids()
            if group_ids:
                self._delete_selected_group(group_ids[0])
            return
        items = [
            DeleteItem(path_str=p, size=_size_on_disk(p)) for p in paths
        ]
        self._toolbar.set_has_selection(False)
        dry = (
            self._store.get_state().dry_run
            if self._use_state_for_view and self._store
            else False
        )
        run_delete_ceremony(
            parent=self,
            items=items,
            scan_mode=self._scan_mode,
            on_remove_paths=self._remove_paths,
            on_navigate_home=self._on_navigate_home,
            on_rescan=self._on_rescan,
            source_tag="results_page",
            dry_run=dry,
        )

    def _delete_selected_group(self, group_id: int) -> None:
        group = next((g for g in self._groups if g.group_id == group_id), None)
        if not group or len(group.files) < 2:
            return
        from cerebro.v2.ui.delete_ceremony_widgets import GroupDeleteDialog
        dlg = GroupDeleteDialog(self, group=group)
        if dlg.result != "keep_one":
            return
        keeper = max(group.files, key=lambda f: int(getattr(f, "size", 0) or 0))
        items = [
            DeleteItem(path_str=str(f.path), size=int(getattr(f, "size", 0) or 0))
            for f in group.files
            if f is not keeper
        ]
        if not items:
            return
        self._toolbar.set_has_selection(False)
        dry = (
            self._store.get_state().dry_run
            if self._use_state_for_view and self._store
            else False
        )
        run_delete_ceremony(
            parent=self,
            items=items,
            scan_mode=self._scan_mode,
            on_remove_paths=self._remove_paths,
            on_navigate_home=self._on_navigate_home,
            on_rescan=self._on_rescan,
            source_tag="results_page.group_delete",
            dry_run=dry,
        )

    def _remove_paths(self, paths: Set[str]) -> None:
        pset = {str(Path(p)) for p in paths}
        if self._use_state_for_view and self._coordinator is not None:
            self._coordinator.results_files_removed(pset)
            return
        self._groups = prune_paths_from_groups(self._groups, list(pset))
        if self._dupes is not None:
            self._dupes.set_groups(self._groups)
        self._refresh_type_counts()
        if self._dupes is not None:
            self._dupes.refresh_from_state()

    def _move_selected_files(self) -> None:
        if self._dupes is None:
            return
        dest = filedialog.askdirectory(title="Move files to…")
        if not dest:
            return
        paths = self._dupes.get_selected_file_paths()
        if not paths:
            return
        dest_path = Path(dest)
        rows = [{"path": p} for p in paths]
        threading.Thread(
            target=self._move_worker,
            args=(rows, dest_path),
            daemon=True,
        ).start()

    def _move_worker(self, rows: List[Dict], dest: Path) -> None:
        import shutil

        moved: Set[str] = set()
        for row in rows:
            src = Path(row["path"])
            try:
                shutil.move(str(src), str(dest / src.name))
                moved.add(str(src))
            except OSError:
                pass
        self.after(0, lambda: self._remove_paths(moved))

    def get_groups(self) -> List[DuplicateGroup]:
        return self._groups


def _size_on_disk(path_str: str) -> int:
    try:
        return int(Path(path_str).stat().st_size)
    except OSError:
        return 0
