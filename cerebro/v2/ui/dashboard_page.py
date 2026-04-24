"""
DashboardPage — FINAL PLAN v2.0 §4.

States:
  Empty:    "No scans yet" + [Start Scan]
  Minimal:  Last scan summary, Start scan button, Recent scans (last 5)
  Advanced: Scan profiles, Detailed metrics
"""

from __future__ import annotations

import tkinter as tk
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from cerebro.v2.ui.theme_applicator import ThemeApplicator, theme_token

_NAVY     = "#0B1929"
_NAVY_MID = "#1E3A5F"
_RED      = "#E74C3C"
_GREEN    = "#27AE60"
_WHITE    = "#FFFFFF"

_W45 = "#798095"
_W38 = "#677080"
_W28 = "#4F5961"
_W25 = "#48535C"
_W22 = "#414C59"
_W12 = "#1E2B3A"
_W8  = "#1E2B3A"
_W6  = "#1A2636"
_W5  = "#172534"
_W9  = "#212D3E"

_NAVY_MID_HOVER = "#234A78"


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
    """Return (scans_run, duplicates_found, bytes_recovered, recent[:5])."""
    try:
        from cerebro.v2.core.scan_history_db import get_scan_history_db
        rows = get_scan_history_db().get_recent(limit=200)
        scans = len(rows)
        dupes = sum(
            max(0, getattr(r, "files_found", 0) - getattr(r, "groups_found", 0))
            for r in rows
        )
        recovered = sum(getattr(r, "bytes_reclaimable", 0) for r in rows)
        return scans, dupes, recovered, rows[:5]
    except Exception:
        return 0, 0, 0, []


