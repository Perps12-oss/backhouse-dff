# cerebro/ui/widgets/page_card.py

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget
from PySide6.QtCore import Signal, Qt, QSize
from PySide6.QtGui import QCursor, QMouseEvent, QFont

from .modern_card import ModernCard


class PageCard(ModernCard):
    clicked = Signal()

    def __init__(self, title: str, subtitle: str, parent: QWidget = None):
        super().__init__(parent)
        self._clickable = False
        self._title_text = title
        self._subtitle_text = subtitle
        self._init_layout()

    def _init_layout(self):
        self.setMinimumSize(QSize(180, 130))
        self.setCursor(Qt.ArrowCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(6)

        self.title_label = QLabel(self._title_text)
        self.title_label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.title_label.setWordWrap(True)
        self.title_label.setStyleSheet("font-size: 16px; font-weight: 600;")
        layout.addWidget(self.title_label)

        self.subtitle_label = QLabel(self._subtitle_text)
        self.subtitle_label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.subtitle_label.setWordWrap(True)
        self.subtitle_label.setStyleSheet("font-size: 13px; color: gray;")
        layout.addWidget(self.subtitle_label)

        layout.addStretch()

    def set_clickable(self, enabled: bool):
        self._clickable = enabled
        if enabled:
            self.setCursor(QCursor(Qt.PointingHandCursor))
            self.setProperty("hoverable", True)
        else:
            self.setCursor(Qt.ArrowCursor)
            self.setProperty("hoverable", False)
        self.setStyle(self.style())  # Refresh styles

    def mousePressEvent(self, event: QMouseEvent):
        if self._clickable and event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)
