# cerebro/ui/components/modern/preview_inspector.py
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import QFrame, QVBoxLayout, QPushButton, QWidget, QScrollArea

from ._tokens import INSPECTOR_WIDTH, RADIUS_MD, SPACE_UNIT, token


class PreviewInspector(QFrame):
    closed = Signal()

    def __init__(self, parent=None, width: int = INSPECTOR_WIDTH):
        super().__init__(parent)
        self.setObjectName("PreviewInspector")
        self._width = width
        self.setMinimumWidth(width)
        self._content_widget: Optional[QWidget] = None
        self._collapsed = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._toggle_btn = QPushButton("◀ Close")
        self._toggle_btn.setObjectName("previewInspectorToggle")
        self._toggle_btn.clicked.connect(self._on_toggle)
        layout.addWidget(self._toggle_btn, 0)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setStyleSheet("background: transparent;")
        layout.addWidget(self._scroll, 1)

        self._apply_theme()

    def _on_toggle(self) -> None:
        self.toggle()
        self.closed.emit()

    def _apply_theme(self) -> None:
        panel = token("panel")
        line = token("line")
        text = token("text")
        self.setStyleSheet(f"""
            PreviewInspector {{
                background: {panel};
                border-left: 1px solid {line};
            }}
            QPushButton#previewInspectorToggle {{
                color: {text};
                text-align: left;
                padding: {SPACE_UNIT}px;
            }}
        """)

    def set_content(self, widget: QWidget) -> None:
        self._content_widget = widget
        self._scroll.setWidget(widget)

    def collapse(self) -> None:
        self._collapsed = True
        self._scroll.setVisible(False)
        self._toggle_btn.setText("▶ Expand")
        self.setMaximumWidth(48)

    def expand(self) -> None:
        self._collapsed = False
        self._scroll.setVisible(True)
        self._toggle_btn.setText("◀ Close")
        self.setMaximumWidth(16777215)
        self.setMinimumWidth(self._width)

    def toggle(self) -> None:
        if self._collapsed:
            self.expand()
        else:
            self.collapse()
