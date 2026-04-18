"""
HistoryPage — full-tab History page for the CEREBRO v2 overhaul.

Content (two sub-tabs):
  • Scan History    — replicates ScanHistoryDialog treeview, in-page
  • Deletion History — replicates DeletionHistoryDialog treeview, in-page

All surfaces are driven by :class:`ThemeApplicator` tokens so the page
repaints whenever the active theme changes (top-bar quick dropdown or
Settings > Appearance).
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
from cerebro.v2.ui.theme_applicator import ThemeApplicator


# ---------------------------------------------------------------------------
# Token helpers — map ThemeApplicator tokens onto the HistoryPage surfaces.
# ---------------------------------------------------------------------------

def _tk(t: dict, key: str, default: str) -> str:
    """Safe token lookup with a fallback to the old static constant."""
    value = t.get(key) if isinstance(t, dict) else None
    return value if isinstance(value, str) and value else default


def _page_colors(t: dict) -> dict:
    return {
        "bg":        _tk(t, "bg",        NAVY),
        "bar":       _tk(t, "nav_bar",   NAVY_MID),
        "card":      _tk(t, "bg2",       CARD_BG),
        "border":    _tk(t, "border",    BORDER),
        "fg":        _tk(t, "fg",        TEXT_PRIMARY),
        "fg2":       _tk(t, "fg2",       TEXT_SECONDARY),
        "fg_muted":  _tk(t, "fg_muted",  TEXT_MUTED),
        "danger":    _tk(t, "danger",    RED),
        "danger_hover": _tk(t, "accent2", RED_DARK),
        "row_sel":   _tk(t, "row_sel",   ROW_SEL),
        "row_sel_fg": _tk(t, "row_sel_fg", TEXT_PRIMARY),
    }


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
        self._title_lbl = tk.Label(
            self, text=title, bg=NAVY_MID, fg=TEXT_PRIMARY,
            font=FONT_HEADER,
        )
        self._title_lbl.pack(side="left", padx=PAD_X)

        self._btn: tk.Button | None = None
        if btn_text and btn_cmd:
            self._btn = tk.Button(
                self, text=btn_text, command=btn_cmd,
                bg=RED, fg=TEXT_PRIMARY, activebackground=RED_DARK,
                activeforeground=TEXT_PRIMARY, relief="flat",
                font=FONT_SMALL, cursor="hand2", padx=10,
            )
            self._btn.pack(side="right", padx=PAD_X, pady=5)

    def apply_theme(self, colors: dict) -> None:
        self.configure(bg=colors["bar"])
        self._title_lbl.configure(bg=colors["bar"], fg=colors["fg"])
        if self._btn is not None:
            self._btn.configure(
                bg=colors["danger"],
                fg=colors["row_sel_fg"],
                activebackground=colors["danger_hover"],
                activeforeground=colors["row_sel_fg"],
            )


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
        self._colors = _page_colors({})

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
        self._active = key
        self._paint()
        self._on_change(key)

    def _paint(self) -> None:
        bar = self._colors["bar"]
        fg  = self._colors["fg"]
        fg2 = self._colors["fg2"]
        self.configure(bg=bar)
        for k, lbl in self._btns.items():
            is_active = k == self._active
            lbl.configure(
                bg=bar,
                fg=fg if is_active else fg2,
                font=(FONT_BODY[0], FONT_BODY[1], "bold") if is_active else FONT_BODY,
            )

    def apply_theme(self, colors: dict) -> None:
        self._colors = colors
        self._paint()


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

    _STYLE_NAME = "History.Treeview"

    def __init__(self, parent: tk.Widget, on_session_click=None) -> None:
        super().__init__(parent, bg=NAVY)
        self._on_session_click = on_session_click
        self._entries: list = []
        self._header: _SectionHeader | None = None
        self._sep: tk.Frame | None = None
        self._tree_frame: tk.Frame | None = None
        self._colors = _page_colors({})
        self._build()

    def _build(self) -> None:
        self._header = _SectionHeader(
            self, "Scan History",
            btn_text="Clear History", btn_cmd=self._clear,
        )
        self._header.pack(fill="x")
        self._sep = tk.Frame(self, bg=BORDER, height=1)
        self._sep.pack(fill="x")

        self._tree_frame = tk.Frame(self, bg=NAVY)
        self._tree_frame.pack(fill="both", expand=True, padx=PAD_X, pady=(PAD_Y, 0))

        style = ttk.Style()
        style.theme_use("default")
        style.configure(
            self._STYLE_NAME,
            background=CARD_BG, foreground=TEXT_PRIMARY,
            fieldbackground=CARD_BG, rowheight=26,
            font=FONT_BODY,
        )
        style.configure(
            f"{self._STYLE_NAME}.Heading",
            background=NAVY_MID, foreground=TEXT_PRIMARY,
            font=FONT_SMALL, relief="flat",
        )
        style.map(self._STYLE_NAME, background=[("selected", ROW_SEL)])

        self._tree = ttk.Treeview(
            self._tree_frame, columns=self._COLS, show="headings",
            selectmode="browse", style=self._STYLE_NAME,
        )
        for col, (text, width) in self._HEADINGS.items():
            self._tree.heading(col, text=text)
            anchor = "w" if col == "date" else "center"
            self._tree.column(col, width=width, anchor=anchor)

        sb = ttk.Scrollbar(self._tree_frame, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self._tree.pack(fill="both", expand=True)
        self._tree.bind("<Double-1>", self._on_row_double_click)

        self._count_lbl = tk.Label(
            self, text="", bg=NAVY_MID, fg=TEXT_MUTED, font=FONT_SMALL,
        )
        self._count_lbl.pack(fill="x", side="bottom", pady=(PAD_Y, 0))

    def apply_theme(self, colors: dict) -> None:
        self._colors = colors
        self.configure(bg=colors["bg"])
        if self._header is not None:
            self._header.apply_theme(colors)
        if self._sep is not None:
            self._sep.configure(bg=colors["border"])
        if self._tree_frame is not None:
            self._tree_frame.configure(bg=colors["bg"])
        self._count_lbl.configure(bg=colors["bar"], fg=colors["fg_muted"])

        style = ttk.Style()
        style.configure(
            self._STYLE_NAME,
            background=colors["card"],
            foreground=colors["fg"],
            fieldbackground=colors["card"],
            rowheight=26,
            font=FONT_BODY,
        )
        style.configure(
            f"{self._STYLE_NAME}.Heading",
            background=colors["bar"],
            foreground=colors["fg"],
            font=FONT_SMALL,
            relief="flat",
        )
        style.map(
            self._STYLE_NAME,
            background=[("selected", colors["row_sel"])],
            foreground=[("selected", colors["row_sel_fg"])],
        )

    def load(self) -> None:
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

    _STYLE_NAME = "Deletion.Treeview"

    def __init__(self, parent: tk.Widget) -> None:
        super().__init__(parent, bg=NAVY)
        self._header: _SectionHeader | None = None
        self._sep: tk.Frame | None = None
        self._tree_frame: tk.Frame | None = None
        self._colors = _page_colors({})
        self._build()

    def _build(self) -> None:
        self._header = _SectionHeader(
            self, "Deletion History",
            btn_text="Clear History", btn_cmd=self._clear,
        )
        self._header.pack(fill="x")
        self._sep = tk.Frame(self, bg=BORDER, height=1)
        self._sep.pack(fill="x")

        self._tree_frame = tk.Frame(self, bg=NAVY)
        self._tree_frame.pack(fill="both", expand=True, padx=PAD_X, pady=(PAD_Y, 0))

        style = ttk.Style()
        style.configure(
            self._STYLE_NAME,
            background=CARD_BG, foreground=TEXT_PRIMARY,
            fieldbackground=CARD_BG, rowheight=26,
            font=FONT_BODY,
        )
        style.configure(
            f"{self._STYLE_NAME}.Heading",
            background=NAVY_MID, foreground=TEXT_PRIMARY,
            font=FONT_SMALL, relief="flat",
        )
        style.map(self._STYLE_NAME, background=[("selected", ROW_SEL)])

        self._tree = ttk.Treeview(
            self._tree_frame, columns=list(self._COLS), show="headings",
            selectmode="browse", style=self._STYLE_NAME,
        )
        for col, (text, width) in self._HEADINGS.items():
            self._tree.heading(col, text=text)
            anchor = "e" if col == "size" else "w" if col in ("date", "filename", "path") else "center"
            self._tree.column(col, width=width, anchor=anchor)

        sb = ttk.Scrollbar(self._tree_frame, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self._tree.pack(fill="both", expand=True)

        self._count_lbl = tk.Label(
            self, text="", bg=NAVY_MID, fg=TEXT_MUTED, font=FONT_SMALL,
        )
        self._count_lbl.pack(fill="x", side="bottom", pady=(PAD_Y, 0))

    def apply_theme(self, colors: dict) -> None:
        self._colors = colors
        self.configure(bg=colors["bg"])
        if self._header is not None:
            self._header.apply_theme(colors)
        if self._sep is not None:
            self._sep.configure(bg=colors["border"])
        if self._tree_frame is not None:
            self._tree_frame.configure(bg=colors["bg"])
        self._count_lbl.configure(bg=colors["bar"], fg=colors["fg_muted"])

        style = ttk.Style()
        style.configure(
            self._STYLE_NAME,
            background=colors["card"],
            foreground=colors["fg"],
            fieldbackground=colors["card"],
            rowheight=26,
            font=FONT_BODY,
        )
        style.configure(
            f"{self._STYLE_NAME}.Heading",
            background=colors["bar"],
            foreground=colors["fg"],
            font=FONT_SMALL,
            relief="flat",
        )
        style.map(
            self._STYLE_NAME,
            background=[("selected", colors["row_sel"])],
            foreground=[("selected", colors["row_sel_fg"])],
        )

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
    """Full-page History tab for AppShell (Scan History + Deletion History sub-tabs)."""

    def __init__(self, parent: tk.Widget, on_session_click=None) -> None:
        super().__init__(parent, bg=NAVY)
        self._on_session_click = on_session_click
        self._panels: dict[str, tk.Frame] = {}
        self._current: str = "scan"
        self._colors = _page_colors({})
        self._build()
        ThemeApplicator.get().register(self._apply_theme)

    def _build(self) -> None:
        self._title_bar = tk.Frame(self, bg=NAVY, height=48)
        self._title_bar.pack(fill="x")
        self._title_bar.pack_propagate(False)
        self._title_lbl = tk.Label(
            self._title_bar, text="History", bg=NAVY, fg=TEXT_PRIMARY,
            font=FONT_TITLE,
        )
        self._title_lbl.pack(side="left", padx=PAD_X, pady=PAD_Y)

        self._title_sep = tk.Frame(self, bg=BORDER, height=1)
        self._title_sep.pack(fill="x")

        self._container = tk.Frame(self, bg=NAVY)
        self._container.pack(fill="both", expand=True)
        self._container.columnconfigure(0, weight=1)
        self._container.rowconfigure(0, weight=1)

        self._panels["scan"] = _ScanHistoryPanel(
            self._container,
            on_session_click=self._on_session_click,
        )
        self._panels["deletion"] = _DeletionHistoryPanel(self._container)

        for panel in self._panels.values():
            panel.grid(row=0, column=0, sticky="nsew")

        # Build sub-tab bar after panels exist; _SubTabBar.__init__ triggers on_change.
        self._tab_bar = _SubTabBar(self, self._on_subtab)
        self._tab_bar.pack(fill="x", before=self._container)
        self._sub_sep = tk.Frame(self, bg=BORDER, height=1)
        self._sub_sep.pack(fill="x", before=self._container)

        self._panels["scan"].tkraise()

    def _apply_theme(self, tokens: dict) -> None:
        colors = _page_colors(tokens)
        self._colors = colors
        self.configure(bg=colors["bg"])
        self._title_bar.configure(bg=colors["bg"])
        self._title_lbl.configure(bg=colors["bg"], fg=colors["fg"])
        self._title_sep.configure(bg=colors["border"])
        self._sub_sep.configure(bg=colors["border"])
        self._container.configure(bg=colors["bg"])
        self._tab_bar.apply_theme(colors)
        for panel in self._panels.values():
            apply = getattr(panel, "apply_theme", None)
            if callable(apply):
                try:
                    apply(colors)
                except tk.TclError:
                    pass

    def _on_subtab(self, key: str) -> None:
        self._current = key
        self._panels[key].tkraise()

    def refresh(self) -> None:
        """Reload the currently visible panel from the database."""
        self._panels[self._current].load()

    def on_show(self) -> None:
        """Called when this page becomes visible — trigger a data load."""
        self._panels[self._current].load()
