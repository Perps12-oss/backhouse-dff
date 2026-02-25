# cerebro/ui/widgets/section_header.py

from PySide6.QtWidgets import QWidget, QLabel, QHBoxLayout
from PySide6.QtGui import QFont
from PySide6.QtCore import Qt
from cerebro.ui.state_bus import bus


class SectionHeader(QWidget):
    """Styled section header with title and optional subtitle."""

    def __init__(self, title: str, subtitle: str = "", parent=None):
        super().__init__(parent)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        title_label = QLabel(title)
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setStyleSheet("color: #f1f5f9;")
        layout.addWidget(title_label)

        if subtitle:
            subtitle_label = QLabel(subtitle)
            subtitle_font = QFont()
            subtitle_font.setPointSize(10)
            subtitle_label.setFont(subtitle_font)
            subtitle_label.setStyleSheet("color: #94a3b8;")
            layout.addWidget(subtitle_label)

        layout.addStretch()
