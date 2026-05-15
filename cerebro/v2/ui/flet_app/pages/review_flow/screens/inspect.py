from __future__ import annotations

from pathlib import Path
from typing import Callable, List, Optional

import flet as ft

from cerebro.engines.base_engine import DuplicateFile
from cerebro.v2.ui.flet_app.pages.review_flow.state import (
    ReviewFlowState,
    inspect_left_right_indices,
    normalize_inspect_ref_cmp,
)
from cerebro.v2.ui.flet_app.services.thumbnail_cache import is_image_path
from cerebro.v2.ui.flet_app.theme import ThemeTokens, fmt_size

_INSPECT_PREVIEW_H = 400
_INSPECT_PANEL_W = 340
_META_MAX_H = 120
_META_CELL_SIZE = 10
_META_HEADER_SIZE = 11


def _file_icon(ext: str) -> str:
    ext = (ext or "").lower()
    if ext in {"jpg", "jpeg", "png", "gif", "webp"}:
        return ft.icons.Icons.IMAGE_OUTLINED
    if ext in {"mp4", "mov", "mkv"}:
        return ft.icons.Icons.MOVIE_OUTLINED
    if ext in {"mp3", "wav", "flac"}:
        return ft.icons.Icons.AUDIOTRACK
    return ft.icons.Icons.INSERT_DRIVE_FILE_OUTLINED


