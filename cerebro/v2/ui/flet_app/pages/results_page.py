"""Results page — displays duplicate groups with filtering, selection, and delete actions."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, List, Optional, Set

import flet as ft

from cerebro.core.deletion import DeletionPolicy
from cerebro.engines.base_engine import DuplicateGroup
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


class ResultsPage(ft.Column):
    """Duplicate group listing with type filters, selection, and delete."""

    def __init__(self, bridge: "StateBridge"):
        super().__init__(expand=True, scroll=ft.ScrollMode.AUTO)
        self._bridge = bridge
        self._t = theme_for_mode("light")
        self._groups: List[DuplicateGroup] = []
        self._filter_key = "all"
        self._scan_mode = "files"
        self._selected_paths: Set[str] = set()
        self._build()

    def _build(self) -> None:
        t = self._t

        self._summary = ft.Text(
            "", size=t.typography.size_base, color=t.colors.fg2,
        )

        # Action bar (appears when files are selected)
        self._selection_label = ft.Text("", size=t.typography.size_sm, color=t.colors.fg2)
        self._delete_btn = ft.ElevatedButton(
            "Move to Trash",
            icon=ft.icons.Icons.DELETE_OUTLINE,
            on_click=self._on_delete_clicked,
            style=ft.ButtonStyle(bgcolor=t.colors.danger, color=t.colors.bg),
            visible=False,
        )
        self._permanent_btn = ft.OutlinedButton(
            "Delete Permanently",
            icon=ft.icons.Icons.DELETE_FOREVER,
            on_click=self._on_permanent_delete_clicked,
            style=ft.ButtonStyle(color=t.colors.danger),
            visible=False,
        )
        self._select_all_btn = ft.TextButton(
            "Select All (keep largest)", on_click=self._select_all_except_largest,
        )

        self._header = ft.Row(
            [
                ft.Text("Scan Results", size=t.typography.size_xl, weight=ft.FontWeight.BOLD, color=t.colors.fg),
                self._summary,
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        )

        self._action_bar = ft.Row(
            [self._selection_label, self._select_all_btn, self._delete_btn, self._permanent_btn],
            alignment=ft.MainAxisAlignment.START,
            spacing=t.spacing.md,
            visible=False,
        )

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

        self._group_list = ft.ListView(expand=True, spacing=t.spacing.sm, padding=t.spacing.lg)

        self._empty = ft.Container(
            content=ft.Column(
                [
                    ft.Icon(ft.icons.Icons.SEARCH_OFF, size=64, color=t.colors.fg_muted),
                    ft.Text("No results yet", size=t.typography.size_lg, color=t.colors.fg2),
                    ft.Text(
                        "Run a scan from the Home page to find duplicates.",
                        size=t.typography.size_base, color=t.colors.fg_muted,
                        text_align=ft.TextAlign.CENTER,
                    ),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=t.spacing.md,
            ),
            expand=True, alignment=ft.Alignment(0.5, 0.5),
        )

        self.controls = [
            ft.Container(content=self._header, padding=ft.padding.only(left=t.spacing.lg, right=t.spacing.lg, top=t.spacing.md)),
            ft.Container(content=self._action_bar, padding=ft.padding.only(left=t.spacing.lg)),
            ft.Container(content=self._filter_bar, padding=ft.padding.only(left=t.spacing.lg, bottom=t.spacing.sm)),
            self._empty,
        ]

    # -- Public API -----------------------------------------------------------

    def load_results(self, groups: List[DuplicateGroup], mode: str = "files") -> None:
        self._groups = list(groups)
        self._scan_mode = mode or "files"
        self._selected_paths.clear()
        self._refresh()

    def get_groups(self) -> List[DuplicateGroup]:
        return list(self._groups)

    # -- Selection ------------------------------------------------------------

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

    def _select_all_except_largest(self, e=None) -> None:
        self._selected_paths.clear()
        for g in self._filtered_groups():
            if len(g.files) < 2:
                continue
            largest = max(g.files, key=lambda f: f.size)
            for f in g.files:
                if f is not largest:
                    self._selected_paths.add(str(f.path))
        self._update_selection_ui()
        self._refresh()

    def _update_selection_ui(self) -> None:
        count = len(self._selected_paths)
        has_selection = count > 0
        self._action_bar.visible = has_selection or len(self._groups) > 0
        self._select_all_btn.visible = len(self._groups) > 0
        self._delete_btn.visible = has_selection
        self._permanent_btn.visible = has_selection

        if has_selection:
            total_bytes = 0
            for g in self._groups:
                for f in g.files:
                    if str(f.path) in self._selected_paths:
                        total_bytes += f.size
            self._selection_label.value = f"{count:,} files selected  ·  {fmt_size(total_bytes)}"
        else:
            self._selection_label.value = ""
        self._action_bar.update()

    # -- Delete ---------------------------------------------------------------

    def _on_delete_clicked(self, e) -> None:
        self._show_delete_dialog(DeletionPolicy.TRASH)

    def _on_permanent_delete_clicked(self, e) -> None:
        self._show_delete_dialog(DeletionPolicy.PERMANENT)

    def _show_delete_dialog(self, policy: DeletionPolicy) -> None:
        count = len(self._selected_paths)
        if count == 0:
            return
        policy_label = "permanently delete" if policy == DeletionPolicy.PERMANENT else "move to trash"

        def _confirm(e) -> None:
            self._bridge.flet_page.close(dialog)
            self._execute_delete(policy)

        def _cancel(e) -> None:
            self._bridge.flet_page.close(dialog)

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Confirm Deletion"),
            content=ft.Text(
                f"Are you sure you want to {policy_label} {count:,} files?\n"
                f"This will keep one copy of each duplicate."
            ),
            actions=[
                ft.TextButton("Cancel", on_click=_cancel),
                ft.ElevatedButton(
                    policy_label.title(),
                    on_click=_confirm,
                    style=ft.ButtonStyle(
                        bgcolor=self._t.colors.danger,
                        color=self._t.colors.bg,
                    ),
                ),
            ],
        )
        self._bridge.flet_page.open(dialog)

    def _execute_delete(self, policy: DeletionPolicy) -> None:
        from cerebro.v2.ui.flet_app.services.delete_service import DeleteService
        paths = list(self._selected_paths)
        service = DeleteService()
        new_groups, deleted, failed, bytes_reclaimed = service.delete_and_prune(
            paths, self._groups, policy,
        )
        self._selected_paths.clear()
        self._groups = new_groups
        self._bridge.coordinator.results_files_removed(paths)
        self._refresh()

    # -- Filtering ------------------------------------------------------------

    def _set_filter(self, key: str) -> None:
        self._filter_key = key
        for btn in self._filter_bar.controls:
            is_active = btn.data == key
            btn.style = ft.ButtonStyle(
                bgcolor=self._t.colors.primary if is_active else self._t.colors.bg3,
                color=self._t.colors.bg if is_active else self._t.colors.fg2,
            )
            btn.update()
        self._refresh()

    def _filtered_groups(self) -> List[DuplicateGroup]:
        if self._filter_key == "all":
            return self._groups
        exts = FILTER_EXTS.get(self._filter_key)
        if exts is None:
            return [
                g for g in self._groups
                if all(classify_file(getattr(f, "extension", "")) == "other" for f in g.files)
            ]
        return [
            g for g in self._groups
            if any(getattr(f, "extension", "").lower() in exts for f in g.files)
        ]

    # -- Rendering ------------------------------------------------------------

    def _refresh(self) -> None:
        filtered = self._filtered_groups()
        t = self._t

        total_files = sum(len(g.files) for g in filtered)
        recoverable = sum(g.reclaimable for g in filtered)
        self._summary.value = f"{len(filtered):,} groups  ·  {total_files:,} files  ·  {fmt_size(recoverable)} recoverable"
        self._summary.update()
        self._update_selection_ui()

        if not filtered:
            if self._empty not in self.controls:
                self.controls.append(self._empty)
            if self._group_list in self.controls:
                self.controls.remove(self._group_list)
            self._empty.update()
            self.update()
            return

        if self._empty in self.controls:
            self.controls.remove(self._empty)
        if self._group_list not in self.controls:
            self.controls.append(self._group_list)

        self._group_list.controls = [self._build_group_card(g) for g in filtered]
        self._group_list.update()
        self.update()

    def _build_group_card(self, group: DuplicateGroup) -> ft.Container:
        t = self._t
        paths = [str(f.path) for f in group.files]
        sample = paths[0] if paths else ""
        folder = str(Path(sample).parent) if sample else ""
        name = Path(sample).name if sample else "Group"

        # File checkboxes for this group
        file_checks = ft.Column(
            [
                ft.Row(
                    [
                        ft.Checkbox(
                            label=str(Path(str(f.path)).name),
                            value=str(f.path) in self._selected_paths,
                            on_change=lambda e, p=str(f.path): self._on_file_checkbox(e, p),
                            label_style=ft.TextStyle(size=t.typography.size_sm, color=t.colors.fg2),
                        ),
                        ft.Text(fmt_size(f.size), size=t.typography.size_xs, color=t.colors.fg_muted),
                    ],
                    spacing=t.spacing.sm,
                )
                for f in group.files
            ],
            spacing=0,
            visible=False,
        )

        def _toggle_expand(e) -> None:
            file_checks.visible = not file_checks.visible
            file_checks.update()
            expand_btn.text = "Collapse" if file_checks.visible else "Expand"
            expand_btn.update()

        expand_btn = ft.TextButton("Expand", on_click=_toggle_expand)

        return ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Icon(ft.icons.Icons.CONTENT_COPY, color=t.colors.primary),
                            ft.Column(
                                [
                                    ft.Text(name, weight=ft.FontWeight.W_600, color=t.colors.fg, size=t.typography.size_md),
                                    ft.Text(
                                        f"{len(group.files)} files  ·  {fmt_size(group.total_size)}  ·  {folder}",
                                        color=t.colors.fg2, size=t.typography.size_sm,
                                    ),
                                ],
                                spacing=2, expand=True,
                            ),
                            ft.Text(fmt_size(group.reclaimable), weight=ft.FontWeight.BOLD, color=t.colors.primary, size=t.typography.size_md),
                            expand_btn,
                            ft.IconButton(
                                icon=ft.icons.Icons.VISIBILITY,
                                tooltip="Review group",
                                on_click=lambda e, g=group: self._open_group(g),
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    file_checks,
                ],
                spacing=t.spacing.xs,
            ),
            padding=t.spacing.md,
            border=ft.border.all(1, t.colors.border),
            border_radius=t.border_radius,
            bgcolor=t.colors.bg,
        )

    def _open_group(self, group: DuplicateGroup) -> None:
        from cerebro.v2.ui.flet_app.layout import AppLayout
        self._bridge.coordinator.review_open_group(group.group_id, self._groups)
        fp = self._bridge.flet_page
        layout = fp.controls[0] if fp.controls else None
        if isinstance(layout, AppLayout):
            layout.navigate_to("review")
