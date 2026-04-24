"""
Duplicates (Results) page body — grouped expandable DataGrid + preview (Sprint 2–3).

One tree row per :class:`DuplicateGroup`; expand to list files. Smart Select and
dry-run are triggered from the parent :class:`ResultsPage` toolbar.
"""

from __future__ import annotations

import logging
import os
import tkinter as tk
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, TYPE_CHECKING

from cerebro.engines.base_engine import DuplicateGroup
from cerebro.v2.ui.delete_flow import DeleteItem, run_delete_ceremony
from cerebro.v2.ui.file_type_filters import (
    _EXT_ALL_KNOWN,
    _FILTER_EXTS,
    classify_file,
)
from cerebro.v2.ui.widgets.data_grid import DataGrid, DataGridColumn
from cerebro.v2.state import StateStore
from cerebro.v2.state.actions import (
    ResultsGroupGridSortChanged,
    ResultsViewFilterChanged,
    ResultsViewTextFilterChanged,
)
from cerebro.v2.state.app_state import AppState
from cerebro.v2.ui.theme_applicator import ThemeApplicator

if TYPE_CHECKING:
    from cerebro.v2.coordinator import CerebroCoordinator

_log = logging.getLogger(__name__)

VALID_GROUP_SORT = ("reclaimable", "files", "group_id", "path")

_COL_FILES = "n_files"
_COL_RECLAIM = "reclaim"
_COL_KIND = "kind"
_COL_PATH = "path"

_HEADING_TO_STATE = {
    _COL_FILES: "files",
    _COL_RECLAIM: "reclaimable",
    _COL_KIND: "group_id",
    _COL_PATH: "path",
}

_DEFAULT_ASC: Dict[str, bool] = {
    "reclaimable": False,
    "files": False,
    "group_id": True,
    "path": True,
}


def _fmt_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024**2:
        return f"{n/1024:.1f} KB"
    if n < 1024**3:
        return f"{n/1024**2:.1f} MB"
    return f"{n/1024**3:.1f} GB"


def _group_passes_type_filter(g: DuplicateGroup, key: str) -> bool:
    if key == "all":
        return True
    for f in g.files:
        e = (getattr(f, "extension", None) or Path(f.path).suffix)
        if classify_file(e) == key:
            return True
    return False


def _group_passes_text(g: DuplicateGroup, needle: str) -> bool:
    n = (needle or "").strip().lower()
    if not n:
        return True
    if n in str(g.group_id).lower():
        return True
    for f in g.files:
        p = str(f.path).lower()
        if n in p or n in Path(f.path).name.lower():
            return True
    return False


def _visible_groups(
    groups: List[DuplicateGroup],
    type_key: str,
    text: str,
) -> List[DuplicateGroup]:
    return [
        g
        for g in groups
        if _group_passes_type_filter(g, type_key) and _group_passes_text(g, text)
    ]


def _filter_aware_all_members_visible(g: DuplicateGroup, type_key: str) -> bool:
    if type_key == "all":
        return len(g.files) >= 2
    for f in g.files:
        e = (getattr(f, "extension", None) or Path(f.path).suffix)
        b = classify_file(e)
        if b != type_key:
            return False
    return len(g.files) >= 2


def _sort_key(g: DuplicateGroup, col: str) -> Any:
    if col == "reclaimable":
        return int(g.reclaimable)
    if col == "files":
        return len(g.files)
    if col == "group_id":
        return g.group_id
    if col == "path":
        p = g.files[0].path if g.files else Path("")
        return str(p).lower()
    return 0


