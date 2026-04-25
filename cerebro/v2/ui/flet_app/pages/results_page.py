"""Results page — displays duplicate groups with filtering, smart selection, and delete actions."""

from __future__ import annotations

import asyncio
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


class ResultsPage(ft.Column):
    """Duplicate group listing with type filters, smart selection, and delete."""

    def __init__(self, bridge: "StateBridge"):
        super().__init__(expand=True, scroll=ft.ScrollMode.AUTO)
        self._bridge = bridge
        self._t = theme_for_mode("light")
        self._groups: List[DuplicateGroup] = []
        self._filter_key = "all"
        self._scan_mode = "files"
        self._selected_paths: Set[str] = set()
        self._smart_rule = "keep_largest"
        self._list_build_generation = 0

        # UI References
        self._summary: ft.Text
        self._smart_dropdown: ft.Dropdown
        self._apply_smart_btn: ft.ElevatedButton
        self._smart_row: ft.Row
        self._selection_label: ft.Text
        self._delete_btn: ft.ElevatedButton
        self._permanent_btn: ft.OutlinedButton
        self._action_bar: ft.Row
        self._header: ft.Row
        self._filter_bar: ft.Row
        self._group_list: ft.ListView
        self._empty: ft.Container

        self._build_ui()

    # ------------------------------------------------------------------
    # Glass helper
    # ------------------------------------------------------------------
    def _get_glass_style(self, opacity: float = 0.06) -> dict:
        is_light = "light" in self._bridge.app_theme.lower() if hasattr(self._bridge, 'app_theme') else False
        bg = ft.Colors.with_opacity(opacity, ft.Colors.WHITE if not is_light else ft.Colors.BLACK)
        border_color = ft.Colors.with_opacity(0.12, ft.Colors.WHITE if not is_light else ft.Colors.BLACK)
        return dict(
            bgcolor=bg,
            border=ft.border.all(1, border_color),
            border_radius=ft.border_radius.all(12),
            blur=ft.Blur(8, 8),
        )
    
    def _get_filter_btn_style(self, is_active: bool) -> ft.ButtonStyle:
        return ft.ButtonStyle(
            bgcolor=self._t.colors.primary if is_active else self._t.colors.bg3,
            color=self._t.colors.bg if is_active else self._t.colors.fg2,
            shape=ft.RoundedRectangleBorder(radius=8),
        )

    # ------------------------------------------------------------------
    # Build (Runs Once)
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        t = self._t

        self._summary = ft.Text("", size=t.typography.size_base, color=t.colors.fg2)

        # Smart select row
        self._smart_dropdown = ft.Dropdown(
            options=[ft.dropdown.Option(key=val, text=label) for val, label in _SMART_SELECT_OPTIONS],
            value=self._smart_rule,
            width=160,
            label="Smart Select",
            text_size=12,
            border_radius=8,
            bgcolor=ft.Colors.with_opacity(0.08, t.colors.primary),
            on_select=self._on_smart_rule_changed,
        )
        self._apply_smart_btn = ft.ElevatedButton(
            "Apply",
            on_click=self._apply_smart_select,
            style=ft.ButtonStyle(
                bgcolor=ft.Colors.with_opacity(0.15, t.colors.primary),
                color=t.colors.fg,
                shape=ft.RoundedRectangleBorder(radius=8),
            ),
        )
        self._smart_row = ft.Row(
            [self._smart_dropdown, self._apply_smart_btn],
            spacing=t.spacing.sm,
            visible=False,
        )

        # Selection label and delete buttons
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
        self._action_bar = ft.Row(
            [self._selection_label, self._smart_row, self._delete_btn, self._permanent_btn],
            alignment=ft.MainAxisAlignment.START,
            spacing=t.spacing.md,
            visible=False,
        )

        self._header = ft.Row(
            [
                ft.Text("Scan Results", size=t.typography.size_xl, weight=ft.FontWeight.BOLD, color=t.colors.fg),
                self._summary,
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        )

        self._filter_bar = ft.Row(
            [
                ft.ElevatedButton(
                    label,
                    on_click=lambda e, k=key: self._set_filter(k),
                    data=key,
                    style=self._get_filter_btn_style(key == "all"),
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
                    ft.Text("Run a scan from the Home page to find duplicates.",
                            size=t.typography.size_base, color=t.colors.fg_muted, text_align=ft.TextAlign.CENTER),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=t.spacing.md,
            ),
            expand=True,
            alignment=ft.Alignment(0.5, 0.5),
            **self._get_glass_style(0.04),
        )

        self.controls = [
            ft.Container(content=self._header, padding=ft.padding.only(left=t.spacing.lg, right=t.spacing.lg, top=t.spacing.md),
                         **self._get_glass_style(0.04)),
            ft.Container(content=self._action_bar, padding=ft.padding.only(left=t.spacing.lg)),
            ft.Container(content=self._filter_bar, padding=ft.padding.only(left=t.spacing.lg, bottom=t.spacing.sm),
                         **self._get_glass_style(0.03)),
            self._empty,
        ]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def load_results(self, groups: List[DuplicateGroup], mode: str = "files") -> None:
        self._groups = list(groups)
        self._scan_mode = mode or "files"
        self._selected_paths.clear()
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

    def _on_smart_rule_changed(self, e) -> None:
        self._smart_rule = self._smart_dropdown.value

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
        self._action_bar.visible = len(self._groups) > 0
        self._smart_row.visible = len(self._groups) > 0
        self._delete_btn.visible = has_selection
        self._permanent_btn.visible = has_selection
        if has_selection:
            # Calculate size based on current groups
            total_bytes = 0
            # Optimization: Create a set for fast lookup if groups are massive
            selected_set = self._selected_paths 
            for g in self._groups:
                for f in g.files:
                    if str(f.path) in selected_set:
                        total_bytes += f.size
            
            self._selection_label.value = f"{count:,} files selected · {fmt_size(total_bytes)}"
        else:
            self._selection_label.value = ""
        self._safe_update(self._action_bar)

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

    # ------------------------------------------------------------------
    # Filtering
    # ------------------------------------------------------------------
    def _set_filter(self, key: str) -> None:
        self._filter_key = key
        for btn in self._filter_bar.controls:
            is_active = btn.data == key
            btn.style = self._get_filter_btn_style(is_active)
            self._safe_update(btn)
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

        if not filtered:
            if self._empty not in self.controls:
                self.controls.append(self._empty)
            if self._group_list in self.controls:
                self.controls.remove(self._group_list)
            self._safe_update(self)
            return

        if self._empty in self.controls:
            self.controls.remove(self._empty)
        if self._group_list not in self.controls:
            self.controls.append(self._group_list)

        n = len(filtered)
        if n <= _LIST_BUILD_ASYNC_THRESHOLD:
            self._group_list.controls = [self._build_group_card(g) for g in filtered]
            self._safe_update(self)
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
        self._safe_update(self)
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
                self._safe_update(self)
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
            self._safe_update(self)
            try:
                self._bridge.flet_page.update()
            except Exception:
                pass
            await asyncio.sleep(0)

    def _build_group_card(self, group: DuplicateGroup) -> ft.Container:
        t = self._t
        sample = group.files[0].path if group.files else ""
        name = Path(str(sample)).name if sample else "Group"
        folder = str(Path(str(sample)).parent) if sample else ""
        
        # We need to capture the group reference correctly in the closure
        # Use a local function to avoid lambda capture issues in loops if expanded later
        group_id = group.group_id
        
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

        def _toggle_expand(e):
            file_checks.visible = not file_checks.visible
            ResultsPage._safe_update(file_checks)
            expand_btn.text = "Collapse" if file_checks.visible else "Expand"
            ResultsPage._safe_update(expand_btn)
            self._safe_update(self)

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
                                    ft.Text(f"{len(group.files)} files · {fmt_size(group.total_size)} · {folder}",
                                            color=t.colors.fg2, size=t.typography.size_sm),
                                ],
                                spacing=2,
                                expand=True,
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
            **self._get_glass_style(0.06),
        )

    def _open_group(self, group: DuplicateGroup) -> None:
        self._bridge.coordinator.review_open_group(group.group_id, self._groups)
        self._bridge.navigate("review")

    def apply_theme(self, mode: str) -> None:
        """Updates theme properties without destroying UI controls."""
        self._t = theme_for_mode(mode)

        # Update colors on static elements
        self._summary.color = self._t.colors.fg2

        # Update container glass styles (parent exists only when this page is mounted)
        hdr_parent = getattr(self._header, "parent", None)
        if hdr_parent is not None:
            hdr_parent.bgcolor = self._get_glass_style(0.04).get("bgcolor")
            hdr_parent.border = self._get_glass_style(0.04).get("border")
        filt_parent = getattr(self._filter_bar, "parent", None)
        if filt_parent is not None:
            filt_parent.bgcolor = self._get_glass_style(0.03).get("bgcolor")
            filt_parent.border = self._get_glass_style(0.03).get("border")

        self._empty.bgcolor = self._get_glass_style(0.04).get("bgcolor")
        self._empty.border = self._get_glass_style(0.04).get("border")

        # Update Filter Buttons
        for btn in self._filter_bar.controls:
            is_active = btn.data == self._filter_key
            btn.style = self._get_filter_btn_style(is_active)

        # Re-render list items to apply new theme colors to text/icons
        self._refresh()

        self._safe_update(self)