class DashboardPage(tk.Frame):
    """Full-viewport dashboard (FINAL PLAN §4)."""

    def __init__(
        self,
        master,
        on_start_scan: Optional[Callable[[], None]] = None,
        on_open_session: Optional[Callable[[Any], None]] = None,
        store: Optional[object] = None,
        coordinator: Optional[object] = None,
        **kwargs,
    ) -> None:
        kwargs.setdefault("bg", _NAVY)
        super().__init__(master, **kwargs)
        self._on_start_scan = on_start_scan
        self._on_open_session = on_open_session
        self._store = store
        self._coordinator = coordinator
        self._t: Dict[str, Any] = {}
        self._advanced = False
        self._build()
        self._t = ThemeApplicator.get().build_tokens()
        ThemeApplicator.get().register(self._apply_theme)

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
        has_scans = scans > 0

        body = tk.Frame(self, bg=bg)
        body.place(relx=0.5, y=0, anchor="n")

        tk.Frame(body, bg=bg, height=56).pack()

        if not has_scans:
            self._build_empty(body, bg=bg, nav_bg=nav_bg,
                              nav_hov=nav_hov, fg=fg)
        else:
            self._build_minimal(body, scans, dupes, recovered, recent,
                                bg=bg, nav_bg=nav_bg, nav_hov=nav_hov,
                                fg=fg, danger=danger, success=success,
                                last=last)

            if self._advanced:
                self._build_advanced(body, bg=bg, fg=fg, danger=danger,
                                     success=success)

        self._build_recent_bar(recent, bg=bg)

    def _build_empty(self, parent: tk.Frame, bg: str, nav_bg: str,
                     nav_hov: str, fg: str) -> None:
        tk.Label(parent, text="No scans yet", bg=bg, fg=_W38,
                 font=("Segoe UI", 22)).pack(pady=(40, 24))
        btn = tk.Button(
            parent, text="Start Scan",
            bg=nav_bg, fg=fg,
            font=("Segoe UI", 13, "bold"),
            relief="flat", cursor="hand2",
            padx=32, pady=12,
            bd=0, activebackground=nav_hov, activeforeground=fg,
            command=self._start_scan,
        )
        btn.pack()
        _hover(btn, nav_bg, nav_hov)

    def _build_minimal(self, parent: tk.Frame, scans: int, dupes: int,
                       recovered: int, recent: list,
                       bg: str, nav_bg: str, nav_hov: str, fg: str,
                       danger: str, success: str, last: Any = None) -> None:
        tk.Label(parent, text="Last scan summary", bg=bg, fg=fg,
                 font=("Segoe UI", 18, "bold")).pack(pady=(10, 16))

        row = tk.Frame(parent, bg=bg)
        row.pack(pady=(0, 20))

        data = [
            (str(scans),            fg,      "Total scans"),
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

        btn_row = tk.Frame(parent, bg=bg)
        btn_row.pack(pady=(0, 12))

        start_btn = tk.Button(
            btn_row, text="Start new scan",
            bg=nav_bg, fg=fg,
            font=("Segoe UI", 11, "bold"),
            relief="flat", cursor="hand2",
            padx=28, pady=11,
            bd=0, activebackground=nav_hov, activeforeground=fg,
            command=self._start_scan,
        )
        start_btn.pack(side="left", padx=(0, 12))
        _hover(start_btn, nav_bg, nav_hov)

        if last:
            open_btn = tk.Button(
                btn_row, text="Open last session",
                bg=bg, fg=_W45,
                font=("Segoe UI", 11),
                relief="flat",
                padx=28, pady=10,
                bd=1,
                highlightbackground=_W12, highlightthickness=1,
                activebackground=bg, activeforeground=fg,
                command=lambda: self._open_session(last),
            )
            open_btn.configure(cursor="hand2")
            _hover(open_btn, bg, "#1A2C40")
            open_btn.pack(side="left")

    def _build_advanced(self, parent: tk.Frame, bg: str, fg: str,
                        danger: str, success: str) -> None:
        tk.Frame(parent, bg=_W6, height=1).pack(fill="x", pady=(20, 10))

        tk.Label(parent, text="Scan Profiles", bg=bg, fg=_W38,
                 font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=40)

        profile_frame = tk.Frame(parent, bg=bg)
        profile_frame.pack(fill="x", padx=40, pady=8)

        profiles = [
            ("Quick Scan", "Files only, top-level folders"),
            ("Deep Scan", "All file types, recursive"),
            ("Photos Only", "Image dedup with visual similarity"),
        ]
        for name, desc in profiles:
            row = tk.Frame(profile_frame, bg=_W5, padx=12, pady=8)
            row.pack(fill="x", pady=2)
            row.configure(cursor="hand2")
            tk.Label(row, text=name, bg=_W5, fg=fg,
                     font=("Segoe UI", 10, "bold")).pack(anchor="w")
            tk.Label(row, text=desc, bg=_W5, fg=_W38,
                     font=("Segoe UI", 9)).pack(anchor="w")

        tk.Frame(parent, bg=bg, height=16).pack()

        tk.Label(parent, text="Detailed Metrics", bg=bg, fg=_W38,
                 font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=40)

        metrics_frame = tk.Frame(parent, bg=bg)
        metrics_frame.pack(fill="x", padx=40, pady=8)

        metrics = [
            ("Avg scan time", "2m 34s"),
            ("Total files scanned", "145,230"),
            ("Most common duplicate", "Photos (42%)"),
        ]
        for label, value in metrics:
            row = tk.Frame(metrics_frame, bg=bg)
            row.pack(fill="x", pady=2)
            tk.Label(row, text=label, bg=bg, fg=_W38,
                     font=("Segoe UI", 9)).pack(side="left")
            tk.Label(row, text=value, bg=bg, fg=fg,
                     font=("Segoe UI", 9, "bold")).pack(side="right")

    def _build_recent_bar(self, recent: list, bg: str = _NAVY) -> None:
        bar = tk.Frame(self, bg=bg, height=44)
        bar.place(relx=0, rely=1.0, anchor="sw", relwidth=1)
        bar.pack_propagate(False)

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
                chip.bind("<Enter>",    lambda _e, w=chip: w.configure(bg=_W9, fg=_W45))
                chip.bind("<Leave>",    lambda _e, w=chip: w.configure(bg=_W5, fg=_W38))
        else:
            tk.Label(inner, text="No scans yet", bg=bg, fg=_W22,
                     font=("Segoe UI", 9)).pack(side="left")

        new_lbl = tk.Label(
            inner, text="+ New scan", bg=bg, fg=_W28,
            font=("Segoe UI", 9), cursor="hand2",
        )
        new_lbl.pack(side="right")
        new_lbl.bind("<Button-1>", lambda _e: self._start_scan())

    def _start_scan(self) -> None:
        if self._on_start_scan:
            self._on_start_scan()

    def _open_session(self, session: Any) -> None:
        if session and self._on_open_session:
            self._on_open_session(session)

    def set_advanced(self, value: bool) -> None:
        """Called when global advanced toggle changes."""
        self._advanced = value
        for w in self.winfo_children():
            w.destroy()
        self._build()

    def refresh(self) -> None:
        for w in self.winfo_children():
            w.destroy()
        self._build()

    def on_show(self) -> None:
        self.refresh()
