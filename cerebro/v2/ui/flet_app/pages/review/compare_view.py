"""Compare mode: cmp bar + minimal A/B workspace (fixed layout for Flet desktop)."""

from __future__ import annotations

import datetime
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional

import flet as ft

from cerebro.engines.base_engine import DuplicateFile
from cerebro.v2.ui.flet_app.pages.review._types import RC
from cerebro.v2.ui.flet_app.pages.review.compare_delegate import ReviewCompareDelegate
from cerebro.v2.ui.flet_app.pages.review.group_list import GroupListPanel
from cerebro.v2.ui.flet_app.services.thumbnail_cache import is_image_path
from cerebro.v2.ui.flet_app.pill_button_styles import pill_text_button_style
from cerebro.v2.ui.flet_app.components.files.group_filmstrip import GroupFilmstrip
from cerebro.v2.ui.flet_app.design_system.accents import METADATA, WARNING
from cerebro.v2.ui.flet_app.design_system.glass import glass_container
from cerebro.v2.ui.flet_app.theme import ThemeTokens, fmt_size

if TYPE_CHECKING:
    from cerebro.v2.ui.flet_app.services.state_bridge import StateBridge

_log = logging.getLogger(__name__)
_UI_SLOW_MS = 80.0

# Compare body is only mounted when CEREBRO_ENABLE_COMPARE=1 (off by default on Flet desktop).
_COMPARE_PREVIEW_SLOT_HEIGHT = 80
_COMPARE_PREVIEW_SLOT_WIDTH = 80
_COMPARE_ROW_HEIGHT = 96
_COMPARE_PANEL_W = 96
_TEXT_DIFF_MAX_BYTES = 2 * 1024 * 1024


