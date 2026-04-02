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


class ThemePage(BaseStation):
    """VS Code-style theme picker: one-click apply, instant preview.

    Shows both the new 12 semantic themes (from ThemeEngineV3) and the
    legacy 23 themes (from ThemeEngine). Clicking any card applies it
    immediately with no confirmation dialog.
    """

    station_id = "themes"
    station_title = "Themes"

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._legacy = get_theme_manager()
        self._legacy_themes: List[ThemeSpec] = []
        self._v3_themes: List[dict] = []  # ThemeEngineV3 theme data
        self._cards: List[ThemeCard] = []
        self._last_query = ""
        self._build_ui()
        self._load()
        self._legacy.theme_changed.connect(self._on_theme_changed)

    def _on_theme_changed(self) -> None:
        self._render()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self._scaffold = PageScaffold(self, show_sidebar=False, show_sticky_action=False)
        root.addWidget(self._scaffold)
        self._header = PageHeader("Themes", "Click any theme to apply it instantly — no confirmation needed.")
        self._scaffold.set_header(self._header)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(18, 18, 18, 18)
        content_layout.setSpacing(12)

        # Section label for new themes
        self._v3_label = QLabel("")
        self._v3_label.setStyleSheet(f"""
            font-size: 13px; font-weight: bold;
            color: {theme_token('accent')};
            padding: 4px 0;
        """)
        self._v3_label.setVisible(False)
        content_layout.addWidget(self._v3_label)

        # V3 theme grid
        self._v3_grid_host = QWidget()
        self._v3_grid = QGridLayout(self._v3_grid_host)
        self._v3_grid.setContentsMargins(0, 0, 0, 0)
        self._v3_grid.setHorizontalSpacing(10)
        self._v3_grid.setVerticalSpacing(10)
        self._v3_grid_host.setVisible(False)
        content_layout.addWidget(self._v3_grid_host)

        # Legacy section label
        self._legacy_label = QLabel("")
        self._legacy_label.setStyleSheet(f"""
            font-size: 13px; font-weight: bold;
            color: {theme_token('muted')};
            padding: 4px 0;
        """)
        self._legacy_label.setVisible(False)
        content_layout.addWidget(self._legacy_label)

        # Search + legacy grid
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
        self._status.setStyleSheet(f"color: {theme_token('muted')}; font-size: 12px;")
        content_layout.addWidget(self._status)
        self._scaffold.set_content(content)

    def _load(self) -> None:
        """Load themes from both engines."""
        # Load v3 themes
        self._v3_themes = []
        try:
            from cerebro.core.theme_engine_v3 import ThemeEngineV3
            v3 = ThemeEngineV3.get()
            for name in v3.all_theme_names():
                data = v3.get_theme_data(name)
                if data:
                    self._v3_themes.append(data)
        except Exception:
            pass

        # Load legacy themes
        self._legacy_themes = self._legacy.list_themes()
        self._render()

    def _render(self) -> None:
        """Render theme cards for both v3 and legacy themes."""
        q = (self._search.text() or "").strip().lower()
        cur_legacy = self._legacy.current_theme_key

        # ---- Determine current v3 theme name ----
        cur_v3_name = ""
        try:
            from cerebro.core.theme_engine_v3 import ThemeEngineV3
            cur_v3_name = ThemeEngineV3.get().active_theme_name
        except Exception:
            pass

        # ---- Render V3 themes (always visible above legacy) ----
        self._render_v3_section(q, cur_v3_name)

        # ---- Render legacy themes ----
        self._render_legacy_section(q, cur_legacy, cur_v3_name)

        # Status
        total = len(self._cards)
        active = cur_v3_name if cur_v3_name else cur_legacy
        self._status.setText(f"{total} themes · current: {active}")
        self._last_query = q

    def _render_v3_section(self, q: str, cur_v3_name: str) -> None:
        """Render the v3 semantic themes."""
        # Clear existing v3 cards
        while self._v3_grid.count():
            item = self._v3_grid.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)
                self._cards.remove(w) if w in self._cards else None

        if not self._v3_themes:
            self._v3_label.setVisible(False)
            self._v3_grid_host.setVisible(False)
            return

        # Filter
        items = self._v3_themes
        if q:
            items = [t for t in items if q in t.get("name", "").lower()
                     or q in t.get("type", "").lower()
                     or q in t.get("description", "").lower()]

        self._v3_label.setText(f"🎨 Semantic Themes ({len(items)})")
        self._v3_label.setVisible(True)
        self._v3_grid_host.setVisible(True)

        # Get colors for cards
        try:
            from cerebro.ui.theme_bridge_v1 import get_theme_card_colors
            from cerebro.core.theme_engine_v3 import ThemeEngineV3
            v3 = ThemeEngineV3.get()
        except Exception:
            v3 = None

        cols = 3
        r = c = 0
        for data in items:
            name = data.get("name", "Unknown")
            active = (name == cur_v3_name)
            key = name  # v3 uses name as the key

            if v3:
                was = v3._active
                v3._active = name
                v3._resolve_all()
                colors = get_theme_card_colors(v3)
                if was in v3._themes:
                    v3._active = was
                    v3._resolve_all()
                else:
                    v3._active = name
            else:
                colors = ["#333", "#444", "#7aa2ff", "#ddd"]

            card = ThemeCard(key, name, colors, active=active)
            card.clicked.connect(self._apply_v3_theme)
            self._v3_grid.addWidget(card, r, c)
            self._cards.append(card)
            c += 1
            if c >= cols:
                c = 0
                r += 1

    def _render_legacy_section(self, q: str, cur_legacy: str, cur_v3_name: str) -> None:
        """Render the legacy theme cards."""
        # Clear existing legacy cards from main grid
        while self._grid.count():
            item = self._grid.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)
                self._cards.remove(w) if w in self._cards else None

        if not self._legacy_themes:
            self._legacy_label.setVisible(False)
            return

        # Filter
        valid = [t for t in self._legacy_themes if _is_valid_theme(t)]
        items = valid
        if q:
            items = [t for t in valid if q in t.name.lower()
                     or q in t.key.lower()
                     or q in (getattr(t, "tagline", "") or "").lower()]

        if not items:
            self._legacy_label.setVisible(False)
            return

        self._legacy_label.setText(f"📋 Classic Themes ({len(items)})")
        self._legacy_label.setVisible(True)

        cols = 3
        r = c = 0
        for spec in items:
            pal = getattr(spec, "palette", None) or {}
            colors = [pal.get("bg", ""), pal.get("panel", ""),
                      pal.get("accent", ""), pal.get("text", "")]
            active = (spec.key == cur_legacy) and not cur_v3_name
            card = ThemeCard(spec.key, spec.name, colors, active=active)
            card.clicked.connect(self._apply_legacy_theme)
            self._grid.addWidget(card, r, c)
            self._cards.append(card)
            c += 1
            if c >= cols:
                c = 0
                r += 1

    def _apply_v3_theme(self, name: str) -> None:
        """Apply a v3 semantic theme — updates both engines."""
        try:
            from cerebro.core.theme_engine_v3 import ThemeEngineV3
            from cerebro.ui.theme_bridge_v1 import apply_v3_theme_to_qapp
            v3 = ThemeEngineV3.get()

            # Resolve the theme (temporarily set it to get card colors)
            v3.set_theme(name)

            # Apply to the running QApplication
            apply_v3_theme_to_qapp(v3)

            # Notify StateBus
            try:
                from cerebro.ui.state_bus import get_state_bus
                get_state_bus().theme_changed.emit(name)
            except Exception:
                pass

        except Exception:
            pass

        self._render()

    def _apply_legacy_theme(self, key: str) -> None:
        """Apply a legacy theme via the existing ThemeManager."""
        try:
            from cerebro.core.theme_engine_v3 import ThemeEngineV3
            # Deactivate v3 so active indicator shows correctly
            # (we don't clear v3, just mark it as not the source)
        except Exception:
            pass

        self._legacy.apply_theme(key)
        self._render()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._load()

    def reset(self) -> None:
        """Clear internal state; no workers."""
        pass

    def reset_for_new_scan(self) -> None:
        """No scan-specific state."""
        pass


REQUIRED_PALETTE_KEYS = ("bg", "panel", "accent", "text")


def _is_valid_theme(spec: ThemeSpec) -> bool:
    """Only themes with all required tokens are shown."""
    pal = getattr(spec, "palette", None) or {}
    return all(pal.get(k) for k in REQUIRED_PALETTE_KEYS)
