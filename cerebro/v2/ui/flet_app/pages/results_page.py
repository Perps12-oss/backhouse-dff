"""Results page — displays duplicate groups with filtering, smart selection, and delete actions."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Set

import flet as ft

from cerebro.core.deletion import DeletionPolicy
from cerebro.engines.base_engine import DuplicateGroup
from cerebro.v2.ui.flet_app.theme import (
    FILTER_EXTS, classify_file, fmt_size, theme_for_mode,
)
from cerebro.v2.ui.flet_app.services.thumbnail_cache import get_thumbnail_cache, is_image_path

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

_FILTER_ACCENT = {
    "all": "#C7D2FE",
    "pictures": "#C084FC",
    "music": "#34D399",
    "videos": "#F472B6",
    "documents": "#FB923C",
    "archives": "#FBBF24",
    "other": "#93C5FD",
}

# Above this many duplicate *groups*, build the ListView in chunks so the UI thread
# can still process NavigationRail taps (see debug-4176e4: multi-second sync build).
_LIST_BUILD_ASYNC_THRESHOLD = 72
_LIST_FIRST_SYNC_GROUPS = 28
_LIST_ASYNC_BATCH = 36

_SMART_SELECT_OPTIONS = [
    ("keep_largest", "Keep Largest"),
    ("keep_smallest", "Keep Smallest"),
    ("keep_newest", "Keep Newest"),
    ("keep_oldest", "Keep Oldest"),
]


class ResultsPage(ft.Stack):
    """Duplicate group listing with type filters, smart selection, and delete."""

    def __init__(self, bridge: "StateBridge"):
        super().__init__(expand=True)
        self._scroll_col = ft.Column(expand=True, scroll=ft.ScrollMode.AUTO)
        self._bridge = bridge
        self._t = theme_for_mode("dark")
        self._groups: List[DuplicateGroup] = []
        self._filter_key = "all"
        self._scan_mode = "files"
        self._selected_paths: Set[str] = set()
        self._smart_rule = "keep_largest"
        self._list_build_generation = 0
        self._loading = False
        self._filter_counts: Dict[str, int] = {k: 0 for k, _ in _FILTER_TABS}
        self._filter_sizes: Dict[str, int] = {k: 0 for k, _ in _FILTER_TABS}
        self._filter_group_counts: Dict[str, int] = {k: 0 for k, _ in _FILTER_TABS}
        self._glass_cache: dict = {}
        self._view_mode: str = "list"
        self._thumb_slots: Dict[str, ft.Container] = {}
        self._tile_cache_grid: Dict[str, ft.Container] = {}

        # UI References
        self._summary: ft.Text
        self._smart_seg: ft.SegmentedButton
        self._smart_row: ft.Row
        self._selection_label: ft.Text
        self._delete_btn: ft.ElevatedButton
        self._permanent_btn: ft.OutlinedButton
        self._action_bar: ft.Row
        self._header: ft.Row
        self._filter_seg: ft.SegmentedButton
        self._group_list: ft.ListView
        self._empty: ft.Container
        self._loading_state: ft.Container
        self._results_grid: ft.ListView
        self._grid_btn: ft.IconButton
        self._list_btn: ft.IconButton

        self._build_ui()

    # ------------------------------------------------------------------
    # Glass helper
    # ------------------------------------------------------------------
    def _get_glass_style(self, opacity: float = 0.06) -> dict:
        is_light = "light" in self._bridge.app_theme.lower() if hasattr(self._bridge, 'app_theme') else False
        cache_key = (opacity, is_light)
        if cache_key in self._glass_cache:
            return self._glass_cache[cache_key]
        bg_base = ft.Colors.BLACK if is_light else ft.Colors.WHITE
        border_base = ft.Colors.BLACK if is_light else ft.Colors.WHITE
        bg = ft.Colors.with_opacity(opacity, bg_base)
        border_color = ft.Colors.with_opacity(0.12, border_base)
        result = dict(
            bgcolor=bg,
            border=ft.border.all(1, border_color),
            border_radius=ft.border_radius.all(12),
        )
        self._glass_cache[cache_key] = result
        return result
    
    def _file_type_icon(self, extension: str) -> tuple[str, str]:
        """Return (icon_name, accent_color) for a file extension."""
        ext = (extension or "").lower().lstrip(".")
        _map = {
            # Images
            "jpg": (ft.icons.Icons.IMAGE, "#A78BFA"),
            "jpeg": (ft.icons.Icons.IMAGE, "#A78BFA"),
            "png": (ft.icons.Icons.IMAGE, "#A78BFA"),
            "gif": (ft.icons.Icons.IMAGE, "#A78BFA"),
            "heic": (ft.icons.Icons.IMAGE, "#A78BFA"),
            "webp": (ft.icons.Icons.IMAGE, "#A78BFA"),
            "raw": (ft.icons.Icons.IMAGE, "#A78BFA"),
            # Music
            "mp3": (ft.icons.Icons.MUSIC_NOTE, "#34D399"),
            "flac": (ft.icons.Icons.MUSIC_NOTE, "#34D399"),
            "wav": (ft.icons.Icons.MUSIC_NOTE, "#34D399"),
            "aac": (ft.icons.Icons.MUSIC_NOTE, "#34D399"),
            "m4a": (ft.icons.Icons.MUSIC_NOTE, "#34D399"),
            # Video
            "mp4": (ft.icons.Icons.VIDEOCAM, "#F472B6"),
            "mkv": (ft.icons.Icons.VIDEOCAM, "#F472B6"),
            "mov": (ft.icons.Icons.VIDEOCAM, "#F472B6"),
            "avi": (ft.icons.Icons.VIDEOCAM, "#F472B6"),
            # Documents
            "pdf": (ft.icons.Icons.PICTURE_AS_PDF, "#FB923C"),
            "doc": (ft.icons.Icons.DESCRIPTION, "#60A5FA"),
            "docx": (ft.icons.Icons.DESCRIPTION, "#60A5FA"),
            "xls": (ft.icons.Icons.TABLE_CHART, "#34D399"),
            "xlsx": (ft.icons.Icons.TABLE_CHART, "#34D399"),
            "ppt": (ft.icons.Icons.SLIDESHOW, "#FB923C"),
            "pptx": (ft.icons.Icons.SLIDESHOW, "#FB923C"),
            "txt": (ft.icons.Icons.ARTICLE, "#94A3B8"),
            # Archives
            "zip": (ft.icons.Icons.FOLDER_ZIP, "#FBBF24"),
            "rar": (ft.icons.Icons.FOLDER_ZIP, "#FBBF24"),
            "7z": (ft.icons.Icons.FOLDER_ZIP, "#FBBF24"),
            "tar": (ft.icons.Icons.FOLDER_ZIP, "#FBBF24"),
            "gz": (ft.icons.Icons.FOLDER_ZIP, "#FBBF24"),
        }
        return _map.get(ext, (ft.icons.Icons.INSERT_DRIVE_FILE, "#6E7681"))

    # ------------------------------------------------------------------
    # Build (Runs Once)
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        t = self._t

        self._summary = ft.Text("", size=t.typography.size_base, color="#BFD5FF", weight=ft.FontWeight.W_500)

        # Smart select row
        self._smart_seg = ft.SegmentedButton(
            selected=["keep_largest"],
            allow_multiple_selection=False,
            on_change=self._on_smart_seg_change,
            segments=[
                ft.Segment(value=val, label=ft.Text(label, size=11))
                for val, label in _SMART_SELECT_OPTIONS
            ],
        )
        self._smart_row = ft.Row([self._smart_seg], spacing=t.spacing.sm, visible=False)

        # Selection label and delete buttons
        self._selection_label = ft.Text("", size=t.typography.size_sm, color=t.colors.fg2)
        self._delete_btn = ft.OutlinedButton(
            "Move to Trash",
            icon=ft.icons.Icons.DELETE_OUTLINE,
            on_click=self._on_delete_clicked,
            style=ft.ButtonStyle(
                color=t.colors.danger,
                side=ft.BorderSide(1, t.colors.danger),
                shape=ft.RoundedRectangleBorder(radius=8),
            ),
            visible=False,
        )
        self._permanent_btn = ft.OutlinedButton(
            "Delete Permanently",
            icon=ft.icons.Icons.DELETE_FOREVER,
            on_click=self._on_permanent_delete_clicked,
            style=ft.ButtonStyle(color=t.colors.danger),
            visible=False,
        )
        self._action_bar = ft.Row(
            [self._selection_label, self._smart_row, self._delete_btn, self._permanent_btn],
            alignment=ft.MainAxisAlignment.START,
            spacing=t.spacing.md,
            visible=False,
        )

        self._grid_btn = ft.IconButton(
            icon=ft.icons.Icons.GRID_VIEW,
            tooltip="Grid view",
            icon_color="#22D3EE",
            on_click=lambda e: self._toggle_view("grid"),
        )
        self._list_btn = ft.IconButton(
            icon=ft.icons.Icons.VIEW_LIST,
            tooltip="List view",
            icon_color=t.colors.fg_muted,
            on_click=lambda e: self._toggle_view("list"),
        )
        self._header = ft.Row(
            [
                ft.Text("Scan Results", size=t.typography.size_xl, weight=ft.FontWeight.BOLD, color=t.colors.fg),
                ft.Row([self._summary, self._grid_btn, self._list_btn], spacing=t.spacing.xs, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        )

        self._filter_seg = ft.SegmentedButton(
            selected=["all"],
            allow_multiple_selection=False,
            on_change=self._on_filter_seg_change,
            segments=[
                ft.Segment(
                    value=key,
                    label=ft.Column(
                        [
                            ft.Text(label, size=12, weight=ft.FontWeight.W_600, color="#DDE8FF"),
                            ft.Text("0", size=11, weight=ft.FontWeight.W_600, color=_FILTER_ACCENT.get(key, "#C7D2FE")),
                            ft.Text("0 B", size=10, color="#9FB0D0"),
                        ],
                        spacing=1,
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        tight=True,
                    ),
                )
                for key, label in _FILTER_TABS
            ],
        )

        self._group_list = ft.ListView(expand=True, spacing=t.spacing.sm, padding=t.spacing.lg)
        self._results_grid = ft.ListView(expand=True, spacing=t.spacing.md, padding=t.spacing.lg)

        self._empty = ft.Container(
            content=ft.Column(
                [
                    ft.Container(
                        content=ft.Icon(ft.icons.Icons.MANAGE_SEARCH, size=48, color="#22D3EE"),
                        bgcolor=ft.Colors.with_opacity(0.08, "#22D3EE"),
                        border_radius=16,
                        padding=20,
                    ),
                    ft.Text("No duplicates found yet", size=t.typography.size_lg, weight=ft.FontWeight.W_600, color=t.colors.fg),
                    ft.Text(
                        "Head to Home and run a scan to see results here.",
                        size=t.typography.size_base,
                        color=t.colors.fg_muted,
                        text_align=ft.TextAlign.CENTER,
                    ),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=t.spacing.lg,
            ),
            expand=True,
            alignment=ft.Alignment(0, 0),
            **self._get_glass_style(0.04),
        )
        self._loading_state = ft.Container(
            content=ft.Column(
                [self._build_skeleton_card() for _ in range(5)],
                spacing=t.spacing.sm,
            ),
            expand=True,
            padding=t.spacing.lg,
        )

        self._sticky_bar = ft.Container(
            content=ft.Row(
                [
                    ft.Column(
                        [self._selection_label],
                        expand=True,
                        alignment=ft.MainAxisAlignment.CENTER,
                        spacing=0,
                    ),
                    self._delete_btn,
                    self._permanent_btn,
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=t.spacing.md,
            ),
            padding=ft.padding.symmetric(horizontal=t.spacing.xl, vertical=t.spacing.md),
            bgcolor=ft.Colors.with_opacity(0.97, "#0D0505"),
            border=ft.border.only(top=ft.BorderSide(2, "#EF4444")),
            visible=False,
            shadow=ft.BoxShadow(
                blur_radius=20,
                offset=ft.Offset(0, -4),
                color=ft.Colors.with_opacity(0.45, "#EF4444"),
            ),
        )
        self._sticky_overlay = ft.Column(
            [ft.Container(expand=True), self._sticky_bar],
            expand=True,
            spacing=0,
        )

        self._scroll_col.controls = [
            ft.Container(
                content=self._header,
                padding=ft.padding.only(left=t.spacing.lg, right=t.spacing.lg, top=t.spacing.md),
                **self._get_glass_style(0.04),
            ),
            ft.Container(
                content=self._smart_row,
                padding=ft.padding.only(left=t.spacing.lg, top=t.spacing.xs),
            ),
            ft.Container(
                content=self._filter_seg,
                padding=ft.padding.only(left=t.spacing.lg, bottom=t.spacing.sm),
                **self._get_glass_style(0.03),
            ),
            self._empty,
        ]
        self.controls = [self._scroll_col, self._sticky_overlay]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def load_results(self, groups: List[DuplicateGroup], mode: str = "files") -> None:
        self._groups = list(groups)
        self._scan_mode = mode or "files"
        self._selected_paths.clear()
        self._recompute_filter_counts()
        self._loading = True
        self._refresh()
        page = self._bridge.flet_page
        if hasattr(page, "run_task"):
            page.run_task(self._finish_loading_async)
        else:
            self._loading = False
            self._refresh()

    def get_groups(self) -> List[DuplicateGroup]:
        return list(self._groups)

    def on_show(self) -> None:
        self._refresh()

    def _is_mounted(self) -> bool:
        try:
            return self.page is not None
        except RuntimeError:
            return False

    @staticmethod
    def _safe_update(ctrl: ft.Control | None) -> None:
        """Call ``update()`` only when *ctrl* is on the page (avoids errors on freshly appended children)."""
        if ctrl is None:
            return
        try:
            if ctrl.page is not None:
                ctrl.update()
        except RuntimeError:
            pass

    # ------------------------------------------------------------------
    # Selection and smart select
    # ------------------------------------------------------------------
    def _toggle_file(self, path: str) -> None:
        if path in self._selected_paths:
            self._selected_paths.discard(path)
        else:
            self._selected_paths.add(path)
        self._update_selection_ui()

    def _on_file_checkbox(self, e: ft.ControlEvent, path: str) -> None:
        checked = bool(getattr(e.control, "value", False))
        if checked:
            self._selected_paths.add(path)
        else:
            self._selected_paths.discard(path)
        self._update_selection_ui()

    def _on_smart_seg_change(self, e: ft.ControlEvent) -> None:
        sel = getattr(e.control, "selected", None) or {"keep_largest"}
        self._smart_rule = next(iter(sel), "keep_largest")
        self._apply_smart_select()

    def _apply_smart_select(self, e=None) -> None:
        self._selected_paths.clear()
        for g in self._filtered_groups():
            if len(g.files) < 2:
                continue
            # Determine the file to keep based on rule
            if self._smart_rule == "keep_largest":
                keep = max(g.files, key=lambda f: f.size)
            elif self._smart_rule == "keep_smallest":
                keep = min(g.files, key=lambda f: f.size)
            elif self._smart_rule == "keep_newest":
                keep = max(g.files, key=lambda f: getattr(f, "mtime", 0) or 0)
            elif self._smart_rule == "keep_oldest":
                keep = min(g.files, key=lambda f: getattr(f, "mtime", 0) or 0)
            else:
                keep = max(g.files, key=lambda f: f.size)  # fallback
            for f in g.files:
                if f is not keep:
                    self._selected_paths.add(str(f.path))
        self._refresh()

    def _update_selection_ui(self) -> None:
        count = len(self._selected_paths)
        has_selection = count > 0
        has_groups = len(self._groups) > 0
        self._smart_row.visible = has_groups
        ResultsPage._safe_update(self._smart_row)
        self._delete_btn.visible = has_selection
        self._permanent_btn.visible = has_selection
        if has_selection:
            total_bytes = 0
            selected_set = self._selected_paths
            for g in self._groups:
                for f in g.files:
                    if str(f.path) in selected_set:
                        total_bytes += f.size
            self._selection_label.value = f"{count:,} files selected · {fmt_size(total_bytes)} to be freed"
        else:
            self._selection_label.value = ""
        self._sticky_bar.visible = has_selection
        ResultsPage._safe_update(self._sticky_bar)

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------
    def _on_delete_clicked(self, e) -> None:
        self._show_delete_dialog(DeletionPolicy.TRASH)

    def _on_permanent_delete_clicked(self, e) -> None:
        self._show_delete_dialog(DeletionPolicy.PERMANENT)

    def _show_delete_dialog(self, policy: DeletionPolicy) -> None:
        count = len(self._selected_paths)
        if count == 0:
            return
        policy_label = "permanently delete" if policy == DeletionPolicy.PERMANENT else "move to trash"
        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Confirm Deletion"),
            content=ft.Text(f"Are you sure you want to {policy_label} {count:,} files?\nThis will keep one copy of each duplicate."),
            actions=[
                ft.TextButton("Cancel", on_click=lambda e: self._bridge.dismiss_top_dialog()),
                ft.ElevatedButton(
                    policy_label.title(),
                    on_click=lambda e: self._execute_delete_and_close(dialog, policy),
                    style=ft.ButtonStyle(bgcolor=self._t.colors.danger, color=self._t.colors.bg),
                ),
            ],
        )
        self._bridge.show_modal_dialog(dialog)

    def _execute_delete_and_close(self, dialog, policy):
        self._bridge.dismiss_top_dialog()
        self._execute_delete(policy)

    def _execute_delete(self, policy: DeletionPolicy) -> None:
        from cerebro.v2.ui.flet_app.services.delete_service import DeleteService
        paths = list(self._selected_paths)
        service = DeleteService()
        new_groups, deleted, failed, bytes_reclaimed = service.delete_and_prune(paths, self._groups, policy)
        self._selected_paths.clear()
        self._groups = new_groups
        self._bridge.coordinator.results_files_removed(paths)
        self._refresh()
        if deleted > 0:
            if policy == DeletionPolicy.TRASH:
                self._bridge.show_snackbar(
                    f"Moved {deleted:,} files to Trash ({fmt_size(bytes_reclaimed)} reclaimed).",
                    success=True,
                    action_label="Undo",
                    on_action=lambda _e: self._undo_last_trash_delete(),
                )
            else:
                self._bridge.show_snackbar(
                    f"Permanently deleted {deleted:,} files ({fmt_size(bytes_reclaimed)} reclaimed).",
                    success=True,
                )
        if failed > 0:
            self._bridge.show_snackbar(
                f"{failed:,} files could not be deleted.",
                error=True,
            )

    def _undo_last_trash_delete(self) -> None:
        from cerebro.v2.ui.flet_app.services.delete_service import DeleteService

        ok, restored = DeleteService.undo_last_trash_delete()
        if ok and restored > 0:
            self._bridge.show_snackbar(f"Restored {restored:,} file(s) from Trash.", success=True)
        elif restored > 0:
            self._bridge.show_snackbar(
                f"Partially restored {restored:,} file(s). Check missing paths.",
                info=True,
            )
        else:
            self._bridge.show_snackbar("Nothing to undo.", info=True)

    # ------------------------------------------------------------------
    # Filtering
    # ------------------------------------------------------------------
    def _on_filter_seg_change(self, e: ft.ControlEvent) -> None:
        sel = getattr(e.control, "selected", None) or {"all"}
        self._filter_key = next(iter(sel), "all")
        self._refresh()

    def _filtered_groups(self) -> List[DuplicateGroup]:
        if self._filter_key == "all":
            return self._groups
        exts = FILTER_EXTS.get(self._filter_key)
        if exts is None:
            return [g for g in self._groups if all(classify_file(getattr(f, "extension", "")) == "other" for f in g.files)]
        return [g for g in self._groups if any(getattr(f, "extension", "").lower() in exts for f in g.files)]

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------
    def _refresh(self) -> None:
        filtered = self._filtered_groups()
        t = self._t
        total_files = sum(len(g.files) for g in filtered)
        recoverable = sum(g.reclaimable for g in filtered)
        self._summary.value = f"{len(filtered):,} groups · {total_files:,} files · {fmt_size(recoverable)} recoverable"
        self._safe_update(self._summary)
        self._update_selection_ui()
        self._refresh_filter_labels()
        sc = self._scroll_col.controls
        if self._loading:
            if self._empty in sc:
                sc.remove(self._empty)
            if self._group_list in sc:
                sc.remove(self._group_list)
            if self._loading_state not in sc:
                sc.append(self._loading_state)
            self._safe_update(self._scroll_col)
            return
        if self._loading_state in sc:
            sc.remove(self._loading_state)

        if not filtered:
            if self._empty not in sc:
                sc.append(self._empty)
            if self._group_list in sc:
                sc.remove(self._group_list)
            if self._results_grid in sc:
                sc.remove(self._results_grid)
            self._safe_update(self._scroll_col)
            return

        if self._empty in sc:
            sc.remove(self._empty)

        if self._view_mode == "grid":
            if self._group_list in sc:
                sc.remove(self._group_list)
            if self._results_grid not in sc:
                sc.append(self._results_grid)
            self._thumb_slots.clear()
            self._tile_cache_grid.clear()
            self._results_grid.controls = [
                self._build_group_grid_section(g, i) for i, g in enumerate(filtered)
            ]
            self._loading = False
            self._safe_update(self._scroll_col)
            page = self._bridge.flet_page
            if self._thumb_slots and hasattr(page, "run_task"):
                page.run_task(self._load_grid_thumbnails_async, dict(self._thumb_slots))
            return

        if self._results_grid in sc:
            sc.remove(self._results_grid)
        if self._group_list not in sc:
            sc.append(self._group_list)

        n = len(filtered)
        if n <= _LIST_BUILD_ASYNC_THRESHOLD:
            self._group_list.controls = [self._build_group_card(g) for g in filtered]
            self._loading = False
            self._safe_update(self._scroll_col)
            if n > 80:
                try:
                    self._bridge.flet_page.update()
                except Exception:
                    pass
            return

        self._list_build_generation += 1
        gen = self._list_build_generation
        head_n = min(_LIST_FIRST_SYNC_GROUPS, n)
        head = filtered[:head_n]
        tail = filtered[head_n:]
        self._group_list.controls = [self._build_group_card(g) for g in head]
        self._safe_update(self._scroll_col)
        try:
            self._bridge.flet_page.update()
        except Exception:
            pass
        if tail:
            page = self._bridge.flet_page
            if hasattr(page, "run_task"):
                page.run_task(self._append_group_cards_async, tail, gen)
            else:
                self._group_list.controls.extend([self._build_group_card(g) for g in tail])
                self._safe_update(self._scroll_col)
                try:
                    page.update()
                except Exception:
                    pass

    async def _append_group_cards_async(self, tail: List[DuplicateGroup], gen: int) -> None:
        for i in range(0, len(tail), _LIST_ASYNC_BATCH):
            if gen != self._list_build_generation:
                return
            chunk = tail[i : i + _LIST_ASYNC_BATCH]
            self._group_list.controls.extend([self._build_group_card(g) for g in chunk])
            self._safe_update(self._scroll_col)
            try:
                self._bridge.flet_page.update()
            except Exception:
                pass
            await asyncio.sleep(0)
        if gen == self._list_build_generation:
            self._loading = False
            self._refresh()

    async def _finish_loading_async(self) -> None:
        await asyncio.sleep(0)
        self._loading = False
        self._refresh()

    def _build_skeleton_card(self) -> ft.Container:
        t = self._t
        bar = lambda w: ft.Container(
            width=w,
            height=10,
            bgcolor=ft.Colors.with_opacity(0.10, ft.Colors.WHITE),
            border_radius=4,
        )
        return ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Container(
                                width=30,
                                height=30,
                                bgcolor=ft.Colors.with_opacity(0.10, ft.Colors.WHITE),
                                border_radius=8,
                            ),
                            ft.Column([bar(220), bar(160)], spacing=8, expand=True),
                            bar(80),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    )
                ],
                spacing=t.spacing.xs,
            ),
            padding=t.spacing.md,
            **self._get_glass_style(0.04),
        )

    def _build_group_card(self, group: DuplicateGroup) -> ft.Container:
        t = self._t
        sample = group.files[0].path if group.files else ""
        sample_path = Path(str(sample))
        name = sample_path.name if sample else "Group"
        parent = str(sample_path.parent) if sample else ""
        ext = sample_path.suffix if sample else ""
        icon_name, accent = self._file_type_icon(ext)

        # Build heavy duplicate rows lazily on first expand to avoid long filter/render stalls.
        file_checks = ft.Column([], spacing=2, visible=False)
        details_built = {"value": False}

        def _toggle_expand(e):
            if not details_built["value"]:
                file_checks.controls = [
                    ft.Container(
                        content=ft.Row(
                            [
                                ft.Checkbox(
                                    label=str(Path(str(f.path)).name),
                                    value=str(f.path) in self._selected_paths,
                                    on_change=lambda e, p=str(f.path): self._on_file_checkbox(e, p),
                                    label_style=ft.TextStyle(
                                        size=t.typography.size_base,
                                        color=t.colors.fg,
                                        weight=ft.FontWeight.W_500,
                                    ),
                                ),
                                ft.Text(
                                    fmt_size(f.size),
                                    size=t.typography.size_sm,
                                    color=t.colors.fg2,
                                    weight=ft.FontWeight.W_500,
                                ),
                            ],
                            spacing=t.spacing.sm,
                        ),
                        padding=ft.padding.only(left=t.spacing.xl, top=2, bottom=2),
                        border=ft.border.only(left=ft.BorderSide(2, ft.Colors.with_opacity(0.3, accent))),
                    )
                    for f in group.files
                ]
                details_built["value"] = True
            file_checks.visible = not file_checks.visible
            ResultsPage._safe_update(file_checks)
            expand_btn.text = "Collapse" if file_checks.visible else "Expand"
            ResultsPage._safe_update(expand_btn)
            self._safe_update(self._scroll_col)

        expand_btn = ft.TextButton(
            "Expand",
            on_click=_toggle_expand,
            style=ft.ButtonStyle(
                color=t.colors.fg2,
                text_style=ft.TextStyle(size=t.typography.size_sm, weight=ft.FontWeight.W_600),
            ),
        )

        return ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Container(
                                content=ft.Icon(icon_name, size=18, color=accent),
                                bgcolor=ft.Colors.with_opacity(0.12, accent),
                                border_radius=8,
                                padding=8,
                            ),
                            ft.Column(
                                [
                                    ft.Text(name, weight=ft.FontWeight.W_600, color=t.colors.fg, size=t.typography.size_md, no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS),
                                    ft.Row(
                                        [
                                            ft.Text(
                                                f"{len(group.files)} files",
                                                size=t.typography.size_sm,
                                                color="#7DD3FC",
                                                weight=ft.FontWeight.W_500,
                                            ),
                                            ft.Text("·", size=t.typography.size_sm, color=t.colors.fg_muted),
                                            ft.Text(
                                                fmt_size(group.total_size),
                                                size=t.typography.size_sm,
                                                color="#A78BFA",
                                                weight=ft.FontWeight.W_500,
                                            ),
                                            ft.Text("·", size=t.typography.size_sm, color=t.colors.fg_muted),
                                            ft.Text(
                                                parent,
                                                size=t.typography.size_sm,
                                                color="#93C5FD",
                                                no_wrap=True,
                                                overflow=ft.TextOverflow.ELLIPSIS,
                                                expand=True,
                                            ),
                                        ],
                                        spacing=4,
                                    ),
                                ],
                                spacing=3,
                                expand=True,
                            ),
                            ft.Text(fmt_size(group.reclaimable), weight=ft.FontWeight.BOLD, color="#22D3EE", size=t.typography.size_md),
                            expand_btn,
                            ft.IconButton(
                                icon=ft.icons.Icons.VISIBILITY,
                                tooltip="Review group",
                                icon_color=t.colors.fg2,
                                on_click=lambda e, g=group: self._open_group(g),
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    file_checks,
                ],
                spacing=t.spacing.xs,
            ),
            padding=t.spacing.md,
            ink=True,
            **self._get_glass_style(0.06),
        )

    # ------------------------------------------------------------------
    # View toggle
    # ------------------------------------------------------------------
    def _toggle_view(self, mode: str) -> None:
        if self._view_mode == mode:
            return
        self._view_mode = mode
        self._grid_btn.icon_color = "#22D3EE" if mode == "grid" else self._t.colors.fg_muted
        self._list_btn.icon_color = "#22D3EE" if mode == "list" else self._t.colors.fg_muted
        ResultsPage._safe_update(self._grid_btn)
        ResultsPage._safe_update(self._list_btn)
        self._refresh()

    def _build_file_tile(self, f) -> ft.Container:
        """Build a 120x120 thumbnail tile with checkbox and size overlay."""
        t = self._t
        key = str(getattr(f, "path", ""))
        p = Path(key)

        cb = ft.Checkbox(
            value=key in self._selected_paths,
            on_change=lambda e, path=key: self._on_file_checkbox(e, path),
            active_color="#2563EB",
        )

        size_bar = ft.Container(
            content=ft.Text(
                fmt_size(f.size),
                size=9,
                color="#FFFFFF",
                text_align=ft.TextAlign.CENTER,
            ),
            bgcolor=ft.Colors.with_opacity(0.72, "#0A0E14"),
            padding=ft.padding.symmetric(horizontal=4, vertical=3),
            alignment=ft.alignment.center,
        )

        placeholder = ft.Container(
            content=ft.Icon(
                ft.icons.Icons.INSERT_DRIVE_FILE,
                size=36,
                color=ft.Colors.with_opacity(0.3, ft.Colors.WHITE),
            ),
            expand=True,
            alignment=ft.Alignment(0, 0),
            bgcolor=ft.Colors.with_opacity(0.06, ft.Colors.WHITE),
        )
        thumb_slot = ft.Container(
            content=placeholder,
            expand=True,
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
        )
        self._thumb_slots[key] = thumb_slot

        stack = ft.Stack(
            [
                thumb_slot,
                ft.Column([ft.Container(expand=True), size_bar], expand=True, spacing=0),
                ft.Container(content=cb, padding=ft.padding.only(left=2, top=2)),
            ],
            expand=True,
        )

        is_sel = key in self._selected_paths
        tile = ft.Container(
            content=stack,
            width=120,
            height=120,
            border_radius=8,
            border=ft.border.all(
                2 if is_sel else 1,
                "#2563EB" if is_sel else ft.Colors.with_opacity(0.15, ft.Colors.WHITE),
            ),
            bgcolor=ft.Colors.with_opacity(0.06, ft.Colors.WHITE),
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
            tooltip=p.name,
        )
        self._tile_cache_grid[key] = tile
        return tile

    def _build_group_grid_section(self, group, idx: int) -> ft.Container:
        """Build a group card with thumbnail tiles for grid view."""
        t = self._t
        tiles = [self._build_file_tile(f) for f in group.files]
        header = ft.Row(
            [
                ft.Container(
                    content=ft.Text(
                        f"Group {idx + 1}",
                        size=t.typography.size_sm,
                        weight=ft.FontWeight.W_700,
                        color=t.colors.fg,
                    ),
                    bgcolor=ft.Colors.with_opacity(0.08, ft.Colors.WHITE),
                    border_radius=4,
                    padding=ft.padding.symmetric(horizontal=8, vertical=2),
                ),
                ft.Text(
                    f"{len(group.files)} files · {fmt_size(group.reclaimable)} reclaimable",
                    size=t.typography.size_sm,
                    color=t.colors.fg_muted,
                ),
            ],
            spacing=t.spacing.sm,
        )
        return ft.Container(
            content=ft.Column(
                [header, ft.Row(tiles, spacing=t.spacing.sm, wrap=True)],
                spacing=t.spacing.sm,
            ),
            padding=t.spacing.md,
            **self._get_glass_style(0.05),
        )

    async def _load_grid_thumbnails_async(self, slots: Dict[str, ft.Container]) -> None:
        import asyncio as _aio
        loop = _aio.get_event_loop()
        for i, (key, slot) in enumerate(slots.items()):
            p = Path(key)
            if not is_image_path(p):
                continue
            try:
                b64 = await loop.run_in_executor(
                    None,
                    lambda fp=p: get_thumbnail_cache().get_base64(fp),
                )
            except Exception:
                continue
            if not b64:
                continue
            slot.content = ft.Image(
                src=f"data:image/jpeg;base64,{b64}",
                width=120,
                height=120,
                fit=ft.BoxFit.COVER,
                border_radius=6,
            )
            ResultsPage._safe_update(slot)
            if i % 8 == 0:
                await _aio.sleep(0)

    def _recompute_filter_counts(self) -> None:
        counts: Dict[str, int] = {k: 0 for k, _ in _FILTER_TABS}
        group_counts: Dict[str, int] = {k: 0 for k, _ in _FILTER_TABS}
        sizes: Dict[str, int] = {k: 0 for k, _ in _FILTER_TABS}
        for g in self._groups:
            files = list(g.files)
            counts["all"] += len(files)
            group_counts["all"] += 1
            seen_group_kinds: set[str] = set()
            for f in files:
                key = classify_file(getattr(f, "extension", ""))
                bucket = key if key in counts else "other"
                counts[bucket] += 1
                sizes["all"] += f.size
                sizes[bucket] += f.size
                seen_group_kinds.add(key if key in group_counts else "other")
            for kind in seen_group_kinds:
                group_counts[kind] += 1
        self._filter_counts = counts
        self._filter_sizes = sizes
        self._filter_group_counts = group_counts

    def _refresh_filter_labels(self) -> None:
        selected = set(self._filter_seg.selected or [])
        for seg in self._filter_seg.segments:
            key = seg.value
            base = next((label for k, label in _FILTER_TABS if k == key), key.title())
            files_n = self._filter_counts.get(key, 0)
            size_n = self._filter_sizes.get(key, 0)
            col = seg.label
            if isinstance(col, ft.Column) and len(col.controls) >= 3:
                is_active = key in selected
                accent = _FILTER_ACCENT.get(key, "#C7D2FE")
                col.controls[0].value = base
                col.controls[0].color = "#FFFFFF" if is_active else "#DDE8FF"
                col.controls[0].weight = ft.FontWeight.W_700 if is_active else ft.FontWeight.W_600
                col.controls[1].value = f"{files_n:,}"
                col.controls[1].color = accent if is_active else ft.Colors.with_opacity(0.85, accent)
                col.controls[1].weight = ft.FontWeight.W_700 if is_active else ft.FontWeight.W_600
                col.controls[2].value = fmt_size(size_n)
                col.controls[2].color = "#B7C6E6" if is_active else "#9FB0D0"

    def _open_group(self, group: DuplicateGroup) -> None:
        self._bridge.coordinator.review_open_group(group.group_id, self._groups)
        self._bridge.navigate("review")

    def apply_theme(self, mode: str) -> None:
        """Updates theme properties without destroying UI controls."""
        self._glass_cache = {}
        self._t = theme_for_mode(mode)

        # Update colors on static elements
        self._summary.color = self._t.colors.fg2

        # Update container glass styles (parent exists only when this page is mounted)
        hdr_parent = getattr(self._header, "parent", None)
        if hdr_parent is not None:
            hdr_parent.bgcolor = self._get_glass_style(0.04).get("bgcolor")
            hdr_parent.border = self._get_glass_style(0.04).get("border")
        filt_parent = getattr(self._filter_seg, "parent", None)
        if filt_parent is not None:
            filt_parent.bgcolor = self._get_glass_style(0.03).get("bgcolor")
            filt_parent.border = self._get_glass_style(0.03).get("border")

        self._empty.bgcolor = self._get_glass_style(0.04).get("bgcolor")
        self._empty.border = self._get_glass_style(0.04).get("border")

        self._safe_update(self)