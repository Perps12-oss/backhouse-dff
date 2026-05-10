"""Smart-delete confirmation and async delete+prune orchestration for Review."""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable, List

import flet as ft

from cerebro.core.deletion import DeletionPolicy
from cerebro.engines.base_engine import DuplicateGroup
from cerebro.v2.ui.flet_app.pages.review.deletion_dialog import build_confirm_dialog
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
    """Confirm bulk delete for ``paths`` (rule-based wording); then ``on_confirmed(policy)``."""

    def _confirmed(policy: DeletionPolicy) -> None:
        bridge.dismiss_top_dialog()
        on_confirmed(policy)

    bridge.show_modal_dialog(
        build_confirm_dialog(
            f"{len(paths):,} file(s) according to the selected rule",
            _confirmed,
            bridge.dismiss_top_dialog,
            t,
        )
    )


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
    """Show progress modal, run ``delete_and_prune_async``, invoke ``on_complete`` on the UI thread."""
    progress_text = ft.Text("Preparing deletion...", size=t.typography.size_sm)
    progress_bar = ft.ProgressBar(value=0)
    progress_dialog = ft.AlertDialog(
        modal=True,
        title=ft.Text("Deleting files"),
        content=ft.Column([progress_text, progress_bar], tight=True, spacing=10),
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
