# cerebro/ui/pages/theme_page.py
from __future__ import annotations

from pathlib import Path
from typing import Optional, List
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QResizeEvent
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QFrame, QScrollArea, QGridLayout, QPushButton, QSizePolicy,
)

from cerebro.ui.components.modern import PageHeader, PageScaffold, ThemeCard
from cerebro.ui.components.modern._tokens import token as theme_token, SPACE_UNIT, RADIUS_SM
from cerebro.ui.pages.base_station import BaseStation
from cerebro.ui.state_bus import get_state_bus
from cerebro.ui.theme_engine import get_theme_manager, ThemeSpec

REQUIRED_PALETTE_KEYS = ("bg", "panel", "accent", "text")

FILTER_CATEGORIES = ("All", "Dark", "Light", "Studio", "Neon", "Warm", "Cool", "Nature")


def _is_valid_theme(spec: ThemeSpec) -> bool:
    pal = getattr(spec, "palette", None) or {}
    return all(pal.get(k) for k in REQUIRED_PALETTE_KEYS)


def _theme_matches_filter(spec: ThemeSpec, filt: str) -> bool:
    if filt == "All":
        return True
    tags = getattr(spec, "tags", ()) or ()
    category = getattr(spec, "category", "") or ""
    if filt == "Dark":
        return spec.is_dark
    if filt == "Light":
        return not spec.is_dark
    return filt == category or filt in tags


def _theme_matches_query(spec: ThemeSpec, q: str) -> bool:
    if not q:
        return True
    haystack = " ".join([
        spec.key,
        spec.name,
        getattr(spec, "tagline", "") or "",
        getattr(spec, "category", "") or "",
        " ".join(getattr(spec, "tags", ()) or ()),
    ]).lower()
    return q in haystack


class _FilterChip(QPushButton):
    """Small pill-shaped filter button."""

    def __init__(self, label: str, parent=None):
        super().__init__(label, parent)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self._label = label
        self._restyle()

    def _restyle(self) -> None:
        accent = theme_token("accent")
        panel = theme_token("panel")
        line = theme_token("line")
        text = theme_token("text")
        bg = theme_token("bg")

        self.setStyleSheet(f"""
            QPushButton {{
                font-size: 11px;
                font-weight: 600;
                padding: 3px 12px;
                border-radius: 10px;
                border: 1px solid {line};
                background: {panel};
                color: {text};
            }}
            QPushButton:hover {{
                border-color: {accent};
                background: {bg};
            }}
            QPushButton:checked {{
                background: {accent};
                color: {bg};
                border-color: {accent};
            }}
        """)

    def refresh_style(self) -> None:
        self._restyle()


