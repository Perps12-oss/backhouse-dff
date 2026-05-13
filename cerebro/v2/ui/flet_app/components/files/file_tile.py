"""Compact grid tile for legacy results browsing."""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import Callable, Dict

import flet as ft

from cerebro.v2.ui.flet_app.design_system.glass import glass_container
from cerebro.v2.ui.flet_app.theme import ThemeTokens, fmt_size


def build_results_file_tile(
    t: ThemeTokens,
    file: object,
    *,
    icon_for_extension: Callable[[str], tuple[str, str]],
    thumb_slots: Dict[str, ft.Container],
    tile_cache: Dict[str, ft.Container],
    on_open: Callable[[object], None],
) -> ft.Container:
    """Build a thumbnail tile and register thumb/cache slots for async decode."""
    key = str(getattr(file, "path", ""))
    p = Path(key)
    icon_name, accent = icon_for_extension(p.suffix)
    modified = ""
    try:
        ts = float(getattr(file, "mtime", None) or getattr(file, "modified", 0) or 0)
        if ts > 0:
            modified = datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
    except Exception:
        modified = ""

    size_bar = ft.Container(
        content=ft.Text(
            fmt_size(file.size),
            size=9,
            color="#FFFFFF",
            text_align=ft.TextAlign.CENTER,
        ),
        bgcolor=ft.Colors.with_opacity(0.72, "#0A0E14"),
        padding=ft.Padding.symmetric(horizontal=4, vertical=3),
        alignment=ft.Alignment(0, 0),
    )
    placeholder = ft.Container(
        content=ft.Icon(
            icon_name,
            size=30,
            color=ft.Colors.with_opacity(0.9, accent),
        ),
        expand=True,
        alignment=ft.Alignment(0, 0),
        bgcolor=ft.Colors.with_opacity(0.06, ft.Colors.WHITE),
    )
    thumb_slot = ft.Container(
        content=placeholder,
        expand=True,
        clip_behavior=ft.ClipBehavior.HARD_EDGE,
    )
    thumb_slots[key] = thumb_slot

    metadata_bar = ft.Container(
        content=ft.Column(
            [
                ft.Text(
                    p.name,
                    size=8,
                    color="#FFFFFF",
                    max_lines=1,
                    overflow=ft.TextOverflow.ELLIPSIS,
                    text_align=ft.TextAlign.CENTER,
                ),
                ft.Text(
                    str(p.parent),
                    size=7,
                    color="#B9CAE6",
                    max_lines=1,
                    overflow=ft.TextOverflow.ELLIPSIS,
                    text_align=ft.TextAlign.CENTER,
                ),
                ft.Text(
                    modified,
                    size=7,
                    color="#9FB0D0",
                    max_lines=1,
                    overflow=ft.TextOverflow.ELLIPSIS,
                    text_align=ft.TextAlign.CENTER,
                ),
            ],
            spacing=1,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        bgcolor=ft.Colors.with_opacity(0.82, "#0A0E14"),
        padding=ft.Padding.symmetric(horizontal=4, vertical=4),
    )
    stack = ft.Stack(
        [
            ft.Column([thumb_slot, metadata_bar], expand=True, spacing=0),
            ft.Container(
                content=size_bar,
                alignment=ft.Alignment(1, -1),
                padding=ft.padding.only(top=2, right=2),
            ),
        ],
        expand=True,
    )
    tile = ft.Container(
        content=stack,
        width=136,
        height=128,
        border_radius=8,
        border=ft.border.all(1, ft.Colors.with_opacity(0.15, ft.Colors.WHITE)),
        bgcolor=ft.Colors.with_opacity(0.06, ft.Colors.WHITE),
        clip_behavior=ft.ClipBehavior.HARD_EDGE,
        tooltip=str(p),
        ink=True,
        on_click=lambda e, _f=file: on_open(_f),
    )
    tile_cache[key] = tile
    return tile


def build_results_group_grid_section(
    t: ThemeTokens,
    group: object,
    idx: int,
    *,
    tile_builder: Callable[[object], ft.Container],
) -> ft.Container:
    tiles = [tile_builder(f) for f in group.files]
    header = ft.Row(
        [
            ft.Container(
                content=ft.Text(
                    f"Group {idx + 1}",
                    size=t.typography.size_sm,
                    weight=ft.FontWeight.W_700,
                    color=t.colors.fg,
                ),
                bgcolor=ft.Colors.with_opacity(0.08, ft.Colors.WHITE),
                border_radius=6,
                padding=ft.Padding.symmetric(horizontal=8, vertical=4),
            ),
            ft.Text(
                f"{len(group.files)} files",
                size=t.typography.size_sm,
                color=t.colors.fg_muted,
            ),
            ft.Container(expand=True),
            ft.Text(
                fmt_size(group.reclaimable),
                size=t.typography.size_sm,
                weight=ft.FontWeight.W_700,
                color="#22D3EE",
            ),
        ],
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )
    return glass_container(
        content=ft.Column(
            [header, ft.Row(tiles, spacing=t.spacing.sm, wrap=True)],
            spacing=t.spacing.sm,
        ),
        t=t,
        padding=t.spacing.md,
    )