class DuplicatesView(tk.Frame):
    """
    Expandable group tree + right-hand preview.
    """

    def __init__(
        self,
        master: tk.Misc,
        store: StateStore,
        coordinator: "CerebroCoordinator",
        on_open_group: Callable[[int, List[DuplicateGroup]], None],
        on_remove_paths: Callable[[Set[str]], None],
        on_navigate_home: Optional[Callable[[], None]] = None,
        on_rescan: Optional[Callable[[], None]] = None,
        get_scan_mode: Optional[Callable[[], str]] = None,
        on_file_selection_changed: Optional[Callable[[int], None]] = None,
        **kwargs,
    ) -> None:
        t = ThemeApplicator.get().build_tokens()
        kwargs.setdefault("bg", t.get("bg", "#FFFFFF"))
        super().__init__(master, **kwargs)
        self._store = store
        self._coordinator = coordinator
        self._on_open_group = on_open_group
        self._on_remove_paths = on_remove_paths
        self._on_navigate_home = on_navigate_home
        self._on_rescan = on_rescan
        self._get_scan_mode = get_scan_mode or (lambda: "files")
        self._on_file_selection_changed = on_file_selection_changed
        self._unsub_store: Optional[Callable[[], None]] = None
        self._groups: List[DuplicateGroup] = []
        self._t = t
        self._expanded_children_loaded: Set[int] = set()
        self._preview_img: Optional[Any] = None

        self._body = tk.PanedWindow(
            self,
            orient=tk.HORIZONTAL,
            sashrelief=tk.FLAT,
            bg=t.get("bg", "#FFFFFF"),
        )
        self._body.pack(fill="both", expand=True)
        self._left = tk.Frame(self._body, bg=t.get("bg", "#FFFFFF"))
        self._right = tk.Frame(self._body, width=300, bg=t.get("bg2", "#F5F5F5"))
        self._body.add(self._left, minsize=400, stretch="always")
        self._body.add(self._right, minsize=240, stretch="never")

        self._grid = DataGrid(
            self._left,
            [
                DataGridColumn(_COL_FILES, "Files", 64, "center"),
                DataGridColumn(_COL_RECLAIM, "Reclaimable", 100, "e"),
                DataGridColumn(_COL_KIND, "Kind", 80, "center"),
                DataGridColumn(_COL_PATH, "Path", 280, "w"),
            ],
            tree=True,
            style_name="Cerebro.Duplicates",
            on_sort_column=self._on_sort_column,
            on_row_select=self._on_row_select,
            on_row_open=self._on_row_open,
            on_tree_open=self._on_tree_open,
            select_mode="extended",
            row_height=24,
        )
        self._grid.pack(fill="both", expand=True)
        self._grid.treeview.bind(
            "<<TreeviewSelect>>", self._on_tree_select_maybe_empty, add=True
        )

        self._prev_title = tk.Label(
            self._right,
            text="Preview",
            font=("Segoe UI", 10, "bold"),
            bg=t.get("bg2", "#F5F5F5"),
        )
        self._prev_title.pack(anchor="w", padx=8, pady=6)
        self._prev_img = tk.Label(self._right, bg=t.get("bg2", "#F5F5F5"))
        self._prev_img.pack(padx=8, pady=4)
        self._prev_meta = tk.Label(
            self._right,
            text="Select a file or group",
            font=("Segoe UI", 9),
            fg=t.get("fg2", "#555555"),
            justify="left",
            wraplength=260,
            bg=t.get("bg2", "#F5F5F5"),
        )
        self._prev_meta.pack(anchor="w", padx=8, pady=4, fill="x")

        if self._store is not None:
            self._unsub_store = self._store.subscribe(self._on_store_sub)

    def destroy(self) -> None:  # type: ignore[override]
        if self._unsub_store is not None:
            try:
                self._unsub_store()
            except Exception:
                pass
            self._unsub_store = None
        super().destroy()

    def set_groups(self, groups: List[DuplicateGroup]) -> None:
        self._groups = list(groups)
        self._expanded_children_loaded.clear()
        self.refresh_from_state()

    def refresh_from_state(self) -> None:
        self._expanded_children_loaded.clear()
        s = self._store.get_state()
        if not self._groups:
            self._grid.clear()
            return
        vis = _visible_groups(
            self._groups,
            s.results_file_filter,
            s.results_text_filter,
        )
        col = s.results_group_sort_column
        if col not in VALID_GROUP_SORT:
            col = "reclaimable"
        asc = s.results_group_sort_asc
        vis.sort(key=lambda g: _sort_key(g, col), reverse=not asc)
        self._grid.clear()
        for g in vis:
            pth = str(g.files[0].path) if g.files else ""
            if len(pth) > 60:
                pth = pth[:28] + "…" + pth[-28:]
            iid = f"G{g.group_id}"
            self._grid.insert_row(
                iid,
                values=(
                    str(len(g.files)),
                    _fmt_size(int(g.reclaimable)),
                    str(getattr(g, "similarity_type", "exact") or "exact")[:12],
                    pth,
                ),
                text=f"  #{g.group_id}  ",
                data={
                    "kind": "group",
                    "group_id": g.group_id,
                    "path": None,
                },
            )

    def _on_sort_column(self, dg_col: str) -> None:
        key = _HEADING_TO_STATE.get(dg_col, "reclaimable")
        s = self._store.get_state()
        if s.results_group_sort_column == key:
            new_asc = not s.results_group_sort_asc
        else:
            new_asc = _DEFAULT_ASC.get(key, True)
        self._coordinator.results_set_group_sort(key, new_asc)

    def _on_store_sub(
        self, s: AppState, _old: AppState, action: object
    ) -> None:
        self.on_store(s, action)

    def _on_tree_select_maybe_empty(self, _e: object) -> None:
        if self._grid.treeview.selection():
            return
        t = self._t
        bg2 = t.get("bg2", "#F5F5F5")
        self._prev_img.configure(image="", bg=bg2)
        self._preview_img = None
        self._prev_meta.configure(
            text="Select a file or group", bg=bg2, justify="left"
        )
        if self._on_file_selection_changed is not None:
            self._on_file_selection_changed(0)

    def _on_row_select(self, iid: str, _data: Dict[str, Any]) -> None:
        d = self._grid.get_row_data(iid)
        self._update_preview(d, iid)
        if self._on_file_selection_changed is not None:
            self._on_file_selection_changed(
                len(self.get_selected_file_paths())
            )

    def _on_row_open(self, iid: str, _data: Dict[str, Any]) -> None:
        d = self._grid.get_row_data(iid)
        if d.get("kind") == "group" and d.get("group_id") is not None:
            self._on_open_group(int(d["group_id"]), self._groups)
        elif d.get("path"):
            p = str(d["path"])
            try:
                if os.name == "nt":
                    os.startfile(p)  # type: ignore[attr-defined]
            except (OSError, AttributeError):
                _log.debug("open file failed: %s", p)

    def _on_tree_open(self, iid: str, _data: Dict[str, Any]) -> None:
        d = self._grid.get_row_data(iid)
        if d.get("kind") != "group" or d.get("group_id") is None:
            return
        gid = int(d["group_id"])
        if gid in self._expanded_children_loaded:
            return
        g = next((x for x in self._groups if x.group_id == gid), None)
        if g is None:
            return
        s = self._store.get_state()
        fk = s.results_file_filter
        for i, f in enumerate(g.files):
            ext = (getattr(f, "extension", None) or Path(f.path).suffix).lower()
            b = classify_file(ext) if fk != "all" else "all"
            if fk != "all" and fk != b:
                continue
            c_iid = f"G{gid}F{i}"
            self._grid.insert_row(
                c_iid,
                values=(
                    Path(f.path).name,
                    _fmt_size(int(f.size or 0)),
                    ext or "—",
                    str(f.path),
                ),
                text="",
                parent=f"G{gid}",
                data={"kind": "file", "group_id": gid, "path": str(f.path)},
            )
        self._expanded_children_loaded.add(gid)

    def _update_preview(self, data: Dict[str, Any], _iid: str) -> None:
        kind = data.get("kind")
        t = self._t
        bg2 = t.get("bg2", "#F5F5F5")
        self._prev_img.configure(image="", bg=bg2)
        self._preview_img = None
        if kind == "file" and data.get("path"):
            p = str(data["path"])
            ext = Path(p).suffix.lower()
            if ext in (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"):
                try:
                    from PIL import Image, ImageTk

                    im = Image.open(p)
                    im.thumbnail((260, 200))
                    self._preview_img = ImageTk.PhotoImage(im)
                    self._prev_img.configure(image=self._preview_img, bg=bg2)
                except (OSError, ValueError, ImportError):
                    pass
            st = f"{Path(p).name}\n{p}"
            try:
                st += f"\n{Path(p).stat().st_size} bytes" if Path(p).is_file() else ""
            except OSError:
                pass
            self._prev_meta.configure(text=st, bg=bg2, justify="left")
        elif kind == "group" and data.get("group_id") is not None:
            gid = int(data["group_id"])
            g = next((x for x in self._groups if x.group_id == gid), None)
            if g:
                self._prev_meta.configure(
                    text=(
                        f"Group {gid}\n{len(g.files)} files\n"
                        f"{_fmt_size(int(g.reclaimable))} reclaimable"
                    ),
                    bg=bg2,
                )
        else:
            self._prev_meta.configure(text="Select a file or group", bg=bg2)

    def get_selected_file_paths(self) -> List[str]:
        paths: List[str] = []
        for iid in self._grid.selected_iids():
            d = self._grid.get_row_data(iid)
            if d.get("kind") == "file" and d.get("path"):
                paths.append(str(d["path"]))
        return paths

    def run_smart_select(self, rule: str) -> None:
        s = self._store.get_state()
        dry = s.dry_run
        vis = _visible_groups(
            self._groups, s.results_file_filter, s.results_text_filter
        )
        items: List[DeleteItem] = []
        for g in vis:
            if not _filter_aware_all_members_visible(g, s.results_file_filter):
                continue
            files = list(g.files)
            if len(files) < 2:
                continue
            if rule == "select_except_oldest":
                keep = min(files, key=lambda f: getattr(f, "modified", 0) or 0)
            elif rule == "select_except_newest":
                keep = max(files, key=lambda f: getattr(f, "modified", 0) or 0)
            elif rule == "select_except_first":
                keep = files[0]
            elif rule == "select_except_last":
                keep = files[-1]
            elif rule == "select_except_largest":
                keep = max(files, key=lambda f: int(getattr(f, "size", 0) or 0))
            else:
                keep = files[0]
            for f in files:
                if f is keep:
                    continue
                items.append(
                    DeleteItem(
                        path_str=str(f.path),
                        size=int(getattr(f, "size", 0) or 0),
                    )
                )
        if not items:
            return
        run_delete_ceremony(
            parent=self.winfo_toplevel(),
            items=items,
            scan_mode=self._get_scan_mode(),
            on_remove_paths=self._on_remove_paths,
            on_navigate_home=self._on_navigate_home,
            on_rescan=self._on_rescan,
            source_tag="duplicates_page.smart_select",
            dry_run=dry,
        )

    def on_store(self, s: AppState, action: object) -> None:
        if isinstance(
            action,
            (ResultsViewFilterChanged, ResultsViewTextFilterChanged, ResultsGroupGridSortChanged),
        ):
            self.refresh_from_state()

    def apply_theme(self, t: dict) -> None:
        self._t = t
        bg = t.get("bg", "#FFFFFF")
        bg2 = t.get("bg2", "#F5F5F5")
        self.configure(bg=bg)
        self._body.configure(bg=bg)
        self._left.configure(bg=bg)
        for w in (self._right, self._prev_title, self._prev_img, self._prev_meta):
            w.configure(bg=bg2)
        self._grid.apply_theme(
            bg=bg,
            fg=t.get("fg", "#111111"),
            heading_bg=t.get("nav_bar", "#1E3A5F"),
            heading_fg=t.get("row_sel_fg", "#F0F0F0"),
            select_bg=t.get("row_sel", "#1E3A8A"),
        )
