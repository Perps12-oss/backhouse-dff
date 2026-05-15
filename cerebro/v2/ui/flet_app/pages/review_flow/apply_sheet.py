"""Bottom-sheet UI for Apply cleanup: summary → confirm → progress → outcome."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, List, Literal, Optional, Tuple

import flet as ft

from cerebro.v2.ui.flet_app.theme import ThemeTokens, fmt_size

ApplyStep = Literal["summary", "confirm", "progress", "outcome"]


@dataclass
class ApplyOutcomeModel:
    deleted_count: int
    freed_bytes: int
    error_count: int
    failures: List[Tuple[str, str]] = field(default_factory=list)


def _fmt_stats_line(deleted: int, freed: int, errors: int) -> str:
    err = f"{errors} error" + ("s" if errors != 1 else "")
    return f"{deleted} file(s) removed · {fmt_size(freed)} freed · {err}"


def build_apply_sheet_column(
    t: ThemeTokens,
    *,
    step: ApplyStep,
    delete_count: int,
    freed_bytes: int,
    protected_count: int,
    confirm_checkbox: Optional[ft.Checkbox],
    progress_bar: ft.ProgressBar,
    progress_label: ft.Text,
    outcome: Optional[ApplyOutcomeModel],
    reduce_motion: bool,
    on_close: Callable[[ft.ControlEvent | None], None],
    on_continue_summary: Callable[[ft.ControlEvent | None], None],
    on_back_confirm: Callable[[ft.ControlEvent | None], None],
    on_apply: Callable[[ft.ControlEvent | None], None],
    on_restore_managed: Callable[[ft.ControlEvent | None], None],
    on_back_overview: Callable[[ft.ControlEvent | None], None],
    on_new_scan: Callable[[ft.ControlEvent | None], None],
) -> ft.Column:
    title = ft.Text("Remove files", weight=ft.FontWeight.W_700, size=t.typography.size_md)
    footer_close = ft.TextButton("Cancel", on_click=on_close)

    if step == "summary":
        lines: list[ft.Control] = [
            title,
            ft.Text(
                f"{delete_count} file(s) · {fmt_size(freed_bytes)} reclaimable",
                size=t.typography.size_sm,
                color=t.colors.fg_muted,
            ),
            ft.Container(height=4),
            ft.Text(
                "Files are moved to app-managed storage (not the OS Recycle Bin). You can restore the last batch afterwards.",
                size=t.typography.size_xs,
            ),
        ]
        if protected_count:
            lines.append(
                ft.Text(
                    f"{protected_count} protected path(s) will be skipped.",
                    size=t.typography.size_xs,
                    color=t.colors.warning,
                )
            )
        lines.extend(
            [
                ft.Container(height=8),
                ft.Row(
                    [
                        footer_close,
                        ft.FilledButton("Continue", on_click=on_continue_summary),
                    ],
                    alignment=ft.MainAxisAlignment.END,
                ),
            ]
        )
        return ft.Column(lines, spacing=8, tight=True, scroll=ft.ScrollMode.AUTO, height=420)

    if step == "confirm":
        if confirm_checkbox is None:
            raise ValueError("confirm_checkbox required for confirm step")
        return ft.Column(
            [
                title,
                ft.Text(
                    f"Move {delete_count} file(s) — {fmt_size(freed_bytes)} — to managed storage.",
                    size=t.typography.size_xs,
                ),
                confirm_checkbox,
                ft.Container(height=8),
                ft.Row(
                    [
                        ft.TextButton("Back", on_click=on_back_confirm),
                        footer_close,
                        ft.FilledButton("Move files", on_click=on_apply),
                    ],
                    alignment=ft.MainAxisAlignment.END,
                ),
            ],
            spacing=8,
            tight=True,
            scroll=ft.ScrollMode.AUTO,
            height=420,
        )

    if step == "progress":
        return ft.Column(
            [
                title,
                ft.Text("Moving files…", weight=ft.FontWeight.W_600, size=t.typography.size_sm),
                progress_label,
                progress_bar,
            ],
            spacing=12,
            tight=True,
            height=420,
        )

    # outcome
    assert outcome is not None
    err_controls: list[ft.Control] = []
    if outcome.failures:
        detail_rows = [
            ft.Column(
                [
                    ft.Text(path, size=t.typography.size_xs, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
                    ft.Text(reason, size=t.typography.size_xs, color=t.colors.danger),
                ],
                spacing=0,
            )
            for path, reason in outcome.failures[:200]
        ]
        err_controls.append(
            ft.ExpansionTile(
                title=ft.Text(f"Error details ({len(outcome.failures)})", size=t.typography.size_sm),
                controls=detail_rows,
                initially_expanded=False,
            )
        )

    success_icon = ft.Icon(ft.icons.Icons.CHECK_CIRCLE, color=t.colors.success, size=36)
    header = ft.Row([success_icon, ft.Text("Done", weight=ft.FontWeight.W_700)], spacing=8)

    restore_visible = outcome.deleted_count > 0
    return ft.Column(
        [
            title,
            header,
            ft.Text(_fmt_stats_line(outcome.deleted_count, outcome.freed_bytes, outcome.error_count), size=t.typography.size_sm),
            *err_controls,
            ft.Container(height=8),
            ft.OutlinedButton(
                "Restore from managed storage",
                visible=restore_visible,
                on_click=on_restore_managed,
            ),
            ft.Row(
                [
                    ft.TextButton("Back to review", on_click=on_back_overview),
                    ft.OutlinedButton("New scan", on_click=on_new_scan),
                ],
                alignment=ft.MainAxisAlignment.START,
            ),
            ft.Row([ft.TextButton("Close", on_click=on_close)], alignment=ft.MainAxisAlignment.END),
        ],
        spacing=8,
        tight=True,
        scroll=ft.ScrollMode.AUTO,
        height=420,
    )
