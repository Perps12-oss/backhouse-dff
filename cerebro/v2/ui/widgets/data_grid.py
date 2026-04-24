"""
Reusable ttk.Treeview-based DataGrid (Blueprint Sprint 2).

- Flat mode: ``show="headings"`` for history-style tables.
- Tree mode: ``show="tree headings"`` for duplicate groups with expandable file rows.

Callers own sort/filter/pagination in :class:`AppState`; the grid only renders rows
and invokes callbacks: ``on_sort_column``, ``on_row_select``, ``on_row_open``.
"""

from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

from tkinter import ttk

OnSort = Callable[[str], None]
OnSelect = Callable[[str, Dict[str, Any]], None]
OnOpen = Callable[[str, Dict[str, Any]], None]
OnTreeOpen = Callable[[str, Dict[str, Any]], None]


@dataclass(frozen=True)
class DataGridColumn:
    """One logical column in :class:`DataGrid`."""

    id: str
    title: str
    width: int
    anchor: str = "w"
    sortable: bool = True


class DataGrid(tk.Frame):
    """
    Themed ttk.Treeview with optional tree column, scrollbar, and header sort hooks.
    """

    def __init__(
        self,
        parent: tk.Misc,
        columns: List[DataGridColumn],
        *,
        tree: bool = False,
        style_name: str = "Cerebro.DataGrid",
        on_sort_column: Optional[OnSort] = None,
        on_row_select: Optional[OnSelect] = None,
        on_row_open: Optional[OnOpen] = None,
        on_tree_open: Optional[OnTreeOpen] = None,
        select_mode: str = "extended",
        row_height: int = 26,
        **kwargs,
    ) -> None:
        kwargs.setdefault("bg", parent.cget("bg") if parent else "#FFFFFF")
        super().__init__(parent, **kwargs)
        self._cols = list(columns)
        self._ids = [c.id for c in self._cols]
        self._tree = bool(tree)
        self._style_name = style_name
        self._on_sort = on_sort_column
        self._on_row_select = on_row_select
        self._on_row_open = on_row_open
        self._on_tree_open = on_tree_open
        self._row_by_iid: Dict[str, Dict[str, Any]] = {}
        self._row_height = int(row_height)

        self._style = ttk.Style()
        self._style.theme_use("default")
        self._style.configure(
            self._style_name,
            background="#FFFFFF",
            fieldbackground="#FFFFFF",
            font=("Segoe UI", 10),
            rowheight=self._row_height,
        )
        self._style.configure(
            f"{self._style_name}.Heading",
            background="#1E3A5F",
            foreground="#F0F0F0",
            font=("Segoe UI", 9),
        )

        show = "tree headings" if self._tree else "headings"
        self._tv = ttk.Treeview(
            self,
            columns=self._ids,
            show=show,
            selectmode=select_mode,
            style=self._style_name,
        )
        for c in self._cols:
            col_id = c.id
            if c.sortable and self._on_sort is not None:
                self._tv.heading(
                    col_id,
                    text=c.title,
                    command=(lambda _cid=col_id: self._on_sort(_cid)),
                )
            else:
                self._tv.heading(col_id, text=c.title)
            self._tv.column(col_id, width=c.width, anchor=c.anchor)

        if self._tree:
            self._tv.heading("#0", text="")
            self._tv.column("#0", width=28, stretch=False)

        sb = ttk.Scrollbar(self, orient="vertical", command=self._tv.yview)
        self._tv.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self._tv.pack(side="left", fill="both", expand=True)

        self._tv.bind("<<TreeviewSelect>>", self._on_select_ev)
        self._tv.bind("<Double-1>", self._on_dbl)
        if self._tree and self._on_tree_open is not None:
            self._tv.bind("<<TreeviewOpen>>", self._on_tree_open_ev)

    @property
    def treeview(self) -> ttk.Treeview:
        return self._tv

    def clear(self) -> None:
        self._row_by_iid.clear()
        for iid in self._tv.get_children(""):
            self._tv.delete(iid)

    def set_row_data(self, iid: str, data: Dict[str, Any]) -> None:
        self._row_by_iid[iid] = dict(data)

    def get_row_data(self, iid: str) -> Dict[str, Any]:
        return dict(self._row_by_iid.get(iid, {}))

    def iter_flat_children(self) -> List[str]:
        return list(self._tv.get_children(""))

    def insert_row(
        self,
        iid: str,
        values: Tuple[object, ...],
        *,
        text: str = "",
        parent: str = "",
        data: Optional[Dict[str, Any]] = None,
    ) -> str:
        if data is not None:
            self._row_by_iid[iid] = dict(data)
        return str(
            self._tv.insert(
                parent,
                "end",
                iid=iid,
                text=text,
                values=tuple(values),
            )
        )

    def delete(self, *iids: str) -> None:
        for i in iids:
            self._row_by_iid.pop(i, None)
        self._tv.delete(*iids)

    def get_children(self, iid: str) -> List[str]:
        return list(self._tv.get_children(iid))

    def see(self, iid: str) -> None:
        self._tv.see(iid)

    def focus(self, iid: str) -> None:
        self._tv.focus(iid)
        self._tv.selection_set(iid)

    def selected_iids(self) -> List[str]:
        return list(self._tv.selection())

    def _on_select_ev(self, _e: object) -> None:
        if self._on_row_select is None:
            return
        sel = self._tv.selection()
        if not sel:
            return
        iid = sel[0]
        self._on_row_select(iid, self.get_row_data(iid))

    def _on_dbl(self, _e: object) -> None:
        if self._on_row_open is None:
            return
        sel = self._tv.selection()
        if not sel:
            return
        iid = sel[0]
        self._on_row_open(iid, self.get_row_data(iid))

    def _on_tree_open_ev(self, _e: object) -> None:
        if self._on_tree_open is None:
            return
        sel = self._tv.focus()
        if not sel:
            return
        self._on_tree_open(sel, self.get_row_data(sel))

    def apply_theme(
        self,
        *,
        bg: str = "#FFFFFF",
        fg: str = "#111111",
        heading_bg: str = "#1E3A5F",
        heading_fg: str = "#F0F0F0",
        select_bg: str = "#1E3A8A",
    ) -> None:
        self._style.configure(
            self._style_name,
            background=bg,
            fieldbackground=bg,
            foreground=fg,
            rowheight=self._row_height,
        )
        self._style.map(
            self._style_name,
            background=[("selected", select_bg)],
            foreground=[("selected", "#FFFFFF")],
        )
        self._style.configure(
            f"{self._style_name}.Heading",
            background=heading_bg,
            foreground=heading_fg,
        )
