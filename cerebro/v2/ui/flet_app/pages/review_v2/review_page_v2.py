"""Review workspace v2 — Batch 0–1: env-gated scaffold + minimal two-pane shell.

Enable with environment variable::

    CEREBRO_REVIEW_SHELL=v2

Next batches replace stubs with real sidebar, group list, compare, etc.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import flet as ft

from cerebro.v2.ui.flet_app.theme import theme_for_mode

if TYPE_CHECKING:
    from cerebro.v2.ui.flet_app.services.state_bridge import StateBridge


class ReviewPageV2(ft.Column):
    """Minimal review route: left stub + center stub (validates Flet layout without legacy shell)."""

    def __init__(self, bridge: "StateBridge") -> None:
        super().__init__(expand=True, spacing=0, scroll=None)
        self._bridge = bridge
        self._pending_deferred_render = False
        # Invisible placeholders so ``main.py`` bridge.register_action_control(...) stays safe.
        self._noop = ft.Container(width=0, height=0, visible=False)
        self._grid = self._noop
        self._compare_view = self._noop
        self._cmp_bar = self._noop
        self._workstation_sidebar = self._noop

        self._t = theme_for_mode("dark")
        self._shell_row: ft.Row | None = None
        self._build_ui(self._t)

    def _build_ui(self, t) -> None:
        sidebar = ft.Container(
            width=220,
            padding=16,
            content=ft.Column(
                [
                    ft.Text("Sidebar (stub)", size=14, weight=ft.FontWeight.W_700, color=t.colors.fg),
                    ft.Text(
                        "Batch 1 — left rail placeholder.\n"
                        "Replace with workstation sidebar in a later batch.",
                        size=12,
                        color=t.colors.fg_muted,
                    ),
                ],
                tight=True,
                spacing=8,
            ),
            border=ft.border.only(right=ft.BorderSide(1, t.colors.border3)),
        )
        center = ft.Container(
            expand=True,
            padding=20,
            content=ft.Column(
                [
                    ft.Text("Review shell v2", size=20, weight=ft.FontWeight.W_800, color=t.colors.fg),
                    ft.Text(
                        "Batch 0–1: scaffold + two-pane row. "
                        "Set environment variable CEREBRO_REVIEW_SHELL=v2 to use this route.",
                        size=13,
                        color=t.colors.fg_muted,
                    ),
                    ft.Container(height=16),
                    ft.Text("Center workspace (stub)", size=15, weight=ft.FontWeight.W_600, color=t.colors.fg),
                    ft.Text(
                        "If this area paints reliably while legacy compare stays blank, "
                        "the bug is likely in the old shell / mount path — not Flet globally.",
                        size=12,
                        color=t.colors.fg_muted,
                    ),
                ],
                expand=True,
                spacing=6,
                alignment=ft.MainAxisAlignment.START,
            ),
        )
        self._shell_row = ft.Row(
            [sidebar, center],
            expand=True,
            vertical_alignment=ft.CrossAxisAlignment.START,
        )
        self.controls = [self._shell_row]

    def on_show(self) -> None:
        """Layout calls this after mount; no-op until deferred load is implemented."""
        self._pending_deferred_render = False

    def apply_theme(self, mode: str) -> None:
        self._t = theme_for_mode(mode)
        # Batch 1: rebuild shell with new tokens (simplest correct path).
        self.controls.clear()
        self._build_ui(self._t)
        try:
            if self.page is not None:
                self.update()
        except RuntimeError:
            pass

    # --- Stubs: ``main.py`` / listeners call these on the review singleton regardless of shell version.
    def get_groups(self):
        return []

    def load_results(self, groups, mode: str = "files", defer_render: bool = False) -> None:
        """Batch 2+: wire duplicate groups into this shell."""

    def apply_pruned_groups(self, groups, mode: str = "files") -> None:
        """Batch 2+: mirror pruned groups from store."""
