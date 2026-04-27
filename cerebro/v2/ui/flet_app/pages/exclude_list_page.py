"""Exclude List page — manage paths excluded from duplicate scans."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, List

import flet as ft

from cerebro.v2.ui.flet_app.theme import theme_for_mode

if TYPE_CHECKING:
    from cerebro.v2.ui.flet_app.services.state_bridge import StateBridge

_log = logging.getLogger(__name__)


class ExcludeListPage(ft.Column):
    """Manage the list of folders/files excluded from scans."""

    def __init__(self, bridge: "StateBridge"):
        super().__init__(expand=True, scroll=ft.ScrollMode.AUTO)
        self._bridge = bridge
        self._t = theme_for_mode("dark")
        self._paths: List[str] = []
        self._glass_cache: dict = {}
        self._folder_picker: ft.FilePicker
        self._list_col: ft.Column
        self._empty: ft.Container
        self._build_ui()

    def _get_glass_style(self, opacity: float = 0.06) -> dict:
        is_light = "light" in self._bridge.app_theme.lower() if hasattr(self._bridge, "app_theme") else False
        cache_key = (opacity, is_light)
        if cache_key in self._glass_cache:
            return self._glass_cache[cache_key]
        bg_base = ft.Colors.BLACK if is_light else ft.Colors.WHITE
        border_base = ft.Colors.BLACK if is_light else ft.Colors.WHITE
        result = dict(
            bgcolor=ft.Colors.with_opacity(opacity, bg_base),
            border=ft.border.all(1, ft.Colors.with_opacity(0.12, border_base)),
            border_radius=ft.border_radius.all(12),
        )
        self._glass_cache[cache_key] = result
        return result

    @staticmethod
    def _safe_update(ctrl: ft.Control | None) -> None:
        if ctrl is None:
            return
        try:
            if ctrl.page is not None:
                ctrl.update()
        except RuntimeError:
            pass

    def _build_ui(self) -> None:
        t = self._t

        header = ft.Container(
            content=ft.Row(
                [
                    ft.Column(
                        [
                            ft.Text("Exclude List", size=t.typography.size_xl, weight=ft.FontWeight.BOLD, color=t.colors.fg),
                            ft.Text(
                                "Folders listed here are skipped during every scan.",
                                size=t.typography.size_sm, color=t.colors.fg_muted,
                            ),
                        ],
                        spacing=4, expand=True,
                    ),
                    ft.FilledButton(
                        "Add Folder",
                        icon=ft.icons.Icons.CREATE_NEW_FOLDER,
                        on_click=self._on_add_folder,
                        style=ft.ButtonStyle(
                            bgcolor="#00BFA5",
                            color="#0A0E14",
                            shape=ft.RoundedRectangleBorder(radius=8),
                        ),
                    ),
                    ft.OutlinedButton(
                        "Clear All",
                        icon=ft.icons.Icons.DELETE_SWEEP,
                        on_click=self._on_clear_all,
                        style=ft.ButtonStyle(
                            color=t.colors.danger,
                            side=ft.BorderSide(1, t.colors.danger),
                            shape=ft.RoundedRectangleBorder(radius=8),
                        ),
                    ),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                vertical_alignment=ft.CrossAxisAlignment.START,
                spacing=t.spacing.md,
            ),
            padding=ft.padding.only(left=t.spacing.xl, right=t.spacing.xl, top=t.spacing.xl, bottom=t.spacing.md),
            **self._get_glass_style(0.04),
        )

        self._list_col = ft.Column(spacing=t.spacing.sm)
        self._list_container = ft.Container(
            content=self._list_col,
            padding=ft.padding.symmetric(horizontal=t.spacing.xl, vertical=t.spacing.md),
            visible=False,
        )

        self._empty = ft.Container(
            content=ft.Column(
                [
                    ft.Container(
                        content=ft.Icon(ft.icons.Icons.BLOCK, size=44, color="#FBBF24"),
                        bgcolor=ft.Colors.with_opacity(0.08, "#FBBF24"),
                        border_radius=14, padding=18,
                    ),
                    ft.Text("No exclusions yet", size=t.typography.size_lg, weight=ft.FontWeight.W_600, color=t.colors.fg),
                    ft.Text(
                        "Add folders to skip them during scans.\nGreat for system directories or cloud sync folders.",
                        size=t.typography.size_base, color=t.colors.fg_muted, text_align=ft.TextAlign.CENTER,
                    ),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=t.spacing.md,
            ),
            expand=True, alignment=ft.Alignment(0, 0),
            **self._get_glass_style(0.04),
        )

        self._folder_picker = ft.FilePicker()
        self._folder_picker.on_result = self._on_folder_picked

        self.controls = [header, self._list_container, self._empty]

    def _refresh(self) -> None:
        has = bool(self._paths)
        self._list_container.visible = has
        self._empty.visible = not has
        self._list_col.controls = [self._build_path_row(p) for p in self._paths]
        self._safe_update(self)

    def _build_path_row(self, path: str) -> ft.Container:
        t = self._t
        return ft.Container(
            content=ft.Row(
                [
                    ft.Container(
                        content=ft.Icon(ft.icons.Icons.FOLDER_OFF, size=18, color="#FBBF24"),
                        bgcolor=ft.Colors.with_opacity(0.10, "#FBBF24"),
                        border_radius=6, padding=8,
                    ),
                    ft.Text(path, size=t.typography.size_sm, color=t.colors.fg2, expand=True, overflow=ft.TextOverflow.ELLIPSIS),
                    ft.IconButton(
                        icon=ft.icons.Icons.REMOVE_CIRCLE_OUTLINE,
                        icon_color=t.colors.danger,
                        icon_size=18,
                        tooltip="Remove",
                        on_click=lambda e, p=path: self._remove_path(p),
                    ),
                ],
                alignment=ft.MainAxisAlignment.START,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=t.spacing.md,
            ),
            padding=ft.padding.symmetric(horizontal=t.spacing.md, vertical=t.spacing.sm),
            **self._get_glass_style(0.05),
        )

    def _on_add_folder(self, e) -> None:
        page = self._bridge.flet_page
        # Flet 0.8x+ prefers FilePicker as a page service.
        if hasattr(page, "services"):
            if self._folder_picker not in page.services:
                page.services.append(self._folder_picker)
                page.update()
        elif hasattr(page, "overlay"):
            if self._folder_picker not in page.overlay:
                page.overlay.append(self._folder_picker)
                page.update()
        self._folder_picker.get_directory_path(dialog_title="Select folder to exclude")

    def _on_folder_picked(self, e: ft.FilePickerResultEvent) -> None:
        path = getattr(e, "path", None)
        if not path:
            return
        path = str(path).strip()
        if path and path not in self._paths:
            self._paths.append(path)
            self._persist()
            self._refresh()

    def _remove_path(self, path: str) -> None:
        self._paths = [p for p in self._paths if p != path]
        self._persist()
        self._refresh()

    def _on_clear_all(self, e) -> None:
        if not self._paths:
            return
        def _confirm(ev):
            self._bridge.dismiss_top_dialog()
            self._paths.clear()
            self._persist()
            self._refresh()
        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Clear Exclude List"),
            content=ft.Text("Remove all exclusions? Scans will include all previously excluded paths."),
            actions=[
                ft.TextButton("Cancel", on_click=lambda ev: self._bridge.dismiss_top_dialog()),
                ft.ElevatedButton(
                    "Clear All", on_click=_confirm,
                    style=ft.ButtonStyle(bgcolor=self._t.colors.danger, color=self._t.colors.bg),
                ),
            ],
        )
        self._bridge.show_modal_dialog(dialog)

    def _persist(self) -> None:
        try:
            s = self._bridge.get_settings()
            if not isinstance(s, dict):
                s = {}
            s.setdefault("general", {})["exclude_list"] = list(self._paths)
            self._bridge.save_settings(s)
        except Exception as exc:
            _log.debug("Could not persist exclude list: %s", exc)

    def on_show(self) -> None:
        try:
            s = self._bridge.get_settings()
            self._paths = list(s.get("general", {}).get("exclude_list", []))
        except Exception:
            self._paths = []
        self._refresh()

    def apply_theme(self, mode: str) -> None:
        self._glass_cache = {}
        self._t = theme_for_mode(mode)
        self._safe_update(self)
