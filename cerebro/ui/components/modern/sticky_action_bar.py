# cerebro/ui/components/modern/sticky_action_bar.py
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QWidget

from ._tokens import SPACE_UNIT, RADIUS_SM, STICKY_BAR_HEIGHT, token


class StickyActionBar(QFrame):
    primary_clicked = Signal()
    secondary_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("StickyActionBar")
        self.setFixedHeight(STICKY_BAR_HEIGHT)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(SPACE_UNIT * 2, 0, SPACE_UNIT * 2, 0)
        layout.setSpacing(SPACE_UNIT * 2)

        self._summary = QLabel("")
        self._summary.setObjectName("stickySummary")
        self._subtext = QLabel("")
        self._subtext.setObjectName("stickySubtext")
        layout.addWidget(self._summary, 0)
        layout.addWidget(self._subtext, 1)
        layout.addStretch(1)

        self._secondary_btn = QPushButton("Cancel")
        self._secondary_btn.clicked.connect(self.secondary_clicked.emit)
        layout.addWidget(self._secondary_btn, 0)

        self._primary_btn = QPushButton("Confirm")
        self._primary_btn.clicked.connect(self.primary_clicked.emit)
        layout.addWidget(self._primary_btn, 0)

        self._apply_theme()

    def _apply_theme(self) -> None:
        text = token("text")
        muted = token("muted")
        accent = token("accent")
        line = token("line")
        panel = token("panel")
        self.setStyleSheet(f"""
            StickyActionBar {{
                background: {panel};
                border-top: 1px solid {line};
            }}
            QLabel#stickySummary {{ font-size: 14px; font-weight: bold; color: {text}; }}
            QLabel#stickySubtext {{ font-size: 12px; color: {muted}; }}
            QPushButton {{ border-radius: {RADIUS_SM}px; padding: {SPACE_UNIT}px {SPACE_UNIT * 2}px; }}
            QPushButton:hover {{ background: {token('hover_bg')}; }}
        """)
        self._primary_btn.setStyleSheet(f"background: {accent}; color: white;")

    def refresh_theme(self) -> None:
        self._apply_theme()
        self.update()

    def set_summary(self, text: str, subtext: str = "") -> None:
        self._summary.setText(text)
        self._subtext.setText(subtext)

    def set_primary_enabled(self, enabled: bool) -> None:
        self._primary_btn.setEnabled(enabled)

    def set_primary_text(self, text: str) -> None:
        self._primary_btn.setText(text)

    def set_secondary_text(self, text: str) -> None:
        self._secondary_btn.setText(text)

    def set_secondary_enabled(self, enabled: bool) -> None:
        self._secondary_btn.setEnabled(enabled)
