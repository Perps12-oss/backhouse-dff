"""Right inspector column — selection-driven metadata, recommendations, and trust copy."""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import Optional, Set

import flet as ft

from cerebro.engines.base_engine import DuplicateFile, DuplicateGroup
from cerebro.v2.ui.flet_app.pages.review._types import RC
from cerebro.v2.ui.flet_app.pages.review.smart_rules import RULE_LABELS, apply_rule, normalized_rule
from cerebro.v2.ui.flet_app.pages.review.theme_detect import app_theme_is_light
from cerebro.v2.ui.flet_app.theme import ThemeTokens, fmt_size

_PLACEHOLDER_TEXT = "Select a duplicate group or file to preview metadata, paths, and recommendations."


def _section_header(label: str, t: ThemeTokens) -> ft.Row:
    return ft.Row(
        [
            ft.Container(width=3, height=12, bgcolor=RC.side_a, border_radius=2),
            ft.Text(
                label.upper(),
                size=t.typography.size_xs,
                weight=ft.FontWeight.W_700,
                color=t.colors.fg_muted,
            ),
        ],
        spacing=6,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )


def _divider(is_light: bool) -> ft.Container:
    return ft.Container(
        height=1,
        bgcolor=ft.Colors.with_opacity(0.1, ft.Colors.BLACK if is_light else ft.Colors.WHITE),
        margin=ft.margin.symmetric(vertical=8),
    )


def _status_badge(label: str, color: str, bg: str) -> ft.Container:
    return ft.Container(
        content=ft.Text(label, size=9, weight=ft.FontWeight.W_800, color=color),
        bgcolor=bg,
        border_radius=4,
        padding=ft.Padding.symmetric(horizontal=7, vertical=3),
    )


