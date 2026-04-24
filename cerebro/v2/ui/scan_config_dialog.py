"""Scan configuration dialog — folder picker + mode selector.

Opens modally before a scan starts. Returns ``(folders, mode)`` on confirm,
``([], "")`` on cancel.
"""
from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import List, Tuple

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

_BG     = "#1E3A5F"
_FG     = "#FFFFFF"
_BTN    = "#2563EB"
_BTN_HV = "#1D4ED8"
_DANGER = "#E74C3C"
_ROW    = "#162D4A"
_BORDER = "#2D4F73"


class ScanConfigDialog:
    """Modal dialog for picking folders and scan mode before a scan."""

    def __init__(self, parent: tk.Misc) -> None:
        self._parent = parent
        self._folders: List[Path] = []
        self._result: Tuple[List[Path], str] = ([], "")
        self._row_frames: dict = {}

    def show(self) -> Tuple[List[Path], str]:
        """Block until the user confirms or cancels, then return (folders, mode)."""
        win = tk.Toplevel(self._parent)
        win.title("Configure Scan")
        win.resizable(True, True)
        win.minsize(480, 380)
        win.configure(bg=_BG)
        win.grab_set()

        # Centre relative to parent
        win.update_idletasks()
        pw = self._parent.winfo_rootx()
        py = self._parent.winfo_rooty()
        pw2 = self._parent.winfo_width()
        py2 = self._parent.winfo_height()
        w, h = 540, 460
        x = pw + (pw2 - w) // 2
        y = py + (py2 - h) // 2
        win.geometry(f"{w}x{h}+{x}+{y}")

        self._win = win
        self._build(win)
        win.wait_window()
        return self._result

    # ------------------------------------------------------------------
    # Build

    def _build(self, win: tk.Toplevel) -> None:
        # ── Header ───────────────────────────────────────────────────────
        hdr = tk.Frame(win, bg="#0B1929", height=48)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(hdr, text="Select Folders & Scan Mode",
                 bg="#0B1929", fg=_FG,
                 font=("Segoe UI", 13, "bold")).pack(side="left", padx=16, pady=12)

        body = tk.Frame(win, bg=_BG)
        body.pack(fill="both", expand=True, padx=16, pady=12)

        # ── Scan mode ────────────────────────────────────────────────────
        mode_row = tk.Frame(body, bg=_BG)
        mode_row.pack(fill="x", pady=(0, 10))
        tk.Label(mode_row, text="Scan mode:", bg=_BG, fg=_FG,
                 font=("Segoe UI", 10)).pack(side="left", padx=(0, 8))

        mode_labels = [label for _, label in _SCAN_MODES]
        self._mode_var = tk.StringVar(value=mode_labels[0])
        mode_menu = tk.OptionMenu(mode_row, self._mode_var, *mode_labels)
        mode_menu.configure(
            bg=_ROW, fg=_FG, activebackground=_BTN, activeforeground=_FG,
            font=("Segoe UI", 10), relief="flat", highlightthickness=0,
        )
        mode_menu["menu"].configure(bg=_ROW, fg=_FG, activebackground=_BTN)
        mode_menu.pack(side="left", fill="x", expand=True)

        # ── Folder list header ───────────────────────────────────────────
        fl_hdr = tk.Frame(body, bg=_BG)
        fl_hdr.pack(fill="x", pady=(4, 4))
        tk.Label(fl_hdr, text="Folders to scan:", bg=_BG, fg=_FG,
                 font=("Segoe UI", 10)).pack(side="left")

        add_row = tk.Frame(fl_hdr, bg=_BG)
        add_row.pack(side="right")
        self._mk_btn(add_row, "+ Local", self._add_local, small=True).pack(side="left", padx=2)
        self._mk_btn(add_row, "+ Network", self._add_network, small=True).pack(side="left", padx=2)

        # ── Folder list ──────────────────────────────────────────────────
        list_outer = tk.Frame(body, bg=_BORDER, bd=1, relief="solid")
        list_outer.pack(fill="both", expand=True, pady=(0, 10))

        self._list_canvas = tk.Canvas(list_outer, bg=_BG, highlightthickness=0)
        scrollbar = tk.Scrollbar(list_outer, orient="vertical",
                                 command=self._list_canvas.yview)
        self._list_canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self._list_canvas.pack(side="left", fill="both", expand=True)

        self._list_frame = tk.Frame(self._list_canvas, bg=_BG)
        self._list_win = self._list_canvas.create_window(
            (0, 0), window=self._list_frame, anchor="nw"
        )
        self._list_frame.bind("<Configure>", self._on_list_configure)
        self._list_canvas.bind("<Configure>", self._on_canvas_configure)

        self._empty_lbl = tk.Label(
            self._list_frame,
            text="No folders added yet.\nClick  + Local  or  + Network  above.",
            bg=_BG, fg="#7090A8",
            font=("Segoe UI", 10), justify="center",
        )
        self._empty_lbl.pack(pady=24)

        # ── Footer buttons ───────────────────────────────────────────────
        footer = tk.Frame(win, bg=_BG)
        footer.pack(fill="x", padx=16, pady=(0, 14))
        self._mk_btn(footer, "Cancel", self._cancel).pack(side="right", padx=(6, 0))
        self._start_btn = self._mk_btn(footer, "Start Scan", self._confirm,
                                       primary=True)
        self._start_btn.pack(side="right")

        win.bind("<Escape>", lambda _e: self._cancel())

    # ------------------------------------------------------------------
    # Folder list management

    def _add_local(self) -> None:
        path = filedialog.askdirectory(title="Select folder to scan",
                                       parent=self._win)
        if path:
            self._add_folder(Path(path))

    def _add_network(self) -> None:
        from cerebro.v2.ui.folder_panel import NetworkPathDialog
        dlg = NetworkPathDialog(self._win)
        dlg.show()
        if dlg.result:
            from cerebro.utils.paths import validate_scan_path
            ok, reason = validate_scan_path(dlg.result)
            if not ok:
                messagebox.showwarning(
                    "Path Warning",
                    f"Path may be unreachable:\n{reason}\n\nIt will still be added.",
                    parent=self._win,
                )
            self._add_folder(Path(dlg.result))

    def _add_folder(self, path: Path) -> None:
        if path in self._folders:
            return
        self._folders.append(path)
        self._empty_lbl.pack_forget()
        self._render_folder_row(path)

    def _render_folder_row(self, path: Path) -> None:
        row = tk.Frame(self._list_frame, bg=_ROW)
        row.pack(fill="x", padx=4, pady=2)

        name = str(path)
        if len(name) > 56:
            name = "…" + name[-55:]
        tk.Label(row, text=name, bg=_ROW, fg=_FG,
                 font=("Segoe UI", 9), anchor="w").pack(side="left", padx=8, pady=6,
                                                          fill="x", expand=True)
        rm = tk.Button(row, text="✕", bg=_ROW, fg="#E74C3C",
                       activebackground=_ROW, activeforeground=_DANGER,
                       font=("Segoe UI", 9, "bold"), relief="flat",
                       cursor="hand2", padx=6, pady=4,
                       command=lambda p=path, r=row: self._remove_folder(p, r))
        rm.pack(side="right", padx=4)
        self._row_frames[path] = row

    def _remove_folder(self, path: Path, row: tk.Frame) -> None:
        if path in self._folders:
            self._folders.remove(path)
        self._row_frames.pop(path, None)
        row.destroy()
        if not self._folders:
            self._empty_lbl.pack(pady=24)

    def _on_list_configure(self, _event: object) -> None:
        self._list_canvas.configure(
            scrollregion=self._list_canvas.bbox("all")
        )

    def _on_canvas_configure(self, event: tk.Event) -> None:  # type: ignore[type-arg]
        self._list_canvas.itemconfigure(self._list_win, width=event.width)

    # ------------------------------------------------------------------
    # Confirm / cancel

    def _confirm(self) -> None:
        if not self._folders:
            messagebox.showwarning("No folders",
                                   "Please add at least one folder to scan.",
                                   parent=self._win)
            return
        label = self._mode_var.get()
        mode = next((k for k, lbl in _SCAN_MODES if lbl == label), "files")
        self._result = (list(self._folders), mode)
        self._win.destroy()

    def _cancel(self) -> None:
        self._result = ([], "")
        self._win.destroy()

    # ------------------------------------------------------------------
    # Widget helper

    def _mk_btn(self, parent: tk.Frame, text: str, cmd,
                primary: bool = False, small: bool = False) -> tk.Button:
        bg = _BTN if primary else _ROW
        hv = _BTN_HV if primary else "#2A4F78"
        font_size = 9 if small else 10
        b = tk.Button(
            parent, text=text, command=cmd,
            bg=bg, fg=_FG,
            activebackground=hv, activeforeground=_FG,
            font=("Segoe UI", font_size, "bold" if primary else "normal"),
            relief="flat", cursor="hand2",
            padx=10 if small else 18, pady=5,
            highlightthickness=0,
        )
        b.bind("<Enter>", lambda _e: b.configure(bg=hv))
        b.bind("<Leave>", lambda _e: b.configure(bg=bg))
        return b
