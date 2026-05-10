"""Group overview card for the review page groups list."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Callable, List, Set

import flet as ft

from cerebro.engines.base_engine import DuplicateFile, DuplicateGroup
from cerebro.v2.ui.flet_app.pages.review._types import RC
from cerebro.v2.ui.flet_app.pages.review.theme_detect import app_theme_is_light
from cerebro.v2.ui.flet_app.theme import ThemeTokens, fmt_size

if TYPE_CHECKING:
    from cerebro.v2.ui.flet_app.services.state_bridge import StateBridge

_GROUP_STRIPE = RC.group_stripe


def group_duplicate_summary(g: DuplicateGroup) -> str:
    n = len(g.files)
    sim = (getattr(g, "similarity_type", None) or "exact").lower()
    names = list(dict.fromkeys(Path(str(f.path)).name for f in g.files))
    if n < 2:
        return f"{n} file in this group"
    if sim == "exact":
        if len(names) == 1:
            return f'{n} byte-identical copies of "{names[0]}"'
        head = ", ".join(names[:3])
        tail = ", ..." if len(names) > 3 else ""
        return f"{n} byte-identical files · {head}{tail}"
    if len(names) == 1:
        return f'{n} similar matches for "{names[0]}"'
    head = ", ".join(names[:3])
    tail = ", ..." if len(names) > 3 else ""
    return f"{n} similar matches · {head}{tail}"


def group_path_hint(files: List[DuplicateFile]) -> str:
    if not files:
        return ""
    paths = [Path(str(f.path)) for f in files]
    if len(paths) == 1:
        return str(paths[0].parent)
    parents = [p.parent for p in paths]
    uniq_parents = {str(p) for p in parents}
    names = list(dict.fromkeys(p.name for p in paths))
    if len(uniq_parents) == 1:
        if len(names) <= 3:
            return f"Same folder · {', '.join(names)}"
        return f"Same folder · {', '.join(names[:3])}... (+{len(names) - 3} names)"
    try:
        common = os.path.commonpath([str(p) for p in paths])
    except ValueError:
        bits = [f"{p.parent.name}/{p.name}" for p in paths[:3]]
        return " · ".join(dict.fromkeys(bits))
    rel_bits: list[str] = []
    for p in paths:
        try:
            rel_bits.append(os.path.relpath(str(p), common))
        except ValueError:
            rel_bits.append(str(p))
    ordered = list(dict.fromkeys(rel_bits))
    return " · ".join(ordered[:3]) + (" ..." if len(ordered) > 3 else "")


def build_group_card(
    t: ThemeTokens,
    bridge: "StateBridge",
    g: DuplicateGroup,
    idx: int,
    total_reclaim_scan: int,
    reviewed_ids: Set[int],
    *,
    get_glass_style: Callable[[float], dict],
) -> ft.Container:
    reclaim = int(getattr(g, "reclaimable", 0) or 0)
    reviewed = g.group_id in reviewed_ids
    title_color = RC.group_title_reviewed if reviewed else t.colors.fg
    pct = (100.0 * reclaim / total_reclaim_scan) if total_reclaim_scan > 0 else 0.0
    pct_s = f" · {pct:.1f}% of scan reclaim" if total_reclaim_scan > 0 and reclaim > 0 else ""
    stripe = _GROUP_STRIPE[g.group_id % len(_GROUP_STRIPE)]
    line_dup = group_duplicate_summary(g)
    line_path = group_path_hint(list(g.files))
    glass = get_glass_style(0.05)
    is_light = app_theme_is_light(bridge)
    edge = ft.Colors.with_opacity(0.1, ft.Colors.BLACK if is_light else ft.Colors.WHITE)
    thin = ft.BorderSide(1, edge)
    return ft.Container(
        padding=ft.padding.only(left=8, right=12, top=8, bottom=8),
        border=ft.Border(left=ft.BorderSide(2, stripe), top=thin, right=thin, bottom=thin),
        content=ft.Row(
            [
                ft.Icon(ft.icons.Icons.LAYERS_OUTLINED, size=18, color=stripe),
                ft.Column(
                    [
                        ft.Text(
                            f"Group {idx + 1} · {fmt_size(reclaim)} reclaimable{pct_s}",
                            size=t.typography.size_base,
                            weight=ft.FontWeight.W_700,
                            color=title_color,
                        ),
                        ft.Text(
                            line_dup,
                            size=t.typography.size_sm,
                            color=t.colors.fg2,
                            max_lines=2,
                        ),
                        ft.Text(
                            line_path,
                            size=t.typography.size_xs,
                            color=t.colors.fg_muted,
                            overflow=ft.TextOverflow.ELLIPSIS,
                            max_lines=2,
                        ),
                    ],
                    spacing=4,
                    expand=True,
                ),
            ],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=10,
        ),
        bgcolor=glass["bgcolor"],
        border_radius=glass["border_radius"],
    )
