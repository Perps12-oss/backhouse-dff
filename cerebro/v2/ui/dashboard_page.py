"""
DashboardPage — FINAL PLAN v2.0 §4.

Three embedded view states (no dialogs):
  idle        — "No scans yet" / last-scan summary + [Start Scan]
  configuring — inline folder picker + mode selector
  scanning    — live progress bar, file counter, current file, [Cancel]
"""

from __future__ import annotations

import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog
from typing import Any, Callable, Dict, List, Optional

from cerebro.v2.ui.theme_applicator import ThemeApplicator

_SCAN_MODES = [
    ("files",           "Duplicate Files"),
    ("photos",          "Duplicate Photos"),
    ("videos",          "Duplicate Videos"),
    ("music",           "Duplicate Music"),
    ("documents",       "Similar Documents"),
    ("burst",           "Burst Shots"),
    ("similar_folders", "Similar Folders"),
    ("empty_folders",   "Empty Folders"),
    ("large_files",     "Large Files"),
]

_NAVY           = "#0B1929"
_NAVY_MID       = "#1E3A5F"
_NAVY_MID_HOVER = "#234A78"
_RED            = "#E74C3C"
_GREEN          = "#27AE60"
_WHITE          = "#FFFFFF"
_ROW            = "#162D4A"
_BORDER         = "#2D4F73"
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


def _fmt_bytes(n: int) -> str:
    if n < 1024:       return f"{n} B"
    if n < 1024 ** 2:  return f"{n / 1024:.1f} KB"
    if n < 1024 ** 3:  return f"{n / 1024 ** 2:.1f} MB"
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
    try:
        from cerebro.v2.core.scan_history_db import get_scan_history_db
        rows = get_scan_history_db().get_recent(limit=200)
        scans = len(rows)
        dupes = sum(max(0, getattr(r, "files_found", 0) - getattr(r, "groups_found", 0)) for r in rows)
        recovered = sum(getattr(r, "bytes_reclaimable", 0) for r in rows)
        return scans, dupes, recovered, rows[:5]
    except Exception:
        return 0, 0, 0, []


