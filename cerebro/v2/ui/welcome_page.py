"""
WelcomePage — full-viewport dark-navy landing screen.

Layout (top-to-bottom, centred):
  56 px top padding
  Logo mark (52×52 canvas)
  28 px gap
  "CEREBRO" tagline
  16 px gap
  "Find duplicates. / Reclaim your space." headline
  10 px gap
  Subtitle
  44 px gap
  [Start new scan]  [Open last session]
  52 px gap
  Stats row (Scans run · Duplicates found · Space recovered)
  Recent bar pinned to bottom
"""
from __future__ import annotations

import tkinter as tk
from datetime import datetime
from typing import Any, Callable, List, Optional, TYPE_CHECKING

from cerebro.v2.ui.space_dashboard import SpaceDashboard
from cerebro.v2.ui.theme_applicator import ThemeApplicator

if TYPE_CHECKING:
    from cerebro.v2.state import StateStore

_NAVY     = "#0B1929"
_NAVY_MID = "#1E3A5F"
_RED      = "#E74C3C"
_GREEN    = "#27AE60"
_WHITE    = "#FFFFFF"

# Opaque approximations of semi-transparent white blended onto #0B1929
_W65 = "#AABBCC"   # white 65 % — chip hover text
_W45 = "#798095"   # white 45 % — open-last text
_W38 = "#677080"   # white 38 % — subtitle / chip text
_W28 = "#4F5961"   # white 28 % — "CEREBRO" tagline
_W25 = "#48535C"   # white 25 % — stat labels
_W22 = "#414C59"   # white 22 % — "RECENT" label
_W20 = "#3C4759"   # white 20 % — "+ New scan"
_W12 = "#1E2B3A"   # white 12 % — open-last button border
_W8  = "#1E2B3A"   # white  8 % — stat dividers
_W6  = "#1A2636"   # white  6 % — recent bar top border
_W5  = "#172534"   # white  5 % — chip bg
_W9  = "#212D3E"   # white  9 % — chip hover bg

