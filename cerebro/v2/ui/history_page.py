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
from pathlib import Path
from tkinter import ttk
from typing import Any, Optional

from cerebro.v2.state.actions import (
    DeletionHistoryDataLoaded,
    HistoryDataLoaded,
    HistoryGridFilterChanged,
    HistoryGridPageChanged,
    HistoryGridSortChanged,
    HistorySubTabChanged,
)
from cerebro.v2.state.history_view import (
    apply_scan_history_view,
    default_sort_asc_for_column,
    row_to_entry_proxy,
)

from cerebro.v2.ui.design_tokens import (
    BORDER, CARD_BG, FONT_BODY, FONT_HEADER, FONT_SMALL, FONT_TITLE,
    NAVY, NAVY_MID, PAD_X, PAD_Y, RED, RED_DARK, ROW_SEL, TEXT_MUTED,
    TEXT_PRIMARY, TEXT_SECONDARY,
)
from cerebro.v2.ui.theme_applicator import ThemeApplicator, theme_token
from cerebro.v2.ui.widgets.data_grid import DataGrid, DataGridColumn


# ---------------------------------------------------------------------------
# Token helpers — map ThemeApplicator tokens onto the HistoryPage surfaces.
# ---------------------------------------------------------------------------

def _page_colors(t: dict) -> dict:
    return {
        "bg":        theme_token(t, "bg",        NAVY),
        "bar":       theme_token(t, "nav_bar",   NAVY_MID),
        "card":      theme_token(t, "bg2",       CARD_BG),
        "border":    theme_token(t, "border",    BORDER),
        "fg":        theme_token(t, "fg",        TEXT_PRIMARY),
        "fg2":       theme_token(t, "fg2",       TEXT_SECONDARY),
        "fg_muted":  theme_token(t, "fg_muted",  TEXT_MUTED),
        "danger":    theme_token(t, "danger",    RED),
        "danger_hover": theme_token(t, "accent2", RED_DARK),
        "row_sel":   theme_token(t, "row_sel",   ROW_SEL),
        "row_sel_fg": theme_token(t, "row_sel_fg", TEXT_PRIMARY),
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

    def __init__(
        self, parent: tk.Widget, on_change, *, state_driven: bool = False
    ) -> None:
        super().__init__(parent, bg=NAVY_MID, height=34)
        self.pack_propagate(False)
        self._on_change = on_change
        self._state_driven = state_driven
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

        if self._state_driven:
            self._paint()
        else:
            self._select("scan")

    def set_active_key(self, key: str) -> None:
        if key in self._btns:
            self._active = key
            self._paint()

    def _select(self, key: str) -> None:
        if self._state_driven:
            self._on_change(key)
        else:
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
    """Scan history: sort / filter / pagination driven by :class:`AppState` (Blueprint §3)."""

    def __init__(
        self,
        parent: tk.Widget,
        on_session_click=None,
        store: Any = None,
        coordinator: Any = None,
    ) -> None:
        super().__init__(parent, bg=NAVY)
        self._on_session_click = on_session_click
        self._store = store
        self._coordinator = coordinator
        self._unsub: Any = None
        self._iid_to_row: dict = {}
        self._filter_var = tk.StringVar(value="")
        self._filter_after: Optional[str] = None
        self._toolbar: tk.Frame | None = None
        self._filter_entry: tk.Entry | None = None
        self._pg_frame: tk.Frame | None = None
        self._pg_lbl: tk.Label | None = None
        self._header: _SectionHeader | None = None
        self._sep: tk.Frame | None = None
        self._tree_frame: tk.Frame | None = None
        self._colors = _page_colors({})
        self._build()
        if self._store is not None:
            self._unsub = self._store.subscribe(self._on_store)

    def _on_store(self, s: Any, _old: Any, action: Any) -> None:
        if not isinstance(
            action,
            (
                HistoryDataLoaded,
                HistoryGridSortChanged,
                HistoryGridFilterChanged,
                HistoryGridPageChanged,
            ),
        ):
            return
        self._render_from_state(s)

    def _build(self) -> None:
        self._header = _SectionHeader(
            self, "Scan History",
            btn_text="Clear History", btn_cmd=self._clear,
        )
        self._header.pack(fill="x")
        self._sep = tk.Frame(self, bg=BORDER, height=1)
        self._sep.pack(fill="x")

        # Filter row (state-driven path only; legacy list mode has no filter)
        self._toolbar = None
        self._filter_entry = None
        if self._coordinator is not None:
            self._toolbar = tk.Frame(self, bg=NAVY)
            self._toolbar.pack(fill="x", padx=PAD_X, pady=(PAD_Y // 2, 0))
            fl = tk.Label(
                self._toolbar, text="Filter:", bg=NAVY, fg=TEXT_SECONDARY, font=FONT_SMALL,
            )
            fl.pack(side="left", padx=(0, 8))
            self._filter_entry = tk.Entry(
                self._toolbar, textvariable=self._filter_var, width=32, font=FONT_SMALL,
            )
            self._filter_entry.pack(side="left", fill="x", expand=True)
            self._filter_entry.bind("<KeyRelease>", self._on_filter_key)

        self._tree_frame = tk.Frame(self, bg=NAVY)
        self._tree_frame.pack(fill="both", expand=True, padx=PAD_X, pady=(PAD_Y, 0))

        self._data_grid = DataGrid(
            self._tree_frame,
            [
                DataGridColumn("date", "Date / Time", 160, "w"),
                DataGridColumn("mode", "Mode", 90, "center"),
                DataGridColumn("folders", "Folders", 80, "center"),
                DataGridColumn("groups", "Groups", 70, "center"),
                DataGridColumn("files", "Files", 70, "center"),
                DataGridColumn("reclaimable", "Reclaimable", 110, "e"),
                DataGridColumn("duration", "Duration", 80, "center"),
            ],
            tree=False,
            style_name="Cerebro.HistoryDataGrid",
            on_sort_column=self._on_sort_column
            if self._coordinator
            else None,
            on_row_open=self._on_row_open,
            select_mode="browse",
            row_height=26,
        )
        self._data_grid.pack(fill="both", expand=True)

        # Pagination (only when state-driven; legacy mode shows list without pager)
        self._pg_frame = None
        self._pg_lbl = None
        if self._coordinator is not None and self._store is not None:
            self._pg_frame = tk.Frame(self, bg=NAVY_MID, height=28)
            self._pg_frame.pack(fill="x", padx=PAD_X, pady=(4, 0))
            self._pg_frame.pack_propagate(False)
            tk.Button(
                self._pg_frame, text="<< Prev", command=self._on_page_prev,
                font=FONT_SMALL, relief="flat", padx=8,
            ).pack(side="left", padx=(0, 8))
            self._pg_lbl = tk.Label(
                self._pg_frame, text="Page —", bg=NAVY_MID, fg=TEXT_SECONDARY, font=FONT_SMALL,
            )
            self._pg_lbl.pack(side="left", expand=True)
            tk.Button(
                self._pg_frame, text="Next >>", command=self._on_page_next,
                font=FONT_SMALL, relief="flat", padx=8,
            ).pack(side="right")

        self._count_lbl = tk.Label(
            self, text="", bg=NAVY_MID, fg=TEXT_MUTED, font=FONT_SMALL,
        )
        self._count_lbl.pack(fill="x", side="bottom", pady=(PAD_Y, 0))

    def _on_filter_key(self, _event) -> None:
        if not self._coordinator:
            return
        if self._filter_after is not None:
            try:
                self.after_cancel(self._filter_after)
            except (tk.TclError, ValueError):
                pass
            self._filter_after = None
        self._filter_after = str(self.after(250, self._apply_filter_debounced))

    def _apply_filter_debounced(self) -> None:
        self._filter_after = None
        if self._coordinator is not None:
            self._coordinator.history_set_filter(self._filter_var.get())

    def _on_sort_column(self, col: str) -> None:
        if not (self._coordinator and self._store):
            return
        s = self._store.get_state()
        if s.history_sort_column == col:
            new_asc = not s.history_sort_asc
        else:
            new_asc = default_sort_asc_for_column(col)
        self._coordinator.history_set_sort(col, new_asc)

    def _on_page_prev(self) -> None:
        if not (self._coordinator and self._store):
            return
        p = int(self._store.get_state().history_page)
        if p > 0:
            self._coordinator.history_set_page(p - 1)

    def _on_page_next(self) -> None:
        if not (self._coordinator and self._store):
            return
        s = self._store.get_state()
        _slice, _nf, n_pages, cpage, _ta = apply_scan_history_view(
            s.history_scan_rows,
            s.history_sort_column,
            s.history_sort_asc,
            s.history_filter,
            s.history_page,
            s.history_page_size,
        )
        if cpage < n_pages - 1 and self._coordinator:
            self._coordinator.history_set_page(cpage + 1)

    def _render_from_state(self, s: Any) -> None:
        if not self._store or not self._coordinator:
            return
        page_rows, n_filtered, n_pages, cpage, n_all = apply_scan_history_view(
            s.history_scan_rows,
            s.history_sort_column,
            s.history_sort_asc,
            s.history_filter,
            s.history_page,
            s.history_page_size,
        )
        if cpage != s.history_page:
            self._coordinator.history_set_page(cpage)
            return
        self._iid_to_row = {}
        self._data_grid.clear()
        for idx, rowd in enumerate(page_rows):
            ts = float(rowd.get("ts") or 0)
            date = datetime.fromtimestamp(ts).strftime("%Y-%m-%d  %H:%M") if ts else "—"
            mode = str(rowd.get("mode", "")).replace("_", " ").title()
            folders = str(rowd.get("folder_count", 0))
            groups = str(rowd.get("groups", 0))
            files = str(rowd.get("files", 0))
            rec = _fmt_bytes(int(rowd.get("bytes", 0)))
            dur = _fmt_dur(float(rowd.get("duration", 0.0)))
            iid = f"hs{int(cpage)}_{idx}"
            self._data_grid.insert_row(
                iid,
                (date, mode, folders, groups, files, rec, dur),
                data={},
            )
            self._iid_to_row[iid] = rowd
        if self._pg_lbl is not None:
            self._pg_lbl.configure(
                text=f"  Page {cpage + 1} / {n_pages}  ·  {n_filtered} of {n_all} scans shown  ",
            )
        hint = "  Double-click a row to open session" if n_filtered and self._on_session_click else ""
        self._count_lbl.configure(
            text=f"  {n_all} scan total · {n_filtered} match filter{hint}",
        )

    def apply_theme(self, colors: dict) -> None:
        self._colors = colors
        self.configure(bg=colors["bg"])
        if self._header is not None:
            self._header.apply_theme(colors)
        if self._sep is not None:
            self._sep.configure(bg=colors["border"])
        if self._toolbar is not None:
            self._toolbar.configure(bg=colors["bg"])
            for c in self._toolbar.winfo_children():
                if isinstance(c, (tk.Label, tk.Entry, tk.Button)):
                    try:
                        c.configure(
                            bg=colors["bg"] if not isinstance(c, ttk.Button) else None,
                        )
                    except (tk.TclError, TypeError, ValueError):
                        pass
        if self._tree_frame is not None:
            self._tree_frame.configure(bg=colors["bg"])
        if self._pg_frame is not None:
            self._pg_frame.configure(bg=colors["bar"])
        if self._pg_lbl is not None:
            self._pg_lbl.configure(bg=colors["bar"], fg=colors["fg2"])
        self._count_lbl.configure(bg=colors["bar"], fg=colors["fg_muted"])
        for fl in (getattr(self, "_filter_entry", None),):
            if fl is not None and isinstance(fl, tk.Entry):
                try:
                    fl.configure(bg=colors["card"], fg=colors["fg"], insertbackground=colors["fg"])
                except (tk.TclError, TypeError, ValueError):
                    pass

        self._data_grid.apply_theme(
            bg=colors["card"],
            fg=colors["fg"],
            heading_bg=colors["bar"],
            heading_fg=colors["fg"],
            select_bg=colors["row_sel"],
        )
        tfb = self._pg_frame
        if tfb is not None:
            for c in tfb.winfo_children():
                if isinstance(c, tk.Button):
                    try:
                        c.configure(
                            bg=colors["bar"], fg=colors["fg2"],
                            activebackground=colors["bar"], activeforeground=colors["fg"],
                        )
                    except (tk.TclError, TypeError, ValueError):
                        pass
        tlab = self._toolbar
        if tlab is not None and tlab.winfo_children():
            c0 = tlab.winfo_children()[0]
            if isinstance(c0, tk.Label):
                try:
                    c0.configure(bg=colors["bg"], fg=colors["fg2"])
                except (tk.TclError, TypeError, ValueError):
                    pass

    def load(self) -> None:
        if self._coordinator is not None:
            threading.Thread(target=self._worker, daemon=True).start()
        else:
            threading.Thread(target=self._worker_legacy, daemon=True).start()

    def _worker(self) -> None:
        try:
            from cerebro.v2.core.scan_history_db import get_scan_history_db
            entries = get_scan_history_db().get_recent(limit=500)
        except Exception:
            entries = []
        def _ok() -> None:
            if self._coordinator is not None:
                self._coordinator.history_data_loaded(entries)
        self.after(0, _ok)

    def _worker_legacy(self) -> None:
        try:
            from cerebro.v2.core.scan_history_db import get_scan_history_db
            entries = get_scan_history_db().get_recent(limit=500)
        except Exception:
            entries = []
        self.after(0, lambda: self._populate_legacy(entries))

    def _populate_legacy(self, entries) -> None:
        if self._coordinator is not None:
            return
        from cerebro.v2.state.history_view import scan_entry_to_row

        rows = [scan_entry_to_row(e) for e in entries]
        self._data_grid.clear()
        self._iid_to_row = {}
        for idx, rowd in enumerate(rows):
            ts = float(rowd.get("ts") or 0)
            date = datetime.fromtimestamp(ts).strftime("%Y-%m-%d  %H:%M") if ts else "—"
            mode = str(rowd.get("mode", "")).replace("_", " ").title()
            iid = f"leg_{idx}"
            self._data_grid.insert_row(
                iid,
                (
                    date,
                    mode,
                    str(rowd.get("folder_count", 0)),
                    str(rowd.get("groups", 0)),
                    str(rowd.get("files", 0)),
                    _fmt_bytes(int(rowd.get("bytes", 0))),
                    _fmt_dur(float(rowd.get("duration", 0.0))),
                ),
                data={},
            )
            self._iid_to_row[iid] = rowd
        self._count_lbl.configure(
            text=f"  {len(rows)} scan{'s' if len(rows) != 1 else ''} recorded",
        )

    def _on_row_open(self, iid: str, _data: object) -> None:
        if not self._on_session_click:
            return
        rowd = self._iid_to_row.get(iid)
        if rowd is not None:
            self._on_session_click(row_to_entry_proxy(rowd))

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

    def __init__(self, parent: tk.Widget, store: Any = None, coordinator: Any = None) -> None:
        super().__init__(parent, bg=NAVY)
        self._store = store
        self._coordinator = coordinator
        self._unsub: Any = None
        self._header: _SectionHeader | None = None
        self._sep: tk.Frame | None = None
        self._tree_frame: tk.Frame | None = None
        self._colors = _page_colors({})
        self._build()
        if self._store is not None:
            self._unsub = self._store.subscribe(self._on_store)

    def _on_store(self, s: Any, _old: Any, action: Any) -> None:
        if not isinstance(action, DeletionHistoryDataLoaded):
            return
        self._render_from_state(s)

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

        self._data_grid = DataGrid(
            self._tree_frame,
            [
                DataGridColumn("date", "Date", 160, "w"),
                DataGridColumn("filename", "File", 160, "w"),
                DataGridColumn("path", "Original Path", 340, "w"),
                DataGridColumn("size", "Size", 90, "e"),
                DataGridColumn("mode", "Mode", 90, "center"),
            ],
            tree=False,
            style_name="Cerebro.DeletionDataGrid",
            on_sort_column=None,
            select_mode="browse",
            row_height=26,
        )
        self._data_grid.pack(fill="both", expand=True)

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
        self._data_grid.apply_theme(
            bg=colors["card"],
            fg=colors["fg"],
            heading_bg=colors["bar"],
            heading_fg=colors["fg"],
            select_bg=colors["row_sel"],
        )

    def load(self) -> None:
        threading.Thread(target=self._worker, daemon=True).start()

    def _worker(self) -> None:
        try:
            from cerebro.v2.core.deletion_history_db import get_default_history_manager
            rows = get_default_history_manager().get_recent_history(limit=500)
        except Exception:
            rows = []
        if self._coordinator is not None:
            self.after(0, lambda: self._coordinator.deletion_history_data_loaded(rows))
        else:
            self.after(0, lambda: self._populate(rows))

    def _render_from_state(self, s: Any) -> None:
        if not (self._store and self._coordinator):
            return
        self._fill_tree_from_dicts(s.history_deletion_rows)

    def _fill_tree_from_dicts(self, data: list) -> None:
        self._data_grid.clear()
        for di, d in enumerate(data):
            try:
                path = d.get("path", "")
                filename = d.get("filename", Path(str(path)).name)
                size = int(d.get("size", 0) or 0)
                del_date = d.get("deletion_date", "")
                mode = d.get("mode", "")
                try:
                    dt = datetime.fromisoformat(str(del_date))
                    date_txt = dt.strftime("%Y-%m-%d %H:%M")
                except (ValueError, TypeError):
                    date_txt = str(del_date)
                size_txt = _fmt_bytes(size)
                iid = f"del{di}"
                self._data_grid.insert_row(
                    iid,
                    (date_txt, str(filename), str(path), size_txt, str(mode)),
                    data={},
                )
            except (ValueError, TypeError, KeyError, OSError, AttributeError):
                continue
        count = len(data)
        self._count_lbl.configure(
            text=f"  {count} entr{'y' if count == 1 else 'ies'} recorded"
        )

    def _populate(self, rows) -> None:
        if self._coordinator is not None:
            return
        self._data_grid.clear()
        for ri, row in enumerate(rows):
            try:
                _id, filename, path, size, deletion_date, mode = row
                try:
                    dt = datetime.fromisoformat(str(deletion_date))
                    date_txt = dt.strftime("%Y-%m-%d %H:%M")
                except (ValueError, TypeError):
                    date_txt = str(deletion_date)
                size_txt = _fmt_bytes(int(size))
                iid = f"dlr{ri}"
                self._data_grid.insert_row(
                    iid,
                    (date_txt, filename, path, size_txt, str(mode)),
                    data={},
                )
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

    def __init__(
        self,
        parent: tk.Widget,
        on_session_click=None,
        store: Any = None,
        coordinator: Any = None,
    ) -> None:
        super().__init__(parent, bg=NAVY)
        self._on_session_click = on_session_click
        self._store = store
        self._coordinator = coordinator
        self._unsub: Any = None
        self._panels: dict[str, tk.Frame] = {}
        self._current: str = "scan"
        self._colors = _page_colors({})
        self._build()
        if self._coordinator is not None and self._store is not None:
            self._unsub = self._store.subscribe(self._on_store_history)
            k0 = str(self._store.get_state().ui.get("history_subtab", "scan"))
            if k0 in self._panels:
                self._current = k0
                self._tab_bar.set_active_key(k0)
                self._panels[k0].tkraise()
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
            store=self._store,
            coordinator=self._coordinator,
        )
        self._panels["deletion"] = _DeletionHistoryPanel(
            self._container,
            store=self._store,
            coordinator=self._coordinator,
        )

        for panel in self._panels.values():
            panel.grid(row=0, column=0, sticky="nsew")

        st_driven = self._coordinator is not None and self._store is not None
        # Sub-tab: dispatch → store (state_driven) or local raise.
        self._tab_bar = _SubTabBar(
            self, self._on_subtab, state_driven=st_driven,
        )
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
        if self._coordinator is not None:
            self._coordinator.history_set_subtab(key)
        else:
            self._current = key
            self._panels[key].tkraise()

    def _on_store_history(self, s: Any, _old: Any, action: Any) -> None:
        if not isinstance(action, HistorySubTabChanged):
            return
        k = str(s.ui.get("history_subtab", "scan"))
        if k not in self._panels:
            k = "scan"
        self._current = k
        self._tab_bar.set_active_key(k)
        self._panels[k].tkraise()

    def refresh(self) -> None:
        """Reload history panels from the database (all subtabs)."""
        for panel in self._panels.values():
            load = getattr(panel, "load", None)
            if callable(load):
                try:
                    load()
                except tk.TclError:
                    pass

    def on_show(self) -> None:
        """Called when this page becomes visible — trigger a data load."""
        if self._coordinator is not None and self._store is not None:
            k = str(self._store.get_state().ui.get("history_subtab", "scan"))
            if k in self._panels:
                self._current = k
                self._tab_bar.set_active_key(k)
                self._panels[k].tkraise()
        self._panels[self._current].load()
