# cerebro/ui/components/modern/theme_card.py
from __future__ import annotations

from typing import Optional, List, Sequence

from PySide6.QtCore import Signal, Qt, QSize
from PySide6.QtGui import QPainter, QLinearGradient, QColor, QBrush, QPen
from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, QWidget, QSizePolicy,
)

from ._tokens import RADIUS_MD, RADIUS_SM, SPACE_UNIT, token


class _GradientStrip(QWidget):
    """Thin horizontal strip that paints a two-color gradient."""

    def __init__(self, color1: str, color2: str, height: int = 4, parent=None):
        super().__init__(parent)
        self._c1 = color1
        self._c2 = color2
        self.setFixedHeight(height)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_colors(self, c1: str, c2: str) -> None:
        self._c1 = c1
        self._c2 = c2
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        grad = QLinearGradient(0, 0, self.width(), 0)
        grad.setColorAt(0.0, QColor(self._c1))
        grad.setColorAt(1.0, QColor(self._c2))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(grad))
        p.drawRoundedRect(self.rect(), 2, 2)
        p.end()


class ThemeCard(QFrame):
    """
    Premium theme preview card.

    Shows: gradient strip, name, tagline, badge pills, 4-color swatch,
    and an active indicator. Click anywhere to apply instantly.
    """

    clicked = Signal(str)

    def __init__(
        self,
        theme_key: str,
        theme_name: str,
        colors: List[str],
        active: bool = False,
        tagline: str = "",
        tags: Sequence[str] = (),
        is_dark: bool = True,
        parent=None,
    ):
        super().__init__(parent)
        self.setObjectName("ThemeCard")
        self._key = theme_key
        self._active = active
        self._is_dark = is_dark
        self._tagline = tagline
        self._tags = tags
        self._colors = colors
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumWidth(180)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, SPACE_UNIT + 2)
        layout.setSpacing(0)

        accent = (colors[2] if len(colors) > 2 else "#7aa2ff")
        accent2_color = (colors[3] if len(colors) > 3 else accent)

        self._gradient = _GradientStrip(accent, accent2_color, height=4)
        layout.addWidget(self._gradient)

        inner = QVBoxLayout()
        inner.setContentsMargins(SPACE_UNIT + 4, SPACE_UNIT + 2, SPACE_UNIT + 4, 0)
        inner.setSpacing(3)

        self._name_label = QLabel(theme_name)
        self._name_label.setObjectName("tcName")
        inner.addWidget(self._name_label)

        self._tagline_label = QLabel(tagline or "")
        self._tagline_label.setObjectName("tcTagline")
        self._tagline_label.setWordWrap(True)
        inner.addWidget(self._tagline_label)

        if tags:
            badge_row = QHBoxLayout()
            badge_row.setContentsMargins(0, 2, 0, 0)
            badge_row.setSpacing(4)
            for tag_text in tags[:5]:
                pill = QLabel(tag_text)
                pill.setObjectName("tcBadge")
                pill.setAlignment(Qt.AlignCenter)
                badge_row.addWidget(pill)
            badge_row.addStretch(1)
            inner.addLayout(badge_row)

        inner.addSpacing(4)

        swatch_row = QHBoxLayout()
        swatch_row.setContentsMargins(0, 0, 0, 0)
        swatch_row.setSpacing(3)
        display_colors = (colors or ["#0f1115", "#161b24", "#7aa2ff", "#e4e9f1"])[:4]
        for c in display_colors:
            box = QFrame()
            box.setFixedSize(QSize(28, 16))
            box.setStyleSheet(f"background:{c}; border-radius:3px; border:none;")
            swatch_row.addWidget(box)
        swatch_row.addStretch(1)
        inner.addLayout(swatch_row)

        inner.addSpacing(2)

        self._active_label = QLabel("Active" if active else "")
        self._active_label.setObjectName("tcActive")
        inner.addWidget(self._active_label)

        layout.addLayout(inner)

        self._apply_card_style()

    def _apply_card_style(self) -> None:
        panel = token("panel")
        line = token("line")
        text = token("text")
        muted = token("muted")
        accent = token("accent")
        bg = token("bg")

        border_color = accent if self._active else line
        border_width = "2px" if self._active else "1px"
        active_color = accent if self._active else "transparent"

        self.setStyleSheet(f"""
            ThemeCard {{
                background: {panel};
                border-radius: {RADIUS_MD}px;
                border: {border_width} solid {border_color};
            }}
            ThemeCard:hover {{
                border-color: {accent};
                background: {bg};
            }}
            QLabel#tcName {{
                font-weight: 700;
                font-size: 12px;
                color: {text};
                background: transparent;
            }}
            QLabel#tcTagline {{
                font-size: 10px;
                color: {muted};
                background: transparent;
            }}
            QLabel#tcBadge {{
                font-size: 9px;
                font-weight: 600;
                color: {text};
                background: {line};
                border-radius: 6px;
                padding: 1px 6px;
            }}
            QLabel#tcActive {{
                font-size: 10px;
                font-weight: 700;
                color: {active_color};
                background: transparent;
            }}
        """)

    def set_active(self, active: bool) -> None:
        self._active = active
        self._active_label.setText("Active" if active else "")
        self._apply_card_style()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._key)
        super().mousePressEvent(event)
