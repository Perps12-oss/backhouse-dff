"""Review page — visual grid + side-by-side compare for duplicate groups."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional

import flet as ft

from cerebro.engines.base_engine import DuplicateFile, DuplicateGroup
from cerebro.v2.ui.flet_app.services.thumbnail_cache import get_thumbnail_cache, is_image_path
from cerebro.v2.ui.flet_app.theme import (
    FILTER_EXTS, EXT_ALL_KNOWN, ThemeTokens, classify_file, fmt_size, theme_for_mode,
)

if TYPE_CHECKING:
    from cerebro.v2.ui.flet_app.services.state_bridge import StateBridge

_log = logging.getLogger(__name__)

_FILTER_TABS = [
    ("all", "All"),
    ("pictures", "Images"),
    ("music", "Music"),
    ("videos", "Videos"),
    ("documents", "Docs"),
    ("archives", "Archives"),
    ("other", "Other"),
]


class ReviewPage(ft.Column):
    """Grid and compare view for visual triage of duplicate groups."""

    def __init__(self, bridge: "StateBridge"):
        super().__init__(expand=True, scroll=ft.ScrollMode.AUTO)
        self._bridge = bridge
        self._t = theme_for_mode("light")
        self._groups: List[DuplicateGroup] = []
        self._group_files: Dict[int, List[DuplicateFile]] = {}
        self._filter_key = "all"
        self._mode = "empty"  # "empty" | "grid" | "compare"
        self._compare_gid: Optional[int] = None
        self._compare_a: Optional[DuplicateFile] = None
        self._compare_b: Optional[DuplicateFile] = None
        self._build()

    def _build(self) -> None:
        t = self._t

        # Top bar
        self._title_lbl = ft.Text(
            "Review",
            size=t.typography.size_lg,
            weight=ft.FontWeight.BOLD,
            color=t.colors.fg,
        )
        self._summary_lbl = ft.Text(
            "",
            size=t.typography.size_sm,
            color=t.colors.fg2,
        )
        self._top_bar = ft.Row(
            [
                ft.TextButton(
                    "← Back to Results",
                    on_click=self._go_back,
                    style=ft.ButtonStyle(color=t.colors.primary),
                ),
                self._title_lbl,
                self._summary_lbl,
            ],
            alignment=ft.MainAxisAlignment.START,
        )

        # Compare navigation bar
        self._cmp_title = ft.Text("", size=t.typography.size_sm, color=t.colors.fg, weight=ft.FontWeight.W_600)
        self._delete_btn = ft.ElevatedButton(
            "Delete B", icon=ft.icons.Icons.DELETE_OUTLINE,
            on_click=lambda e: self._delete_compare_side("b"),
            style=ft.ButtonStyle(bgcolor=t.colors.danger, color=t.colors.bg),
        )
        self._keep_btn = ft.OutlinedButton(
            "Keep A", icon=ft.icons.Icons.CHECK,
            on_click=lambda e: self._delete_compare_side("a"),
            style=ft.ButtonStyle(color=t.colors.success),
        )
        self._cmp_bar = ft.Row(
            [
                ft.TextButton("← Grid", on_click=self._to_grid),
                ft.TextButton("← Prev", on_click=self._prev_group),
                ft.TextButton("Next →", on_click=self._next_group),
                self._cmp_title,
                self._keep_btn,
                self._delete_btn,
                ft.TextButton("Open A", on_click=lambda e: self._open_side("a")),
                ft.TextButton("Open B", on_click=lambda e: self._open_side("b")),
            ],
            visible=False,
        )

        # Filter bar
        self._filter_bar = ft.Row(
            [
                ft.ElevatedButton(
                    label,
                    on_click=lambda e, k=key: self._set_filter(k),
                    data=key,
                    style=ft.ButtonStyle(
                        bgcolor=t.colors.primary if key == "all" else t.colors.bg3,
                        color=t.colors.bg if key == "all" else t.colors.fg2,
                    ),
                )
                for key, label in _FILTER_TABS
            ],
            spacing=t.spacing.xs,
            wrap=True,
        )

        # Content area
        self._content = ft.Column(expand=True)

        # Empty state
        self._empty_state = ft.Container(
            content=ft.Column(
                [
                    ft.Icon(ft.icons.Icons.SEARCH, size=64, color=t.colors.fg_muted),
                    ft.Text("No scan results yet", size=t.typography.size_lg, color=t.colors.fg2),
                    ft.Text(
                        "Run a scan, then come here for visual triage.",
                        size=t.typography.size_base,
                        color=t.colors.fg_muted,
                        text_align=ft.TextAlign.CENTER,
                    ),
                    ft.ElevatedButton(
                        "Go to Results",
                        on_click=lambda e: self._bridge.navigate("duplicates"),
                        style=ft.ButtonStyle(bgcolor=t.colors.primary, color=t.colors.bg),
                    ),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=t.spacing.md,
            ),
            expand=True,
            alignment=ft.Alignment(0.5, 0.5),
        )

        # Grid view
        self._grid = ft.GridView(
            expand=True,
            runs_count=5,
            max_extent=180,
            child_aspect_ratio=1.0,
            spacing=t.spacing.sm,
            run_spacing=t.spacing.sm,
            padding=t.spacing.lg,
        )

        # Compare view
        self._compare_panel_a = ft.Container(
            expand=True,
            padding=t.spacing.md,
            border=ft.border.all(1, t.colors.border),
            border_radius=t.border_radius,
        )
        self._compare_panel_b = ft.Container(
            expand=True,
            padding=t.spacing.md,
            border=ft.border.all(1, t.colors.border),
            border_radius=t.border_radius,
        )
        self._compare_view = ft.Row(
            [
                self._compare_panel_a,
                ft.VerticalDivider(width=1),
                self._compare_panel_b,
            ],
            expand=True,
            visible=False,
        )

        self.controls = [
            ft.Container(content=self._top_bar, padding=t.spacing.lg),
            ft.Container(content=self._filter_bar, padding=ft.padding.only(left=t.spacing.lg, bottom=t.spacing.sm)),
            self._content,
        ]

    # -- Public API (matches Tkinter ReviewPage contract) ---------------------

    def load_group(
        self,
        groups: List[DuplicateGroup],
        group_id: int,
        mode: Optional[str] = None,
    ) -> None:
        self._groups = list(groups)
        self._group_files = {g.group_id: list(g.files) for g in self._groups}
        if not self._groups:
            self._enter_mode("empty")
            return
        self._enter_compare(group_id)

    def load_results(self, groups: List[DuplicateGroup], mode: str = "files") -> None:
        self._groups = list(groups)
        self._group_files = {g.group_id: list(g.files) for g in self._groups}
        if not self._groups:
            self._enter_mode("empty")
            return
        self._enter_mode("grid")

    def apply_pruned_groups(self, groups: List[DuplicateGroup], mode: str = "files") -> None:
        self._groups = list(groups)
        self._group_files = {g.group_id: list(g.files) for g in self._groups}
        if not self._groups:
            self._enter_mode("empty")
            return
        if self._mode == "compare":
            if self._compare_gid is None or self._compare_gid not in self._group_files:
                self._enter_compare(self._groups[0].group_id)
                return
            files = self._group_files[self._compare_gid]
            if not files:
                self._enter_compare(self._groups[0].group_id)
                return
            self._compare_a = files[0]
            self._compare_b = files[1] if len(files) > 1 else None
            self._update_compare_panels()
            self._update_compare_chrome()
        else:
            self._refresh_grid()

    def on_show(self) -> None:
        if not self._groups:
            self._enter_mode("empty")

    def get_groups(self) -> List[DuplicateGroup]:
        return list(self._groups)

    # -- Mode management ------------------------------------------------------

    def _enter_mode(self, mode: str) -> None:
        self._mode = mode
        if mode != "compare":
            self._page.on_keyboard_event = None
        self._content.controls.clear()

        if mode == "empty":
            self._filter_bar.visible = False
            self._cmp_bar.visible = False
            self._content.controls.append(self._empty_state)
        elif mode == "grid":
            self._filter_bar.visible = True
            self._cmp_bar.visible = False
            self._refresh_grid()
            self._content.controls.append(self._grid)
        elif mode == "compare":
            self._filter_bar.visible = False
            self._cmp_bar.visible = True
            self._content.controls.append(self._compare_view)

        self._content.update()
        self._filter_bar.update()
        self._cmp_bar.update()

    def _to_grid(self, e=None) -> None:
        self._enter_mode("grid")

    # -- Grid -----------------------------------------------------------------

    def _refresh_grid(self) -> None:
        t = self._t
        self._grid.controls = [
            self._build_tile(f)
            for g in self._groups
            for f in g.files
            if self._passes_filter(f)
        ]
        self._grid.update()

    def _passes_filter(self, f: DuplicateFile) -> bool:
        if self._filter_key == "all":
            return True
        ext = getattr(f, "extension", Path(str(f.path)).suffix.lower())
        if self._filter_key == "other":
            return ext.lower() not in EXT_ALL_KNOWN
        exts = FILTER_EXTS.get(self._filter_key)
        return ext.lower() in exts if exts else True

    def _thumb_widget(self, path: Path, edge: int) -> ft.Control:
        t = self._t
        if is_image_path(path):
            b64 = get_thumbnail_cache().get_base64(path)
            if b64:
                return ft.Image(
                    src=f"data:image/jpeg;base64,{b64}",
                    width=edge,
                    height=edge,
                    fit=ft.BoxFit.CONTAIN,
                    border_radius=8,
                )
        return ft.Icon(
            ft.icons.Icons.INSERT_DRIVE_FILE,
            size=max(28, edge // 2),
            color=t.colors.primary,
        )

    def _build_tile(self, f: DuplicateFile) -> ft.Container:
        t = self._t
        p = Path(str(f.path))
        name = p.name
        thumb = self._thumb_widget(p, 72)
        tile = ft.Container(
            content=ft.Column(
                [
                    thumb,
                    ft.Text(
                        name,
                        size=t.typography.size_xs,
                        color=t.colors.fg2,
                        overflow=ft.TextOverflow.ELLIPSIS,
                        max_lines=1,
                        text_align=ft.TextAlign.CENTER,
                    ),
                    ft.Text(fmt_size(f.size), size=t.typography.size_xs, color=t.colors.fg_muted),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=4,
            ),
            padding=t.spacing.sm,
            border=ft.border.all(1, t.colors.border),
            border_radius=t.border_radius,
            bgcolor=t.colors.bg,
            on_click=lambda e, file=f: self._on_tile_clicked(file),
        )

        def _hover(e: ft.ControlEvent) -> None:
            raw = getattr(e, "data", None)
            enter = raw is True or str(raw).lower() in ("true", "1", "enter")
            tile.bgcolor = t.colors.bg3 if enter else t.colors.bg
            tile.update()

        tile.on_hover = _hover
        return tile

    def _on_tile_clicked(self, f: DuplicateFile) -> None:
        gid = next(
            (g.group_id for g in self._groups if f in g.files),
            None,
        )
        if gid is not None:
            self._enter_compare(gid)

    # -- Compare --------------------------------------------------------------

    def _enter_compare(self, gid: int) -> None:
        files = self._group_files.get(gid) or []
        if not files:
            self._to_grid()
            return

        self._compare_gid = gid
        self._compare_a = files[0]
        self._compare_b = files[1] if len(files) > 1 else None
        self._update_compare_panels()
        self._update_compare_chrome()
        self._enter_mode("compare")
        self._bind_keys()

    def _update_compare_panels(self) -> None:
        t = self._t
        self._compare_panel_a.content = self._build_compare_side(self._compare_a, "A")
        self._compare_panel_b.content = self._build_compare_side(self._compare_b, "B")
        self._compare_panel_a.update()
        self._compare_panel_b.update()

    def _build_compare_side(self, f: Optional[DuplicateFile], label: str) -> ft.Column:
        t = self._t
        if not f:
            return ft.Column(
                [ft.Text(f"Side {label}: No peer file", color=t.colors.fg_muted)],
                alignment=ft.MainAxisAlignment.CENTER,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                expand=True,
            )
        p = Path(str(f.path))
        name = p.name
        thumb = self._thumb_widget(p, 120)
        return ft.Column(
            [
                ft.Text(f"Side {label}", size=t.typography.size_sm, weight=ft.FontWeight.BOLD, color=t.colors.primary),
                thumb,
                ft.Text(name, size=t.typography.size_md, weight=ft.FontWeight.W_600, color=t.colors.fg),
                ft.Text(fmt_size(f.size), size=t.typography.size_sm, color=t.colors.fg2),
                ft.Text(
                    str(Path(str(f.path)).parent),
                    size=t.typography.size_xs,
                    color=t.colors.fg_muted,
                    overflow=ft.TextOverflow.ELLIPSIS,
                ),
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=t.spacing.sm,
            alignment=ft.MainAxisAlignment.CENTER,
        )

    def _update_compare_chrome(self) -> None:
        gid = self._compare_gid
        if gid is None:
            return
        idx = next((i for i, g in enumerate(self._groups) if g.group_id == gid), 0)
        total = len(self._groups)
        count = len(self._group_files.get(gid, []))
        name_a = Path(str(getattr(self._compare_a, "path", ""))).name if self._compare_a else "(A)"
        name_b = Path(str(getattr(self._compare_b, "path", ""))).name if self._compare_b else "(no peer)"
        self._cmp_title.value = f"Group {idx + 1}/{total}  ·  {count} copies  ·  {name_a}  ↔  {name_b}"
        self._cmp_title.update()

    def _prev_group(self, e=None) -> None:
        if self._compare_gid is None:
            return
        idx = next((i for i, g in enumerate(self._groups) if g.group_id == self._compare_gid), 0)
        if idx > 0:
            self._enter_compare(self._groups[idx - 1].group_id)

    def _next_group(self, e=None) -> None:
        if self._compare_gid is None:
            return
        idx = next((i for i, g in enumerate(self._groups) if g.group_id == self._compare_gid), 0)
        if idx < len(self._groups) - 1:
            self._enter_compare(self._groups[idx + 1].group_id)

    def _open_side(self, side: str) -> None:
        f = self._compare_a if side == "a" else self._compare_b
        if not f:
            return
        import subprocess, sys
        path = Path(str(f.path))
        folder = path.parent if path.is_file() else path
        try:
            if sys.platform == "win32":
                subprocess.Popen(["explorer", "/select,", str(path)])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(folder)])
            else:
                subprocess.Popen(["xdg-open", str(folder)])
        except Exception:
            pass

    # -- Filter ---------------------------------------------------------------

    def _set_filter(self, key: str) -> None:
        self._filter_key = key
        for btn in self._filter_bar.controls:
            is_active = btn.data == key
            btn.style = ft.ButtonStyle(
                bgcolor=self._t.colors.primary if is_active else self._t.colors.bg3,
                color=self._t.colors.bg if is_active else self._t.colors.fg2,
            )
            btn.update()
        if self._mode == "grid":
            self._refresh_grid()

    # -- Keyboard navigation --------------------------------------------------

    def _bind_keys(self) -> None:
        self._page.on_keyboard_event = self._on_key

    def _on_key(self, e: ft.KeyboardEvent) -> None:
        if self._mode != "compare":
            return
        k = e.key.lower().replace(" ", "")
        if k in ("arrowleft", "left"):
            self._prev_group()
        elif k in ("arrowright", "right"):
            self._next_group()
        elif k == "d":
            self._delete_compare_side("b")
        elif k == "k":
            self._delete_compare_side("a")

    # -- Delete from compare --------------------------------------------------

    def _delete_compare_side(self, side: str) -> None:
        f = self._compare_a if side == "a" else self._compare_b
        if not f:
            return
        path = str(f.path)
        from cerebro.v2.ui.flet_app.services.delete_service import DeleteService
        service = DeleteService()
        new_groups, *_ = service.delete_and_prune([path], self._groups)
        self._groups = new_groups
        self._group_files = {g.group_id: list(g.files) for g in self._groups}
        self._bridge.coordinator.results_files_removed([path])
        if not self._groups:
            self._enter_mode("empty")
            return
        gid = self._compare_gid
        if gid not in self._group_files:
            gid = self._groups[0].group_id
        self._enter_compare(gid)

    # -- Navigation -----------------------------------------------------------

    def _go_back(self, e=None) -> None:
        if self._mode == "compare":
            self._to_grid()
            return
        self._bridge.navigate("duplicates")
