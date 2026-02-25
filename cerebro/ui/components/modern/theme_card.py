# cerebro/ui/components/modern/theme_card.py
from __future__ import annotations

from typing import Optional, List

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton

from ._tokens import RADIUS_MD, SPACE_UNIT, token


class ThemeCard(QFrame):
    """Preview swatch (4-color palette), name, and active indicator. Click card to apply instantly (VS Code style)."""

    clicked = Signal(str)

    def __init__(
        self,
        theme_key: str,
        theme_name: str,
        colors: List[str],
        active: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self.setObjectName("ThemeCard")
        self._key = theme_key
        self._active = active
        self.setCursor(Qt.PointingHandCursor)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACE_UNIT * 2, SPACE_UNIT * 2, SPACE_UNIT * 2, SPACE_UNIT * 2)
        layout.setSpacing(SPACE_UNIT)

        # 4-color swatch row
        swatch = QFrame()
        swatch.setFixedHeight(32)
        swatch.setObjectName("themeCardSwatch")
        swatch_layout = QHBoxLayout(swatch)
        swatch_layout.setContentsMargins(0, 0, 0, 0)
        swatch_layout.setSpacing(2)
        for c in (colors or [token("bg"), token("panel"), token("accent"), token("text")])[:4]:
            box = QFrame()
            box.setStyleSheet(f"background: {c}; border-radius: 3px;")
            box.setFixedHeight(32)
            box.setFixedWidth(50)
            swatch_layout.addWidget(box, 1)
        layout.addWidget(swatch, 0)

        name_label = QLabel(theme_name)
        name_label.setObjectName("themeCardName")
        layout.addWidget(name_label, 0)

        self._active_label = QLabel("✓ Active" if active else "")
        self._active_label.setObjectName("themeCardActive")
        layout.addWidget(self._active_label, 0)

        layout.addStretch(1)

        self._apply_theme()

    def _apply_theme(self) -> None:
        panel = token("panel")
        line = token("line")
        text = token("text")
        accent = token("accent")
        bg = token("bg")
        
        # VS Code style: Active card has accent border, hover has lighter border
        border_color = accent if self._active else line
        border_width = "2px" if self._active else "1px"
        
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
            QLabel#themeCardName {{ 
                font-weight: bold; 
                font-size: 13px;
                color: {text}; 
            }}
            QLabel#themeCardActive {{ 
                font-size: 11px; 
                font-weight: bold;
                color: {accent}; 
            }}
        """)

    def set_active(self, active: bool) -> None:
        """Update active state (VS Code style with checkmark)."""
        self._active = active
        self._active_label.setText("✓ Active" if active else "")
        self._apply_theme()
    
    def mousePressEvent(self, event) -> None:
        """Click anywhere on the card to apply theme instantly (VS Code style)."""
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._key)
        super().mousePressEvent(event)
