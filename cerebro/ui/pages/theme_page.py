# cerebro/ui/pages/theme_page.py
from __future__ import annotations

from typing import Optional, List
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QFrame, QScrollArea, QGridLayout,
)

from cerebro.ui.components.modern import PageHeader, PageScaffold, ThemeCard
from cerebro.ui.components.modern._tokens import token as theme_token
from cerebro.ui.pages.base_station import BaseStation
from cerebro.ui.theme_engine import get_theme_manager, ThemeSpec

REQUIRED_PALETTE_KEYS = ("bg", "panel", "accent", "text")


def _is_valid_theme(spec: ThemeSpec) -> bool:
    """Only themes with all required tokens are shown."""
    pal = getattr(spec, "palette", None) or {}
    return all(pal.get(k) for k in REQUIRED_PALETTE_KEYS)


class ThemePage(BaseStation):
    station_id = "themes"
    station_title = "Themes"

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._theme = get_theme_manager()
        self._all: List[ThemeSpec] = []
        self._cards: List[ThemeCard] = []
        self._last_query = ""
        self._build_ui()
        self._load()
        self._theme.theme_changed.connect(self._on_theme_changed)

    def _on_theme_changed(self) -> None:
        self._render()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self._scaffold = PageScaffold(self, show_sidebar=False, show_sticky_action=False)
        root.addWidget(self._scaffold)
        self._header = PageHeader("Themes", "Click any theme to preview it instantly.")
        self._scaffold.set_header(self._header)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(18, 18, 18, 18)
        content_layout.setSpacing(12)
        self._search = QLineEdit()
        self._search.setPlaceholderText("Search themes…")
        self._search.textChanged.connect(self._render)
        self._search.setStyleSheet(f"""
            QLineEdit {{
                background: {theme_token('panel')};
                border: 1px solid {theme_token('line')};
                border-radius: 10px;
                padding: 8px 12px;
                color: {theme_token('text')};
            }}
            QLineEdit:focus {{ border-color: {theme_token('accent')}; }}
        """)
        content_layout.addWidget(self._search)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        self._grid_host = QWidget()
        self._grid = QGridLayout(self._grid_host)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(10)
        self._grid.setVerticalSpacing(10)
        self._scroll.setWidget(self._grid_host)
        content_layout.addWidget(self._scroll, 1)
        self._status = QLabel("")
        self._status.setStyleSheet(f"color: {theme_token('muted')};")
        content_layout.addWidget(self._status)
        self._scaffold.set_content(content)

    def _load(self) -> None:
        self._all = self._theme.list_themes()
        self._render()

    def _render(self) -> None:
        cur = self._theme.current_theme_key
        q = (self._search.text() or "").strip().lower()
        
        # Fast path: just update active states if search unchanged (VS Code style - instant!)
        if self._cards and self._last_query == q:
            for card in self._cards:
                is_active = (card._key == cur)
                card.set_active(is_active)
            self._status.setText(f"{len(self._cards)} themes · current: {cur}")
            return
        
        # Full rebuild when search changes or initial load
        self._cards.clear()
        while self._grid.count():
            item = self._grid.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)
        
        valid = [t for t in self._all if _is_valid_theme(t)]
        items = [t for t in valid if (q in t.name.lower() or q in t.key.lower() or q in (getattr(t, "tagline", "") or "").lower())] if q else valid
        
        cols = 3
        r = c = 0
        for spec in items:
            pal = getattr(spec, "palette", None) or {}
            colors = [pal.get("bg", ""), pal.get("panel", ""), pal.get("accent", ""), pal.get("text", "")]
            card = ThemeCard(spec.key, spec.name, colors, active=(spec.key == cur))
            card.clicked.connect(self._apply_theme_key)
            self._grid.addWidget(card, r, c)
            self._cards.append(card)
            c += 1
            if c >= cols:
                c = 0
                r += 1
        
        self._status.setText(f"{len(items)} themes · current: {cur}")
        self._last_query = q

    def _apply_theme_key(self, key: str) -> None:
        """Apply theme immediately on card Apply click."""
        self._theme.apply_theme(key)
        self._render()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._render()

    def reset(self) -> None:
        """Clear internal state; no workers."""
        pass

    def reset_for_new_scan(self) -> None:
        """No scan-specific state."""
        pass