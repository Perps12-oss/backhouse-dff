"""Shared page chrome — consistent headers across tab pages."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import flet as ft

from cerebro.v2.ui.flet_app.theme import ThemeTokens


@dataclass(frozen=True)
class PageHeaderBlock:
    """Return value of :func:`build_page_header` for theme updates."""

    root: ft.Container
    title: ft.Text
    subtitle: Optional[ft.Text]


def build_page_header(
    t: ThemeTokens,
    title: str,
    *,
    subtitle: Optional[str] = None,
    trailing: Optional[ft.Control] = None,
    padding: Optional[ft.Padding] = None,
) -> PageHeaderBlock:
    """Title + optional subtitle + optional trailing controls (e.g. action buttons)."""
    title_w = ft.Text(
        title,
        size=t.typography.size_xl,
        weight=ft.FontWeight.W_700,
        color=t.colors.fg,
    )
    col_children: list[ft.Control] = [title_w]
    subtitle_w: Optional[ft.Text] = None
    if subtitle:
        subtitle_w = ft.Text(subtitle, size=t.typography.size_sm, color=t.colors.fg_muted)
        col_children.append(subtitle_w)

    left = ft.Column(
        col_children,
        spacing=t.spacing.xs,
        expand=trailing is not None,
        tight=True,
    )

    row_children: list[ft.Control] = [left]
    if trailing is not None:
        row_children.append(trailing)

    row = ft.Row(
        row_children,
        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        vertical_alignment=ft.CrossAxisAlignment.START,
        spacing=t.spacing.md,
    )
    pad = padding or ft.padding.only(
        left=t.spacing.lg,
        right=t.spacing.lg,
        top=t.spacing.lg,
        bottom=t.spacing.sm,
    )
    root = ft.Container(content=row, padding=pad)
    return PageHeaderBlock(root=root, title=title_w, subtitle=subtitle_w)