class ReviewInspectorPanel(ft.Container):
    def __init__(self, bridge, t: ThemeTokens, *, on_compare_file=None) -> None:
        self._bridge = bridge
        self._t = t
        self._on_compare_file = on_compare_file
        self._current_mode: str = "placeholder"  # "placeholder" | "group" | "file"
        self._current_group: Optional[DuplicateGroup] = None
        self._current_file: Optional[DuplicateFile] = None
        self._current_smart_rule: str = "keep_largest"
        self._current_marked: Set[str] = set()

        self._scroll_col = ft.Column(
            controls=self._build_placeholder_controls(t),
            spacing=0,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
            animate_opacity=ft.Animation(160, ft.AnimationCurve.EASE_OUT),
        )

        is_light = app_theme_is_light(bridge)
        edge = ft.Colors.with_opacity(0.12, ft.Colors.BLACK if is_light else ft.Colors.WHITE)
        super().__init__(
            width=336,
            expand=False,
            bgcolor=ft.Colors.with_opacity(0.03, ft.Colors.WHITE if not is_light else ft.Colors.BLACK),
            border=ft.border.only(left=ft.BorderSide(1, edge)),
            padding=ft.padding.all(14),
            content=self._scroll_col,
        )

    # ── public API ───────────────────────────────────────────────────────────

    def show_placeholder(self) -> None:
        self._current_mode = "placeholder"
        self._current_group = None
        self._current_file = None
        self._swap_content(self._build_placeholder_controls(self._t))

    def show_group(
        self,
        group: DuplicateGroup,
        smart_rule: str,
        marked_paths: Set[str],
    ) -> None:
        self._current_mode = "group"
        self._current_group = group
        self._current_file = None
        self._current_smart_rule = smart_rule
        self._current_marked = set(marked_paths)
        self._swap_content(self._build_group_controls(group, smart_rule, marked_paths, self._t))

    def show_file(
        self,
        file: DuplicateFile,
        smart_rule: str,
        group: DuplicateGroup,
        marked_paths: Set[str],
    ) -> None:
        self._current_mode = "file"
        self._current_file = file
        self._current_group = group
        self._current_smart_rule = smart_rule
        self._current_marked = set(marked_paths)
        self._swap_content(self._build_file_controls(file, smart_rule, group, marked_paths, self._t))

    def sync_theme(self, t: ThemeTokens) -> None:
        self._t = t
        is_light = app_theme_is_light(self._bridge)
        edge = ft.Colors.with_opacity(0.12, ft.Colors.BLACK if is_light else ft.Colors.WHITE)
        self.border = ft.border.only(left=ft.BorderSide(1, edge))
        self.bgcolor = ft.Colors.with_opacity(0.03, ft.Colors.WHITE if not is_light else ft.Colors.BLACK)
        # Re-render current state with new theme tokens.
        if self._current_mode == "group" and self._current_group:
            self._scroll_col.controls = self._build_group_controls(
                self._current_group, self._current_smart_rule, self._current_marked, t
            )
        elif self._current_mode == "file" and self._current_file and self._current_group:
            self._scroll_col.controls = self._build_file_controls(
                self._current_file, self._current_smart_rule, self._current_group, self._current_marked, t
            )
        else:
            self._scroll_col.controls = self._build_placeholder_controls(t)
        self._safe_update()

    # ── builders ─────────────────────────────────────────────────────────────

    def _build_placeholder_controls(self, t: ThemeTokens) -> list:
        return [
            ft.Text("Inspector", size=t.typography.size_base, weight=ft.FontWeight.W_700, color=t.colors.fg),
            ft.Container(height=8),
            ft.Text(_PLACEHOLDER_TEXT, size=t.typography.size_sm, color=t.colors.fg_muted),
        ]

    def _build_group_controls(
        self,
        g: DuplicateGroup,
        smart_rule: str,
        marked_paths: Set[str],
        t: ThemeTokens,
    ) -> list:
        is_light = app_theme_is_light(self._bridge)
        stripe = RC.group_stripe[g.group_id % len(RC.group_stripe)]
        reclaim = int(getattr(g, "reclaimable", 0) or 0)
        files = list(g.files)
        sim_type = (getattr(g, "similarity_type", None) or "exact").capitalize()
        n = len(files)

        # Keeper from smart rule
        keeper: Optional[DuplicateFile] = None
        rule_lbl = next((lbl for k, lbl in RULE_LABELS if k == smart_rule), smart_rule)
        if n >= 2:
            try:
                keeper = apply_rule(normalized_rule(smart_rule), files)
            except Exception:
                pass

        controls: list = [
            # Group title
            ft.Row(
                [
                    ft.Container(width=3, height=20, bgcolor=stripe, border_radius=2),
                    ft.Text(
                        f"Group — {fmt_size(reclaim)} reclaimable",
                        size=t.typography.size_base,
                        weight=ft.FontWeight.W_700,
                        color=t.colors.fg,
                    ),
                ],
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            ft.Container(height=2),
            ft.Row(
                [
                    ft.Container(
                        content=ft.Text(sim_type, size=9, weight=ft.FontWeight.W_700, color=RC.info),
                        bgcolor=ft.Colors.with_opacity(0.15, ft.Colors.BLUE),
                        border_radius=4,
                        padding=ft.Padding.symmetric(horizontal=6, vertical=2),
                    ),
                    ft.Text(
                        f"{n} files",
                        size=t.typography.size_xs,
                        color=t.colors.fg_muted,
                    ),
                ],
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            _divider(is_light),
            _section_header("Recommendation", t),
            ft.Container(height=4),
            ft.Text(
                f"Rule: {rule_lbl}",
                size=t.typography.size_xs,
                color=t.colors.fg2,
            ),
        ]

        if keeper:
            controls += [
                ft.Container(height=2),
                ft.Row(
                    [
                        _status_badge(
                            "KEEP",
                            RC.group_title_reviewed,
                            ft.Colors.with_opacity(0.18, ft.Colors.GREEN),
                        ),
                        ft.Text(
                            Path(str(keeper.path)).name,
                            size=t.typography.size_xs,
                            weight=ft.FontWeight.W_600,
                            color=t.colors.fg,
                            overflow=ft.TextOverflow.ELLIPSIS,
                            expand=True,
                        ),
                    ],
                    spacing=6,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                ft.Container(height=2),
                ft.Text(
                    f"Delete {n - 1} {'copy' if n - 1 == 1 else 'copies'} · save {fmt_size(reclaim)}",
                    size=t.typography.size_xs,
                    color=t.colors.fg_muted,
                ),
            ]

        controls += [
            _divider(is_light),
            _section_header("Files", t),
            ft.Container(height=4),
        ]

        for f in files:
            p = Path(str(f.path))
            is_keeper = keeper is not None and str(f.path) == str(keeper.path)
            is_marked = str(f.path) in marked_paths
            badge_txt = "KEEP" if is_keeper else ("REMOVE" if is_marked else "REVIEW")
            badge_color = (
                RC.group_title_reviewed if is_keeper else (RC.marked_label_soft if is_marked else t.colors.fg_muted)
            )
            badge_bg = (
                ft.Colors.with_opacity(0.18, ft.Colors.GREEN)
                if is_keeper
                else (ft.Colors.with_opacity(0.18, ft.Colors.RED) if is_marked else ft.Colors.with_opacity(0.1, ft.Colors.WHITE))
            )
            controls.append(
                ft.Container(
                    content=ft.Row(
                        [
                            _status_badge(badge_txt, badge_color, badge_bg),
                            ft.Column(
                                [
                                    ft.Text(
                                        p.name,
                                        size=t.typography.size_xs,
                                        weight=ft.FontWeight.W_600,
                                        color=t.colors.fg,
                                        overflow=ft.TextOverflow.ELLIPSIS,
                                        max_lines=1,
                                    ),
                                    ft.Text(
                                        fmt_size(f.size),
                                        size=t.typography.size_xs,
                                        color=t.colors.fg_muted,
                                    ),
                                ],
                                spacing=1,
                                expand=True,
                            ),
                        ],
                        spacing=6,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    padding=ft.Padding.symmetric(vertical=4),
                )
            )

        return controls

    def _build_file_controls(
        self,
        f: DuplicateFile,
        smart_rule: str,
        group: DuplicateGroup,
        marked_paths: Set[str],
        t: ThemeTokens,
    ) -> list:
        is_light = app_theme_is_light(self._bridge)
        p = Path(str(f.path))
        is_marked = str(f.path) in marked_paths
        files = list(group.files)
        rule_lbl = next((lbl for k, lbl in RULE_LABELS if k == smart_rule), smart_rule)

        keeper: Optional[DuplicateFile] = None
        if len(files) >= 2:
            try:
                keeper = apply_rule(normalized_rule(smart_rule), files)
            except Exception:
                pass

        is_keeper = keeper is not None and str(f.path) == str(keeper.path)
        badge_txt = "KEEP" if is_keeper else ("REMOVE" if is_marked else "REVIEW")
        badge_color = (
            RC.group_title_reviewed if is_keeper else (RC.marked_label_soft if is_marked else t.colors.fg_muted)
        )
        badge_bg = (
            ft.Colors.with_opacity(0.18, ft.Colors.GREEN)
            if is_keeper
            else (ft.Colors.with_opacity(0.18, ft.Colors.RED) if is_marked else ft.Colors.with_opacity(0.1, ft.Colors.WHITE))
        )

        # Modified date
        try:
            dt = datetime.datetime.fromtimestamp(float(f.modified))
            date_str = dt.strftime("%b %d, %Y  %H:%M")
        except Exception:
            date_str = "—"

        # Similarity
        sim = float(getattr(f, "similarity", 1.0))
        sim_str = f"{int(sim * 100)}% match" if sim < 1.0 else "Exact match"

        # Why recommended
        if is_keeper:
            why = f"This is the recommended file to keep ({rule_lbl})."
        elif is_marked:
            why = f"Marked for removal based on rule: {rule_lbl}."
        else:
            why = "Not yet reviewed."

        controls: list = [
            ft.Text(p.name, size=t.typography.size_base, weight=ft.FontWeight.W_700, color=t.colors.fg),
            ft.Container(height=4),
            _status_badge(badge_txt, badge_color, badge_bg),
            _divider(is_light),
            _section_header("Location", t),
            ft.Container(height=4),
            ft.Text(
                str(p.parent),
                size=t.typography.size_xs,
                color=t.colors.fg_muted,
                selectable=True,
            ),
            _divider(is_light),
            _section_header("Details", t),
            ft.Container(height=4),
            ft.Row(
                [
                    ft.Text("Size", size=t.typography.size_xs, color=t.colors.fg_muted, expand=1),
                    ft.Text(fmt_size(f.size), size=t.typography.size_xs, color=t.colors.fg, expand=2),
                ],
                spacing=0,
            ),
            ft.Container(height=2),
            ft.Row(
                [
                    ft.Text("Modified", size=t.typography.size_xs, color=t.colors.fg_muted, expand=1),
                    ft.Text(date_str, size=t.typography.size_xs, color=t.colors.fg, expand=2),
                ],
                spacing=0,
            ),
            ft.Container(height=2),
            ft.Row(
                [
                    ft.Text("Match", size=t.typography.size_xs, color=t.colors.fg_muted, expand=1),
                    ft.Text(sim_str, size=t.typography.size_xs, color=t.colors.fg, expand=2),
                ],
                spacing=0,
            ),
            _divider(is_light),
            _section_header("Recommendation", t),
            ft.Container(height=4),
            ft.Text(why, size=t.typography.size_xs, color=t.colors.fg2),
        ]

        if not is_keeper and keeper:
            controls += [
                ft.Container(height=4),
                ft.Text(
                    f"Preferred: {Path(str(keeper.path)).name}",
                    size=t.typography.size_xs,
                    color=RC.group_title_reviewed,
                    overflow=ft.TextOverflow.ELLIPSIS,
                    max_lines=1,
                ),
            ]

        if self._on_compare_file is not None:
            captured_f = f

            def _on_cmp_click(e: ft.ControlEvent, _f=captured_f) -> None:
                if self._on_compare_file:
                    self._on_compare_file(_f)

            controls += [
                _divider(is_light),
                ft.OutlinedButton(
                    "Compare in context →",
                    icon=ft.icons.Icons.COMPARE,
                    on_click=_on_cmp_click,
                    style=ft.ButtonStyle(
                        color=RC.side_a,
                        side=ft.BorderSide(1, ft.Colors.with_opacity(0.4, RC.side_a)),
                        padding=ft.Padding.symmetric(horizontal=12, vertical=8),
                        shape=ft.RoundedRectangleBorder(radius=8),
                    ),
                ),
            ]

        return controls

    # ── internals ─────────────────────────────────────────────────────────────

    def _swap_content(self, controls: list) -> None:
        """Replace scroll column content with a brief opacity fade-in."""
        self._scroll_col.opacity = 0.0
        self._scroll_col.controls = controls
        self._scroll_col.opacity = 1.0
        self._safe_update()

    def _safe_update(self) -> None:
        try:
            if self.page is not None:
                self.update()
        except RuntimeError:
            pass
