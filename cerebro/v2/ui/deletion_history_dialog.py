"""Deletion history dialog backed by sqlite."""

from __future__ import annotations

from datetime import datetime
import logging
import tkinter as tk
from tkinter import ttk

try:
    import customtkinter as ctk
    CTkToplevel = ctk.CTkToplevel
    CTkFrame = ctk.CTkFrame
    CTkLabel = ctk.CTkLabel
    CTkButton = ctk.CTkButton
    CTkEntry = ctk.CTkEntry
except ImportError:
    CTkToplevel = tk.Toplevel
    CTkFrame = tk.Frame
    CTkLabel = tk.Label
    CTkButton = tk.Button
    CTkEntry = tk.Entry

from cerebro.v2.core.design_tokens import Spacing, Typography
from cerebro.v2.core.theme_bridge_v2 import theme_color, subscribe_to_theme
from cerebro.v2.core.deletion_history_db import get_default_history_manager
from cerebro.v2.ui.feedback import confirm_yes_no

logger = logging.getLogger(__name__)


class DeletionHistoryDialog:
    @classmethod
    def show(cls, parent: tk.Misc) -> None:
        cls(parent)

    def __init__(self, parent: tk.Misc) -> None:
        self._parent = parent
        self._manager = get_default_history_manager()
        self._win = CTkToplevel(parent)
        self._win.title("Deletion History")
        self._win.geometry("900x520")
        self._win.transient(parent)
        self._win.grab_set()
        subscribe_to_theme(self._win, self._apply_theme)
        self._build()
        self._load()

    def _build(self) -> None:
        self._win.configure(fg_color=theme_color("base.background"))
        header = CTkFrame(self._win, fg_color=theme_color("toolbar.background"), height=48)
        header.pack(fill="x")
        header.pack_propagate(False)
        CTkLabel(header, text="Deletion History", font=("", 15, "bold")).pack(
            side="left", padx=Spacing.LG, pady=Spacing.SM
        )
        self._search_var = tk.StringVar(value="")
        search = CTkEntry(header, textvariable=self._search_var, width=220, height=30)
        search.pack(side="left", padx=(Spacing.MD, Spacing.XS), pady=Spacing.SM)
        CTkButton(
            header,
            text="Search",
            width=90,
            height=30,
            command=self._search,
            fg_color=theme_color("button.secondary"),
            hover_color=theme_color("button.secondaryHover"),
        ).pack(side="left", pady=Spacing.SM)
        CTkButton(
            header,
            text="Clear",
            width=90,
            height=30,
            command=self._clear,
            fg_color=theme_color("button.danger"),
            hover_color=theme_color("button.dangerHover"),
        ).pack(side="right", padx=Spacing.MD, pady=Spacing.SM)

        cols = ("date", "filename", "path", "size", "mode")
        frame = CTkFrame(self._win, fg_color=theme_color("base.backgroundSecondary"))
        frame.pack(fill="both", expand=True, padx=Spacing.MD, pady=Spacing.SM)
        self._tree = ttk.Treeview(frame, columns=cols, show="headings")
        self._tree.heading("date", text="Date")
        self._tree.heading("filename", text="File")
        self._tree.heading("path", text="Original Path")
        self._tree.heading("size", text="Size")
        self._tree.heading("mode", text="Mode")
        self._tree.column("date", width=170, anchor="w")
        self._tree.column("filename", width=160, anchor="w")
        self._tree.column("path", width=360, anchor="w")
        self._tree.column("size", width=90, anchor="e")
        self._tree.column("mode", width=90, anchor="center")
        sb = ttk.Scrollbar(frame, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self._tree.pack(fill="both", expand=True)

        footer = CTkFrame(self._win, fg_color=theme_color("toolbar.background"), height=42)
        footer.pack(fill="x")
        footer.pack_propagate(False)
        self._count = CTkLabel(footer, text="", font=Typography.FONT_SM)
        self._count.pack(side="left", padx=Spacing.MD, pady=Spacing.SM)
        CTkButton(
            footer,
            text="Close",
            width=90,
            height=30,
            command=self._win.destroy,
            fg_color=theme_color("button.secondary"),
            hover_color=theme_color("button.secondaryHover"),
        ).pack(side="right", padx=Spacing.MD, pady=Spacing.SM)

    def _fmt_bytes(self, n: int) -> str:
        val = float(n)
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if val < 1024 or unit == "TB":
                return f"{val:.1f} {unit}" if unit != "B" else f"{int(val)} {unit}"
            val /= 1024
        return f"{val:.1f} TB"

    def _rows_to_tree(self, rows) -> None:
        self._tree.delete(*self._tree.get_children())
        for _id, filename, path, size, deletion_date, mode in rows:
            try:
                dt = datetime.fromisoformat(str(deletion_date))
                date_txt = dt.strftime("%Y-%m-%d %H:%M")
            except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
                date_txt = str(deletion_date)
            self._tree.insert(
                "",
                "end",
                values=(date_txt, filename, path, self._fmt_bytes(int(size)), str(mode)),
            )
        self._count.configure(text=f"{len(rows)} entr{'y' if len(rows) == 1 else 'ies'}")

    def _load(self) -> None:
        self._rows_to_tree(self._manager.get_recent_history(limit=500))

    def _search(self) -> None:
        pattern = self._search_var.get().strip()
        if not pattern:
            self._load()
            return
        self._rows_to_tree(self._manager.search_history(pattern))

    def _clear(self) -> None:
        if confirm_yes_no(self._win, "Clear Deletion History", "Delete all deletion history entries?"):
            self._manager.clear_history()
            self._load()

    def _apply_theme(self) -> None:
        try:
            self._win.configure(fg_color=theme_color("base.background"))
        except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
            pass