class ThemePage(BaseStation):
    station_id = "themes"
    station_title = "Themes"

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self._theme = get_theme_manager()
        self._bus = get_state_bus()
        self._all: List[ThemeSpec] = []
        self._cards: List[ThemeCard] = []
        self._last_query = ""
        self._last_filter = "All"
        self._drag_highlight = False
        self._cols = 3
        self._build_ui()
        self._load()
        self._theme.theme_changed.connect(self._on_theme_changed)

    # -- drag & drop (unchanged) -----------------------------------------------

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData() and event.mimeData().hasUrls():
            event.acceptProposedAction()
            self._drag_highlight = True
            self.setStyleSheet(f"border: 2px solid {theme_token('accent')}; border-radius: 12px;")

    def dropEvent(self, event: QDropEvent) -> None:
        self._drag_highlight = False
        self.setStyleSheet("")
        if event.mimeData() and event.mimeData().hasUrls():
            url = event.mimeData().urls()[0]
            path = url.toLocalFile()
            if path and Path(path).is_dir() and hasattr(self._bus, "resume_scan_requested"):
                self._bus.resume_scan_requested.emit({"root": path})
                event.acceptProposedAction()
                return
        event.ignore()

    def dragLeaveEvent(self, event) -> None:
        self._drag_highlight = False
        self.setStyleSheet("")

    # -- callbacks --------------------------------------------------------------

    def _on_theme_changed(self) -> None:
        self._force_render()

    def _on_filter_clicked(self, chip: _FilterChip) -> None:
        for c in self._filter_chips:
            if c is not chip:
                c.setChecked(False)
        chip.setChecked(True)
        self._last_filter = chip._label
        self._force_render()

    # -- UI build ---------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._scaffold = PageScaffold(self, show_sidebar=False, show_sticky_action=False)
        root.addWidget(self._scaffold)

        self._header = PageHeader("Themes", "Click any theme to preview it instantly.")
        self._scaffold.set_header(self._header)

        content = QWidget()
        cl = QVBoxLayout(content)
        cl.setContentsMargins(12, 8, 12, 8)
        cl.setSpacing(6)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Search themes\u2026")
        self._search.textChanged.connect(self._force_render)
        self._search.setFixedHeight(30)
        self._search.setStyleSheet(f"""
            QLineEdit {{
                background: {theme_token('panel')};
                border: 1px solid {theme_token('line')};
                border-radius: 8px;
                padding: 4px 10px;
                font-size: 12px;
                color: {theme_token('text')};
            }}
            QLineEdit:focus {{ border-color: {theme_token('accent')}; }}
        """)
        cl.addWidget(self._search)

        chip_row = QHBoxLayout()
        chip_row.setContentsMargins(0, 0, 0, 0)
        chip_row.setSpacing(4)
        self._filter_chips: List[_FilterChip] = []
        for label in FILTER_CATEGORIES:
            chip = _FilterChip(label)
            chip.setChecked(label == "All")
            chip.clicked.connect(lambda checked=False, c=chip: self._on_filter_clicked(c))
            chip_row.addWidget(chip)
            self._filter_chips.append(chip)
        chip_row.addStretch(1)
        cl.addLayout(chip_row)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        self._grid_host = QWidget()
        self._grid = QGridLayout(self._grid_host)
        self._grid.setContentsMargins(0, 4, 0, 0)
        self._grid.setHorizontalSpacing(8)
        self._grid.setVerticalSpacing(8)
        self._scroll.setWidget(self._grid_host)
        cl.addWidget(self._scroll, 1)

        self._status = QLabel("")
        self._status.setStyleSheet(f"color: {theme_token('muted')}; font-size: 11px;")
        cl.addWidget(self._status)

        self._scaffold.set_content(content)

    # -- data -------------------------------------------------------------------

    def _load(self) -> None:
        self._all = self._theme.list_themes()
        self._force_render()

    def _compute_cols(self) -> int:
        w = self._scroll.viewport().width() if self._scroll.viewport() else 600
        if w < 420:
            return 2
        if w < 680:
            return 3
        return 4

    def _force_render(self) -> None:
        self._last_query = "__force__"
        self._render()

    def _render(self) -> None:
        cur = self._theme.current_theme_key
        q = (self._search.text() or "").strip().lower()
        filt = self._last_filter
        new_cols = self._compute_cols()

        if self._cards and self._last_query == q and self._cols == new_cols:
            for card in self._cards:
                card.set_active(card._key == cur)
            self._status.setText(f"{len(self._cards)} themes \u00b7 current: {cur}")
            return

        self._cols = new_cols
        self._cards.clear()
        while self._grid.count():
            item = self._grid.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)

        valid = [t for t in self._all if _is_valid_theme(t)]
        filtered = [t for t in valid if _theme_matches_filter(t, filt)]
        items = [t for t in filtered if _theme_matches_query(t, q)]

        ordered = self._group_ordered(items, filt)

        r = c = 0
        for entry in ordered:
            if isinstance(entry, str):
                if c != 0:
                    r += 1
                    c = 0
                header = QLabel(entry)
                header.setStyleSheet(
                    f"font-size:11px; font-weight:700; color:{theme_token('muted')}; "
                    f"padding:6px 0 2px 2px; background:transparent;"
                )
                self._grid.addWidget(header, r, 0, 1, self._cols)
                r += 1
                c = 0
                continue

            spec = entry
            pal = getattr(spec, "palette", None) or {}
            colors = [
                pal.get("bg", ""),
                pal.get("panel", ""),
                pal.get("accent", ""),
                pal.get("accent2", pal.get("text", "")),
            ]
            card = ThemeCard(
                theme_key=spec.key,
                theme_name=spec.name,
                colors=colors,
                active=(spec.key == cur),
                tagline=getattr(spec, "tagline", ""),
                tags=getattr(spec, "tags", ()),
                is_dark=spec.is_dark,
            )
            card.clicked.connect(self._apply_theme_key)
            self._grid.addWidget(card, r, c)
            self._cards.append(card)
            c += 1
            if c >= self._cols:
                c = 0
                r += 1

        self._status.setText(f"{len(self._cards)} themes \u00b7 current: {cur}")
        self._last_query = q

    def _group_ordered(self, items: List[ThemeSpec], filt: str):
        """Return items optionally with group header strings when filter is All."""
        if filt != "All" or not items:
            return items

        buckets = {}
        order = ["Studio", "Neon", "Warm", "Cool", "Nature"]
        for spec in items:
            cat = getattr(spec, "category", "Studio") or "Studio"
            buckets.setdefault(cat, []).append(spec)

        result = []
        for cat in order:
            group = buckets.pop(cat, [])
            if group:
                result.append(cat)
                result.extend(group)
        for cat, group in buckets.items():
            if group:
                result.append(cat)
                result.extend(group)
        return result

    # -- actions ----------------------------------------------------------------

    def _apply_theme_key(self, key: str) -> None:
        self._theme.apply_theme(key)
        self._force_render()

    # -- events -----------------------------------------------------------------

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        new_cols = self._compute_cols()
        if new_cols != self._cols:
            self._force_render()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._all = self._theme.list_themes()
        self._force_render()

    def reset(self) -> None:
        pass

    def reset_for_new_scan(self) -> None:
        pass
