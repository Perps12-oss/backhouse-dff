from __future__ import annotations

from typing import Callable, Dict

import flet as ft

from cerebro.v2.ui.flet_app.pages.review._types import FILTER_TAB_ACCENTS, RC
from cerebro.v2.ui.flet_app.theme import ThemeTokens, fmt_size

_FILTER_TABS = [
    ("all", "All"),
    ("pictures", "Images"),
    ("music", "Music"),
    ("videos", "Videos"),
    ("documents", "Docs"),
    ("archives", "Archives"),
    ("other", "Other"),
]

class FilterBar(ft.Container):
    """Segmented filter bar with per-tab file count and size labels."""

    def __init__(self, t: ThemeTokens, on_change: Callable[[str], None]) -> None:
        self._t = t
        self._key_cb = on_change
        self._filter_seg_lines: Dict[str, tuple[ft.Text, ft.Text, ft.Text]] = {}

        segments: list[ft.Segment] = []
        for key, label in _FILTER_TABS:
            t0 = ft.Text(label, size=12, weight=ft.FontWeight.W_600, color=t.colors.fg2)
            t1 = ft.Text("0", size=11, weight=ft.FontWeight.W_600, color=FILTER_TAB_ACCENTS.get(key, RC.filter_all))
            t2 = ft.Text("0 B", size=10, color=t.colors.fg_muted)
            self._filter_seg_lines[key] = (t0, t1, t2)
            segments.append(
                ft.Segment(
                    value=key,
                    label=ft.Column(
                        [t0, t1, t2],
                        spacing=1,
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        tight=True,
                    ),
                )
            )

        self._seg = ft.SegmentedButton(
            selected=["all"],
            allow_multiple_selection=False,
            on_change=self._on_seg_change,
            segments=segments,
        )

        super().__init__(
            content=ft.Row(
                [ft.Container(expand=True), self._seg, ft.Container(expand=True)],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.padding.only(left=t.spacing.lg, right=t.spacing.lg, bottom=t.spacing.sm),
        )

    def _on_seg_change(self, e: ft.ControlEvent) -> None:
        ctrl = getattr(e, "control", None) or self._seg
        sel = getattr(ctrl, "selected", None)
        if isinstance(sel, list):
            key = str(sel[0]) if sel else "all"
        elif isinstance(sel, (set, frozenset)):
            key = str(next(iter(sel))) if sel else "all"
        else:
            key = "all"
        self._key_cb(key)

    @staticmethod
    def _safe_update(ctrl: ft.Control | None) -> None:
        if ctrl is None:
            return
        try:
            if ctrl.page is not None:
                ctrl.update()
        except RuntimeError:
            pass

    def sync_theme(self, t: ThemeTokens) -> None:
        """Update spacing tokens; caller should invoke ``update_counts`` so label colors match."""
        self._t = t
        self.padding = ft.padding.only(left=t.spacing.lg, right=t.spacing.lg, bottom=t.spacing.sm)
        FilterBar._safe_update(self)

    def update_counts(self, counts: Dict[str, int], sizes: Dict[str, int], active_key: str) -> None:
        """Refresh label text for all tabs. Called by ReviewPage after filter index rebuild."""
        t = self._t
        for key, (t0, t1, t2) in self._filter_seg_lines.items():
            base = next((label for k, label in _FILTER_TABS if k == key), key.title())
            files_n = counts.get(key, 0)
            size_n = sizes.get(key, 0)
            is_active = key == active_key
            accent = FILTER_TAB_ACCENTS.get(key, RC.filter_all)
            t0.value = base
            t0.color = t.colors.fg if is_active else t.colors.fg2
            t0.weight = ft.FontWeight.W_700 if is_active else ft.FontWeight.W_600
            t1.value = f"{files_n:,}"
            t1.size = 12
            t1.color = accent if is_active else ft.Colors.with_opacity(0.85, accent)
            t1.weight = ft.FontWeight.W_700 if is_active else ft.FontWeight.W_600
            t2.value = fmt_size(size_n)
            t2.color = t.colors.fg2 if is_active else t.colors.fg_muted
        FilterBar._safe_update(self._seg)