def _preview_panel(
    t: ThemeTokens,
    f: Optional[DuplicateFile],
    *,
    role_label: str,
    panel_label: str,
) -> tuple[ft.Container, Optional[ft.Container]]:
    if f is None:
        empty = ft.Column(
            [
                ft.Text(panel_label, size=_META_HEADER_SIZE, weight=ft.FontWeight.W_600),
                ft.Text(role_label, size=_META_CELL_SIZE, color=t.colors.fg_muted),
                ft.Text("No preview", size=_META_CELL_SIZE, color=t.colors.fg_muted),
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        )
        return ft.Container(width=_INSPECT_PANEL_W, bgcolor=t.colors.bg2, border_radius=8, padding=12, content=empty), None
    ext = (f.extension or Path(str(f.path)).suffix.lstrip(".")).lower()
    path = Path(str(f.path))
    preview_slot: Optional[ft.Container] = None
    body: List[ft.Control] = [
        ft.Row(
            [
                ft.Text(panel_label, size=_META_HEADER_SIZE, weight=ft.FontWeight.W_600),
                ft.Container(expand=True),
                ft.Container(
                    padding=ft.padding.symmetric(horizontal=8, vertical=4),
                    border_radius=6,
                    bgcolor=ft.Colors.with_opacity(0.08, t.colors.primary),
                    content=ft.Text(role_label, size=_META_CELL_SIZE, color=t.colors.primary),
                ),
            ],
        ),
    ]
    if is_image_path(path):
        preview_slot = ft.Container(
            width=_INSPECT_PANEL_W,
            height=_INSPECT_PREVIEW_H,
            bgcolor=t.colors.bg,
            border_radius=8,
            alignment=ft.Alignment.CENTER,
            content=ft.ProgressRing(width=22, height=22),
            data=str(path),
        )
        body.append(preview_slot)
    else:
        body.append(ft.Icon(_file_icon(ext), size=48, color=t.colors.primary))
    body.extend(
        [
            ft.Text(
                f.path.name,
                size=t.typography.size_xs,
                weight=ft.FontWeight.W_600,
                max_lines=2,
                overflow=ft.TextOverflow.ELLIPSIS,
            ),
            ft.Text(fmt_size(int(f.size)), size=t.typography.size_xs, color=t.colors.fg_muted),
            ft.Text(
                str(f.path.parent),
                size=_META_CELL_SIZE,
                color=t.colors.fg_muted,
                max_lines=1,
                overflow=ft.TextOverflow.ELLIPSIS,
            ),
        ]
    )
    if ext in {"txt", "md", "json", "py"}:
        body.append(ft.Text("Document preview placeholder", size=t.typography.size_xs, color=t.colors.fg_muted))
    if ext in {"mp4", "mov"}:
        body.append(ft.Text("Video thumbnail strip placeholder", size=t.typography.size_xs, color=t.colors.fg_muted))
    if ext in {"mp3", "wav"}:
        body.append(ft.Text("Audio waveform placeholder", size=t.typography.size_xs, color=t.colors.fg_muted))
    panel = ft.Container(
        content=ft.Column(body, spacing=4, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
        width=_INSPECT_PANEL_W,
        padding=8,
        border_radius=8,
        border=ft.border.all(1, t.colors.border),
        bgcolor=t.colors.bg2,
    )
    return panel, preview_slot


def metadata_match_flags(left: Optional[DuplicateFile], right: Optional[DuplicateFile]) -> list[tuple[str, str, str, str]]:
    rows = []
    fields = [
        ("Size", lambda f: f"{int(f.size)}" if f else "—"),
        ("Modified", lambda f: f"{float(getattr(f, 'modified', 0) or 0):.0f}" if f else "—"),
        ("Path", lambda f: str(f.path) if f else "—"),
        ("Hash", lambda f: str((f.metadata or {}).get("hash", "—")) if f else "—"),
    ]
    for label, fn in fields:
        lv = fn(left)
        rv = fn(right)
        match = "✓" if left and right and lv == rv else ("⚠" if left and right else "—")
        rows.append((label, lv, rv, match))
    return rows


def _metadata_rows(t: ThemeTokens, left: Optional[DuplicateFile], right: Optional[DuplicateFile]) -> ft.DataTable:
    cell_style = ft.TextStyle(size=_META_CELL_SIZE, color=t.colors.fg)
    head_style = ft.TextStyle(size=_META_HEADER_SIZE, weight=ft.FontWeight.W_600, color=t.colors.fg)
    rows = []
    for label, lv, rv, match in metadata_match_flags(left, right):
        rows.append(
            ft.DataRow(
                cells=[
                    ft.DataCell(ft.Text(label, size=_META_CELL_SIZE, color=t.colors.fg_muted)),
                    ft.DataCell(ft.Text(lv, size=_META_CELL_SIZE, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS)),
                    ft.DataCell(ft.Text(rv, size=_META_CELL_SIZE, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS)),
                    ft.DataCell(ft.Text(match, size=_META_CELL_SIZE)),
                ]
            )
        )
    return ft.DataTable(
        columns=[
            ft.DataColumn(ft.Text("Property", size=_META_HEADER_SIZE)),
            ft.DataColumn(ft.Text("Left", size=_META_HEADER_SIZE)),
            ft.DataColumn(ft.Text("Right", size=_META_HEADER_SIZE)),
            ft.DataColumn(ft.Text("Match", size=_META_HEADER_SIZE)),
        ],
        rows=rows,
        heading_row_color=ft.Colors.with_opacity(0.04, t.colors.fg),
        heading_text_style=head_style,
        data_text_style=cell_style,
        data_row_min_height=26,
        heading_row_height=30,
        horizontal_lines=ft.border.BorderSide(0, ft.Colors.TRANSPARENT),
        vertical_lines=ft.border.BorderSide(0, ft.Colors.TRANSPARENT),
    )


def _member_chip(
    t: ThemeTokens,
    i: int,
    f: DuplicateFile,
    *,
    ref_i: int,
    cmp_i: int,
    on_tap: Callable[[int], None],
    on_long_make_reference: Callable[[int], None],
) -> ft.Control:
    name = f.path.name
    if len(name) > 28:
        name = name[:25] + "…"
    is_ref = i == ref_i
    is_cmp = i == cmp_i
    if is_ref:
        border_w = 1
        border_c = t.colors.primary
        bg = ft.Colors.with_opacity(0.14, t.colors.primary)
        badge = ft.Row(
            [
                ft.Icon(ft.icons.Icons.PUSH_PIN, size=14, color=t.colors.primary),
                ft.Text("Ref", size=_META_CELL_SIZE, color=t.colors.primary, weight=ft.FontWeight.W_600),
            ],
            spacing=4,
        )
    elif is_cmp:
        border_w = 2
        border_c = t.colors.primary
        bg = t.colors.bg
        badge = ft.Text("Compare", size=_META_CELL_SIZE, color=t.colors.primary, weight=ft.FontWeight.W_600)
    else:
        border_w = 1
        border_c = ft.Colors.with_opacity(0.35, t.colors.border)
        bg = ft.Colors.with_opacity(0.04, t.colors.fg)
        badge = ft.Text("", size=_META_CELL_SIZE)

    inner = ft.Container(
        padding=ft.padding.symmetric(horizontal=10, vertical=6),
        border_radius=8,
        border=ft.border.all(border_w, border_c),
        bgcolor=bg,
        content=ft.Column(
            [
                badge,
                ft.Text(f"{i + 1}. {name}", size=_META_CELL_SIZE, color=t.colors.fg if (is_ref or is_cmp) else t.colors.fg_muted),
            ],
            spacing=2,
            tight=True,
        ),
    )

    def _tap(_e) -> None:
        on_tap(i)

    def _long(_e) -> None:
        on_long_make_reference(i)

    def _secondary(_e) -> None:
        on_long_make_reference(i)

    return ft.GestureDetector(
        mouse_cursor=ft.MouseCursor.CLICK,
        on_tap=_tap,
        on_long_press=_long,
        on_secondary_tap=_secondary,
        content=inner,
    )


def _member_scroll_strip(
    t: ThemeTokens,
    files: List[DuplicateFile],
    ref_i: int,
    cmp_i: int,
    on_tap: Callable[[int], None],
    on_long_make_reference: Callable[[int], None],
) -> Optional[ft.Control]:
    if len(files) < 2:
        return None
    chips: List[ft.Control] = [_member_chip(t, i, f, ref_i=ref_i, cmp_i=cmp_i, on_tap=on_tap, on_long_make_reference=on_long_make_reference) for i, f in enumerate(files)]
    ref_name = files[ref_i].path.name if files else ""
    cmp_name = files[cmp_i].path.name if files else ""
    hint = f"Reference: {ref_name} · tap another to compare · comparing against {cmp_name}"
    return ft.Column(
        [
            ft.Text(hint, size=_META_CELL_SIZE, color=t.colors.fg_muted),
            ft.Row(
                chips,
                scroll=ft.ScrollMode.AUTO,
                spacing=8,
                wrap=False,
            ),
            ft.Text("Long-press or right-click a chip to make it the reference.", size=_META_CELL_SIZE - 1, color=t.colors.fg_muted),
        ],
        spacing=4,
    )


def build_inspect_screen(
    t: ThemeTokens,
    state: ReviewFlowState,
    *,
    on_back,
    on_prev_set,
    on_next_set,
    on_keep_left,
    on_keep_right,
    on_keep_both,
    on_delete_all,
    on_mark_next,
    on_strip_tap,
    on_strip_long_make_reference,
    on_swap_panels,
    on_pin_compare_as_reference,
    on_step_compare,
    on_toggle_diff=None,
    on_toggle_blink=None,
    stub_only: bool = False,
) -> tuple[ft.Column, Optional[ft.Container], Optional[ft.Container]]:
    group = state.group_by_id(state.inspect_set_id or -1)
    files = list(group.files) if group else []
    n = len(files)
    ref_i, cmp_i = normalize_inspect_ref_cmp(n, state.inspect_ref_index, state.inspect_cmp_index)
    left_i, right_i = inspect_left_right_indices(state.inspect_swap_panels, ref_i, cmp_i)
    left = files[left_i] if n else None
    right = files[right_i] if n and right_i < n else None
    left_semantic_ref = not state.inspect_swap_panels
    left_role = "Reference" if left_semantic_ref else "Compare"
    right_role = "Compare" if left_semantic_ref else "Reference"

    if stub_only:
        return ft.Column(
            [
                ft.TextButton("← Duplicates", on_click=on_back),
                ft.Container(
                    expand=True,
                    alignment=ft.Alignment.CENTER,
                    content=ft.Text("Inspect screen stub — comparison arrives in Slice 2"),
                ),
                ft.FilledButton("Back to Browse", on_click=on_back),
            ],
            expand=True,
        ), None, None

    header = ft.Row(
        [
            ft.TextButton("← Duplicates", on_click=on_back),
            ft.Text(f"Set {state.inspect_set_id} of {len(state.scan_results)}", weight=ft.FontWeight.W_600),
            ft.Text(
                "[ / ] · PgUp / PgDn — prev / next set",
                size=_META_CELL_SIZE - 1,
                color=t.colors.fg_muted,
            ),
            ft.Container(expand=True),
            ft.IconButton(icon=ft.icons.Icons.ARROW_BACK, tooltip="Previous set ([ or PgUp)", on_click=on_prev_set),
            ft.IconButton(icon=ft.icons.Icons.ARROW_FORWARD, tooltip="Next set (] or PgDn)", on_click=on_next_set),
        ],
    )
    panel_left, slot_left = _preview_panel(t, left, role_label=left_role, panel_label="A (left)")
    panel_right, slot_right = _preview_panel(t, right, role_label=right_role, panel_label="B (right)")
    previews = ft.Row(
        [panel_left, panel_right],
        scroll=ft.ScrollMode.AUTO,
        spacing=12,
        alignment=ft.MainAxisAlignment.START,
    )
    cmp_nav_disabled = n <= 2
    cmp_nav = ft.Row(
        [
            ft.Text("Compare file:", size=_META_CELL_SIZE, color=t.colors.fg_muted),
            ft.IconButton(
                icon=ft.icons.Icons.CHEVRON_LEFT,
                tooltip="Previous compare file",
                disabled=cmp_nav_disabled,
                on_click=lambda _e: on_step_compare(-1),
            ),
            ft.IconButton(
                icon=ft.icons.Icons.CHEVRON_RIGHT,
                tooltip="Next compare file",
                disabled=cmp_nav_disabled,
                on_click=lambda _e: on_step_compare(1),
            ),
            ft.FilledTonalButton(
                "Pin compare as reference",
                icon=ft.icons.Icons.PUSH_PIN_OUTLINED,
                on_click=lambda _e: on_pin_compare_as_reference(),
            ),
            ft.OutlinedButton(
                "Swap panels",
                icon=ft.icons.Icons.SWAP_HORIZ,
                on_click=lambda _e: on_swap_panels(),
            ),
        ],
        spacing=4,
        wrap=True,
    )
    strip = _member_scroll_strip(t, files, ref_i, cmp_i, on_strip_tap, on_strip_long_make_reference)
    toolbar = ft.Row(
        [
            ft.Switch(
                label="Diff (ref vs cmp)",
                value=state.inspect_diff_enabled,
                on_change=on_toggle_diff,
            ),
            ft.Switch(label="Blink compare", value=state.inspect_blink_enabled, on_change=on_toggle_blink),
            ft.Text("Metadata (left / right columns)", color=t.colors.fg_muted, size=_META_CELL_SIZE),
        ],
        spacing=12,
        wrap=True,
    )
    meta_inner = _metadata_rows(t, left, right)
    meta = ft.Container(
        height=_META_MAX_H,
        padding=ft.padding.symmetric(horizontal=4, vertical=0),
        content=ft.Column(
            [meta_inner],
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        ),
    )
    actions = ft.Row(
        [
            ft.OutlinedButton("Keep left file", on_click=on_keep_left),
            ft.OutlinedButton("Keep right file", on_click=on_keep_right),
            ft.OutlinedButton("Keep both", on_click=on_keep_both),
            ft.FilledButton("Delete all in set", on_click=on_delete_all),
            ft.FilledButton("Mark & next set", on_click=on_mark_next),
        ],
        wrap=True,
    )
    inspect_body: List[ft.Control] = [header, previews, cmp_nav]
    if strip is not None:
        inspect_body.append(strip)
    inspect_body.extend([toolbar, meta, actions])
    return ft.Column(inspect_body, expand=True, spacing=10), slot_left, slot_right
