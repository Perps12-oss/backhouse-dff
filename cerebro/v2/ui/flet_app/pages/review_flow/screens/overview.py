from __future__ import annotations

from typing import Any, List, Optional

import flet as ft

from cerebro.engines.base_engine import DuplicateGroup
from cerebro.v2.ui.flet_app.theme import ThemeTokens, fmt_size


def _metrics_from_groups(groups: List[DuplicateGroup]) -> dict[str, int]:
    file_count = sum(len(g.files) for g in groups)
    reclaimable = sum(int(getattr(g, "reclaimable", 0) or 0) for g in groups)
    return {"set_count": len(groups), "file_count": file_count, "reclaimable_bytes": reclaimable}


def _format_elapsed(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.0f}s"
    m, s = int(seconds // 60), int(seconds % 60)
    if m < 60:
        return f"{m}m {s:02d}s"
    h, m = divmod(m, 60)
    return f"{h}h {m}m"


def build_overview_screen(
    t: ThemeTokens,
    groups: List[DuplicateGroup],
    *,
    on_start_review: Any,
    recent_lines: list[str] | None = None,
    scan_elapsed_seconds: Optional[float] = None,
) -> ft.Column:
    metrics = _metrics_from_groups(groups)
    n_sets = metrics["set_count"]
    has_sets = n_sets > 0

    if has_sets:
        hero = ft.Text(
            f"{n_sets:,} duplicate set{'s' if n_sets != 1 else ''} found",
            size=t.typography.size_xxl,
            weight=ft.FontWeight.W_700,
            color=t.colors.fg,
            text_align=ft.TextAlign.CENTER,
        )
        sub = ft.Text(
            f"{metrics['file_count']:,} files • {fmt_size(int(metrics['reclaimable_bytes']))} recoverable",
            size=t.typography.size_md,
            color=t.colors.fg_muted,
            text_align=ft.TextAlign.CENTER,
        )
        icon = ft.Icon(ft.icons.Icons.CHECK_CIRCLE, size=56, color=t.colors.success)
    else:
        hero = ft.Text(
            "No duplicate sets loaded",
            size=t.typography.size_xxl,
            weight=ft.FontWeight.W_700,
            color=t.colors.fg,
            text_align=ft.TextAlign.CENTER,
        )
        sub = ft.Text(
            "Run a scan from the dashboard, then open this tab again.",
            size=t.typography.size_md,
            color=t.colors.fg_muted,
            text_align=ft.TextAlign.CENTER,
        )
        icon = ft.Icon(ft.icons.Icons.FOLDER_OPEN, size=56, color=t.colors.fg_muted)

    def metric_stat(label: str, value: str) -> ft.Column:
        return ft.Column(
            [
                ft.Text(
                    value,
                    size=t.typography.size_xl,
                    weight=ft.FontWeight.W_700,
                    color=t.colors.fg,
                    text_align=ft.TextAlign.CENTER,
                ),
                ft.Text(
                    label,
                    size=t.typography.size_xs,
                    color=t.colors.fg_muted,
                    text_align=ft.TextAlign.CENTER,
                ),
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=2,
            tight=True,
        )

    stat_controls: list[ft.Column] = [
        metric_stat("duplicate sets", f"{metrics['set_count']:,}"),
        metric_stat("files in groups", f"{metrics['file_count']:,}"),
        metric_stat("reclaimable", fmt_size(int(metrics["reclaimable_bytes"]))),
    ]
    if scan_elapsed_seconds is not None and scan_elapsed_seconds > 0:
        stat_controls.append(metric_stat("last scan", _format_elapsed(float(scan_elapsed_seconds))))

    cards = ft.Row(
        stat_controls,
        spacing=32,
        alignment=ft.MainAxisAlignment.CENTER,
        wrap=True,
    )

    start_btn = ft.FilledButton(
        "Start review",
        on_click=on_start_review,
        width=280,
        disabled=not has_sets,
    )

    return ft.Column(
        [
            icon,
            hero,
            sub,
            ft.Container(height=16),
            cards,
            ft.Container(height=24),
            start_btn,
            ft.Container(height=32),
            ft.Text(
                "Recent reviews",
                size=t.typography.size_sm,
                color=t.colors.fg_muted,
                text_align=ft.TextAlign.CENTER,
            ),
            ft.Column(
                [
                    ft.Text(
                        line,
                        size=t.typography.size_xs,
                        color=t.colors.fg_muted,
                        text_align=ft.TextAlign.CENTER,
                    )
                    for line in (recent_lines or ["No saved sessions yet"])
                ],
                spacing=2,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        ],
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        alignment=ft.MainAxisAlignment.CENTER,
        expand=True,
        scroll=ft.ScrollMode.AUTO,
    )
