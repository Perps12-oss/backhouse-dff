"""
ReviewPage — visual triage of every file in every duplicate group.

Part of the Phase-6 course correction (Results → Review split): this page
used to focus on *one* group at a time (breadcrumb + single-file preview
+ per-file Keep/Delete buttons). After user feedback — "reviewing one
group at a time is too slow when the scan surfaces hundreds of groups
and 200k duplicates" — it was rebuilt around two modes:

  grid     — the entire scan flattened into a ``VirtualThumbGrid``
             (canvas-virtualized, lazy-decoded, LRU-cached thumbs). A
             count badge on every tile tells the user how many copies
             the file's group has; the size label is deliberately the
             largest, boldest text on the tile so users can triage by
             reclaim potential at a glance.
  compare  — entered by clicking a tile. Re-uses the legacy
             ``PreviewPanel`` (side-by-side A/B) with ``ZoomCanvas``
             sync. Prev/Next buttons walk the groups; "Open A/B in
             Explorer" buttons surface the file locations.

Actions:
  * Smart Select ▼  — dropdown with the 5 auto-mark rules (moved here
                      from the old Results toolbar). Applies the rule
                      across *all* groups, then pipes the computed
                      file set into ``delete_flow.run_delete_ceremony``.
  * ← Back to Results — returns to the table view.

Deliberate non-features (per user feedback):
  * No per-tile delete checkbox. Manual per-group marking creates a
    surface area for accidental loss when Smart Select is later used
    — it silently overwrites the manual marks. Results owns the
    manual-curation path; Review owns the bulk path.
  * No "Keep / Delete this one" single-file buttons. The user said
    they never want the destructive action one click away from a
    preview; the ceremony is the only delete path.
  * No "ORIGINAL" / "DUPLICATE" badges. The scanner cannot reliably
    determine which copy is the "true original" — surfacing an
    arbitrary pick as authoritative was misleading.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import ttk
from typing import Any, Callable, Dict, List, Optional, Set

_log = logging.getLogger(__name__)

try:
    import customtkinter as ctk
    CTkFrame  = ctk.CTkFrame
    CTkLabel  = ctk.CTkLabel
    CTkButton = ctk.CTkButton
except ImportError:
    CTkFrame  = tk.Frame   # type: ignore[misc,assignment]
    CTkLabel  = tk.Label   # type: ignore[misc,assignment]
    CTkButton = tk.Button  # type: ignore[misc,assignment]

from cerebro.engines.base_engine import DuplicateGroup, DuplicateFile
from cerebro.v2.ui.theme_applicator import ThemeApplicator
from cerebro.v2.ui.widgets.virtual_thumb_grid import VirtualThumbGrid
from cerebro.v2.ui.delete_flow import run_delete_ceremony, DeleteItem


# ---------------------------------------------------------------------------
# Tokens
# ---------------------------------------------------------------------------
_WHITE    = "#FFFFFF"
_F8       = "#F8F8F8"
_BORDER   = "#E0E0E0"
_NAVY_MID = "#1E3A5F"
_RED      = "#E74C3C"
_GRAY     = "#666666"
_DIMGRAY  = "#AAAAAA"


# ---------------------------------------------------------------------------
# Formatters — kept local so this file has no cross-imports on helpers.
# ---------------------------------------------------------------------------
def _fmt_size(n: int) -> str:
    if n < 1024:     return f"{n} B"
    if n < 1024**2:  return f"{n/1024:.1f} KB"
    if n < 1024**3:  return f"{n/1024**2:.1f} MB"
    return             f"{n/1024**3:.1f} GB"


def _fmt_date(ts: float) -> str:
    if not ts:
        return "—"
    from datetime import datetime
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
    except Exception:   # pylint: disable=broad-except
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
    except Exception:   # pylint: disable=broad-except
        pass


# ===========================================================================
# ReviewPage
# ===========================================================================
class ReviewPage(tk.Frame):
    """Canvas-grid review with an opt-in side-by-side comparison mode.

    Entry points:
      - ``load_group(groups, group_id)`` is called by AppShell when the
        user double-clicks a Results row. We flatten every group into
        the thumb grid and enter compare mode for the picked group.
      - Top-nav click without a prior scan → empty-state overlay.
    """

    SMART_SELECT_RULES = [
        ("Mark all except the oldest in each group",    "select_except_oldest"),
        ("Mark all except the newest in each group",    "select_except_newest"),
        ("Mark all except the first listed",            "select_except_first"),
        ("Mark all except the last listed",             "select_except_last"),
        ("Mark all except the largest in each group",   "select_except_largest"),
    ]

    def __init__(
        self,
        master,
        on_back:             Optional[Callable]               = None,
        on_navigate_results: Optional[Callable[[], None]]     = None,
        on_navigate_home:    Optional[Callable[[], None]]     = None,
        on_rescan:           Optional[Callable[[], None]]     = None,
        **kw,
    ) -> None:
        initial = ThemeApplicator.get().build_tokens()
        kw.setdefault("bg", initial.get("bg", _WHITE))
        super().__init__(master, **kw)

        self._on_back             = on_back
        self._on_navigate_results = on_navigate_results
        self._on_navigate_home    = on_navigate_home
        self._on_rescan           = on_rescan

        self._groups:   List[DuplicateGroup] = []
        self._rows:     List[Dict]           = []       # flat, all groups
        self._scan_mode: str                 = "files"
        self._group_files: Dict[int, List[DuplicateFile]] = {}

        self._mode:           str            = "empty"  # "empty" | "grid" | "compare"
        self._compare_gid:    Optional[int]  = None
        self._compare_a:      Optional[DuplicateFile] = None
        self._compare_b:      Optional[DuplicateFile] = None
        self._compare_panel:  Any            = None     # lazy PreviewPanel

        self._t: dict = initial
        self._build()
        self._build_empty_state()
        self._bind_keys()
        self._apply_theme(initial)
        ThemeApplicator.get().register(self._apply_theme)
        self._enter_mode("empty")

    # ------------------------------------------------------------------
    # Build — top chrome, body (grid + lazy compare), empty state
    # ------------------------------------------------------------------
    def _build(self) -> None:
        bg     = self._t.get("bg",     _WHITE)
        border = self._t.get("border", _BORDER)

        # Top chrome: always visible. Hosts Back, Smart Select, and a
        # compact group summary that updates per mode.
        self._top = tk.Frame(self, bg=bg, height=48)
        self._top.pack(fill="x", side="top")
        self._top.pack_propagate(False)
        self._top_border = tk.Frame(self, bg=border, height=1)
        self._top_border.pack(fill="x", side="top")

        self._back_btn = tk.Button(
            self._top, text="\u2190  Back to Results",
            command=self._go_back,
            bg="#2E75B6", fg=_WHITE,
            activebackground="#3A87CC", activeforeground=_WHITE,
            font=("Segoe UI", 9, "bold"), relief="flat",
            cursor="hand2", padx=14, pady=5,
            borderwidth=0, highlightthickness=0,
        )
        self._back_btn.pack(side="left", padx=10, pady=8)

        self._title_lbl = tk.Label(
            self._top, text="Review", bg=bg,
            fg=self._t.get("fg", "#111111"),
            font=("Segoe UI", 12, "bold"),
        )
        self._title_lbl.pack(side="left", padx=(6, 16))

        self._summary_lbl = tk.Label(
            self._top, text="", bg=bg,
            fg=self._t.get("fg2", _GRAY),
            font=("Segoe UI", 10),
        )
        self._summary_lbl.pack(side="left")

        self._smart_btn = tk.Button(
            self._top, text="Smart Select \u25BC",
            command=self._show_smart_select,
            bg="#8E44AD", fg=_WHITE,
            activebackground="#A255C5", activeforeground=_WHITE,
            font=("Segoe UI", 9, "bold"), relief="flat",
            cursor="hand2", padx=14, pady=5,
            borderwidth=0, highlightthickness=0,
        )
        self._smart_btn.pack(side="right", padx=10, pady=8)

        # Compare-mode chrome row: only visible in "compare". Holds
        # ← Grid / breadcrumb / ← Prev / Next → / Open A / Open B.
        self._cmp_bar = tk.Frame(self, bg=bg, height=40)
        self._cmp_bar_border = tk.Frame(self, bg=border, height=1)

        self._cmp_grid_btn = tk.Button(
            self._cmp_bar, text="\u2190  Grid",
            command=self._to_grid_mode,
            bg=self._t.get("bg3", "#F0F0F0"),
            fg=self._t.get("fg", "#333333"),
            font=("Segoe UI", 9, "bold"), relief="flat",
            cursor="hand2", padx=12, pady=4,
            borderwidth=0, highlightthickness=0,
        )
        self._cmp_grid_btn.pack(side="left", padx=(10, 6), pady=6)

        self._cmp_prev_btn = tk.Button(
            self._cmp_bar, text="\u2190  Prev Group",
            command=self._prev_group,
            bg=self._t.get("bg3", "#F0F0F0"),
            fg=self._t.get("fg", "#333333"),
            font=("Segoe UI", 9, "bold"), relief="flat",
            cursor="hand2", padx=10, pady=4,
            borderwidth=0, highlightthickness=0,
        )
        self._cmp_prev_btn.pack(side="left", padx=2, pady=6)

        self._cmp_next_btn = tk.Button(
            self._cmp_bar, text="Next Group  \u2192",
            command=self._next_group,
            bg=self._t.get("bg3", "#F0F0F0"),
            fg=self._t.get("fg", "#333333"),
            font=("Segoe UI", 9, "bold"), relief="flat",
            cursor="hand2", padx=10, pady=4,
            borderwidth=0, highlightthickness=0,
        )
        self._cmp_next_btn.pack(side="left", padx=2, pady=6)

        self._cmp_title = tk.Label(
            self._cmp_bar, text="", bg=bg,
            fg=self._t.get("fg", "#111111"),
            font=("Segoe UI", 10, "bold"),
        )
        self._cmp_title.pack(side="left", padx=(14, 10))

        self._cmp_open_b = tk.Button(
            self._cmp_bar, text="Open B in Explorer",
            command=lambda: self._open_compare_side("b"),
            bg=self._t.get("bg3", "#F0F0F0"),
            fg=self._t.get("fg", "#333333"),
            font=("Segoe UI", 9), relief="flat",
            cursor="hand2", padx=10, pady=4,
            borderwidth=0, highlightthickness=0,
        )
        self._cmp_open_b.pack(side="right", padx=(2, 10), pady=6)

        self._cmp_open_a = tk.Button(
            self._cmp_bar, text="Open A in Explorer",
            command=lambda: self._open_compare_side("a"),
            bg=self._t.get("bg3", "#F0F0F0"),
            fg=self._t.get("fg", "#333333"),
            font=("Segoe UI", 9), relief="flat",
            cursor="hand2", padx=10, pady=4,
            borderwidth=0, highlightthickness=0,
        )
        self._cmp_open_a.pack(side="right", padx=2, pady=6)

        # Body: hosts either the grid frame or the compare frame —
        # never both. Framed so each mode can own its own scrollbar /
        # chrome without stepping on the other.
        self._body = tk.Frame(self, bg=bg)
        self._body.pack(fill="both", expand=True)

        # ── Grid mode ─────────────────────────────────────────────
        self._grid_frame = tk.Frame(self._body, bg=bg)
        self._thumb_grid = VirtualThumbGrid(
            self._grid_frame,
            on_open_file=self._on_tile_clicked,
        )
        self._grid_vsb = ttk.Scrollbar(
            self._grid_frame, orient="vertical",
            command=self._thumb_grid.yview,
        )
        self._thumb_grid.configure(yscrollcommand=self._grid_vsb.set)
        self._grid_vsb.pack(side="right", fill="y")
        self._thumb_grid.pack(fill="both", expand=True)

        # ── Compare mode ──────────────────────────────────────────
        # PreviewPanel is PIL-heavy; build it only on the first tile
        # click so cold start stays cheap.
        self._cmp_frame = tk.Frame(self._body, bg=bg)

    # ------------------------------------------------------------------
    def _build_empty_state(self) -> None:
        bg = self._t.get("bg", _WHITE)
        self._empty_state = tk.Frame(self, bg=bg)
        center = tk.Frame(self._empty_state, bg=bg)
        center.place(relx=0.5, rely=0.5, anchor="center")

        self._empty_icon = tk.Label(
            center, text="\U0001F50D", bg=bg, fg=_DIMGRAY,
            font=("Segoe UI Emoji", 56),
        )
        self._empty_icon.pack(pady=(0, 12))

        self._empty_title = tk.Label(
            center, text="No scan results yet",
            bg=bg, fg="#333333",
            font=("Segoe UI", 16, "bold"),
        )
        self._empty_title.pack(pady=(0, 6))

        self._empty_subtitle = tk.Label(
            center,
            text="Run a scan, then come here for a visual sweep of\n"
                 "every duplicate — sized up for fast triage.",
            bg=bg, fg=_GRAY, font=("Segoe UI", 10), justify="center",
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

    # ------------------------------------------------------------------
    def _bind_keys(self) -> None:
        # Arrow keys walk groups only while in compare mode; in grid
        # mode the thumb grid owns arrow navigation.
        self.bind("<Left>",  lambda _e: self._mode == "compare" and self._prev_group())
        self.bind("<Right>", lambda _e: self._mode == "compare" and self._next_group())

    # ------------------------------------------------------------------
    # Theme
    # ------------------------------------------------------------------
    def _apply_theme(self, t: dict) -> None:
        self._t = t
        bg     = t.get("bg",     _WHITE)
        fg     = t.get("fg",     "#333333")
        border = t.get("border", _BORDER)
        bg3    = t.get("bg3",    "#F0F0F0")
        muted  = t.get("fg2",    _GRAY)

        try:
            self.configure(bg=bg)
            self._top.configure(bg=bg)
            self._top_border.configure(bg=border)
            self._title_lbl.configure(bg=bg, fg=fg)
            self._summary_lbl.configure(bg=bg, fg=muted)
            self._body.configure(bg=bg)
            self._grid_frame.configure(bg=bg)
            self._cmp_frame.configure(bg=bg)
            self._cmp_bar.configure(bg=bg)
            self._cmp_bar_border.configure(bg=border)
            self._cmp_title.configure(bg=bg, fg=fg)
            for btn in (self._cmp_grid_btn, self._cmp_prev_btn,
                        self._cmp_next_btn, self._cmp_open_a,
                        self._cmp_open_b):
                btn.configure(bg=bg3, fg=fg, activebackground=bg,
                              activeforeground=fg)
        except tk.TclError:
            pass

        try:
            self._thumb_grid.apply_theme(t)
        except Exception:   # pylint: disable=broad-except
            pass

        # Empty state bg follows theme; the distinct CTA colour is kept.
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
            self._empty_subtitle.configure(fg=muted)
        except tk.TclError:
            pass

    # ------------------------------------------------------------------
    # Public API — called by AppShell
    # ------------------------------------------------------------------
    def load_group(
        self,
        groups:   List[DuplicateGroup],
        group_id: int,
        mode:     Optional[str] = None,
    ) -> None:
        """Called when the user double-clicks a Results row.

        Loads every group into the grid, then jumps into compare mode
        for the specific group the user picked — that's what the
        gesture meant (inspect *that* group), and it's the fastest way
        to land on the side-by-side view for it.

        ``mode`` is the scan media mode ("files" | "photos" | "videos"
        | "music"); threaded through from AppShell so Smart Select's
        delete ceremony picks the right noun in its dialogs.
        """
        self._groups = list(groups)
        if mode:
            self._scan_mode = mode
        self._group_files = {g.group_id: list(g.files) for g in self._groups}
        self._rows = self._flatten_rows(self._groups)

        if not self._groups:
            self._enter_mode("empty")
            return

        self._thumb_grid.load(self._rows)
        self._update_summary()
        # Compare mode for the picked group — pick A = first file, B = second.
        gid = group_id if any(g.group_id == group_id for g in self._groups) \
                       else self._groups[0].group_id
        self._enter_compare(gid)

    def load_results(self, groups: List[DuplicateGroup], mode: str = "files") -> None:
        """Called when the user picks Review from the top nav directly
        (or when AppShell wants to refresh the page without entering
        compare). Lands in grid mode."""
        self._groups = list(groups)
        self._scan_mode = mode or "files"
        self._group_files = {g.group_id: list(g.files) for g in self._groups}
        self._rows = self._flatten_rows(self._groups)
        if not self._groups:
            self._enter_mode("empty")
            return
        self._thumb_grid.load(self._rows)
        self._update_summary()
        self._enter_mode("grid")

    def on_show(self) -> None:
        """AppShell hook when this tab becomes active."""
        if not self._groups:
            self._enter_mode("empty")

    # ------------------------------------------------------------------
    def _flatten_rows(self, groups: List[DuplicateGroup]) -> List[Dict]:
        rows: List[Dict] = []
        for shade, g in enumerate(groups):
            for fi, f in enumerate(g.files):
                rows.append({
                    "group_id":     g.group_id,
                    "file_idx":     fi,
                    "name":         Path(f.path).name,
                    "size":         f.size,
                    "size_str":     _fmt_size(f.size),
                    "date":         _fmt_date(f.modified),
                    "folder":       str(Path(f.path).parent),
                    "path":         str(f.path),
                    "extension":    getattr(f, "extension",
                                            Path(f.path).suffix.lower()),
                    "_group_shade": shade % 2 == 1,
                })
        return rows

    # ------------------------------------------------------------------
    # Mode transitions
    # ------------------------------------------------------------------
    def _enter_mode(self, mode: str) -> None:
        """Pack exactly one of: empty overlay, grid frame, compare frame."""
        if mode not in ("empty", "grid", "compare"):
            return
        self._mode = mode

        # Tear down all three so ordering is deterministic.
        try:
            self._empty_state.place_forget()
            self._grid_frame.pack_forget()
            self._cmp_frame.pack_forget()
            self._cmp_bar.pack_forget()
            self._cmp_bar_border.pack_forget()
        except tk.TclError:
            pass

        if mode == "empty":
            self._empty_state.place(relx=0, rely=0, relwidth=1, relheight=1)
            self._empty_state.lift()
            self._summary_lbl.configure(text="")
            return

        if mode == "grid":
            self._grid_frame.pack(in_=self._body, fill="both", expand=True)
            self.focus_set()
            return

        # compare
        self._cmp_bar.pack(fill="x",
                           before=self._body if self._body.winfo_ismapped()
                           else None)
        self._cmp_bar_border.pack(fill="x",
                                  before=self._body if self._body.winfo_ismapped()
                                  else None)
        self._cmp_frame.pack(in_=self._body, fill="both", expand=True)
        self.focus_set()

    def _to_grid_mode(self) -> None:
        self._enter_mode("grid")

    # ------------------------------------------------------------------
    # Compare mode
    # ------------------------------------------------------------------
    def _ensure_compare_panel(self) -> bool:
        """Lazy-build the PreviewPanel. Returns False if PIL/PreviewPanel
        can't be imported — caller should degrade gracefully."""
        if self._compare_panel is not None:
            return True
        try:
            from cerebro.v2.ui.preview_panel import PreviewPanel
        except ImportError:
            _log.exception("PreviewPanel unavailable — compare mode disabled")
            return False
        self._compare_panel = PreviewPanel(self._cmp_frame)
        self._compare_panel.pack(fill="both", expand=True, padx=8, pady=(4, 8))
        try:
            self._compare_panel.set_layout_mode("compact")
        except Exception:   # pylint: disable=broad-except
            pass
        return True

    def _enter_compare(self, gid: int) -> None:
        """Open compare mode for a specific group id. A = files[0],
        B = files[1] (or None if the group is a singleton after a
        partial delete)."""
        files = self._group_files.get(gid) or []
        if not files:
            # Group emptied — fall back to grid.
            self._to_grid_mode()
            return
        if not self._ensure_compare_panel():
            # Graceful degrade: bounce to grid instead of stranding the user.
            self._to_grid_mode()
            return

        self._compare_gid = gid
        self._compare_a = files[0]
        self._compare_b = files[1] if len(files) > 1 else None

        try:
            self._compare_panel.load_comparison(self._compare_a,
                                                self._compare_b)
        except Exception:   # pylint: disable=broad-except
            _log.exception("PreviewPanel.load_comparison raised")

        self._update_compare_chrome()
        self._enter_mode("compare")

    def _update_compare_chrome(self) -> None:
        gid = self._compare_gid
        if gid is None:
            return
        # Group index within the ordered group list, 1-based for display.
        idx = next((i for i, g in enumerate(self._groups)
                    if g.group_id == gid), 0)
        total_groups = len(self._groups)
        count = len(self._group_files.get(gid, []))
        name_a = Path(str(getattr(self._compare_a, "path", "") or "")).name or "(A)"
        name_b = (Path(str(getattr(self._compare_b, "path", "") or "")).name
                  if self._compare_b else "(no peer)")
        self._cmp_title.configure(
            text=f"Group {idx + 1}/{total_groups}   ·   "
                 f"{count} copies   ·   {name_a}  \u2194  {name_b}"
        )
        # Enable/disable nav buttons at edges.
        try:
            if idx <= 0:
                self._cmp_prev_btn.configure(state="disabled")
            else:
                self._cmp_prev_btn.configure(state="normal")
            if idx >= total_groups - 1:
                self._cmp_next_btn.configure(state="disabled")
            else:
                self._cmp_next_btn.configure(state="normal")
        except tk.TclError:
            pass

    def _on_tile_clicked(self, row: Dict) -> None:
        """VirtualThumbGrid double-click. Enter compare for the clicked
        tile's group; A defaults to the clicked file so the user sees
        *their* pick on the left."""
        gid = int(row.get("group_id", -1))
        target_path = str(row.get("path", ""))
        files = self._group_files.get(gid) or []
        if not files:
            return
        if not self._ensure_compare_panel():
            return

        file_a = next((f for f in files if str(f.path) == target_path),
                      files[0])
        file_b = next((f for f in files if str(f.path) != str(file_a.path)),
                      None)
        self._compare_gid = gid
        self._compare_a = file_a
        self._compare_b = file_b
        try:
            self._compare_panel.load_comparison(file_a, file_b)
        except Exception:   # pylint: disable=broad-except
            _log.exception("PreviewPanel.load_comparison raised")
        self._update_compare_chrome()
        self._enter_mode("compare")

    def _prev_group(self) -> None:
        if self._compare_gid is None:
            return
        idx = next((i for i, g in enumerate(self._groups)
                    if g.group_id == self._compare_gid), 0)
        if idx <= 0:
            return
        self._enter_compare(self._groups[idx - 1].group_id)

    def _next_group(self) -> None:
        if self._compare_gid is None:
            return
        idx = next((i for i, g in enumerate(self._groups)
                    if g.group_id == self._compare_gid), 0)
        if idx >= len(self._groups) - 1:
            return
        self._enter_compare(self._groups[idx + 1].group_id)

    def _open_compare_side(self, side: str) -> None:
        f = self._compare_a if side == "a" else self._compare_b
        if not f:
            return
        try:
            import threading
            threading.Thread(
                target=_open_in_explorer,
                args=(Path(str(f.path)),),
                daemon=True,
            ).start()
        except Exception:   # pylint: disable=broad-except
            _log.exception("open-in-explorer failed")

    # ------------------------------------------------------------------
    # Summary label (top chrome)
    # ------------------------------------------------------------------
    def _update_summary(self) -> None:
        if not self._groups:
            self._summary_lbl.configure(text="")
            return
        total_files = sum(len(g.files) for g in self._groups)
        recoverable = sum(int(getattr(g, "reclaimable", 0) or 0)
                          for g in self._groups)
        self._summary_lbl.configure(
            text=f"{len(self._groups):,} groups  ·  "
                 f"{total_files:,} files  ·  "
                 f"{_fmt_size(recoverable)} recoverable"
        )

    # ------------------------------------------------------------------
    # Smart Select ▼
    # ------------------------------------------------------------------
    def _show_smart_select(self) -> None:
        if not self._groups:
            return
        menu = tk.Menu(self, tearoff=0)
        for label, rule in self.SMART_SELECT_RULES:
            menu.add_command(
                label=label,
                command=lambda r=rule: self._apply_smart_select(r),
            )
        try:
            x = self._smart_btn.winfo_rootx()
            y = self._smart_btn.winfo_rooty() + self._smart_btn.winfo_height()
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def _apply_smart_select(self, rule: str) -> None:
        """Apply a global mark rule across all loaded groups and pipe
        the resulting file set into the delete ceremony."""
        if not self._groups:
            return

        items: List[DeleteItem] = []
        for g in self._groups:
            files = list(g.files)
            if len(files) < 2:
                continue

            if rule == "select_except_oldest":
                keep = min(files, key=lambda f: getattr(f, "modified", 0) or 0)
            elif rule == "select_except_newest":
                keep = max(files, key=lambda f: getattr(f, "modified", 0) or 0)
            elif rule == "select_except_first":
                keep = files[0]
            elif rule == "select_except_last":
                keep = files[-1]
            elif rule == "select_except_largest":
                keep = max(files, key=lambda f: int(getattr(f, "size", 0) or 0))
            else:
                keep = files[0]

            for f in files:
                if f is keep:
                    continue
                items.append(DeleteItem(
                    path_str=str(f.path),
                    size=int(getattr(f, "size", 0) or 0),
                ))

        if not items:
            return

        run_delete_ceremony(
            parent=self,
            items=items,
            scan_mode=self._scan_mode,
            on_remove_paths=self._remove_paths,
            on_navigate_home=self._on_navigate_home,
            on_rescan=self._on_rescan,
            source_tag="review_page.smart_select",
        )

    # ------------------------------------------------------------------
    # Post-delete state pruning — called by the ceremony helper
    # ------------------------------------------------------------------
    def _remove_paths(self, paths: Set[str]) -> None:
        if not paths:
            return
        # Prune groups in place.
        new_groups: List[DuplicateGroup] = []
        for g in self._groups:
            surviving = [f for f in g.files if str(f.path) not in paths]
            if not surviving:
                continue
            g.files = surviving
            new_groups.append(g)
        self._groups = new_groups
        self._group_files = {g.group_id: list(g.files) for g in self._groups}
        self._rows = self._flatten_rows(self._groups)
        self._thumb_grid.load(self._rows)
        self._update_summary()

        # If compare mode was open for a now-empty group, step sideways
        # or back to grid.
        if self._mode == "compare":
            if self._compare_gid is None or not self._group_files.get(self._compare_gid):
                if self._groups:
                    self._enter_compare(self._groups[0].group_id)
                else:
                    self._enter_mode("empty")
            else:
                files = self._group_files[self._compare_gid]
                self._compare_a = files[0]
                self._compare_b = files[1] if len(files) > 1 else None
                try:
                    if self._compare_panel is not None:
                        self._compare_panel.load_comparison(
                            self._compare_a, self._compare_b
                        )
                except Exception:   # pylint: disable=broad-except
                    pass
                self._update_compare_chrome()
        else:
            # Grid mode: if no groups remain, show empty.
            if not self._groups:
                self._enter_mode("empty")

    # ------------------------------------------------------------------
    # Back / empty-state CTA
    # ------------------------------------------------------------------
    def _go_back(self) -> None:
        if self._mode == "compare":
            self._to_grid_mode()
            return
        if self._on_back:
            self._on_back()

    def _navigate_results(self) -> None:
        if self._on_navigate_results:
            self._on_navigate_results()

    # ------------------------------------------------------------------
    # Legacy API — kept so AppShell code that calls ``get_groups`` etc.
    # continues to work.
    # ------------------------------------------------------------------
    def get_groups(self) -> List[DuplicateGroup]:
        return self._groups
