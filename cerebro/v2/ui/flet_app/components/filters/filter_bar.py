"""Reusable type filter bar with per-tab counts and sizes."""

from __future__ import annotations

from typing import Callable, Dict

import flet as ft

from cerebro.v2.ui.flet_app.theme import ThemeTokens, fmt_size

FILTER_TABS: list[tuple[str, str]] = [
    ("all", "All"),
    ("pictures", "Images"),
    ("music", "Music"),
    ("videos", "Videos"),
    ("documents", "Docs"),
    ("archives", "Archives"),
    ("other", "Other"),
]

FILTER_TAB_ACCENTS: Dict[str, str] = {
    "all": "#C7D2FE",
    "pictures": "#C084FC",
    "music": "#34D399",
    "videos": "#F472B6",
    "documents": "#FB923C",
    "archives": "#FBBF24",
    "other": "#93C5FD",
}


class FilterBar(ft.Container):
    """Segmented filter bar with per-tab file count and size labels."""

    def __init__(
        self,
        t: ThemeTokens,
        on_change: Callable[[str], None],
        *,
        show_files_suffix: bool = False,
        dim_zero_counts: bool = False,
        embedded: bool = False,
    ) -> None:
        self._t = t
        self._key_cb = on_change
        self._show_files_suffix = show_files_suffix
        self._dim_zero_counts = dim_zero_counts
        self._filter_seg_lines: Dict[str, tuple[ft.Text, ft.Text, ft.Text]] = {}

        segments: list[ft.Segment] = []
        for key, label in FILTER_TABS:
            t0 = ft.Text(label, size=12, weight=ft.FontWeight.W_600, color=t.colors.fg2)
            t1 = ft.Text("0", size=11, weight=ft.FontWeight.W_600, color=FILTER_TAB_ACCENTS.get(key, FILTER_TAB_ACCENTS["all"]))
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

        padding = (
            ft.padding.all(0)
            if embedded
            else ft.padding.only(left=t.spacing.lg, right=t.spacing.lg, bottom=t.spacing.sm)
        )
        super().__init__(
            content=ft.Row(
                [ft.Container(expand=True), self._seg, ft.Container(expand=True)],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=padding,
        )

    @property
    def segmented_button(self) -> ft.SegmentedButton:
        return self._seg

    def set_active(self, key: str) -> None:
        if key not in {k for k, _ in FILTER_TABS}:
            key = "all"
        self._seg.selected = [key]
        FilterBar._safe_update(self._seg)

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
        """Refresh label text for all tabs."""
        t = self._t
        for key, (t0, t1, t2) in self._filter_seg_lines.items():
            base = next((label for k, label in FILTER_TABS if k == key), key.title())
            files_n = counts.get(key, 0)
            size_n = sizes.get(key, 0)
            is_active = key == active_key
            accent = FILTER_TAB_ACCENTS.get(key, FILTER_TAB_ACCENTS["all"])
            t0.value = base
            if self._dim_zero_counts and not is_active:
                t0.color = "#DDE8FF"
            else:
                t0.color = t.colors.fg if is_active else t.colors.fg2
            if is_active and self._dim_zero_counts:
                t0.color = "#FFFFFF"
            t0.weight = ft.FontWeight.W_700 if is_active else ft.FontWeight.W_600
            if self._show_files_suffix:
                t1.value = f"{files_n:,} files"
            else:
                t1.value = f"{files_n:,}"
            t1.size = 12
            if self._dim_zero_counts and files_n == 0:
                t1.color = "#6C7C98"
            else:
                t1.color = accent if is_active else ft.Colors.with_opacity(0.85 if not self._dim_zero_counts else 0.72, accent)
            t1.weight = ft.FontWeight.W_700 if is_active else ft.FontWeight.W_600
            t2.value = fmt_size(size_n)
            if self._dim_zero_counts:
                t2.color = "#7D8EAB" if files_n == 0 else ("#B7C6E6" if is_active else "#9FB0D0")
            else:
                t2.color = t.colors.fg2 if is_active else t.colors.fg_muted
        FilterBar._safe_update(self._seg)
