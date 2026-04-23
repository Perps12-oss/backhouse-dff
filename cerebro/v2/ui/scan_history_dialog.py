"""Scan history dialog backed by sqlite (with legacy JSON migration)."""

from __future__ import annotations

import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import tkinter as tk
from tkinter import ttk

try:
    import customtkinter as ctk
    CTkToplevel = ctk.CTkToplevel
    CTkFrame   = ctk.CTkFrame
    CTkLabel   = ctk.CTkLabel
    CTkButton  = ctk.CTkButton
    CTkScrollableFrame = ctk.CTkScrollableFrame
except ImportError:
    CTkToplevel = tk.Toplevel
    CTkFrame   = tk.Frame
    CTkLabel   = tk.Label
    CTkButton  = tk.Button
    CTkScrollableFrame = tk.Frame

from cerebro.v2.core.design_tokens import Spacing, Typography, Dimensions
from cerebro.v2.core.theme_bridge_v2 import theme_color, subscribe_to_theme
from cerebro.v2.ui.feedback import confirm_yes_no
from cerebro.v2.core.scan_history_db import get_scan_history_db

logger = logging.getLogger(__name__)


_LEGACY_HISTORY_FILE = Path.home() / ".cerebro" / "scan_history.json"


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------

def _load_history() -> List[Dict[str, Any]]:
    db = get_scan_history_db()
    rows = db.get_recent(limit=500)
    return [
        {
            "timestamp": r.timestamp,
            "mode": r.mode,
            "folders": r.folders,
            "groups_found": r.groups_found,
            "files_found": r.files_found,
            "bytes_reclaimable": r.bytes_reclaimable,
            "duration_seconds": r.duration_seconds,
        }
        for r in rows
    ]


def _save_history(entries: List[Dict[str, Any]]) -> None:
    db = get_scan_history_db()
    db.clear()
    for row in entries:
        try:
            db.record_scan(
                mode=str(row.get("mode", "files")),
                folders=[str(x) for x in row.get("folders", [])],
                groups_found=int(row.get("groups_found", 0)),
                files_found=int(row.get("files_found", 0)),
                bytes_reclaimable=int(row.get("bytes_reclaimable", 0)),
                duration_seconds=float(row.get("duration_seconds", 0.0)),
                timestamp=float(row.get("timestamp", time.time())),
            )
        except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
            continue


def record_scan(
    mode: str,
    folders: List[str],
    groups_found: int,
    files_found: int,
    bytes_reclaimable: int,
    duration_seconds: float,
) -> None:
    """
    Append a completed scan record to the history file.
    Call this from the scan completion path (e.g. AppShell / ScanPage) after every successful scan.
    """
    get_scan_history_db().record_scan(
        mode=mode,
        folders=folders,
        groups_found=groups_found,
        files_found=files_found,
        bytes_reclaimable=bytes_reclaimable,
        duration_seconds=duration_seconds,
    )


# ---------------------------------------------------------------------------
# Dialog
# ---------------------------------------------------------------------------

