"""Compare mode: nav bar, group list, A/B panels, progress and marked summary."""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional

import flet as ft

from cerebro.engines.base_engine import DuplicateFile
from cerebro.v2.ui.flet_app.pages.review._types import RC
from cerebro.v2.ui.flet_app.pages.review.compare_delegate import ReviewCompareDelegate
from cerebro.v2.ui.flet_app.pages.review.group_list import GroupListPanel
from cerebro.v2.ui.flet_app.services.thumbnail_cache import get_thumbnail_cache, is_image_path
from cerebro.v2.ui.flet_app.pill_button_styles import pill_text_button_style
from cerebro.v2.ui.flet_app.theme import ThemeTokens, fmt_size

if TYPE_CHECKING:
    from cerebro.v2.ui.flet_app.services.state_bridge import StateBridge

_log = logging.getLogger(__name__)
_UI_SLOW_MS = 80.0

_LEFT_NAV_WIDTH = 236


class ReviewCompareView:
    """Compare UI: top ``cmp_bar`` plus scrollable body (group list + A/B)."""

    def __init__(self, delegate: ReviewCompareDelegate, bridge: "StateBridge", t: ThemeTokens) -> None:
        self._del = delegate
        self._bridge = bridge
        self._t = t
        self._compare_render_generation = 0
        self._compare_thumb_slots: Dict[str, ft.Container] = {}

        self._cmp_title = ft.Text("", size=t.typography.size_sm, color=t.colors.fg, weight=ft.FontWeight.W_600)
        self._hero_delete_marked = ft.FilledButton(
            "Delete marked (0 files)",
            icon=ft.icons.Icons.DELETE_FOREVER,
            on_click=self._del.delete_marked_files,
            disabled=True,
            style=ft.ButtonStyle(
                bgcolor=t.colors.danger,
                color="#FFFFFF",
                icon_color="#FFFFFF",
                overlay_color=ft.Colors.with_opacity(0.22, t.colors.danger_hover),
                padding=ft.padding.symmetric(horizontal=28, vertical=16),
                shape=ft.RoundedRectangleBorder(radius=12),
                text_style=ft.TextStyle(size=15, weight=ft.FontWeight.W_800),
            ),
            tooltip="Confirm and remove every file marked for deletion (Trash or permanent, per dialog).",
        )
        self._btn_cmp_grid = ft.TextButton("← Grid", on_click=self._del.to_grid, style=pill_text_button_style(t))
        self._btn_cmp_prev = ft.TextButton("← Prev", on_click=self._del.prev_group, style=pill_text_button_style(t))
        self._btn_cmp_next = ft.TextButton(
            "Next →",
            on_click=self._del.next_group,
            style=pill_text_button_style(t, variant="primary"),
        )
        self.cmp_bar = self._build_cmp_bar_container(t)

        self._group_list = GroupListPanel(t)
        self._group_list_panel = self._group_list.list_view
        self._group_list_scroll_host = ft.Container(
            content=self._group_list_panel,
            expand=True,
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
        )
        left_panel = self._build_left_nav_panel(t)
        self._compare_panel_a = ft.Container(expand=True, padding=t.spacing.md, **self._del.get_glass_style(0.04))
        self._compare_panel_b = ft.Container(expand=True, padding=t.spacing.md, **self._del.get_glass_style(0.04))
        right_view = self._build_ab_row_container(t)
        self._init_progress_and_marked_strip(t)
        self._compare_main_row = ft.Row(
            [left_panel, right_view],
            expand=True,
            vertical_alignment=ft.CrossAxisAlignment.START,
            spacing=t.spacing.sm,
        )
        self.body = ft.Column(
            [
                ft.Container(content=self._compare_main_row, expand=True),
                ft.Container(
                    content=ft.Column([self._progress_bar, self._progress_lbl], spacing=6),
                    padding=ft.padding.symmetric(horizontal=t.spacing.sm),
                ),
                self._marked_bar,
            ],
            expand=True,
            visible=False,
        )

    def _build_cmp_bar_container(self, t: ThemeTokens) -> ft.Container:
        return ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            self._btn_cmp_grid,
                            self._btn_cmp_prev,
                            self._btn_cmp_next,
                            ft.Container(content=self._cmp_title, expand=True),
                        ],
                        wrap=True,
                        spacing=t.spacing.xs,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Container(
                        content=self._hero_delete_marked,
                        padding=ft.padding.only(top=t.spacing.sm),
                        alignment=ft.Alignment(0, 0),
                    ),
                ],
                spacing=t.spacing.xs,
            ),
            visible=False,
            padding=t.spacing.sm,
            **self._del.get_glass_style(0.04),
        )

    def _build_left_nav_panel(self, t: ThemeTokens) -> ft.Container:
        return ft.Container(
            width=_LEFT_NAV_WIDTH,
            padding=t.spacing.sm,
            content=ft.Column(
                [
                    ft.Text("Jump to group", size=t.typography.size_sm, weight=ft.FontWeight.W_700),
                    self._group_list_scroll_host,
                ],
                spacing=t.spacing.xs,
                expand=True,
            ),
            **self._del.get_glass_style(0.04),
        )

    def _build_ab_row_container(self, t: ThemeTokens) -> ft.Container:
        return ft.Container(
            content=ft.Row(
                [
                    self._compare_panel_a,
                    ft.Container(
                        content=ft.VerticalDivider(width=1, color=t.colors.border3, thickness=2),
                        padding=ft.padding.symmetric(horizontal=t.spacing.sm),
                    ),
                    self._compare_panel_b,
                ],
                expand=True,
                spacing=0,
            ),
            expand=True,
        )

    def _init_progress_and_marked_strip(self, t: ThemeTokens) -> None:
        self._progress_bar = ft.ProgressBar(
            value=0,
            color=t.colors.accent,
            bgcolor=ft.Colors.with_opacity(0.14, t.colors.border),
        )
        self._progress_lbl = ft.Text("", size=t.typography.size_sm, color=t.colors.fg2)
        self._marked_lbl = ft.Text("", size=t.typography.size_sm, color=RC.marked_label_soft)
        self._marked_safety_lbl = ft.Text(
            "Deletion always asks for confirmation. Prefer Move to Trash when offered.",
            size=t.typography.size_xs,
            color=t.colors.fg_muted,
        )
        self._marked_bar = ft.Container(
            visible=False,
            padding=ft.padding.symmetric(horizontal=t.spacing.md, vertical=t.spacing.sm),
            bgcolor=ft.Colors.with_opacity(0.95, RC.marked_bar_bg),
            border=ft.border.only(top=ft.BorderSide(1, RC.danger)),
            content=ft.Column(
                [
                    ft.Container(content=self._marked_lbl, expand=True),
                    self._marked_safety_lbl,
                ],
                spacing=t.spacing.xs,
                tight=True,
            ),
        )

    @property
    def group_list(self) -> GroupListPanel:
        return self._group_list

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

    def sync_theme(self, t: ThemeTokens) -> None:
        self._t = t
        self._group_list.sync_theme(t)
        self._marked_safety_lbl.color = t.colors.fg_muted
        self._progress_lbl.color = t.colors.fg2
        self._progress_bar.color = t.colors.accent
        self._progress_bar.bgcolor = ft.Colors.with_opacity(0.14, t.colors.border)
        st = self._hero_delete_marked.style
        if isinstance(st, ft.ButtonStyle):
            self._hero_delete_marked.style = ft.ButtonStyle(
                bgcolor=t.colors.danger,
                color="#FFFFFF",
                icon_color="#FFFFFF",
                overlay_color=ft.Colors.with_opacity(0.22, t.colors.danger_hover),
                padding=st.padding,
                shape=st.shape,
                text_style=st.text_style,
            )

    def apply_cmp_bar_glass(self) -> None:
        g = self._del.get_glass_style(0.04)
        self.cmp_bar.bgcolor = g.get("bgcolor")
        self.cmp_bar.border = g.get("border")

    def refresh_group_list_panel(self) -> None:
        self._group_list.refresh(
            groups=self._del.groups,
            compare_gid=self._del.compare_gid,
            on_pick=self._del.enter_compare,
            safe_update=ReviewCompareView._safe_update,
        )

    def update_compare_panels(self) -> None:
        _t0 = time.perf_counter()
        self._compare_render_generation += 1
        gen = self._compare_render_generation
        self._compare_thumb_slots.clear()
        self._compare_panel_a.content = self._build_compare_side(self._del.compare_a, "A", gen)
        self._compare_panel_b.content = self._build_compare_side(self._del.compare_b, "B", gen)
        self.apply_compare_panel_tints()
        self._safe_update(self._compare_panel_a)
        self._safe_update(self._compare_panel_b)
        self.update_progress_and_marked_bar()
        self._log_if_slow("review:compare_panel_update", _t0)

    def apply_compare_panel_tints(self) -> None:
        self._compare_panel_a.bgcolor = ft.Colors.with_opacity(0.10, RC.side_a)
        self._compare_panel_a.border = ft.border.all(1, ft.Colors.with_opacity(0.38, RC.side_a))
        self._compare_panel_b.bgcolor = ft.Colors.with_opacity(0.10, RC.side_b)
        self._compare_panel_b.border = ft.border.all(1, ft.Colors.with_opacity(0.38, RC.side_b))

    def reset_compare_panels_idle_chrome(self) -> None:
        g = self._del.get_glass_style(0.04)
        self._compare_panel_a.bgcolor = g.get("bgcolor")
        self._compare_panel_a.border = g.get("border")
        self._compare_panel_b.bgcolor = g.get("bgcolor")
        self._compare_panel_b.border = g.get("border")

    def update_compare_chrome(self) -> None:
        gid = self._del.compare_gid
        if gid is None:
            return
        idx = next((i for i, g in enumerate(self._del.groups) if g.group_id == gid), 0)
        total = len(self._del.groups)
        count = len(self._del.group_files.get(gid, []))
        name_a = Path(str(getattr(self._del.compare_a, "path", ""))).name if self._del.compare_a else "(A)"
        name_b = Path(str(getattr(self._del.compare_b, "path", ""))).name if self._del.compare_b else "(no peer)"
        g = self._del.groups[idx] if 0 <= idx < len(self._del.groups) else None
        sim_note = ""
        if g is not None:
            sim = (getattr(g, "similarity_type", None) or "exact").lower()
            sim_note = " · exact match" if sim == "exact" else f" · {sim}"
        self._cmp_title.value = (
            f"Group {idx + 1}/{total} · {count} files{sim_note} · {name_a}"
            + (f" vs {name_b}" if name_b != name_a else "")
        )
        self._safe_update(self._cmp_title)

    def update_progress_and_marked_bar(self) -> None:
        reviewed = len(self._del.reviewed_group_ids)
        total = max(1, len(self._del.groups))
        self._progress_bar.value = min(1.0, reviewed / total)
        marked_bytes = self._del.marked_bytes
        remaining = max(0, sum(g.reclaimable for g in self._del.groups) - marked_bytes)
        self._progress_lbl.value = (
            f"{reviewed} of {len(self._del.groups)} reviewed · {fmt_size(marked_bytes)} marked · {fmt_size(remaining)} remaining"
        )
        n_marked = len(self._del.marked_paths)
        if self._del.mode == "compare":
            self._marked_lbl.value = (
                f"{fmt_size(marked_bytes)} marked for removal ({n_marked} file(s)). "
                "Adjust marks with each checkbox. Use the Delete marked button above to confirm removal."
            )
        else:
            self._marked_lbl.value = f"{fmt_size(marked_bytes)} marked for removal across {n_marked} file(s)"
        self._marked_bar.visible = bool(self._del.marked_paths) or self._del.mode == "compare"
        lbl = f"Delete marked ({n_marked} file{'s' if n_marked != 1 else ''})"
        self._hero_delete_marked.text = lbl
        self._hero_delete_marked.disabled = n_marked == 0
        self._safe_update(self._progress_bar)
        self._safe_update(self._progress_lbl)
        self._safe_update(self._marked_lbl)
        self._safe_update(self._marked_bar)
        self._safe_update(self._hero_delete_marked)

    def _compare_side_empty_column(self, label: str, t: ThemeTokens) -> ft.Column:
        return ft.Column(
            [ft.Text(f"Side {label}: No peer file", color=t.colors.fg_muted)],
            alignment=ft.MainAxisAlignment.CENTER,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            expand=True,
        )

    def _exact_dup_banner_if_needed(self, label: str, t: ThemeTokens) -> ft.Control | None:
        if label != "A":
            return None
        if not (
            self._del.compare_a
            and self._del.compare_b
            and self._del.compare_a.size == self._del.compare_b.size
            and Path(str(self._del.compare_a.path)).name == Path(str(self._del.compare_b.path)).name
        ):
            return None
        grp = next((g for g in self._del.groups if g.group_id == self._del.compare_gid), None)
        if grp is None or (getattr(grp, "similarity_type", None) or "exact").lower() != "exact":
            return None
        return ft.Container(
            content=ft.Text(
                "Same name and size — engine matched these as exact duplicates. Compare paths below.",
                size=t.typography.size_xs,
                color=t.colors.fg_muted,
                text_align=ft.TextAlign.CENTER,
            ),
            padding=ft.padding.symmetric(horizontal=8, vertical=4),
        )

    def _slim_path_size_under_thumb(self, f: DuplicateFile, p: Path, t: ThemeTokens) -> ft.Column:
        path_txt = ft.Text(
            str(p),
            size=t.typography.size_xs,
            color=RC.muted_text,
            max_lines=2,
            overflow=ft.TextOverflow.ELLIPSIS,
            text_align=ft.TextAlign.CENTER,
            tooltip=str(p),
        )
        size_txt = ft.Text(
            fmt_size(f.size),
            size=t.typography.size_xs,
            weight=ft.FontWeight.W_600,
            color=t.colors.fg2,
            text_align=ft.TextAlign.CENTER,
        )
        return ft.Column(
            [
                ft.Divider(height=1, color=ft.Colors.with_opacity(0.2, t.colors.border)),
                path_txt,
                size_txt,
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=4,
            tight=True,
        )

    def _build_compare_side(self, f: Optional[DuplicateFile], label: str, gen: int) -> ft.Column:
        t = self._t
        label_color = RC.side_a if label == "A" else RC.side_b
        if not f:
            return self._compare_side_empty_column(label, t)
        p = Path(str(f.path))
        marked = str(f.path) in self._del.marked_paths
        name = p.name
        thumb_inner = ft.Container(
            content=ft.Icon(ft.icons.Icons.INSERT_DRIVE_FILE, size=56, color=ft.Colors.with_opacity(0.35, ft.Colors.WHITE)),
            expand=True,
            alignment=ft.Alignment.CENTER,
        )
        thumb_slot = ft.Container(
            content=thumb_inner,
            expand=True,
            alignment=ft.Alignment.CENTER,
            bgcolor=ft.Colors.with_opacity(0.06, ft.Colors.WHITE),
            border_radius=8,
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
        )
        label_badge = ft.Container(
            content=ft.Text(
                f"Side {label}",
                size=t.typography.size_sm,
                weight=ft.FontWeight.BOLD,
                color=label_color,
            ),
            bgcolor=ft.Colors.with_opacity(0.12, label_color),
            border=ft.border.all(1, ft.Colors.with_opacity(0.35, label_color)),
            border_radius=6,
            padding=ft.padding.symmetric(horizontal=10, vertical=4),
        )

        slim_meta = self._slim_path_size_under_thumb(f, p, t)

        key = f"{label}:{gen}"
        self._compare_thumb_slots[key] = thumb_slot
        page = self._bridge.flet_page
        if hasattr(page, "run_task"):
            page.run_task(self._populate_compare_media_async, f, p, key, gen)

        head: list[ft.Control] = [label_badge]
        banner = self._exact_dup_banner_if_needed(label, t)
        if banner is not None:
            head.append(banner)

        return ft.Column(
            head
            + [
                thumb_slot,
                ft.Text(name, size=t.typography.size_md, weight=ft.FontWeight.W_600, color=t.colors.fg),
                slim_meta,
                ft.Checkbox(
                    label="Mark for deletion",
                    value=marked,
                    active_color=RC.danger,
                    on_change=lambda e, file=f: self._del.toggle_mark_file(file),
                ),
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=t.spacing.sm,
            alignment=ft.MainAxisAlignment.START,
            expand=True,
        )

    async def _populate_compare_media_async(self, f: DuplicateFile, p: Path, key: str, gen: int) -> None:
        loop = asyncio.get_event_loop()

        def _dims_tooltip() -> str:
            if not is_image_path(p):
                return ""
            try:
                from PIL import Image

                with Image.open(p) as img:
                    return f"{img.width} × {img.height}px"
            except Exception:
                return ""

        b64 = None
        if is_image_path(p):
            try:
                b64 = await loop.run_in_executor(
                    None, lambda: get_thumbnail_cache().get_compare_preview_base64(p)
                )
            except Exception:
                b64 = None
        dims_tip = await loop.run_in_executor(None, _dims_tooltip)

        if gen != self._compare_render_generation:
            return
        slot = self._compare_thumb_slots.get(key)
        if slot is None or not b64:
            return
        tip = f"Pinch or scroll to zoom. Image size: {dims_tip}" if dims_tip else "Pinch or scroll to zoom"
        img = ft.Image(
            src=f"data:image/jpeg;base64,{b64}",
            expand=True,
            fit=ft.BoxFit.COVER,
            filter_quality=ft.FilterQuality.HIGH,
            border_radius=8,
            cache_width=1600,
            cache_height=1200,
            tooltip=tip,
        )
        viewer = ft.InteractiveViewer(
            content=img,
            min_scale=0.85,
            max_scale=3.5,
            boundary_margin=ft.margin.all(20),
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
            expand=True,
        )
        slot.content = viewer
        self._safe_update(slot)

    # --- Pill targets (ReviewPageChromeMixin._apply_pill_chrome) ---
    # Bisect/partial checkout: do not pair this file with an older review_mixins that
    # still styles delete_btn/keep_btn — those controls were removed; use hero_delete_marked_btn.
    # Checkout compare_view + compare_delegate + shell_attach + review_mixins + review_page together.
    @property
    def btn_cmp_grid(self) -> ft.TextButton:
        return self._btn_cmp_grid

    @property
    def btn_cmp_prev(self) -> ft.TextButton:
        return self._btn_cmp_prev

    @property
    def btn_cmp_next(self) -> ft.TextButton:
        return self._btn_cmp_next

    @property
    def hero_delete_marked_btn(self) -> ft.FilledButton:
        return self._hero_delete_marked
