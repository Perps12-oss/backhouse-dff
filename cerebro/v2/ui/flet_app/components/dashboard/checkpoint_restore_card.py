"""Timeline-style checkpoint restore row for Home."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import flet as ft

from cerebro.v2.core.index_presence import format_relative_past
from cerebro.v2.ui.flet_app.pill_button_styles import pill_outlined_button_style, pill_text_button_style
from cerebro.v2.ui.flet_app.theme import ThemeTokens


def _segmented_progress(
    t: ThemeTokens,
    *,
    completed: int,
    total: int,
    segments: int = 20,
) -> ft.Row:
    total = max(1, total)
    filled = int((completed / total) * segments)
    warn = t.colors.warning
    track = ft.Colors.with_opacity(0.35, t.colors.bg3)
    parts: list[ft.Control] = []
    for i in range(segments):
        parts.append(
            ft.Container(
                width=10,
                height=5,
                border_radius=2,
                bgcolor=warn if i < filled else track,
                animate=ft.Animation(400, ft.AnimationCurve.EASE_OUT),
            )
        )
    return ft.Row(parts, spacing=2, tight=True)


@dataclass
class CheckpointRestoreCard:
    """Built checkpoint row; call ``update_relative`` on timer ticks."""

    container: ft.Container
    update_relative: Callable[[], None]


def build_checkpoint_restore_card(
    t: ThemeTokens,
    *,
    scan_id: str,
    folders_preview: str,
    completed: int,
    total: int,
    pending: int,
    created_at: float,
    on_discard: Callable[[ft.ControlEvent], None],
    on_restore: Callable[[ft.ControlEvent], None],
    reduce_motion: bool = False,
) -> CheckpointRestoreCard:
    s = t.spacing
    pct = int(completed / max(1, total) * 100)
    rel_text = ft.Text(
        format_relative_past(created_at),
        size=t.typography.size_xs,
        color=t.colors.fg_muted,
    )
    meta = ft.Text(
        f"{completed:,} of {total:,} hashed ({pct}%)",
        size=t.typography.size_xs,
        color=t.colors.fg_muted,
    )

    def _update_relative() -> None:
        rel_text.value = format_relative_past(created_at)
        try:
            if rel_text.page is not None:
                rel_text.update()
        except RuntimeError:
            pass

    pulse = ft.Container(
        width=8,
        height=8,
        border_radius=4,
        bgcolor=t.colors.warning,
        visible=pending > 0,
    )
    if pending > 0 and not reduce_motion:
        pulse.animate_scale = ft.Animation(2000, ft.AnimationCurve.EASE_IN_OUT)
        pulse.scale = 1.0

    timeline_bar = ft.Container(
        width=4,
        border_radius=2,
        gradient=ft.LinearGradient(
            begin=ft.Alignment(0, -1),
            end=ft.Alignment(0, 1),
            colors=[t.colors.warning, ft.Colors.TRANSPARENT],
        ),
    )
    body = ft.Column(
        [
            ft.Row(
                [
                    pulse,
                    ft.Text(
                        folders_preview,
                        size=t.typography.size_sm,
                        weight=ft.FontWeight.W_600,
                        color=t.colors.fg,
                        expand=True,
                        no_wrap=True,
                        overflow=ft.TextOverflow.ELLIPSIS,
                    ),
                ],
                spacing=s.xs,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            meta,
            rel_text,
            _segmented_progress(t, completed=completed, total=total),
        ],
        spacing=4,
        expand=True,
    )
    actions = ft.Row(
        [
            ft.TextButton(
                "Discard",
                on_click=on_discard,
                style=pill_text_button_style(t, variant="muted"),
            ),
            ft.OutlinedButton(
                f"Restore ({pending:,} left)",
                icon=ft.icons.Icons.RESTORE,
                on_click=on_restore,
                style=pill_outlined_button_style(t),
            ),
        ],
        spacing=s.xs,
        tight=True,
    )
    inner = ft.Row(
        [timeline_bar, body, actions],
        spacing=s.md,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )
    card = ft.Container(
        content=inner,
        padding=ft.Padding.symmetric(horizontal=s.sm, vertical=s.sm),
        border_radius=t.border_radius,
        bgcolor=ft.Colors.with_opacity(0.55, t.colors.glass_bg),
        border=ft.border.all(1, ft.Colors.with_opacity(0.12, t.colors.border)),
    )
    _ = scan_id
    return CheckpointRestoreCard(container=card, update_relative=_update_relative)