class DashboardPage(tk.Frame):
    """Dashboard with embedded scan config and live scan progress."""

    def __init__(
        self,
        master,
        on_start_scan: Optional[Callable] = None,
        on_open_session: Optional[Callable[[Any], None]] = None,
        on_cancel_scan: Optional[Callable[[], None]] = None,
        store: Optional[object] = None,
        coordinator: Optional[object] = None,
        **kwargs,
    ) -> None:
        kwargs.setdefault("bg", _NAVY)
        super().__init__(master, **kwargs)
        self._on_start_scan  = on_start_scan
        self._on_open_session = on_open_session
        self._on_cancel_scan  = on_cancel_scan
        self._store      = store
        self._coordinator = coordinator
        self._t: Dict[str, Any] = {}
        self._advanced = False

        # view state
        self._view = "idle"
        self._config_folders: List[Path] = []
        self._folder_row_map: Dict[Path, tk.Frame] = {}
        self._mode_var: Optional[tk.StringVar] = None

        # scanning progress widgets (updated in-place)
        self._prog_bar:       Optional[tk.Canvas] = None
        self._prog_files_lbl: Optional[tk.Label]  = None
        self._prog_stage_lbl: Optional[tk.Label]  = None
        self._prog_file_lbl:  Optional[tk.Label]  = None
        self._prog_pct: float = 0.0
        self._prog_after_id: Optional[str] = None
        self._anim_x: int = 0

        # folder list widgets (live while in config view)
        self._folder_list_frame: Optional[tk.Frame] = None
        self._folder_empty_lbl:  Optional[tk.Label] = None

        self._body: Optional[tk.Frame] = None
        self._recent_bar: Optional[tk.Frame] = None

        self._build()
        self._t = ThemeApplicator.get().build_tokens()
        ThemeApplicator.get().register(self._apply_theme)
        if store is not None:
            store.subscribe(self._on_store)

    # ------------------------------------------------------------------
    # Store subscription

    def _on_store(self, s: Any, old: Any, action: Any) -> None:
        try:
            from cerebro.v2.state.actions import (
                ScanStarted, ScanProgressSnapshot, ScanCompleted, ScanEnded,
            )
            if isinstance(action, ScanStarted):
                if self._view != "scanning":
                    self._view = "scanning"
                    self.after(0, self._rebuild_body)
            elif isinstance(action, ScanProgressSnapshot) and self._view == "scanning":
                self.after(0, lambda snap=s.scan_progress: self._update_progress(snap))
            elif isinstance(action, (ScanCompleted, ScanEnded)) and self._view == "scanning":
                self._view = "idle"
                self.after(0, self._rebuild_body)
                self.after(0, self._rebuild_recent_bar)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Theme

    def _apply_theme(self, t: dict) -> None:
        self._t = t
        self.configure(bg=t.get("bg", _NAVY))
        self._rebuild_body()
        self._rebuild_recent_bar()

    # ------------------------------------------------------------------
    # Outer shell

    def _build(self) -> None:
        bg = self._t.get("bg", _NAVY)
        self.configure(bg=bg)
        self._body = tk.Frame(self, bg=bg)
        self._body.place(relx=0, rely=0, relwidth=1, relheight=1)
        self._rebuild_body()
        self._rebuild_recent_bar()

    def _stop_animation(self) -> None:
        if self._prog_after_id:
            try:
                self.after_cancel(self._prog_after_id)
            except (tk.TclError, ValueError):
                pass
            self._prog_after_id = None

    def _rebuild_body(self) -> None:
        if self._body is None:
            return
        self._stop_animation()
        for w in self._body.winfo_children():
            w.destroy()
        bg = self._t.get("bg", _NAVY)
        self._body.configure(bg=bg)
        if self._view == "configuring":
            self._render_config()
        elif self._view == "scanning":
            self._render_scanning()
        else:
            self._render_idle()

    # ------------------------------------------------------------------
    # Idle view

    def _render_idle(self) -> None:
        t = self._t
        bg      = t.get("bg", _NAVY)
        nav_bg  = t.get("nav_bar", _NAVY_MID)
        nav_hov = t.get("accent2", _NAVY_MID_HOVER)
        fg      = t.get("fg", _WHITE)
        danger  = t.get("danger", _RED)
        success = t.get("success", _GREEN)

        scans, dupes, recovered, recent = _load_stats()
        last = recent[0] if recent else None
        has_scans = scans > 0

        col = tk.Frame(self._body, bg=bg)
        col.place(relx=0.5, y=0, anchor="n")
        tk.Frame(col, bg=bg, height=60).pack()

        if not has_scans:
            tk.Label(col, text="No scans yet", bg=bg, fg=_W38,
                     font=("Segoe UI", 22)).pack(pady=(40, 12))
            tk.Label(col,
                     text="Scan your folders to find and remove duplicate files.",
                     bg=bg, fg=_W28, font=("Segoe UI", 10),
                     wraplength=320, justify="center").pack(pady=(0, 32))
        else:
            tk.Label(col, text="Last scan summary", bg=bg, fg=fg,
                     font=("Segoe UI", 18, "bold")).pack(pady=(10, 16))
            row = tk.Frame(col, bg=bg)
            row.pack(pady=(0, 24))
            data = [
                (str(scans),            fg,      "Total scans"),
                (str(dupes),            danger,  "Duplicates found"),
                (_fmt_bytes(recovered), success, "Space recovered"),
            ]
            for i, (val, val_fg, lbl) in enumerate(data):
                if i:
                    tk.Frame(row, bg=_W8, width=1).pack(side="left", fill="y", padx=24, pady=4)
                c2 = tk.Frame(row, bg=bg)
                c2.pack(side="left")
                tk.Label(c2, text=val, bg=bg, fg=val_fg,
                         font=("Segoe UI", 20, "bold")).pack()
                tk.Label(c2, text=lbl.upper(), bg=bg, fg=_W25,
                         font=("Segoe UI", 8)).pack()

        btn_row = tk.Frame(col, bg=bg)
        btn_row.pack()
        start_btn = tk.Button(
            btn_row,
            text="Start new scan" if has_scans else "Start Scan",
            bg=nav_bg, fg=fg,
            font=("Segoe UI", 12, "bold"),
            relief="flat", cursor="hand2",
            padx=32, pady=12,
            bd=0, activebackground=nav_hov, activeforeground=fg,
            command=self._enter_config,
        )
        start_btn.pack(side="left", padx=(0, 12))
        _hover(start_btn, nav_bg, nav_hov)

        if has_scans and last:
            open_btn = tk.Button(
                btn_row, text="Open last session",
                bg=bg, fg=_W45,
                font=("Segoe UI", 11),
                relief="flat", cursor="hand2",
                padx=28, pady=10, bd=1,
                highlightbackground=_W12, highlightthickness=1,
                activebackground=bg, activeforeground=fg,
                command=lambda: self._open_session(last),
            )
            _hover(open_btn, bg, "#1A2C40")
            open_btn.pack(side="left")

        if self._advanced:
            self._build_advanced(col, bg=bg, fg=fg, danger=danger, success=success)

    # ------------------------------------------------------------------
    # Config view

    def _render_config(self) -> None:
        t = self._t
        bg      = t.get("bg", _NAVY)
        nav_bg  = t.get("nav_bar", _NAVY_MID)
        nav_hov = t.get("accent2", _NAVY_MID_HOVER)
        fg      = t.get("fg", _WHITE)

        outer = tk.Frame(self._body, bg=bg)
        outer.place(relx=0.5, rely=0.5, anchor="center")

        # Back link
        back = tk.Label(outer, text="← Back", bg=bg, fg=_W38,
                        font=("Segoe UI", 9), cursor="hand2")
        back.pack(anchor="w", pady=(0, 10))
        back.bind("<Button-1>", lambda _e: self._cancel_config())
        back.bind("<Enter>",    lambda _e: back.configure(fg=fg))
        back.bind("<Leave>",    lambda _e: back.configure(fg=_W38))

        tk.Label(outer, text="Configure Scan", bg=bg, fg=fg,
                 font=("Segoe UI", 16, "bold")).pack(anchor="w", pady=(0, 18))

        # Mode row
        mode_row = tk.Frame(outer, bg=bg)
        mode_row.pack(fill="x", pady=(0, 14))
        tk.Label(mode_row, text="SCAN MODE", bg=bg, fg=_W28,
                 font=("Segoe UI", 8, "bold")).pack(anchor="w", pady=(0, 4))
        mode_labels = [lbl for _, lbl in _SCAN_MODES]
        self._mode_var = tk.StringVar(value=mode_labels[0])
        menu = tk.OptionMenu(mode_row, self._mode_var, *mode_labels)
        menu.configure(bg=_ROW, fg=fg, activebackground=nav_bg, activeforeground=fg,
                       font=("Segoe UI", 10), relief="flat", highlightthickness=0, width=26)
        menu["menu"].configure(bg=_ROW, fg=fg, activebackground=nav_bg)
        menu.pack(fill="x")

        # Folder list header
        fl_hdr = tk.Frame(outer, bg=bg)
        fl_hdr.pack(fill="x", pady=(4, 4))
        tk.Label(fl_hdr, text="FOLDERS TO SCAN", bg=bg, fg=_W28,
                 font=("Segoe UI", 8, "bold")).pack(side="left")
        add_row = tk.Frame(fl_hdr, bg=bg)
        add_row.pack(side="right")
        self._mk_small_btn(add_row, "+ Local",   self._add_local).pack(side="left", padx=2)
        self._mk_small_btn(add_row, "+ Network", self._add_network).pack(side="left", padx=2)

        # Folder list box
        list_outer = tk.Frame(outer, bg=_BORDER, bd=1, relief="solid",
                              width=460, height=140)
        list_outer.pack(fill="x", pady=(0, 16))
        list_outer.pack_propagate(False)

        canvas = tk.Canvas(list_outer, bg=bg, highlightthickness=0)
        vsb = tk.Scrollbar(list_outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        self._folder_list_frame = tk.Frame(canvas, bg=bg)
        win_id = canvas.create_window((0, 0), window=self._folder_list_frame, anchor="nw")
        self._folder_list_frame.bind(
            "<Configure>",
            lambda _e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(win_id, width=e.width))

        self._folder_empty_lbl = tk.Label(
            self._folder_list_frame,
            text="No folders added yet.\nClick  + Local  or  + Network  above.",
            bg=bg, fg=_W28, font=("Segoe UI", 9), justify="center",
        )
        self._folder_empty_lbl.pack(pady=20)

        self._folder_row_map.clear()
        for p in self._config_folders:
            self._render_folder_row(p)

        # Action buttons
        btn_row = tk.Frame(outer, bg=bg)
        btn_row.pack(fill="x")
        start_btn = tk.Button(
            btn_row, text="Start Scan",
            bg=nav_bg, fg=fg,
            font=("Segoe UI", 11, "bold"),
            relief="flat", cursor="hand2",
            padx=28, pady=10,
            bd=0, activebackground=nav_hov, activeforeground=fg,
            command=self._confirm_config,
        )
        start_btn.pack(side="left", padx=(0, 10))
        _hover(start_btn, nav_bg, nav_hov)
        cancel_btn = tk.Button(
            btn_row, text="Cancel",
            bg=bg, fg=_W38,
            font=("Segoe UI", 10),
            relief="flat", cursor="hand2",
            padx=18, pady=9, bd=1,
            highlightbackground=_W12, highlightthickness=1,
            activebackground=bg, activeforeground=fg,
            command=self._cancel_config,
        )
        cancel_btn.pack(side="left")

    # ------------------------------------------------------------------
    # Scanning view

    def _render_scanning(self) -> None:
        t = self._t
        bg     = t.get("bg", _NAVY)
        fg     = t.get("fg", _WHITE)
        accent = t.get("accent", "#2563EB")
        danger = t.get("danger", _RED)

        outer = tk.Frame(self._body, bg=bg)
        outer.place(relx=0.5, rely=0.5, anchor="center")

        tk.Label(outer, text="Scanning…", bg=bg, fg=fg,
                 font=("Segoe UI", 22, "bold")).pack(pady=(0, 6))

        self._prog_stage_lbl = tk.Label(outer, text="Starting…", bg=bg, fg=_W38,
                                         font=("Segoe UI", 9))
        self._prog_stage_lbl.pack(pady=(0, 18))

        # Progress bar track
        bar_bg = tk.Frame(outer, bg=_W12, height=8, width=460)
        bar_bg.pack(fill="x", pady=(0, 12))
        bar_bg.pack_propagate(False)
        self._prog_bar = tk.Canvas(bar_bg, bg=_W12, highlightthickness=0, height=8)
        self._prog_bar.pack(fill="both", expand=True)
        self._prog_pct = 0.0
        self._anim_x = 0
        self._animate_bar()

        self._prog_files_lbl = tk.Label(outer, text="Scanning files…", bg=bg, fg=_W45,
                                         font=("Segoe UI", 10))
        self._prog_files_lbl.pack(pady=(0, 4))

        self._prog_file_lbl = tk.Label(outer, text="", bg=bg, fg=_W28,
                                        font=("Segoe UI", 8),
                                        wraplength=460, justify="center")
        self._prog_file_lbl.pack(pady=(0, 24))

        cancel_btn = tk.Button(
            outer, text="Cancel Scan",
            bg=bg, fg=danger,
            font=("Segoe UI", 9),
            relief="flat", cursor="hand2",
            padx=18, pady=6, bd=1,
            highlightbackground="#3D1A1A", highlightthickness=1,
            activebackground=bg, activeforeground=danger,
            command=self._do_cancel_scan,
        )
        cancel_btn.pack()

    def _animate_bar(self) -> None:
        if self._prog_bar is None:
            return
        try:
            if not self._prog_bar.winfo_exists():
                return
            w = self._prog_bar.winfo_width() or 460
            h = self._prog_bar.winfo_height() or 8
            self._prog_bar.delete("all")
            accent = self._t.get("accent", "#2563EB")
            if self._prog_pct > 0:
                fill_w = int(w * min(self._prog_pct, 1.0))
                self._prog_bar.create_rectangle(0, 0, fill_w, h, fill=accent, outline="")
            else:
                block = 90
                x1 = (self._anim_x % (w + block)) - block
                x2 = x1 + block
                self._prog_bar.create_rectangle(
                    max(0, x1), 0, min(w, x2), h, fill=accent, outline="")
                self._anim_x += 10
        except tk.TclError:
            return
        self._prog_after_id = self.after(40, self._animate_bar)

    def _update_progress(self, prog: dict) -> None:
        if self._view != "scanning":
            return
        total   = prog.get("files_total", 0) or 0
        scanned = prog.get("files_scanned", 0) or 0
        stage   = (prog.get("stage", "") or "").replace("_", " ").title()
        current = prog.get("current_file", "") or ""

        self._prog_pct = (scanned / total) if total > 0 else 0.0

        if self._prog_stage_lbl and self._prog_stage_lbl.winfo_exists():
            self._prog_stage_lbl.configure(text=stage or "Scanning…")

        if self._prog_files_lbl and self._prog_files_lbl.winfo_exists():
            if total > 0:
                self._prog_files_lbl.configure(text=f"Files scanned: {scanned:,} / {total:,}")
            elif scanned > 0:
                self._prog_files_lbl.configure(text=f"Files scanned: {scanned:,}")

        if self._prog_file_lbl and self._prog_file_lbl.winfo_exists():
            if current and len(current) > 60:
                current = "…" + current[-57:]
            self._prog_file_lbl.configure(text=current)

    # ------------------------------------------------------------------
    # Folder management (config view)

    def _add_local(self) -> None:
        path = filedialog.askdirectory(title="Select folder to scan",
                                       parent=self.winfo_toplevel())
        if path:
            p = Path(path)
            if p not in self._config_folders:
                self._config_folders.append(p)
                self._render_folder_row(p)

    def _add_network(self) -> None:
        try:
            from cerebro.v2.ui.folder_panel import NetworkPathDialog
            dlg = NetworkPathDialog(self.winfo_toplevel())
            dlg.show()
            if dlg.result:
                from cerebro.utils.paths import validate_scan_path
                from tkinter import messagebox
                ok, reason = validate_scan_path(dlg.result)
                if not ok:
                    messagebox.showwarning(
                        "Path Warning",
                        f"Path may be unreachable:\n{reason}\n\nIt will still be added.",
                        parent=self.winfo_toplevel(),
                    )
                p = Path(dlg.result)
                if p not in self._config_folders:
                    self._config_folders.append(p)
                    self._render_folder_row(p)
        except Exception:
            pass

    def _render_folder_row(self, path: Path) -> None:
        if self._folder_list_frame is None:
            return
        if self._folder_empty_lbl and self._folder_empty_lbl.winfo_exists():
            self._folder_empty_lbl.pack_forget()
        row = tk.Frame(self._folder_list_frame, bg=_ROW)
        row.pack(fill="x", padx=4, pady=2)
        name = str(path)
        if len(name) > 54:
            name = "…" + name[-53:]
        tk.Label(row, text=name, bg=_ROW, fg=_WHITE,
                 font=("Segoe UI", 9), anchor="w").pack(
                     side="left", padx=8, pady=5, fill="x", expand=True)
        rm = tk.Button(row, text="✕", bg=_ROW, fg=_RED,
                       activebackground=_ROW, activeforeground=_RED,
                       font=("Segoe UI", 9, "bold"), relief="flat",
                       cursor="hand2", padx=6, pady=3,
                       command=lambda p=path, r=row: self._remove_folder(p, r))
        rm.pack(side="right", padx=4)
        self._folder_row_map[path] = row

    def _remove_folder(self, path: Path, row: tk.Frame) -> None:
        if path in self._config_folders:
            self._config_folders.remove(path)
        self._folder_row_map.pop(path, None)
        row.destroy()
        if not self._config_folders and self._folder_empty_lbl:
            self._folder_empty_lbl.pack(pady=20)

    # ------------------------------------------------------------------
    # View transitions

    def _enter_config(self) -> None:
        self._view = "configuring"
        self._config_folders = []
        self._folder_row_map = {}
        self._rebuild_body()

    def _cancel_config(self) -> None:
        self._view = "idle"
        self._rebuild_body()

    def _confirm_config(self) -> None:
        from tkinter import messagebox
        if not self._config_folders:
            messagebox.showwarning("No folders",
                                   "Add at least one folder to scan.",
                                   parent=self.winfo_toplevel())
            return
        mode_label = self._mode_var.get() if self._mode_var else "Duplicate Files"
        mode = next((k for k, lbl in _SCAN_MODES if lbl == mode_label), "files")
        if self._on_start_scan:
            self._on_start_scan(list(self._config_folders), mode)

    def _do_cancel_scan(self) -> None:
        if self._on_cancel_scan:
            self._on_cancel_scan()

    # ------------------------------------------------------------------
    # Recent bar

    def _rebuild_recent_bar(self) -> None:
        if self._recent_bar is not None:
            try:
                self._recent_bar.destroy()
            except tk.TclError:
                pass
        _, _, _, recent = _load_stats()
        bg = self._t.get("bg", _NAVY)
        bar = tk.Frame(self, bg=bg, height=44)
        bar.place(relx=0, rely=1.0, anchor="sw", relwidth=1)
        bar.pack_propagate(False)
        self._recent_bar = bar
        tk.Frame(bar, bg=_W6, height=1).pack(fill="x")
        inner = tk.Frame(bar, bg=bg)
        inner.pack(fill="both", expand=True, padx=20)
        tk.Label(inner, text="RECENT", bg=bg, fg=_W22,
                 font=("Segoe UI", 8, "bold")).pack(side="left", padx=(0, 12))
        if recent:
            for session in recent:
                txt = _chip_label(session)
                chip = tk.Label(inner, text=txt, bg=_W5, fg=_W38,
                                font=("Segoe UI", 9), padx=8, pady=2, cursor="hand2")
                chip.pack(side="left", padx=3)
                chip.bind("<Button-1>", lambda _e, s=session: self._open_session(s))
                chip.bind("<Enter>",    lambda _e, w=chip: w.configure(bg=_W9, fg=_W45))
                chip.bind("<Leave>",    lambda _e, w=chip: w.configure(bg=_W5, fg=_W38))
        else:
            tk.Label(inner, text="No scans yet", bg=bg, fg=_W22,
                     font=("Segoe UI", 9)).pack(side="left")
        new_lbl = tk.Label(inner, text="+ New scan", bg=bg, fg=_W28,
                           font=("Segoe UI", 9), cursor="hand2")
        new_lbl.pack(side="right")
        new_lbl.bind("<Button-1>", lambda _e: self._enter_config())

    # ------------------------------------------------------------------
    # Advanced panel (when toggle enabled)

    def _build_advanced(self, parent: tk.Frame, bg: str, fg: str,
                        danger: str, success: str) -> None:
        tk.Frame(parent, bg=_W6, height=1).pack(fill="x", pady=(20, 10))
        tk.Label(parent, text="Scan Profiles", bg=bg, fg=_W38,
                 font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=40)
        pf = tk.Frame(parent, bg=bg)
        pf.pack(fill="x", padx=40, pady=8)
        for name, desc in [
            ("Quick Scan", "Files only, top-level folders"),
            ("Deep Scan", "All file types, recursive"),
            ("Photos Only", "Image dedup with visual similarity"),
        ]:
            row = tk.Frame(pf, bg=_W5, padx=12, pady=8)
            row.pack(fill="x", pady=2)
            tk.Label(row, text=name, bg=_W5, fg=fg,
                     font=("Segoe UI", 10, "bold")).pack(anchor="w")
            tk.Label(row, text=desc, bg=_W5, fg=_W38,
                     font=("Segoe UI", 9)).pack(anchor="w")

    # ------------------------------------------------------------------
    # Widget helper

    def _mk_small_btn(self, parent: tk.Frame, text: str, cmd) -> tk.Button:
        t = self._t
        bg = t.get("nav_bar", _NAVY_MID)
        hv = t.get("accent2", _NAVY_MID_HOVER)
        fg = t.get("fg", _WHITE)
        b = tk.Button(parent, text=text, command=cmd,
                      bg=bg, fg=fg, activebackground=hv, activeforeground=fg,
                      font=("Segoe UI", 9), relief="flat", cursor="hand2",
                      padx=10, pady=4, highlightthickness=0)
        b.bind("<Enter>", lambda _e: b.configure(bg=hv))
        b.bind("<Leave>", lambda _e: b.configure(bg=bg))
        return b

    # ------------------------------------------------------------------
    # Callbacks

    def _open_session(self, session: Any) -> None:
        if session and self._on_open_session:
            self._on_open_session(session)

    # ------------------------------------------------------------------
    # Public API

    def enter_config(self) -> None:
        """Programmatically switch to the embedded scan-config view."""
        self._enter_config()

    def set_advanced(self, value: bool) -> None:
        self._advanced = value
        if self._view == "idle":
            self._rebuild_body()

    def refresh(self) -> None:
        if self._view == "idle":
            self._rebuild_body()
        self._rebuild_recent_bar()

    def on_show(self) -> None:
        self.refresh()
