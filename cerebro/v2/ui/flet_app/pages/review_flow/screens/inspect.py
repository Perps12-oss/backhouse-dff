from __future__ import annotations

from pathlib import Path
from typing import Callable, List, Optional

import flet as ft

from cerebro.engines.base_engine import DuplicateFile, DuplicateGroup
from cerebro.v2.ui.flet_app.pages.review_flow.state import ReviewFlowState
from cerebro.v2.ui.flet_app.theme import ThemeTokens, fmt_size


def _file_icon(ext: str) -> str:
    ext = (ext or "").lower()
    if ext in {"jpg", "jpeg", "png", "gif", "webp"}:
        return ft.icons.Icons.IMAGE_OUTLINED
    if ext in {"mp4", "mov", "mkv"}:
        return ft.icons.Icons.MOVIE_OUTLINED
    if ext in {"mp3", "wav", "flac"}:
        return ft.icons.Icons.AUDIOTRACK
    return ft.icons.Icons.INSERT_DRIVE_FILE_OUTLINED


def _preview_panel(t: ThemeTokens, f: Optional[DuplicateFile], label: str) -> ft.Container:
    if f is None:
        return ft.Container(expand=True, bgcolor=t.colors.bg2, border_radius=8)
    ext = (f.extension or Path(str(f.path)).suffix.lstrip(".")).lower()
    body: List[ft.Control] = [
        ft.Icon(_file_icon(ext), size=48, color=t.colors.primary),
        ft.Text(f.path.name, weight=ft.FontWeight.W_600),
        ft.Text(fmt_size(int(f.size)), color=t.colors.fg_muted),
        ft.Text(str(f.path.parent), size=t.typography.size_xs, color=t.colors.fg_muted),
    ]
    if ext in {"txt", "md", "json", "py"}:
        body.append(ft.Text("Document preview placeholder", size=t.typography.size_xs, color=t.colors.fg_muted))
    if ext in {"mp4", "mov"}:
        body.append(ft.Text("Video thumbnail strip placeholder", size=t.typography.size_xs, color=t.colors.fg_muted))
    if ext in {"mp3", "wav"}:
        body.append(ft.Text("Audio waveform placeholder", size=t.typography.size_xs, color=t.colors.fg_muted))
    return ft.Container(
        content=ft.Column(body, spacing=6, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
        expand=True,
        padding=12,
        border_radius=8,
        border=ft.border.all(1, t.colors.border),
        bgcolor=t.colors.bg2,
    )


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
    rows = []
    for label, lv, rv, match in metadata_match_flags(left, right):
        rows.append(ft.DataRow(cells=[ft.DataCell(ft.Text(label)), ft.DataCell(ft.Text(lv)), ft.DataCell(ft.Text(rv)), ft.DataCell(ft.Text(match))]))
    return ft.DataTable(
        columns=[
            ft.DataColumn(ft.Text("Property")),
            ft.DataColumn(ft.Text("File A")),
            ft.DataColumn(ft.Text("File B")),
            ft.DataColumn(ft.Text("Match")),
        ],
        rows=rows,
        heading_row_color=ft.Colors.with_opacity(0.04, t.colors.fg),
    )


def build_inspect_screen(
    t: ThemeTokens,
    state: ReviewFlowState,
    *,
    on_back,
    on_prev_set,
    on_next_set,
    on_keep_a,
    on_keep_b,
    on_keep_both,
    on_delete_all,
    on_mark_next,
    on_toggle_diff=None,
    on_toggle_blink=None,
    stub_only: bool = False,
) -> ft.Column:
    group = state.group_by_id(state.inspect_set_id or -1)
    files = list(group.files) if group else []
    idx = max(0, min(state.inspect_file_index, max(0, len(files) - 1)))
    left = files[idx] if files else None
    right = files[idx + 1] if len(files) > idx + 1 else files[0] if len(files) == 1 else None
    if stub_only:
        return ft.Column(
            [
                ft.TextButton("← Duplicates", on_click=on_back),
                ft.Container(expand=True, alignment=ft.Alignment.CENTER, content=ft.Text("Inspect screen stub — comparison arrives in Slice 2")),
                ft.FilledButton("Back to Browse", on_click=on_back),
            ],
            expand=True,
        )
    header = ft.Row(
        [
            ft.TextButton("← Duplicates", on_click=on_back),
            ft.Text(f"Set {state.inspect_set_id} of {len(state.scan_results)}", weight=ft.FontWeight.W_600),
            ft.Container(expand=True),
            ft.IconButton(icon=ft.icons.Icons.ARROW_BACK, on_click=on_prev_set),
            ft.IconButton(icon=ft.icons.Icons.ARROW_FORWARD, on_click=on_next_set),
        ],
    )
    previews = ft.Row([_preview_panel(t, left, "A"), _preview_panel(t, right, "B")], expand=True, spacing=12)
    toolbar = ft.Row(
        [
            ft.Switch(label="Diff", value=state.inspect_diff_enabled, on_change=on_toggle_diff),
            ft.Switch(label="Blink", value=state.inspect_blink_enabled, on_change=on_toggle_blink),
            ft.Text("Metadata", color=t.colors.fg_muted),
        ],
        spacing=12,
    )
    meta = ft.Container(content=_metadata_rows(t, left, right), padding=8)
    actions = ft.Row(
        [
            ft.OutlinedButton("Keep A", on_click=on_keep_a),
            ft.OutlinedButton("Keep B", on_click=on_keep_b),
            ft.OutlinedButton("Keep Both", on_click=on_keep_both),
            ft.FilledButton("Delete All", on_click=on_delete_all),
            ft.FilledButton("Mark & Next", on_click=on_mark_next),
        ],
        wrap=True,
    )
    return ft.Column([header, previews, toolbar, meta, actions], expand=True, spacing=10)
