"""Smart-delete confirmation and async delete+prune orchestration for Review."""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable, List

import flet as ft

from cerebro.core.deletion import DeletionPolicy
from cerebro.engines.base_engine import DuplicateGroup
from cerebro.v2.ui.flet_app.services.delete_service import DeleteService
from cerebro.v2.ui.flet_app.theme import ThemeTokens

if TYPE_CHECKING:
    from cerebro.v2.ui.flet_app.services.state_bridge import StateBridge


def show_smart_delete_paths_dialog(
    bridge: StateBridge,
    t: ThemeTokens,
    paths: List[str],
    on_confirmed: Callable[[DeletionPolicy], None],
) -> None:
    """Confirm permanent deletion for ``paths``; then ``on_confirmed(PERMANENT)``."""

    def _confirmed(e) -> None:
        bridge.dismiss_top_dialog()
        on_confirmed(DeletionPolicy.PERMANENT)

    c = t.colors
    danger_bg = ft.Colors.with_opacity(0.08, c.danger)
    danger_border = ft.Colors.with_opacity(0.25, c.danger)

    title_row = ft.Row(
        [
            ft.Container(
                content=ft.Icon(ft.icons.Icons.DELETE_FOREVER, color=c.danger, size=22),
                bgcolor=ft.Colors.with_opacity(0.12, c.danger),
                border_radius=10,
                padding=ft.padding.all(6),
            ),
            ft.Text(
                "Delete permanently?",
                size=t.typography.size_base,
                weight=ft.FontWeight.W_700,
                color=c.fg,
            ),
        ],
        spacing=10,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )

    body = ft.Container(
        content=ft.Column(
            [
                ft.Text(
                    f"{len(paths):,} file{'s' if len(paths) != 1 else ''} will be erased from disk.",
                    size=t.typography.size_sm,
                    color=c.fg,
                    weight=ft.FontWeight.W_600,
                ),
                ft.Text(
                    "This cannot be undone. Use \"Move to Trash\" if you want a safety net.",
                    size=t.typography.size_sm,
                    color=c.fg_muted,
                ),
            ],
            spacing=4,
            tight=True,
        ),
        bgcolor=danger_bg,
        border=ft.border.all(1, danger_border),
        border_radius=10,
        padding=ft.padding.symmetric(horizontal=14, vertical=12),
    )

    dlg = ft.AlertDialog(
        modal=True,
        title=title_row,
        title_padding=ft.padding.fromLTRB(20, 20, 20, 0),
        content=body,
        content_padding=ft.padding.fromLTRB(20, 14, 20, 0),
        actions=[
            ft.TextButton(
                "Cancel",
                on_click=lambda _e: bridge.dismiss_top_dialog(),
                style=ft.ButtonStyle(
                    color=c.fg_muted,
                    padding=ft.padding.symmetric(horizontal=12, vertical=8),
                    shape=ft.RoundedRectangleBorder(radius=999),
                ),
            ),
            ft.FilledButton(
                "Delete Permanently",
                icon=ft.icons.Icons.DELETE_FOREVER,
                on_click=_confirmed,
                style=ft.ButtonStyle(
                    bgcolor=c.danger,
                    color="#FFFFFF",
                    icon_color="#FFFFFF",
                    overlay_color=ft.Colors.with_opacity(0.18, c.danger),
                    padding=ft.padding.symmetric(horizontal=14, vertical=8),
                    shape=ft.RoundedRectangleBorder(radius=999),
                    text_style=ft.TextStyle(size=12, weight=ft.FontWeight.W_700),
                ),
            ),
        ],
        actions_padding=ft.padding.fromLTRB(20, 12, 20, 16),
        actions_alignment=ft.MainAxisAlignment.END,
        shape=ft.RoundedRectangleBorder(radius=16),
        bgcolor=c.bg2,
    )
    bridge.show_modal_dialog(dlg)


def run_delete_with_progress(
    *,
    service: DeleteService,
    bridge: StateBridge,
    t: ThemeTokens,
    paths: List[str],
    policy: DeletionPolicy,
    groups: List[DuplicateGroup],
    safe_update: Callable[[ft.Control | None], None],
    on_complete: Callable[[List[DuplicateGroup], int, int, int, Exception | None], None],
) -> None:
    """Show progress modal, run ``delete_and_prune_async``, invoke ``on_complete`` on the UI thread.

    *safe_update* is typically ``review.safe_controls.safe_update`` (not ``ReviewPage._safe_update``).
    """
    c = t.colors
    progress_text = ft.Text("Preparing…", size=t.typography.size_sm, color=c.fg_muted)
    progress_bar = ft.ProgressBar(value=0, color=c.accent, bgcolor=ft.Colors.with_opacity(0.12, c.accent))

    progress_title = ft.Row(
        [
            ft.ProgressRing(width=16, height=16, stroke_width=2, color=c.accent),
            ft.Text("Deleting files", size=t.typography.size_base, weight=ft.FontWeight.W_700, color=c.fg),
        ],
        spacing=10,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )
    progress_dialog = ft.AlertDialog(
        modal=True,
        title=progress_title,
        title_padding=ft.padding.fromLTRB(20, 20, 20, 0),
        content=ft.Column([progress_text, progress_bar], tight=True, spacing=10),
        content_padding=ft.padding.fromLTRB(20, 14, 20, 20),
        shape=ft.RoundedRectangleBorder(radius=16),
        bgcolor=c.bg2,
    )
    bridge.show_modal_dialog(progress_dialog)
    page = bridge.flet_page

    def _ui_progress(done: int, total: int, name: str) -> None:
        tmax = max(1, int(total or 1))
        progress_bar.value = min(1.0, done / tmax)
        progress_text.value = f"{done:,}/{tmax:,} processed · {name}"
        safe_update(progress_bar)
        safe_update(progress_text)

    def _ui_done(
        new_groups: List[DuplicateGroup],
        deleted: int,
        failed: int,
        bytes_reclaimed: int,
        err: Exception | None,
    ) -> None:
        bridge.dismiss_top_dialog()
        on_complete(new_groups, deleted, failed, bytes_reclaimed, err)

    def _progress(done: int, total: int, name: str) -> None:
        if hasattr(page, "run_thread"):
            page.run_thread(_ui_progress, done, total, name)
        else:
            _ui_progress(done, total, name)

    def _done(
        new_groups: List[DuplicateGroup],
        deleted: int,
        failed: int,
        bytes_reclaimed: int,
        err: Exception | None,
    ) -> None:
        if hasattr(page, "run_thread"):
            page.run_thread(_ui_done, new_groups, deleted, failed, bytes_reclaimed, err)
        else:
            _ui_done(new_groups, deleted, failed, bytes_reclaimed, err)

    service.delete_and_prune_async(
        paths=paths,
        groups=groups,
        policy=policy,
        progress_callback=_progress,
        done_callback=_done,
    )
