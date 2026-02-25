# cerebro/ui/components/modern/content_card.py
from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import QFrame, QVBoxLayout, QWidget

from ._tokens import RADIUS_MD, SPACE_UNIT, token


class ContentCard(QFrame):
    """Wrapper: 16px padding, radius-md, shadow-md (theme)."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("ContentCard")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(SPACE_UNIT * 2, SPACE_UNIT * 2, SPACE_UNIT * 2, SPACE_UNIT * 2)
        self._layout.setSpacing(SPACE_UNIT * 2)
        self._apply_theme()

    def _apply_theme(self) -> None:
        panel = token("panel")
        line = token("line")
        self.setStyleSheet(f"""
            ContentCard {{
                background: {panel};
                border-radius: {RADIUS_MD}px;
                border: 1px solid {line};
            }}
        """)

    def set_content(self, widget: QWidget) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item.widget():
                item.widget().setParent(None)
        self._layout.addWidget(widget, 1)
