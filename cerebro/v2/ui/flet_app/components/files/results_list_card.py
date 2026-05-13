"""List-style duplicate group card for legacy results."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Callable

import flet as ft

from cerebro.engines.base_engine import DuplicateGroup
from cerebro.v2.ui.flet_app.design_system.glass import glass_container
from cerebro.v2.ui.flet_app.theme import ThemeTokens, fmt_size


def is_machine_generated_name(name: str) -> bool:
    stem = Path(name).stem
    if len(stem) <= 40:
        return False
    digits = sum(1 for ch in stem if ch.isdigit())
    ratio = digits / max(1, len(stem))
    return ratio > 0.60 and bool(re.search(r"\d{8,}", stem))


def build_results_list_group_card(
    t: ThemeTokens,
    group: DuplicateGroup,
    *,
    icon_for_extension: Callable[[str], tuple[str, str]],
    extra_badge: str | None = None,
) -> ft.Container:
    sample = group.files[0].path if group.files else ""
    sample_path = Path(str(sample))
    name = sample_path.name if sample else "Group"
    parent = str(sample_path.parent) if sample else ""
    parent_leaf = sample_path.parent.name if sample else ""
    machine_name = is_machine_generated_name(name)
    ext = sample_path.suffix if sample else ""
    icon_name, accent = icon_for_extension(ext)

    return glass_container(
        content=ft.Row(
            [
                ft.Container(
                    content=ft.Icon(icon_name, size=18, color=accent),
                    bgcolor=ft.Colors.with_opacity(0.12, accent),
                    border_radius=8,
                    padding=8,
                ),
                ft.Column(
                    [
                        ft.Text(
                            f"Folder: {parent_leaf}" if machine_name and parent_leaf else name,
                            weight=ft.FontWeight.W_700 if machine_name else ft.FontWeight.W_600,
                            color="#E2F3FF" if machine_name else t.colors.fg,
                            size=t.typography.size_md,
                            no_wrap=True,
                            overflow=ft.TextOverflow.ELLIPSIS,
                        ),
                        ft.Text(
                            name if machine_name else parent,
                            size=t.typography.size_sm,
                            color=t.colors.fg_muted,
                            no_wrap=True,
                            overflow=ft.TextOverflow.ELLIPSIS,
                            visible=bool(machine_name or parent),
                        ),
                        ft.Row(
                            [
                                ft.Text(
                                    f"{len(group.files)} files",
                                    size=t.typography.size_sm,
                                    color="#7DD3FC",
                                    weight=ft.FontWeight.W_500,
                                ),
                                ft.Text("·", size=t.typography.size_sm, color=t.colors.fg_muted),
                                ft.Text(
                                    fmt_size(group.total_size),
                                    size=t.typography.size_sm,
                                    color="#A78BFA",
                                    weight=ft.FontWeight.W_500,
                                ),
                                ft.Text("·", size=t.typography.size_sm, color=t.colors.fg_muted),
                                ft.Text(
                                    parent,
                                    size=t.typography.size_sm,
                                    color="#93C5FD",
                                    no_wrap=True,
                                    overflow=ft.TextOverflow.ELLIPSIS,
                                    expand=True,
                                ),
                                ft.Text(
                                    extra_badge or "",
                                    size=t.typography.size_sm,
                                    color="#FBBF24",
                                    visible=bool(extra_badge),
                                ),
                            ],
                            spacing=4,
                        ),
                    ],
                    spacing=3,
                    expand=True,
                ),
                ft.Text(
                    fmt_size(group.reclaimable),
                    weight=ft.FontWeight.BOLD,
                    color="#22D3EE",
                    size=t.typography.size_md,
                ),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        t=t,
        padding=t.spacing.md,
    )
