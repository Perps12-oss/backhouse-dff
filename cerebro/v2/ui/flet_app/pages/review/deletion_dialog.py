from __future__ import annotations

from typing import Callable

import flet as ft

from cerebro.core.deletion import DeletionPolicy


def build_confirm_dialog(
    label: str,
    on_confirmed: Callable[[DeletionPolicy], None],
    on_cancel: Callable[[], None],
    t,
) -> ft.AlertDialog:
    def _cancel(e): on_cancel()
    def _perm(e): on_confirmed(DeletionPolicy.PERMANENT)
    def _trash(e): on_confirmed(DeletionPolicy.TRASH)
    return ft.AlertDialog(
        modal=True,
        title=ft.Text("Confirm Deletion"),
        content=ft.Text(f"Delete {label}?"),
        actions=[
            ft.TextButton("Cancel", on_click=_cancel),
            ft.OutlinedButton(
                "Delete Permanently",
                on_click=_perm,
                style=ft.ButtonStyle(color=t.colors.danger),
            ),
            ft.ElevatedButton(
                "Move to Trash",
                on_click=_trash,
                style=ft.ButtonStyle(bgcolor=t.colors.danger, color=t.colors.bg),
            ),
        ],
    )
