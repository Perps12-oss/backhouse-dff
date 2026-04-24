"""
DuplicatesPage — FINAL PLAN v2.0 §5.

Layout: [ Filters ] [ Groups ] [ Preview/Compare ]
Empty state: "No duplicates found"
Filters (Minimal): File type, Search
Filters (Advanced): Size, Date, Path, Similarity
Groups: Expandable, shows size + count, checkbox per file
Selection rules: No hidden selections, persists across filters
Smart Select (Minimal): Keep newest, Keep largest
Preview: Single file preview + metadata
Compare: Manual activation, sync zoom/pan, "Keep this" per file
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any, Callable, Dict, List, Optional, Set

from cerebro.v2.ui.theme_applicator import ThemeApplicator, theme_token

_PANEL_BG  = "#F0F0F0"
_CARD_BG   = "#FFFFFF"
_BORDER    = "#E0E0E0"
_ACCENT    = "#E74C3C"
_TEXT      = "#111111"
_TEXT_SEC  = "#666666"
_DANGER    = "#E74C3C"
_SUCCESS   = "#27AE60"
_BLUE      = "#2980B9"

FILE_TYPES = [
    ("all", "All"),
    ("pictures", "Pictures"),
    ("music", "Music"),
    ("videos", "Videos"),
    ("documents", "Documents"),
    ("archives", "Archives"),
    ("other", "Other"),
]


def _fmt_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 ** 2:
        return f"{n / 1024:.1f} KB"
    if n < 1024 ** 3:
        return f"{n / 1024 ** 2:.1f} MB"
    return f"{n / 1024 ** 3:.1f} GB"


class DuplicatesPage(tk.Frame):
    """Duplicates page with filters, groups, and preview (FINAL PLAN §5)."""

    def __init__(
        self,
        master,
        on_open_group: Optional[Callable[[int, list], None]] = None,
        on_navigate_home: Optional[Callable[[], None]] = None,
        on_rescan: Optional[Callable[[], None]] = None,
        store: Optional[object] = None,
        coordinator: Optional[object] = None,
        **kwargs,
    ) -> None:
        kwargs.setdefault("bg", _PANEL_BG)
        super().__init__(master, **kwargs)
        self._on_open_group = on_open_group
        self._on_navigate_home = on_navigate_home
        self._on_rescan = on_rescan
        self._store = store
        self._coordinator = coordinator
        self._groups: List[Any] = []
        self._scan_mode: str = "files"
        self._advanced: bool = False
        self._selected: Set[str] = set()
        self._compare_mode: bool = False
        self._compare_pair: tuple = ()
        self._t: Dict[str, Any] = {}
        self._build()
        self._t = ThemeApplicator.get().build_tokens()
        ThemeApplicator.get().register(self._apply_theme)
        if store is not None:
            store.subscribe(self._on_store)

    def _on_store(self, s: Any, old: Any, action: Any) -> None:
        try:
            from cerebro.v2.state.actions import ScanStarted
            if isinstance(action, ScanStarted):
                self._groups = []
                self._selected = set()
                self.after(0, self._refresh_view)
        except Exception:
            pass

    def _apply_theme(self, t: dict) -> None:
        self._t = t
        self._refresh_view()

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=2)
        self.columnconfigure(2, weight=2)
        self.rowconfigure(0, weight=1)

        self._build_filters()
        self._build_groups()
        self._build_preview()

    def _build_filters(self) -> None:
        t = self._t
        bg = theme_token(t, "bg2", _PANEL_BG)
        fg = theme_token(t, "fg", _TEXT)
        border = theme_token(t, "border", _BORDER)

        self._filter_frame = tk.Frame(self, bg=bg, width=220)
        self._filter_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 1))
        self._filter_frame.grid_propagate(False)

        tk.Label(self._filter_frame, text="Filters", bg=bg, fg=fg,
                 font=("Segoe UI", 11, "bold")).pack(anchor="w", padx=12, pady=(12, 8))

        tk.Label(self._filter_frame, text="File type", bg=bg, fg=fg,
                 font=("Segoe UI", 9)).pack(anchor="w", padx=12, pady=(4, 2))
        self._file_type_var = tk.StringVar(value="all")
        for key, label in FILE_TYPES:
            rb = tk.Radiobutton(
                self._filter_frame, text=label, variable=self._file_type_var,
                value=key, bg=bg, fg=fg, selectcolor=bg,
                activebackground=bg, activeforeground=fg,
                font=("Segoe UI", 9), anchor="w",
                command=self._on_filter_change,
            )
            rb.pack(anchor="w", padx=20)

        tk.Frame(self._filter_frame, bg=border, height=1).pack(fill="x", padx=12, pady=8)

        tk.Label(self._filter_frame, text="Search", bg=bg, fg=fg,
                 font=("Segoe UI", 9)).pack(anchor="w", padx=12, pady=(4, 2))
        self._search_var = tk.StringVar()
        self._search_entry = tk.Entry(
            self._filter_frame, textvariable=self._search_var,
            font=("Segoe UI", 9), relief="flat", bd=0,
        )
        self._search_entry.pack(fill="x", padx=12, pady=(0, 8))
        self._search_var.trace_add("write", lambda *_: self._on_filter_change())

        self._advanced_filters_frame = tk.Frame(self._filter_frame, bg=bg)
        if self._advanced:
            self._build_advanced_filters()

        tk.Frame(self._filter_frame, bg=border, height=1).pack(fill="x", padx=12, pady=8)

        tk.Label(self._filter_frame, text="Smart Select", bg=bg, fg=fg,
                 font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=12, pady=(4, 4))

        tk.Button(
            self._filter_frame, text="Keep newest",
            bg=bg, fg=fg, font=("Segoe UI", 9), relief="flat",
            cursor="hand2", command=self._smart_select_newest,
        ).pack(anchor="w", padx=20, pady=1)

        tk.Button(
            self._filter_frame, text="Keep largest",
            bg=bg, fg=fg, font=("Segoe UI", 9), relief="flat",
            cursor="hand2", command=self._smart_select_largest,
        ).pack(anchor="w", padx=20, pady=1)

        self._advanced_smart_frame = tk.Frame(self._filter_frame, bg=bg)
        if self._advanced:
            self._build_advanced_smart_select()

    def _build_advanced_filters(self) -> None:
        bg = theme_token(self._t, "bg2", _PANEL_BG)
        fg = theme_token(self._t, "fg", _TEXT)

        tk.Label(self._advanced_filters_frame, text="Size range", bg=bg, fg=fg,
                 font=("Segoe UI", 9)).pack(anchor="w", padx=12, pady=(4, 2))
        tk.Entry(self._advanced_filters_frame, font=("Segoe UI", 9),
                 relief="flat").pack(fill="x", padx=12)

        tk.Label(self._advanced_filters_frame, text="Date range", bg=bg, fg=fg,
                 font=("Segoe UI", 9)).pack(anchor="w", padx=12, pady=(4, 2))
        tk.Entry(self._advanced_filters_frame, font=("Segoe UI", 9),
                 relief="flat").pack(fill="x", padx=12)

        tk.Label(self._advanced_filters_frame, text="Path contains", bg=bg, fg=fg,
                 font=("Segoe UI", 9)).pack(anchor="w", padx=12, pady=(4, 2))
        tk.Entry(self._advanced_filters_frame, font=("Segoe UI", 9),
                 relief="flat").pack(fill="x", padx=12)

        tk.Label(self._advanced_filters_frame, text="Min similarity %", bg=bg, fg=fg,
                 font=("Segoe UI", 9)).pack(anchor="w", padx=12, pady=(4, 2))
        tk.Scale(self._advanced_filters_frame, from_=0, to=100, orient="horizontal",
                 bg=bg, fg=fg, troughcolor=bg, highlightthickness=0,
                 font=("Segoe UI", 8)).pack(fill="x", padx=12)

        self._advanced_filters_frame.pack(fill="x")

    def _build_advanced_smart_select(self) -> None:
        bg = theme_token(self._t, "bg2", _PANEL_BG)
        fg = theme_token(self._t, "fg", _TEXT)

        tk.Button(
            self._advanced_smart_frame, text="Keep oldest",
            bg=bg, fg=fg, font=("Segoe UI", 9), relief="flat",
            cursor="hand2",
        ).pack(anchor="w", padx=20, pady=1)

        tk.Button(
            self._advanced_smart_frame, text="Path rules",
            bg=bg, fg=fg, font=("Segoe UI", 9), relief="flat",
            cursor="hand2",
        ).pack(anchor="w", padx=20, pady=1)

        tk.Button(
            self._advanced_smart_frame, text="Custom logic",
            bg=bg, fg=fg, font=("Segoe UI", 9), relief="flat",
            cursor="hand2",
        ).pack(anchor="w", padx=20, pady=1)

        self._advanced_smart_frame.pack(fill="x")

    def _build_groups(self) -> None:
        t = self._t
        bg = theme_token(t, "bg", _CARD_BG)
        fg = theme_token(t, "fg", _TEXT)

        self._groups_frame = tk.Frame(self, bg=bg)
        self._groups_frame.grid(row=0, column=1, sticky="nsew", padx=1)

        header = tk.Frame(self._groups_frame, bg=bg)
        header.pack(fill="x", padx=8, pady=(8, 4))
        self._groups_label = tk.Label(
            header, text="Groups", bg=bg, fg=fg,
            font=("Segoe UI", 11, "bold"),
        )
        self._groups_label.pack(side="left")
        self._groups_count_label = tk.Label(
            header, text="", bg=bg, fg=theme_token(t, "fg2", _TEXT_SEC),
            font=("Segoe UI", 9),
        )
        self._groups_count_label.pack(side="left", padx=(8, 0))

        self._groups_container = tk.Frame(self._groups_frame, bg=bg)
        self._groups_container.pack(fill="both", expand=True, padx=4, pady=4)

        self._empty_label = tk.Label(
            self._groups_container,
            text="No duplicates found",
            bg=bg, fg=theme_token(t, "fg2", _TEXT_SEC),
            font=("Segoe UI", 13),
        )
        self._empty_label.place(relx=0.5, rely=0.4, anchor="center")

    def _build_preview(self) -> None:
        t = self._t
        bg = theme_token(t, "bg", _CARD_BG)
        fg = theme_token(t, "fg", _TEXT)

        self._preview_frame = tk.Frame(self, bg=bg)
        self._preview_frame.grid(row=0, column=2, sticky="nsew")

        header = tk.Frame(self._preview_frame, bg=bg)
        header.pack(fill="x", padx=8, pady=(8, 4))
        tk.Label(header, text="Preview", bg=bg, fg=fg,
                 font=("Segoe UI", 11, "bold")).pack(side="left")

        self._compare_btn = tk.Button(
            header, text="Compare", bg=bg, fg=fg,
            font=("Segoe UI", 9), relief="flat", cursor="hand2",
            command=self._toggle_compare,
        )
        self._compare_btn.pack(side="right")

        self._preview_container = tk.Frame(self._preview_frame, bg=bg)
        self._preview_container.pack(fill="both", expand=True, padx=8, pady=4)

        self._preview_placeholder = tk.Label(
            self._preview_container,
            text="Select a file to preview",
            bg=bg, fg=theme_token(t, "fg2", _TEXT_SEC),
            font=("Segoe UI", 11),
        )
        self._preview_placeholder.place(relx=0.5, rely=0.4, anchor="center")

    def _on_filter_change(self) -> None:
        if self._coordinator:
            self._coordinator.results_set_filter(self._file_type_var.get())
            self._coordinator.results_set_text_filter(self._search_var.get())

    def _toggle_compare(self) -> None:
        self._compare_mode = not self._compare_mode
        if self._compare_mode:
            self._compare_btn.configure(text="Exit Compare")
        else:
            self._compare_btn.configure(text="Compare")

    def _smart_select_newest(self) -> None:
        if not self._groups:
            return
        to_select: Set[str] = set()
        for group in self._groups:
            files = list(group.files) if hasattr(group, "files") else []
            if len(files) < 2:
                continue
            sorted_files = sorted(
                files,
                key=lambda f: getattr(f, "mtime", 0) or 0,
                reverse=True,
            )
            for f in sorted_files[1:]:
                fid = getattr(f, "path", str(id(f)))
                to_select.add(fid)
        self._selected = to_select
        if self._coordinator:
            self._coordinator.set_selected_files(to_select)

    def _smart_select_largest(self) -> None:
        if not self._groups:
            return
        to_select: Set[str] = set()
        for group in self._groups:
            files = list(group.files) if hasattr(group, "files") else []
            if len(files) < 2:
                continue
            sorted_files = sorted(
                files,
                key=lambda f: getattr(f, "size", 0) or 0,
                reverse=True,
            )
            for f in sorted_files[1:]:
                fid = getattr(f, "path", str(id(f)))
                to_select.add(fid)
        self._selected = to_select
        if self._coordinator:
            self._coordinator.set_selected_files(to_select)

    def load_results(self, groups: list, mode: str = "files") -> None:
        self._groups = groups
        self._scan_mode = mode
        self._refresh_view()

    def _refresh_view(self) -> None:
        for w in self._groups_container.winfo_children():
            w.destroy()

        if not self._groups:
            t = self._t
            bg = theme_token(t, "bg", _CARD_BG)
            self._empty_label = tk.Label(
                self._groups_container,
                text="No duplicates found",
                bg=bg, fg=theme_token(t, "fg2", _TEXT_SEC),
                font=("Segoe UI", 13),
            )
            self._empty_label.place(relx=0.5, rely=0.4, anchor="center")
            self._groups_count_label.configure(text="")
            return

        dup_count = sum(max(0, len(g.files) - 1) for g in self._groups if hasattr(g, "files"))
        self._groups_count_label.configure(text=f"{dup_count} duplicates in {len(self._groups)} groups")

        for i, group in enumerate(self._groups):
            self._build_group_row(self._groups_container, group, i)

    def _build_group_row(self, parent: tk.Frame, group: Any, index: int) -> None:
        t = self._t
        bg = theme_token(t, "bg", _CARD_BG)
        fg = theme_token(t, "fg", _TEXT)
        fg2 = theme_token(t, "fg2", _TEXT_SEC)

        files = list(group.files) if hasattr(group, "files") else []
        total_size = sum(getattr(f, "size", 0) or 0 for f in files)

        outer = tk.Frame(parent, bg=bg, bd=1, relief="solid",
                         highlightbackground=theme_token(t, "border", _BORDER),
                         highlightthickness=1)
        outer.pack(fill="x", pady=2, padx=2)

        header = tk.Frame(outer, bg=bg, cursor="hand2")
        header.pack(fill="x", padx=8, pady=(6, 2))

        expand_var = tk.BooleanVar(value=False)

        tk.Label(header, text="\u25B6", bg=bg, fg=fg2,
                 font=("Segoe UI", 8)).pack(side="left", padx=(0, 4))

        tk.Label(header, text=f"Group {index + 1}  ({len(files)} files, {_fmt_size(total_size)})",
                 bg=bg, fg=fg, font=("Segoe UI", 10, "bold")).pack(side="left")

        reclaim = total_size - max((getattr(f, "size", 0) or 0 for f in files), default=0)
        if reclaim > 0:
            tk.Label(header, text=f"({_fmt_size(reclaim)} reclaimable)", bg=bg,
                     fg=theme_token(t, "danger", _DANGER),
                     font=("Segoe UI", 9)).pack(side="left", padx=(8, 0))

        files_frame = tk.Frame(outer, bg=bg)
        expand_var.trace_add("write", lambda *_: self._toggle_expand(files_frame, expand_var))

        def _toggle_header(e=None):
            expand_var.set(not expand_var.get())

        header.bind("<Button-1>", _toggle_header)
        for child in header.winfo_children():
            child.bind("<Button-1>", _toggle_header)

    def _toggle_expand(self, frame: tk.Frame, var: tk.BooleanVar) -> None:
        if var.get():
            frame.pack(fill="x", padx=8, pady=(0, 6))
        else:
            frame.pack_forget()

    def set_advanced(self, value: bool) -> None:
        self._advanced = value
        self._rebuild_filters()

    def _rebuild_filters(self) -> None:
        for w in self.winfo_children():
            w.destroy()
        self._build()

    def get_selected_count(self) -> int:
        return len(self._selected)

    def get_selected_size(self) -> int:
        total = 0
        for group in self._groups:
            for f in (group.files if hasattr(group, "files") else []):
                fid = getattr(f, "path", str(id(f)))
                if fid in self._selected:
                    total += getattr(f, "size", 0) or 0
        return total

    def on_show(self) -> None:
        pass