class ScanHistoryDialog:
    """
    Lightweight dialog showing the last N scan sessions.

    Usage::

        ScanHistoryDialog.show(parent=app_root)  # any CTk / Tk toplevel (e.g. AppShell)
    """

    @classmethod
    def show(cls, parent: tk.Misc) -> None:
        cls(parent)

    def __init__(self, parent: tk.Misc) -> None:
        self._parent = parent
        self._migrate_legacy_history_if_present()
        self._win = CTkToplevel(parent)
        self._win.title("Scan History")
        self._win.geometry("780x480")
        self._win.transient(parent)
        self._win.grab_set()
        subscribe_to_theme(self._win, self._apply_theme)
        self._build()
        self._load()

    # ------------------------------------------------------------------

    def _build(self) -> None:
        self._win.configure(fg_color=theme_color("base.background"))

        # Title row
        header = CTkFrame(self._win, fg_color=theme_color("toolbar.background"), height=48)
        header.pack(fill="x")
        header.pack_propagate(False)
        CTkLabel(
            header, text="Scan History",
            font=("", 15, "bold"),
            text_color=theme_color("base.foreground"),
        ).pack(side="left", padx=Spacing.LG, pady=Spacing.SM)

        CTkButton(
            header, text="Clear History", width=120, height=32,
            font=Typography.FONT_SM,
            fg_color=theme_color("button.danger"),
            hover_color=theme_color("button.dangerHover"),
            corner_radius=Spacing.BORDER_RADIUS_SM,
            command=self._clear_history,
        ).pack(side="right", padx=Spacing.MD, pady=Spacing.SM)

        # Treeview
        cols = ("date", "mode", "folders", "groups", "files", "reclaimable", "duration")
        tree_frame = CTkFrame(self._win, fg_color=theme_color("base.backgroundSecondary"))
        tree_frame.pack(fill="both", expand=True, padx=Spacing.MD, pady=Spacing.SM)

        self._tree = ttk.Treeview(tree_frame, columns=cols, show="headings", selectmode="browse")

        headings = {
            "date":        ("Date / Time",  160),
            "mode":        ("Mode",          90),
            "folders":     ("Folders",       90),
            "groups":      ("Groups",        70),
            "files":       ("Files",         70),
            "reclaimable": ("Reclaimable",  100),
            "duration":    ("Duration",      80),
        }
        for col, (text, width) in headings.items():
            self._tree.heading(col, text=text)
            self._tree.column(col, width=width, anchor="center")
        self._tree.column("date", anchor="w")

        sb = ttk.Scrollbar(tree_frame, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self._tree.pack(fill="both", expand=True)

        # Footer
        footer = CTkFrame(self._win, fg_color=theme_color("toolbar.background"), height=44)
        footer.pack(fill="x", side="bottom")
        footer.pack_propagate(False)
        self._count_lbl = CTkLabel(
            footer, text="", font=Typography.FONT_SM,
            text_color=theme_color("base.foregroundMuted"),
        )
        self._count_lbl.pack(side="left", padx=Spacing.LG, pady=Spacing.SM)
        CTkButton(
            footer, text="Close", width=90, height=32,
            font=Typography.FONT_SM,
            fg_color=theme_color("button.secondary"),
            hover_color=theme_color("button.secondaryHover"),
            corner_radius=Spacing.BORDER_RADIUS_SM,
            command=self._win.destroy,
        ).pack(side="right", padx=Spacing.MD, pady=Spacing.SM)

    def _load(self) -> None:
        """Populate treeview from history file."""
        self._tree.delete(*self._tree.get_children())
        entries = _load_history()
        for entry in reversed(entries):  # newest first
            ts      = entry.get("timestamp", 0)
            date    = datetime.fromtimestamp(ts).strftime("%Y-%m-%d  %H:%M") if ts else "—"
            mode    = entry.get("mode", "—").replace("_", " ").title()
            folders = str(len(entry.get("folders", [])))
            groups  = str(entry.get("groups_found", 0))
            files   = str(entry.get("files_found", 0))
            rec     = _fmt_bytes(entry.get("bytes_reclaimable", 0))
            dur     = _fmt_dur(entry.get("duration_seconds", 0))
            self._tree.insert("", "end", values=(date, mode, folders, groups, files, rec, dur))
        count = len(entries)
        self._count_lbl.configure(text=f"{count} scan{'s' if count != 1 else ''} recorded")

    def _clear_history(self) -> None:
        if confirm_yes_no(self._win, "Clear History", "Delete all scan history entries?"):
            _save_history([])
            self._load()

    def _apply_theme(self) -> None:
        try:
            self._win.configure(fg_color=theme_color("base.background"))
        except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
            pass

    def _migrate_legacy_history_if_present(self) -> None:
        try:
            if _LEGACY_HISTORY_FILE.exists():
                get_scan_history_db().import_legacy_json(_LEGACY_HISTORY_FILE)
        except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
            pass


# ---------------------------------------------------------------------------
# Tiny format helpers
# ---------------------------------------------------------------------------

def _fmt_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def _fmt_dur(s: float) -> str:
    s = int(s)
    if s < 60:
        return f"{s}s"
    return f"{s // 60}m {s % 60}s"
