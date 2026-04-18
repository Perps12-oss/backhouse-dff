"""
HistoryPage — full-tab History page for the CEREBRO v2 overhaul.

Content (two sub-tabs):
  • Scan History    — replicates ScanHistoryDialog treeview, in-page
  • Deletion History — replicates DeletionHistoryDialog treeview, in-page

Design tokens applied: NAVY bg, NAVY_MID headers, BORDER separators,
FONT_* typography, PANEL_BG sub-tab strip.
"""
from __future__ import annotations

import threading
import tkinter as tk
from datetime import datetime
from tkinter import ttk
from typing import List

from cerebro.v2.ui.design_tokens import (
    BORDER, CARD_BG, FONT_BODY, FONT_HEADER, FONT_SMALL, FONT_TITLE,
    NAVY, NAVY_MID, PAD_X, PAD_Y, RED, RED_DARK, ROW_SEL, TEXT_MUTED,
    TEXT_PRIMARY, TEXT_SECONDARY,
)

# ---------------------------------------------------------------------------
# Tiny format helpers (same logic as scan_history_dialog.py)
# ---------------------------------------------------------------------------

def _fmt_bytes(n: int) -> str:
    val = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if val < 1024 or unit == "TB":
            return f"{int(val)} {unit}" if unit == "B" else f"{val:.1f} {unit}"
        val /= 1024
    return f"{val:.1f} PB"


def _fmt_dur(s: float) -> str:
    s = int(s)
    if s < 60:
        return f"{s}s"
    return f"{s // 60}m {s % 60}s"


# ---------------------------------------------------------------------------
# _SectionHeader
# ---------------------------------------------------------------------------

class _SectionHeader(tk.Frame):
    """Dark header bar with a title on the left and optional button on right."""

    def __init__(self, parent: tk.Widget, title: str, btn_text: str = "",
                 btn_cmd=None) -> None:
        super().__init__(parent, bg=NAVY_MID, height=36)
        self.pack_propagate(False)

        tk.Label(
            self, text=title, bg=NAVY_MID, fg=TEXT_PRIMARY,
            font=FONT_HEADER,
        ).pack(side="left", padx=PAD_X)

        if btn_text and btn_cmd:
            tk.Button(
                self, text=btn_text, command=btn_cmd,
                bg=RED, fg=TEXT_PRIMARY, activebackground=RED_DARK,
                activeforeground=TEXT_PRIMARY, relief="flat",
                font=FONT_SMALL, cursor="hand2", padx=10,
            ).pack(side="right", padx=PAD_X, pady=5)


# ---------------------------------------------------------------------------
# _SubTabBar  — "Scan History" | "Deletion History"
# ---------------------------------------------------------------------------

class _SubTabBar(tk.Frame):
    TABS = [("scan", "Scan History"), ("deletion", "Deletion History")]

    def __init__(self, parent: tk.Widget, on_change) -> None:
        super().__init__(parent, bg=NAVY_MID, height=34)
        self.pack_propagate(False)
        self._on_change = on_change
        self._active = "scan"
        self._btns: dict[str, tk.Label] = {}

        for key, label in self.TABS:
            lbl = tk.Label(
                self, text=label, bg=NAVY_MID, fg=TEXT_SECONDARY,
                font=FONT_BODY, cursor="hand2", padx=14,
            )
            lbl.pack(side="left")
            lbl.bind("<Button-1>", lambda e, k=key: self._select(k))
            self._btns[key] = lbl

        self._select("scan")

    def _select(self, key: str) -> None:
        for k, lbl in self._btns.items():
            lbl.configure(
                fg=TEXT_PRIMARY if k == key else TEXT_SECONDARY,
                font=(FONT_BODY[0], FONT_BODY[1], "bold") if k == key else FONT_BODY,
            )
        self._active = key
        self._on_change(key)


# ---------------------------------------------------------------------------
# _ScanHistoryPanel
# ---------------------------------------------------------------------------