class ReviewCompareView:
    """Compare UI: ``cmp_bar`` plus a minimal body (A/B row, progress, marked strip)."""

    def __init__(self, delegate: ReviewCompareDelegate, bridge: "StateBridge", t: ThemeTokens) -> None:
        self._del = delegate
        self._bridge = bridge
        self._t = t
        self._compare_mark_checkboxes: Dict[str, ft.Checkbox] = {}

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
                padding=ft.Padding.symmetric(horizontal=28, vertical=16),
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
        self._compare_details_enabled = False
        self._details_switch = ft.Switch(
            label="Compare details",
            value=False,
            on_change=self._on_compare_details_toggle,
        )
        self.cmp_bar = self._build_cmp_bar_container(t)

        self._group_list = GroupListPanel(t)
        self._group_list_panel = self._group_list.list_view

        edge = ft.border.all(1, t.colors.border3)
        self._compare_panel_a = ft.Container(
            content=self._compare_side_empty_column("A", t),
            width=_COMPARE_PANEL_W,
            padding=4,
            border=edge,
            bgcolor=None,
        )
        self._compare_panel_b = ft.Container(
            content=self._compare_side_empty_column("B", t),
            width=_COMPARE_PANEL_W,
            padding=4,
            border=edge,
            bgcolor=None,
        )
        div = ft.Container(
            content=ft.VerticalDivider(width=1, color=t.colors.border3, thickness=2),
            padding=ft.Padding.symmetric(horizontal=t.spacing.sm),
        )
        self._ab_row = ft.Row(
            [self._compare_panel_a, div, self._compare_panel_b],
            height=_COMPARE_ROW_HEIGHT,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=4,
            tight=True,
        )
        self._init_progress_and_marked_strip(t)
        # Orphan controls: refresh_* still update them if we re-mount chips/metadata later.
        self._file_selector_row = ft.Row([], spacing=6, tight=True)
        self._file_selector_container = ft.Container(content=self._file_selector_row, visible=False)
        self._meta_col_a = ft.Column([], spacing=3, tight=True)
        self._meta_col_b = ft.Column([], spacing=3, tight=True)
        self._metadata_strip = ft.Container(
            content=ft.Row(
                [
                    self._meta_col_a,
                    ft.Container(
                        width=1,
                        bgcolor=ft.Colors.with_opacity(0.2, t.colors.border),
                        margin=ft.margin.symmetric(horizontal=8),
                    ),
                    self._meta_col_b,
                ],
                vertical_alignment=ft.CrossAxisAlignment.START,
            ),
            padding=ft.Padding.symmetric(vertical=4, horizontal=4),
            visible=False,
        )
        self._filmstrip = GroupFilmstrip(t, on_select=self._del.set_compare_a)

        self.body = ft.Column(
            [
                ft.Text(
                    "Thumbnail compare probe (80 px). If both sides show below, sizing was the issue.",
                    size=t.typography.size_xs,
                    color=t.colors.fg_muted,
                ),
                self._ab_row,
            ],
            expand=False,
            spacing=6,
            tight=True,
        )

    def _build_cmp_bar_container(self, t: ThemeTokens) -> ft.Container:
        return glass_container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            self._btn_cmp_grid,
                            self._btn_cmp_prev,
                            self._btn_cmp_next,
                            self._details_switch,
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
            t=t,
            visible=False,
            padding=t.spacing.sm,
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
            padding=ft.Padding.symmetric(horizontal=t.spacing.md, vertical=t.spacing.sm),
            bgcolor=ft.Colors.with_opacity(0.95, RC.marked_bar_bg),
            border=ft.border.only(top=ft.BorderSide(1, RC.danger)),
            content=ft.Column(
                [
                    self._marked_lbl,
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

    @staticmethod
    def _page_set(ctrl: ft.Control | None) -> bool:
        if ctrl is None:
            return False
        try:
            return ctrl.page is not None
        except RuntimeError:
            return False

    def _debug_compare_state(self, label: str) -> None:
        """High-signal diagnostics for blank compare-canvas reports."""
        try:
            gid = self._del.compare_gid
            files = self._del.group_files.get(gid, []) if gid is not None else []
            a = str(getattr(self._del.compare_a, "path", "")) if self._del.compare_a else None
            b = str(getattr(self._del.compare_b, "path", "")) if self._del.compare_b else None
            body_controls = len(getattr(self.body, "controls", []) or [])
            _log.debug(
                "[COMPARE_DEBUG] %s gid=%r files=%s body_visible=%s body_page=%s "
                "body_controls=%s panel_a_page=%s panel_b_page=%s a=%r b=%r",
                label,
                gid,
                len(files),
                getattr(self.body, "visible", None),
                self._page_set(self.body),
                body_controls,
                self._page_set(self._compare_panel_a),
                self._page_set(self._compare_panel_b),
                a,
                b,
            )
        except Exception:
            _log.debug("[COMPARE_DEBUG] %s failed to collect state", label, exc_info=True)

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
        self.cmp_bar.bgcolor = self._t.colors.glass_bg
        self.cmp_bar.border = ft.border.all(1, self._t.colors.glass_border)

    def refresh_group_list_panel(self) -> None:
        self._group_list.refresh(
            groups=self._del.groups,
            compare_gid=self._del.compare_gid,
            on_pick=self._del.enter_compare,
            safe_update=ReviewCompareView._safe_update,
        )

    def update_compare_panels(self) -> None:
        _t0 = time.perf_counter()
        self._debug_compare_state("update_compare_panels:start")
        self._compare_mark_checkboxes.clear()
        self._compare_panel_a.content = self._build_compare_side(self._del.compare_a, "A")
        self._compare_panel_b.content = self._build_compare_side(self._del.compare_b, "B")
        self.apply_compare_panel_tints()
        self._safe_update(self._compare_panel_a)
        self._safe_update(self._compare_panel_b)
        self._refresh_file_selector()
        gid = self._del.compare_gid
        files = self._del.group_files.get(gid, []) if gid is not None else []
        self._filmstrip.refresh(files, active=self._del.compare_a)
        self._refresh_metadata_strip()
        self.update_progress_and_marked_bar()
        self._safe_update(self._ab_row)
        self._safe_update(self.body)
        self._debug_compare_state("update_compare_panels:end")
        self._log_if_slow("review:compare_panel_update", _t0)

    def refresh_compare_marks(self) -> None:
        """Update A/B mark checkboxes and progress strip without rebuilding thumbnails."""
        mp = self._del.marked_paths
        for path_key, cb in self._compare_mark_checkboxes.items():
            want = path_key in mp
            if bool(cb.value) != want:
                cb.value = want
                self._safe_update(cb)
        self.update_progress_and_marked_bar()

    def _refresh_file_selector(self) -> None:
        gid = self._del.compare_gid
        files = self._del.group_files.get(gid, []) if gid is not None else []
        if len(files) > 2:
            self._file_selector_row.controls = self._build_file_chips(
                files, self._del.compare_a, self._del.compare_b
            )
            self._file_selector_container.visible = True
        else:
            self._file_selector_container.visible = False
        self._safe_update(self._file_selector_container)

    def _build_file_chips(
        self,
        files: List[DuplicateFile],
        a: Optional[DuplicateFile],
        b: Optional[DuplicateFile],
    ) -> List[ft.Control]:
        t = self._t
        chips: List[ft.Control] = [
            ft.Text(
                "Pair:",
                size=t.typography.size_xs,
                color=t.colors.fg_muted,
                weight=ft.FontWeight.W_600,
            )
        ]
        for f in files:
            p = Path(str(f.path))
            is_a = a is not None and str(f.path) == str(a.path)
            is_b = b is not None and str(f.path) == str(b.path)
            accent = RC.side_a if is_a else (RC.side_b if is_b else t.colors.fg_muted)
            bg = (
                ft.Colors.with_opacity(0.14, RC.side_a)
                if is_a
                else (ft.Colors.with_opacity(0.14, RC.side_b) if is_b else ft.Colors.with_opacity(0.05, ft.Colors.WHITE))
            )
            border_color = accent if (is_a or is_b) else ft.Colors.with_opacity(0.15, ft.Colors.WHITE)
            side_lbl = "A" if is_a else ("B" if is_b else "")
            name_short = p.name[:20] + ("…" if len(p.name) > 20 else "")

            row_controls: List[ft.Control] = [
                ft.Text(name_short, size=10, color=accent if (is_a or is_b) else t.colors.fg, weight=ft.FontWeight.W_600 if (is_a or is_b) else ft.FontWeight.W_400),
                ft.Text(fmt_size(f.size), size=9, color=t.colors.fg_muted),
            ]
            if side_lbl:
                row_controls.append(
                    ft.Container(
                        content=ft.Text(side_lbl, size=8, weight=ft.FontWeight.W_800, color=accent),
                        bgcolor=ft.Colors.with_opacity(0.18, accent),
                        border_radius=3,
                        padding=ft.Padding.symmetric(horizontal=4, vertical=1),
                    )
                )

            def _make_click(file: DuplicateFile):
                return lambda e: self._del.set_compare_a(file)

            chips.append(
                ft.Container(
                    content=ft.Row(row_controls, spacing=4, tight=True, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                    bgcolor=bg,
                    border=ft.border.all(1, border_color),
                    border_radius=6,
                    padding=ft.Padding.symmetric(horizontal=8, vertical=5),
                    ink=True,
                    on_click=_make_click(f),
                    tooltip=f"Set as Side A: {p.name}",
                )
            )
        return chips

    def _on_compare_details_toggle(self, e: ft.ControlEvent) -> None:
        self._compare_details_enabled = bool(getattr(e.control, "value", False))
        self._refresh_metadata_strip()
        self._safe_update(self._metadata_strip)

    def _refresh_metadata_strip(self) -> None:
        a, b = self._del.compare_a, self._del.compare_b
        if not self._compare_details_enabled or (a is None and b is None):
            self._metadata_strip.visible = False
            self._safe_update(self._metadata_strip)
            return
        self._meta_col_a.controls = self._build_meta_col_controls(a, RC.side_a)
        self._meta_col_b.controls = self._build_meta_col_controls(b, RC.side_b)
        if a is not None and b is not None:
            size_delta = int(b.size) - int(a.size)
            self._meta_col_a.controls.append(
                ft.Text(
                    f"Δ size vs B: {fmt_size(abs(size_delta))}",
                    size=9,
                    color=WARNING if size_delta else METADATA,
                )
            )
        self._metadata_strip.visible = True
        self._safe_update(self._metadata_strip)

    def _build_meta_col_controls(self, f: Optional[DuplicateFile], accent: str) -> List[ft.Control]:
        t = self._t
        if f is None:
            return [ft.Text("—", size=9, color=t.colors.fg_muted)]
        try:
            dt = datetime.datetime.fromtimestamp(float(f.modified))
            date_str = dt.strftime("%b %d, %Y")
        except Exception:
            date_str = "—"
        sim = float(getattr(f, "similarity", 1.0))
        sim_str = f"{int(sim * 100)}% match" if sim < 1.0 else "Exact"
        p = Path(str(f.path))
        rows = [
            ("Size", fmt_size(f.size)),
            ("Modified", date_str),
            ("Type", f.extension or p.suffix or "—"),
            ("Match", sim_str),
        ]
        return [
            ft.Row(
                [
                    ft.Text(lbl, size=9, color=t.colors.fg_muted, width=52),
                    ft.Text(val, size=9, color=accent, weight=ft.FontWeight.W_600),
                ],
                spacing=4,
            )
            for lbl, val in rows
        ]

    def apply_compare_panel_tints(self) -> None:
        self._compare_panel_a.bgcolor = None
        self._compare_panel_a.border = ft.border.all(2, ft.Colors.with_opacity(0.55, RC.side_a))
        self._compare_panel_b.bgcolor = None
        self._compare_panel_b.border = ft.border.all(2, ft.Colors.with_opacity(0.55, RC.side_b))

    def reset_compare_panels_idle_chrome(self) -> None:
        edge = ft.border.all(1, self._t.colors.border3)
        self._compare_panel_a.bgcolor = None
        self._compare_panel_a.border = edge
        self._compare_panel_b.bgcolor = None
        self._compare_panel_b.border = edge

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
        total_rec = int(self._del.total_reclaimable_scan)
        remaining = max(0, total_rec - marked_bytes)
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
            padding=ft.Padding.symmetric(horizontal=8, vertical=4),
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

    def _thumb_media_control(self, f: DuplicateFile, p: Path) -> ft.Control:
        """Synchronous preview: native filesystem path (Flet desktop); avoids data-URI decode."""
        t = self._t
        if is_image_path(p):
            try:
                ok = p.is_file()
            except OSError:
                ok = False
            if ok:
                try:
                    src = str(p.expanduser().resolve(strict=False))
                except (OSError, RuntimeError):
                    src = str(p.expanduser())
                return ft.Image(
                    src=src,
                    fit=ft.BoxFit.COVER,
                    filter_quality=ft.FilterQuality.MEDIUM,
                    width=_COMPARE_PREVIEW_SLOT_WIDTH,
                    height=_COMPARE_PREVIEW_SLOT_HEIGHT,
                    border_radius=4,
                    tooltip=str(p),
                )
        return ft.Container(
            content=ft.Icon(
                ft.icons.Icons.INSERT_DRIVE_FILE,
                size=24,
                color=ft.Colors.with_opacity(0.35, t.colors.fg_muted),
            ),
            alignment=ft.Alignment(0, 0),
            width=_COMPARE_PREVIEW_SLOT_WIDTH,
            height=_COMPARE_PREVIEW_SLOT_HEIGHT,
        )

    def _build_compare_side(self, f: Optional[DuplicateFile], label: str) -> ft.Column:
        t = self._t
        label_color = RC.side_a if label == "A" else RC.side_b
        if not f:
            return self._compare_side_empty_column(label, t)
        p = Path(str(f.path))
        marked = str(f.path) in self._del.marked_paths
        thumb_slot = ft.Container(
            content=self._thumb_media_control(f, p),
            width=_COMPARE_PREVIEW_SLOT_WIDTH,
            height=_COMPARE_PREVIEW_SLOT_HEIGHT,
            alignment=ft.Alignment(0, 0),
            bgcolor=ft.Colors.with_opacity(0.08, label_color),
            border=ft.border.all(2, label_color),
            border_radius=4,
        )
        mark_cb = ft.Checkbox(
            label="Mark",
            value=marked,
            active_color=RC.danger,
            on_change=lambda e, file=f: self._del.toggle_mark_file(file),
        )
        self._compare_mark_checkboxes[str(f.path)] = mark_cb
        return ft.Column(
            [
                ft.Text(label, size=10, weight=ft.FontWeight.W_800, color=label_color),
                thumb_slot,
                ft.Text(
                    p.name,
                    size=9,
                    color=t.colors.fg_muted,
                    max_lines=1,
                    overflow=ft.TextOverflow.ELLIPSIS,
                    tooltip=str(p),
                ),
                mark_cb,
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=4,
            tight=True,
        )

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
