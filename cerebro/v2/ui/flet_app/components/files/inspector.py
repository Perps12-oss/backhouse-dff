"""Right-side file inspector overlay for list/grid triage surfaces."""

from __future__ import annotations

import asyncio
import base64
import datetime
import io
from pathlib import Path
from typing import Optional

import flet as ft

from cerebro.engines.base_engine import DuplicateFile
from cerebro.v2.ui.flet_app.services.thumbnail_cache import is_image_path
from cerebro.v2.ui.flet_app.theme import ThemeTokens, fmt_size


def _meta_row(icon_name: str, text_ctrl: ft.Text) -> ft.Row:
    return ft.Row(
        [
            ft.Icon(icon_name, size=12, color=ft.Colors.with_opacity(0.5, ft.Colors.WHITE)),
            text_ctrl,
        ],
        spacing=6,
        vertical_alignment=ft.CrossAxisAlignment.START,
    )


class FileInspector(ft.Container):
    """Dismissible overlay with file metadata, dimensions, and image preview."""

    def __init__(self, page: ft.Page, t: ThemeTokens) -> None:
        self._page = page
        self._t = t
        self._current_file: Optional[DuplicateFile] = None
        self._dims_generation = 0
        self._preview_generation = 0

        self._thumb = ft.Container(
            width=220,
            height=160,
            border_radius=8,
            bgcolor=ft.Colors.with_opacity(0.08, ft.Colors.WHITE),
            alignment=ft.Alignment(0, 0),
            content=ft.Icon(
                ft.icons.Icons.INSERT_DRIVE_FILE,
                size=48,
                color=ft.Colors.with_opacity(0.3, ft.Colors.WHITE),
            ),
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
        )
        self._name = ft.Text(
            "",
            size=t.typography.size_md,
            weight=ft.FontWeight.W_600,
            color=t.colors.fg,
            text_align=ft.TextAlign.CENTER,
            max_lines=2,
            overflow=ft.TextOverflow.ELLIPSIS,
        )
        self._size = ft.Text("", size=t.typography.size_sm, color="#4ADE80", weight=ft.FontWeight.W_600)
        self._date = ft.Text("", size=t.typography.size_xs, color="#BFD5FF")
        self._dims = ft.Text("", size=t.typography.size_xs, color="#C084FC")
        self._path = ft.Text(
            "",
            size=t.typography.size_xs,
            color=t.colors.fg_muted,
            max_lines=3,
            overflow=ft.TextOverflow.ELLIPSIS,
        )
        self._title = ft.Text(
            "Inspector",
            size=t.typography.size_sm,
            weight=ft.FontWeight.W_700,
            color=t.colors.fg,
            expand=True,
        )

        panel = ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            self._title,
                            ft.IconButton(
                                icon=ft.icons.Icons.CLOSE,
                                icon_size=16,
                                icon_color=t.colors.fg_muted,
                                on_click=lambda e: self.close(),
                                tooltip="Close",
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Divider(height=1, color=ft.Colors.with_opacity(0.12, ft.Colors.WHITE)),
                    self._thumb,
                    self._name,
                    _meta_row(ft.icons.Icons.STORAGE, self._size),
                    _meta_row(ft.icons.Icons.SCHEDULE, self._date),
                    _meta_row(ft.icons.Icons.ASPECT_RATIO, self._dims),
                    _meta_row(ft.icons.Icons.FOLDER_OPEN, self._path),
                ],
                spacing=t.spacing.sm,
                scroll=ft.ScrollMode.AUTO,
            ),
            width=280,
            padding=t.spacing.lg,
            bgcolor=ft.Colors.with_opacity(0.92, "#0B1220"),
            border=ft.border.only(left=ft.BorderSide(1, ft.Colors.with_opacity(0.18, ft.Colors.WHITE))),
            shadow=ft.BoxShadow(
                blur_radius=24,
                offset=ft.Offset(-4, 0),
                color=ft.Colors.with_opacity(0.35, ft.Colors.BLACK),
            ),
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
        )

        super().__init__(
            content=panel,
            alignment=ft.Alignment(1, 0),
            expand=True,
            visible=False,
        )

    @property
    def current_file(self) -> Optional[DuplicateFile]:
        return self._current_file

    def open_file(self, file: DuplicateFile) -> None:
        self._current_file = file
        p = Path(str(getattr(file, "path", "")))
        self._name.value = p.name
        self._size.value = fmt_size(file.size)
        try:
            ts = float(getattr(file, "mtime", None) or getattr(file, "modified", 0) or 0)
            self._date.value = (
                datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d  %H:%M") if ts > 0 else ""
            )
        except Exception:
            self._date.value = ""

        self._dims_generation += 1
        dims_gen = self._dims_generation
        self._dims.value = "Loading..." if is_image_path(p) else ""
        if is_image_path(p) and hasattr(self._page, "run_task"):
            self._page.run_task(self._load_dims_async, p, dims_gen)

        self._preview_generation += 1
        preview_gen = self._preview_generation
        self._path.value = str(p.parent)
        self._thumb.content = ft.Icon(
            ft.icons.Icons.INSERT_DRIVE_FILE,
            size=48,
            color=ft.Colors.with_opacity(0.3, ft.Colors.WHITE),
        )
        if is_image_path(p) and hasattr(self._page, "run_task"):
            self._page.run_task(self._load_preview_async, p, preview_gen)

        self.visible = True
        self._safe_update(self)

    def close(self) -> None:
        self._current_file = None
        self.visible = False
        self._safe_update(self)

    def sync_theme(self, t: ThemeTokens) -> None:
        self._t = t
        self._title.color = t.colors.fg
        self._name.color = t.colors.fg
        self._path.color = t.colors.fg_muted
        self._safe_update(self)

    async def _load_dims_async(self, p: Path, gen: int) -> None:
        loop = asyncio.get_event_loop()

        def _read_dims() -> str:
            try:
                from PIL import Image as _Img

                with _Img.open(p) as img:
                    return f"{img.width} × {img.height}"
            except Exception:
                return ""

        dims = await loop.run_in_executor(None, _read_dims)
        if gen != self._dims_generation:
            return
        self._dims.value = dims
        self._safe_update(self._dims)

    async def _load_preview_async(self, p: Path, gen: int) -> None:
        loop = asyncio.get_event_loop()

        def _read_preview() -> str | None:
            try:
                from PIL import Image as _Img

                with _Img.open(p) as img:
                    img = img.convert("RGB")
                    img.thumbnail((520, 360), _Img.Resampling.LANCZOS)
                    buf = io.BytesIO()
                    img.save(buf, format="JPEG", quality=88, optimize=True)
                    return base64.b64encode(buf.getvalue()).decode("ascii")
            except Exception:
                return None

        b64 = await loop.run_in_executor(None, _read_preview)
        if gen != self._preview_generation:
            return
        if b64:
            self._thumb.content = ft.Image(
                src=f"data:image/jpeg;base64,{b64}",
                width=260,
                height=190,
                fit=ft.BoxFit.CONTAIN,
                border_radius=8,
            )
            self._safe_update(self._thumb)

    @staticmethod
    def _safe_update(ctrl: ft.Control | None) -> None:
        if ctrl is None:
            return
        try:
            if ctrl.page is not None:
                ctrl.update()
        except RuntimeError:
            pass
