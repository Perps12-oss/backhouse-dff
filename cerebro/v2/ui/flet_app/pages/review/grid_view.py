"""Grid mode: tile grid, async thumbnails, zoom pills, rendering badge."""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Dict, List, Set

import flet as ft

from cerebro.engines.base_engine import DuplicateFile
from cerebro.v2.ui.flet_app.pages.review._types import RC
from cerebro.v2.ui.flet_app.services.thumbnail_cache import get_thumbnail_cache
from cerebro.v2.ui.flet_app.pill_button_styles import pill_text_button_selected, pill_text_button_style
from cerebro.v2.ui.flet_app.theme import ThemeTokens, fmt_size

if TYPE_CHECKING:
    from cerebro.v2.ui.flet_app.services.state_bridge import StateBridge

_log = logging.getLogger(__name__)

_GRID_BUILD_ASYNC_THRESHOLD = 220
_GRID_FIRST_SYNC_FILES = 20
_GRID_ASYNC_BATCH = 30
_UI_SLOW_MS = 80.0


class ReviewGridView(ft.Stack):
    """Tile grid with async thumbnail loading, zoom controls, and rendering badge."""

    def __init__(
        self,
        bridge: "StateBridge",
        t: ThemeTokens,
        *,
        reduce_motion: bool,
        on_tile_clicked: Callable[[DuplicateFile], None],
        on_toggle_mark: Callable[[DuplicateFile], None],
        is_grid_mode: Callable[[], bool],
        initial_extent: int = 160,
    ) -> None:
        self._bridge = bridge
        self._t = t
        self._reduce_motion = reduce_motion
        self._on_tile_clicked = on_tile_clicked
        self._on_toggle_mark = on_toggle_mark
        self._is_grid_mode = is_grid_mode

        self._grid_extent = initial_extent
        self._tile_cache: Dict[str, ft.Container] = {}
        self._thumb_slots: Dict[str, ft.Container] = {}
        self._mark_checkboxes: Dict[str, ft.Checkbox] = {}
        self._grid_build_generation = 0
        self._thumb_load_generation = 0

        self._grid = ft.GridView(
            expand=True,
            runs_count=5,
            max_extent=self._grid_extent,
            child_aspect_ratio=1.0,
            spacing=t.spacing.sm,
            run_spacing=t.spacing.sm,
            padding=t.spacing.lg,
        )
        self._rendering_badge = ft.Container(
            alignment=ft.Alignment(-1, -1),
            margin=ft.margin.only(top=t.spacing.sm, right=t.spacing.md),
            visible=False,
            content=ft.Container(
                content=ft.Row(
                    [
                        ft.ProgressRing(width=14, height=14, stroke_width=2, color=RC.side_a),
                        ft.Text("View ready - filling items...", size=t.typography.size_xs, color="#9FDDF7"),
                    ],
                    spacing=6,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                bgcolor=ft.Colors.with_opacity(0.82, "#09111D"),
                border=ft.border.all(1, ft.Colors.with_opacity(0.25, RC.side_a)),
                border_radius=999,
                padding=ft.padding.symmetric(horizontal=10, vertical=6),
            ),
        )

        self._zoom_btn_s: ft.TextButton | None = None
        self._zoom_btn_m: ft.TextButton | None = None
        self._zoom_btn_l: ft.TextButton | None = None
        self._zoom_row = self._build_zoom_row()

        super().__init__(
            [
                ft.Container(content=self._grid, expand=True),
                ft.Container(
                    content=self._rendering_badge,
                    alignment=ft.Alignment(1, -1),
                    padding=ft.padding.only(top=t.spacing.sm, right=t.spacing.md),
                ),
            ],
            expand=True,
        )

    @property
    def grid(self) -> ft.GridView:
        return self._grid

    @property
    def zoom_row(self) -> ft.Row:
        return self._zoom_row

    def set_reduce_motion(self, value: bool) -> None:
        self._reduce_motion = value

    def sync_theme(self, t: ThemeTokens) -> None:
        self._t = t
        self._grid.spacing = t.spacing.sm
        self._grid.run_spacing = t.spacing.sm
        self._grid.padding = t.spacing.lg

    def clear_tile_caches(self) -> None:
        self._tile_cache.clear()
        self._thumb_slots.clear()
        self._mark_checkboxes.clear()

    def bump_thumb_generation(self) -> None:
        self._thumb_load_generation += 1

    def on_zoom_size_click(self, extent: int, _e: ft.ControlEvent | None = None) -> None:
        self._grid_extent = extent
        self._grid.max_extent = extent
        self.sync_zoom_pill_styles(self._t)
        ReviewGridView._safe_update(self._grid)

    def sync_zoom_pill_styles(self, t: ThemeTokens) -> None:
        for extent, btn in (
            (120, self._zoom_btn_s),
            (160, self._zoom_btn_m),
            (210, self._zoom_btn_l),
        ):
            if btn is None:
                continue
            btn.style = pill_text_button_selected(t) if self._grid_extent == extent else pill_text_button_style(t, variant="muted")
            ReviewGridView._safe_update(btn)

    def _build_zoom_row(self) -> ft.Row:
        t = self._t
        self._zoom_btn_s = ft.TextButton(
            "S",
            on_click=lambda e: self.on_zoom_size_click(120, e),
            style=pill_text_button_selected(t) if self._grid_extent == 120 else pill_text_button_style(t, variant="muted"),
        )
        self._zoom_btn_m = ft.TextButton(
            "M",
            on_click=lambda e: self.on_zoom_size_click(160, e),
            style=pill_text_button_selected(t) if self._grid_extent == 160 else pill_text_button_style(t, variant="muted"),
        )
        self._zoom_btn_l = ft.TextButton(
            "L",
            on_click=lambda e: self.on_zoom_size_click(210, e),
            style=pill_text_button_selected(t) if self._grid_extent == 210 else pill_text_button_style(t, variant="muted"),
        )
        return ft.Row(
            [
                ft.Text("Size:", size=9, color=self._t.colors.fg_muted),
                self._zoom_btn_s,
                self._zoom_btn_m,
                self._zoom_btn_l,
            ],
            spacing=4,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    @staticmethod
    def _safe_update(ctrl: ft.Control | None) -> None:
        if ctrl is None:
            return
        try:
            if ctrl.page is not None:
                ctrl.update()
        except RuntimeError:
            pass

    @staticmethod
    def _log_if_slow(label: str, started_at: float) -> None:
        elapsed_ms = (time.perf_counter() - started_at) * 1000.0
        if elapsed_ms > _UI_SLOW_MS:
            _log.debug("[UI_SLOW] %s took %.1f ms", label, elapsed_ms)

    def set_rendering(self, value: bool) -> None:
        self._grid_build_generation += 1
        gen = self._grid_build_generation
        self._rendering_badge.visible = value
        self._safe_update(self._rendering_badge)
        if value:
            page = self._bridge.flet_page
            if hasattr(page, "run_task"):
                page.run_task(self._rendering_failsafe_async, gen)

    async def _rendering_failsafe_async(self, gen: int) -> None:
        await asyncio.sleep(1.6)
        if gen != self._grid_build_generation:
            return
        if self._rendering_badge.visible:
            self._rendering_badge.visible = False
            self._safe_update(self._rendering_badge)

    def refresh_marks(self, marked_paths: Set[str]) -> None:
        for key, cb in self._mark_checkboxes.items():
            cb.value = key in marked_paths
            self._safe_update(cb)

    def refresh(self, files: List[DuplicateFile], marked_paths: Set[str]) -> None:
        _t0 = time.perf_counter()
        self.bump_thumb_generation()
        load_gen = self._thumb_load_generation
        n = len(files)
        if n <= _GRID_BUILD_ASYNC_THRESHOLD:
            self._grid.controls = [self._tile_for_file_placeholder(f, marked_paths) for f in files]
            self.set_rendering(False)
            self._safe_update(self._grid)
            page = self._bridge.flet_page
            if files and hasattr(page, "run_task"):
                page.run_task(self._load_thumbnails_async, list(files), load_gen)
            self._log_if_slow("review:grid_refresh", _t0)
            return

        self.set_rendering(True)
        gen = self._grid_build_generation
        head_n = min(_GRID_FIRST_SYNC_FILES, n)
        head = files[:head_n]
        tail = files[head_n:]
        self._grid.controls = [self._tile_for_file_placeholder(f, marked_paths) for f in head]
        self._safe_update(self._grid)
        try:
            self._grid.update()
        except Exception:
            pass
        page = self._bridge.flet_page
        if tail and hasattr(page, "run_task"):
            page.run_task(self._append_grid_tiles_async, tail, gen, list(files), marked_paths)
        elif tail:
            self._grid.controls.extend([self._tile_for_file_placeholder(f, marked_paths) for f in tail])
            self._safe_update(self._grid)
            self.set_rendering(False)
            if files and hasattr(page, "run_task"):
                page.run_task(self._load_thumbnails_async, list(files), load_gen)
        self._log_if_slow("review:grid_refresh", _t0)

    async def _append_grid_tiles_async(
        self,
        tail: List[DuplicateFile],
        gen: int,
        all_files: List[DuplicateFile],
        marked_paths: Set[str],
    ) -> None:
        for i in range(0, len(tail), _GRID_ASYNC_BATCH):
            if gen != self._grid_build_generation:
                self.set_rendering(False)
                return
            chunk = tail[i : i + _GRID_ASYNC_BATCH]
            self._grid.controls.extend([self._tile_for_file_placeholder(f, marked_paths) for f in chunk])
            try:
                self._grid.update()
            except Exception:
                pass
            await asyncio.sleep(0)
        if gen == self._grid_build_generation:
            self.set_rendering(False)
            page = self._bridge.flet_page
            if all_files and hasattr(page, "run_task"):
                page.run_task(self._load_thumbnails_async, list(all_files), self._thumb_load_generation)

    def _tile_for_file_placeholder(self, f: DuplicateFile, marked_paths: Set[str]) -> ft.Container:
        t = self._t
        p = Path(str(f.path))
        key = str(getattr(f, "path", ""))

        info_bar = ft.Container(
            content=ft.Column(
                [
                    ft.Text(
                        p.name,
                        size=t.typography.size_xs,
                        color="#FFFFFF",
                        overflow=ft.TextOverflow.ELLIPSIS,
                        max_lines=1,
                        text_align=ft.TextAlign.CENTER,
                    ),
                    ft.Text(
                        fmt_size(f.size),
                        size=t.typography.size_xs,
                        color=ft.Colors.with_opacity(0.75, "#FFFFFF"),
                    ),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=2,
            ),
            bgcolor=ft.Colors.with_opacity(0.72, RC.tile_bg),
            padding=ft.padding.symmetric(horizontal=6, vertical=4),
            animate_opacity=(None if self._reduce_motion else ft.Animation(150, ft.AnimationCurve.EASE_IN_OUT)),
            opacity=0,
        )

        placeholder = ft.Container(
            content=ft.Icon(ft.icons.Icons.INSERT_DRIVE_FILE, size=48, color=ft.Colors.with_opacity(0.3, ft.Colors.WHITE)),
            expand=True,
            alignment=ft.Alignment(0, 0),
            bgcolor=ft.Colors.with_opacity(0.06, ft.Colors.WHITE),
        )
        thumb_slot = ft.Container(content=placeholder, expand=True, clip_behavior=ft.ClipBehavior.HARD_EDGE)

        cb = ft.Checkbox(
            value=key in marked_paths,
            on_change=lambda e, file=f: self._on_toggle_mark(file),
            active_color=RC.danger,
        )
        self._mark_checkboxes[key] = cb

        stack = ft.Stack(
            [
                thumb_slot,
                ft.Column([ft.Container(expand=True), info_bar], expand=True, spacing=0),
                ft.Container(
                    alignment=ft.Alignment(-1, -1),
                    padding=ft.padding.only(left=6, top=6),
                    content=cb,
                ),
            ],
            expand=True,
        )

        def _hover(e: ft.ControlEvent) -> None:
            enter = e.data == "true"
            info_bar.opacity = 1 if enter else 0
            tile.border = (
                ft.border.all(2, RC.side_a)
                if enter
                else ft.border.all(1, ft.Colors.with_opacity(0.12, ft.Colors.WHITE))
            )
            self._safe_update(info_bar)
            self._safe_update(tile)

        tile = ft.Container(
            content=stack,
            border_radius=ft.border_radius.all(10),
            border=ft.border.all(1, ft.Colors.with_opacity(0.12, ft.Colors.WHITE)),
            bgcolor=ft.Colors.with_opacity(0.06, ft.Colors.WHITE),
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
            ink=True,
            on_click=lambda e, file=f: self._on_tile_clicked(file),
            on_hover=_hover,
        )
        self._thumb_slots[key] = thumb_slot
        self._tile_cache[key] = tile
        return tile

    async def _load_thumbnails_async(self, files: List[DuplicateFile], load_gen: int) -> None:
        pending: list[tuple[ft.Container, str]] = []

        async def _on_ready(path: Path, b64: str | None) -> None:
            if load_gen != self._thumb_load_generation or not self._is_grid_mode():
                return
            if not b64:
                return
            key = str(path)
            if key not in self._tile_cache:
                return
            thumb_slot = self._thumb_slots.get(key)
            if thumb_slot is None:
                return
            pending.append((thumb_slot, b64))
            if len(pending) >= 8:
                _apply_t0 = time.perf_counter()
                for slot, thumb_b64 in pending:
                    slot.content = ft.Image(
                        src=f"data:image/jpeg;base64,{thumb_b64}",
                        width=96,
                        height=96,
                        fit=ft.BoxFit.CONTAIN,
                        border_radius=8,
                    )
                pending.clear()
                if load_gen == self._thumb_load_generation and self._is_grid_mode():
                    self._safe_update(self._grid)
                self._log_if_slow("review:thumbnail_batch_apply", _apply_t0)
                await asyncio.sleep(0)

        paths = [Path(str(f.path)) for f in files]
        await get_thumbnail_cache().load_batch_async(paths, _on_ready)
        if load_gen != self._thumb_load_generation or not self._is_grid_mode():
            return
        if pending:
            _apply_t0 = time.perf_counter()
            for slot, thumb_b64 in pending:
                slot.content = ft.Image(
                    src=f"data:image/jpeg;base64,{thumb_b64}",
                    width=96,
                    height=96,
                    fit=ft.BoxFit.CONTAIN,
                    border_radius=8,
                )
            if load_gen == self._thumb_load_generation and self._is_grid_mode():
                self._safe_update(self._grid)
            self._log_if_slow("review:thumbnail_batch_apply", _apply_t0)