# Start-scan button hover
_NAVY_MID_HOVER = "#234A78"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt_bytes(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 ** 2:
        return f"{n / 1024:.1f} KB"
    if n < 1024 ** 3:
        return f"{n / 1024 ** 2:.1f} MB"
    return f"{n / 1024 ** 3:.1f} GB"


def _chip_label(session: Any) -> str:
    try:
        ts = getattr(session, "timestamp", None)
        if ts:
            return datetime.fromtimestamp(float(ts)).strftime("%b %d")
    except Exception:
        pass
    return "Session"


def _hover(btn: tk.Button, normal: str, hover: str) -> None:
    btn.bind("<Enter>", lambda _e: btn.configure(bg=hover))
    btn.bind("<Leave>", lambda _e: btn.configure(bg=normal))


def _load_stats():
    """Return (scans_run, duplicates_found, bytes_recovered, recent[:3])."""
    try:
        from cerebro.v2.core.scan_history_db import get_scan_history_db
        rows = get_scan_history_db().get_recent(limit=200)
        scans = len(rows)
        dupes = sum(
            max(0, getattr(r, "files_found", 0) - getattr(r, "groups_found", 0))
            for r in rows
        )
        recovered = sum(getattr(r, "bytes_reclaimable", 0) for r in rows)
        return scans, dupes, recovered, rows[:3]
    except Exception:
        return 0, 0, 0, []


def _load_deletion_rows() -> list:
    """Return deletion history as a list of dicts for SpaceDashboard.load()."""
    try:
        from cerebro.v2.core.deletion_history_db import get_default_history_manager
        entries = get_default_history_manager().get_recent_history(limit=2000)
        return [
            {
                "size":          getattr(e, "file_size", 0),
                "deletion_date": getattr(e, "deletion_date", ""),
                "mode":          getattr(e, "scan_mode", ""),
            }
            for e in entries
        ]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Logo canvas
# ---------------------------------------------------------------------------

def _draw_logo(parent: tk.Widget, bg: str = _NAVY, logo_bg: str = _NAVY_MID,
               danger: str = _RED) -> tk.Canvas:
    SIZE, RADIUS = 52, 13
    c = tk.Canvas(parent, width=SIZE, height=SIZE,
                  bg=bg, highlightthickness=0)
    c.pack()

    # Rounded rectangle in navy-mid
    x0, y0, x1, y1 = 0, 0, SIZE, SIZE
    r = RADIUS
    for x, y, start in [
        (x0,     y0,     90),
        (x1-2*r, y0,     0),
        (x1-2*r, y1-2*r, 270),
        (x0,     y1-2*r, 180),
    ]:
        c.create_arc(x, y, x + 2*r, y + 2*r,
                     start=start, extent=90,
                     fill=logo_bg, outline="")
    c.create_rectangle(x0+r, y0,   x1-r, y1,   fill=logo_bg, outline="")
    c.create_rectangle(x0,   y0+r, x1,   y1-r, fill=logo_bg, outline="")

    # 2×2 grid of squares
    PAD, GAP, SQ = 10, 3, 11
    colors = [["#F0EFEC", danger], ["#4A6070", "#3A4E62"]]
    for ri in range(2):
        for ci in range(2):
            cx = PAD + ci * (SQ + GAP)
            cy = PAD + ri * (SQ + GAP)
            c.create_rectangle(cx, cy, cx + SQ, cy + SQ,
                                fill=colors[ri][ci], outline="")
    return c


# ---------------------------------------------------------------------------
# WelcomePage
# ---------------------------------------------------------------------------

class WelcomePage(tk.Frame):
    """Full-viewport welcome screen. Parent must fill the available space."""

    def __init__(
        self,
        master,
        on_start_scan:   Optional[Callable[[], None]]   = None,
        on_open_session: Optional[Callable[[Any], None]] = None,
        store: Optional["StateStore"] = None,
        **kwargs,
    ) -> None:
        kwargs.setdefault("bg", _NAVY)
        super().__init__(master, **kwargs)
        self._on_start_scan   = on_start_scan
        self._on_open_session = on_open_session
        self._t: dict = {}
        self._build()
        self._t = ThemeApplicator.get().build_tokens()
        ThemeApplicator.get().register(self._apply_theme)
        if store is not None:
            store.subscribe(self._on_store)

    def _on_store(self, s: Any, old: Any, action: Any) -> None:
        try:
            from cerebro.v2.state.actions import DeletionHistoryDataLoaded
            if isinstance(action, DeletionHistoryDataLoaded):
                self.refresh()
        except Exception:
            pass

    # ------------------------------------------------------------------

    def _apply_theme(self, t: dict) -> None:
        self._t = t
        self.configure(bg=t.get("bg", _NAVY))
        for w in self.winfo_children():
            w.destroy()
        self._build()

    def _build(self) -> None:
        t = self._t
        bg       = t.get("bg", _NAVY)
        nav_bg   = t.get("nav_bar", _NAVY_MID)
        nav_hov  = t.get("accent2", _NAVY_MID_HOVER)
        fg       = t.get("fg", _WHITE)
        danger   = t.get("danger", _RED)
        success  = t.get("success", _GREEN)

        scans, dupes, recovered, recent = _load_stats()
        last = recent[0] if recent else None

        # ── Scrollable body (centred column) ─────────────────────────
        body = tk.Frame(self, bg=bg)
        body.place(relx=0.5, y=0, anchor="n")

        # 56 px top padding
        tk.Frame(body, bg=bg, height=56).pack()

        # Logo
        _draw_logo(body, bg=bg, logo_bg=nav_bg, danger=danger)

        # 28 px gap
        tk.Frame(body, bg=bg, height=28).pack()

        # "CEREBRO" sub-tagline
        tk.Label(body, text="CEREBRO", bg=bg, fg=_W28,
                 font=("Segoe UI", 8, "bold")).pack()

        # 16 px gap
        tk.Frame(body, bg=bg, height=16).pack()

        # Headline line 1
        tk.Label(body, text="Find duplicates.",
                 bg=bg, fg=fg,
                 font=("Segoe UI", 28, "bold")).pack()

        # Headline line 2 — mixed colour
        h2 = tk.Frame(body, bg=bg)
        h2.pack()
        tk.Label(h2, text="Reclaim your ", bg=bg, fg=fg,
                 font=("Segoe UI", 28, "bold")).pack(side="left")
        tk.Label(h2, text="space.", bg=bg, fg=danger,
                 font=("Segoe UI", 28, "bold")).pack(side="left")

        # 10 px gap
        tk.Frame(body, bg=bg, height=10).pack()

        # Subtitle
        tk.Label(
            body,
            text="Intelligent deduplication for your entire drive.",
            bg=bg, fg=_W38,
            font=("Segoe UI", 11),
            wraplength=340, justify="center",
        ).pack()

        # 44 px gap
        tk.Frame(body, bg=bg, height=44).pack()

        # Action buttons
        self._build_buttons(body, last, bg=bg, nav_bg=nav_bg,
                            nav_hov=nav_hov, fg=fg)

        # 52 px gap
        tk.Frame(body, bg=bg, height=52).pack()

        # Stats row
        self._build_stats(body, scans, dupes, recovered,
                          bg=bg, fg=fg, danger=danger, success=success)

        # 24 px gap
        tk.Frame(body, bg=bg, height=24).pack()

        # Space reclaimed dashboard
        dash = SpaceDashboard(body, bg=bg)
        dash.pack(fill="x", padx=0, pady=0)
        dash.load(_load_deletion_rows())

        # ── Recent bar — pinned to bottom of the page ─────────────────
        self._build_recent_bar(recent, bg=bg)

    def _build_buttons(self, parent: tk.Frame, last_session: Any,
                       bg: str = _NAVY, nav_bg: str = _NAVY_MID,
                       nav_hov: str = _NAVY_MID_HOVER, fg: str = _WHITE) -> None:
        row = tk.Frame(parent, bg=bg)
        row.pack()

        start_btn = tk.Button(
            row, text="Start new scan",
            bg=nav_bg, fg=fg,
            font=("Segoe UI", 11, "bold"),
            relief="flat", cursor="hand2",
            padx=28, pady=11,
            bd=0, activebackground=nav_hov, activeforeground=fg,
            command=self._start_scan,
        )
        start_btn.pack(side="left", padx=(0, 12))
        _hover(start_btn, nav_bg, nav_hov)

        open_btn = tk.Button(
            row, text="Open last session",
            bg=bg, fg=_W45,
            font=("Segoe UI", 11),
            relief="flat",
            padx=28, pady=10,
            bd=1,
            highlightbackground=_W12, highlightthickness=1,
            activebackground=bg, activeforeground=fg,
            command=lambda: self._open_session(last_session),
        )
        if not last_session:
            open_btn.configure(state="disabled", cursor="", fg=_W28)
        else:
            open_btn.configure(cursor="hand2")
            _hover(open_btn, bg, "#1A2C40")
        open_btn.pack(side="left")

    def _build_stats(self, parent: tk.Frame,
                     scans: int, dupes: int, recovered: int,
                     bg: str = _NAVY, fg: str = _WHITE,
                     danger: str = _RED, success: str = _GREEN) -> None:
        row = tk.Frame(parent, bg=bg)
        row.pack()

        data = [
            (str(scans),            fg,      "Scans run"),
            (str(dupes),            danger,  "Duplicates found"),
            (_fmt_bytes(recovered), success, "Space recovered"),
        ]
        for i, (val, val_fg, lbl) in enumerate(data):
            if i:
                tk.Frame(row, bg=_W8, width=1).pack(
                    side="left", fill="y", padx=24, pady=4)
            col = tk.Frame(row, bg=bg)
            col.pack(side="left")
            tk.Label(col, text=val, bg=bg, fg=val_fg,
                     font=("Segoe UI", 20, "bold")).pack()
            tk.Label(col, text=lbl.upper(), bg=bg, fg=_W25,
                     font=("Segoe UI", 8)).pack()

    def _build_recent_bar(self, recent: List[Any], bg: str = _NAVY) -> None:
        bar = tk.Frame(self, bg=bg, height=44)
        bar.place(relx=0, rely=1.0, anchor="sw", relwidth=1)
        bar.pack_propagate(False)

        # Top border
        tk.Frame(bar, bg=_W6, height=1).pack(fill="x")

        inner = tk.Frame(bar, bg=bg)
        inner.pack(fill="both", expand=True, padx=20)

        tk.Label(inner, text="RECENT", bg=bg, fg=_W22,
                 font=("Segoe UI", 8, "bold")).pack(side="left", padx=(0, 12))

        if recent:
            for session in recent:
                txt = _chip_label(session)
                chip = tk.Label(
                    inner, text=txt,
                    bg=_W5, fg=_W38,
                    font=("Segoe UI", 9), padx=8, pady=2, cursor="hand2",
                )
                chip.pack(side="left", padx=3)
                chip.bind("<Button-1>", lambda _e, s=session: self._open_session(s))
                chip.bind("<Enter>",    lambda _e, w=chip: w.configure(bg=_W9, fg=_W65))
                chip.bind("<Leave>",    lambda _e, w=chip: w.configure(bg=_W5, fg=_W38))
        else:
            tk.Label(inner, text="No scans yet", bg=bg, fg=_W22,
                     font=("Segoe UI", 9)).pack(side="left")

        new_lbl = tk.Label(
            inner, text="+ New scan", bg=bg, fg=_W20,
            font=("Segoe UI", 9), cursor="hand2",
        )
        new_lbl.pack(side="right")
        new_lbl.bind("<Button-1>", lambda _e: self._start_scan())

    # ------------------------------------------------------------------
    # Callbacks

    def _start_scan(self) -> None:
        if self._on_start_scan:
            self._on_start_scan()

    def _open_session(self, session: Any) -> None:
        if session and self._on_open_session:
            self._on_open_session(session)

    def refresh(self) -> None:
        """Reload stats from DB — call after a scan completes."""
        for w in self.winfo_children():
            w.destroy()
        self._build()

    def on_show(self) -> None:
        """Called by AppShell whenever the Welcome tab is activated.

        Ensures the stats row reflects the latest DB state even when the user
        navigates away and back without a fresh scan completing in between.
        """
        self.refresh()