class _ScanHistoryPanel(tk.Frame):
    """Treeview showing scan history entries, loaded from SQLite."""

    _COLS = ("date", "mode", "folders", "groups", "files", "reclaimable", "duration")
    _HEADINGS = {
        "date":        ("Date / Time",  160),
        "mode":        ("Mode",          90),
        "folders":     ("Folders",       80),
        "groups":      ("Groups",        70),
        "files":       ("Files",         70),
        "reclaimable": ("Reclaimable",  110),
        "duration":    ("Duration",      80),
    }

    def __init__(self, parent: tk.Widget, on_session_click=None) -> None:
        super().__init__(parent, bg=NAVY)
        self._on_session_click = on_session_click
        self._entries: list = []
        self._build()

    def _build(self) -> None:
        header = _SectionHeader(
            self, "Scan History",
            btn_text="Clear History", btn_cmd=self._clear,
        )
        header.pack(fill="x")

        # Separator
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")

        # Treeview container
        tree_frame = tk.Frame(self, bg=NAVY)
        tree_frame.pack(fill="both", expand=True, padx=PAD_X, pady=(PAD_Y, 0))

        style = ttk.Style()
        style.theme_use("default")
        style.configure(
            "History.Treeview",
            background=CARD_BG, foreground=TEXT_PRIMARY,
            fieldbackground=CARD_BG, rowheight=26,
            font=FONT_BODY,
        )
        style.configure(
            "History.Treeview.Heading",
            background=NAVY_MID, foreground=TEXT_PRIMARY,
            font=FONT_SMALL, relief="flat",
        )
        style.map("History.Treeview", background=[("selected", ROW_SEL)])

        self._tree = ttk.Treeview(
            tree_frame, columns=self._COLS, show="headings",
            selectmode="browse", style="History.Treeview",
        )
        for col, (text, width) in self._HEADINGS.items():
            self._tree.heading(col, text=text)
            anchor = "w" if col == "date" else "center"
            self._tree.column(col, width=width, anchor=anchor)

        sb = ttk.Scrollbar(tree_frame, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self._tree.pack(fill="both", expand=True)

        # Double-click opens session in Results
        self._tree.bind("<Double-1>", self._on_row_double_click)

        # Footer count label + hint
        self._count_lbl = tk.Label(
            self, text="", bg=NAVY_MID, fg=TEXT_MUTED, font=FONT_SMALL,
        )
        self._count_lbl.pack(fill="x", side="bottom", pady=(PAD_Y, 0))

    def load(self) -> None:
        """Reload from SQLite in a background thread."""
        threading.Thread(target=self._worker, daemon=True).start()

    def _worker(self) -> None:
        try:
            from cerebro.v2.core.scan_history_db import get_scan_history_db
            entries = get_scan_history_db().get_recent(limit=500)
        except Exception:
            entries = []
        self.after(0, lambda: self._populate(entries))

    def _populate(self, entries) -> None:
        self._entries = list(entries)
        self._iid_to_idx: dict[str, int] = {}
        self._tree.delete(*self._tree.get_children())
        for idx, entry in enumerate(entries):
            ts  = entry.timestamp or 0
            date = datetime.fromtimestamp(ts).strftime("%Y-%m-%d  %H:%M") if ts else "—"
            mode = entry.mode.replace("_", " ").title()
            folders = str(len(entry.folders))
            groups  = str(entry.groups_found)
            files   = str(entry.files_found)
            rec     = _fmt_bytes(entry.bytes_reclaimable)
            dur     = _fmt_dur(entry.duration_seconds)
            iid = self._tree.insert("", "end", values=(date, mode, folders, groups, files, rec, dur))
            self._iid_to_idx[iid] = idx
        count = len(entries)
        hint = "  Double-click a row to load session" if count and self._on_session_click else ""
        self._count_lbl.configure(
            text=f"  {count} scan{'s' if count != 1 else ''} recorded{hint}"
        )

    def _on_row_double_click(self, event) -> None:
        if not self._on_session_click:
            return
        sel = self._tree.selection()
        if not sel:
            return
        idx = self._iid_to_idx.get(sel[0])
        if idx is not None and idx < len(self._entries):
            self._on_session_click(self._entries[idx])

    def _clear(self) -> None:
        from cerebro.v2.ui.feedback import confirm_yes_no
        if confirm_yes_no(self, "Clear History", "Delete all scan history entries?"):
            threading.Thread(target=self._do_clear, daemon=True).start()

    def _do_clear(self) -> None:
        try:
            from cerebro.v2.core.scan_history_db import get_scan_history_db
            get_scan_history_db().clear()
        except Exception:
            pass
        self.after(0, self.load)


# ---------------------------------------------------------------------------
# _DeletionHistoryPanel
# ---------------------------------------------------------------------------

class _DeletionHistoryPanel(tk.Frame):
    """Treeview showing deletion history entries, loaded from SQLite."""

    _COLS = ("date", "filename", "path", "size", "mode")
    _HEADINGS = {
        "date":     ("Date",          160),
        "filename": ("File",          160),
        "path":     ("Original Path", 340),
        "size":     ("Size",           90),
        "mode":     ("Mode",           90),
    }

    def __init__(self, parent: tk.Widget) -> None:
        super().__init__(parent, bg=NAVY)
        self._build()

    def _build(self) -> None:
        header = _SectionHeader(
            self, "Deletion History",
            btn_text="Clear History", btn_cmd=self._clear,
        )
        header.pack(fill="x")
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")

        tree_frame = tk.Frame(self, bg=NAVY)
        tree_frame.pack(fill="both", expand=True, padx=PAD_X, pady=(PAD_Y, 0))

        style = ttk.Style()
        style.configure(
            "Deletion.Treeview",
            background=CARD_BG, foreground=TEXT_PRIMARY,
            fieldbackground=CARD_BG, rowheight=26,
            font=FONT_BODY,
        )
        style.configure(
            "Deletion.Treeview.Heading",
            background=NAVY_MID, foreground=TEXT_PRIMARY,
            font=FONT_SMALL, relief="flat",
        )
        style.map("Deletion.Treeview", background=[("selected", ROW_SEL)])

        self._tree = ttk.Treeview(
            tree_frame, columns=list(self._COLS), show="headings",
            selectmode="browse", style="Deletion.Treeview",
        )
        for col, (text, width) in self._HEADINGS.items():
            self._tree.heading(col, text=text)
            anchor = "e" if col == "size" else "w" if col in ("date", "filename", "path") else "center"
            self._tree.column(col, width=width, anchor=anchor)

        sb = ttk.Scrollbar(tree_frame, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self._tree.pack(fill="both", expand=True)

        self._count_lbl = tk.Label(
            self, text="", bg=NAVY_MID, fg=TEXT_MUTED, font=FONT_SMALL,
        )
        self._count_lbl.pack(fill="x", side="bottom", pady=(PAD_Y, 0))

    def load(self) -> None:
        threading.Thread(target=self._worker, daemon=True).start()

    def _worker(self) -> None:
        try:
            from cerebro.v2.core.deletion_history_db import get_default_history_manager
            rows = get_default_history_manager().get_recent_history(limit=500)
        except Exception:
            rows = []
        self.after(0, lambda: self._populate(rows))

    def _populate(self, rows) -> None:
        self._tree.delete(*self._tree.get_children())
        for row in rows:
            try:
                _id, filename, path, size, deletion_date, mode = row
                try:
                    dt = datetime.fromisoformat(str(deletion_date))
                    date_txt = dt.strftime("%Y-%m-%d %H:%M")
                except (ValueError, TypeError):
                    date_txt = str(deletion_date)
                size_txt = _fmt_bytes(int(size))
                self._tree.insert("", "end", values=(date_txt, filename, path, size_txt, str(mode)))
            except (ValueError, TypeError):
                continue
        count = len(rows)
        self._count_lbl.configure(
            text=f"  {count} entr{'y' if count == 1 else 'ies'} recorded"
        )

    def _clear(self) -> None:
        from cerebro.v2.ui.feedback import confirm_yes_no
        if confirm_yes_no(self, "Clear Deletion History", "Delete all deletion history entries?"):
            threading.Thread(target=self._do_clear, daemon=True).start()

    def _do_clear(self) -> None:
        try:
            from cerebro.v2.core.deletion_history_db import get_default_history_manager
            get_default_history_manager().clear_history()
        except Exception:
            pass
        self.after(0, self.load)


# ---------------------------------------------------------------------------
# HistoryPage (public)
# ---------------------------------------------------------------------------

class HistoryPage(tk.Frame):
    """
    Full-page History tab for AppShell.

    Replaces the 'history' placeholder frame.  Contains two sub-tabs:
    Scan History and Deletion History, styled with Phase-6 design tokens.

    on_session_click(entry) — optional callback fired when the user
    double-clicks a scan history row.  The caller (AppShell) should load
    the session into ResultsPage and switch to the Results tab.
    """

    def __init__(self, parent: tk.Widget, on_session_click=None) -> None:
        super().__init__(parent, bg=NAVY)
        self._on_session_click = on_session_click
        self._panels: dict[str, tk.Frame] = {}
        self._current: str = "scan"
        self._build()

    def _build(self) -> None:
        # Page title header
        title_bar = tk.Frame(self, bg=NAVY, height=48)
        title_bar.pack(fill="x")
        title_bar.pack_propagate(False)
        tk.Label(
            title_bar, text="History", bg=NAVY, fg=TEXT_PRIMARY,
            font=FONT_TITLE,
        ).pack(side="left", padx=PAD_X, pady=PAD_Y)

        # Separator
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")

        # Sub-tab bar
        self._tab_bar = _SubTabBar(self, self._on_subtab)
        self._tab_bar.pack(fill="x")
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")

        # Panel container
        self._container = tk.Frame(self, bg=NAVY)
        self._container.pack(fill="both", expand=True)
        self._container.columnconfigure(0, weight=1)
        self._container.rowconfigure(0, weight=1)

        # Build panels
        self._panels["scan"] = _ScanHistoryPanel(
            self._container,
            on_session_click=self._on_session_click,
        )
        self._panels["deletion"] = _DeletionHistoryPanel(self._container)

        for panel in self._panels.values():
            panel.grid(row=0, column=0, sticky="nsew")

        # Show scan panel first
        self._panels["scan"].tkraise()

    def _on_subtab(self, key: str) -> None:
        self._current = key
        self._panels[key].tkraise()

    def refresh(self) -> None:
        """Reload the currently visible panel from the database."""
        self._panels[self._current].load()

    def on_show(self) -> None:
        """Called when this page becomes visible — trigger a data load."""
        self._panels[self._current].load()
