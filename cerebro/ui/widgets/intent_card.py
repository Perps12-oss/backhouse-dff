# cerebro/ui/widgets/intent_card.py

try:
    from PySide6.QtWidgets import QFrame, QVBoxLayout, QHBoxLayout, QLabel
    from PySide6.QtGui import QFont, QColor
    from PySide6.QtCore import Qt, Signal
except ImportError:
    from PyQt6.QtWidgets import QFrame, QVBoxLayout, QHBoxLayout, QLabel
    from PyQt6.QtGui import QFont, QColor
    from PyQt6.QtCore import Qt
    from PyQt6.QtCore import pyqtSignal as Signal


class IntentCard(QFrame):
    clicked = Signal()

    def __init__(self, icon: str, title: str, description: str, enabled: bool = True, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(200, 140)
        self._enabled = enabled
        self._selected = False  # Add selection state tracking

        self._update_style()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        self.icon = QLabel(icon)
        self.icon.setAlignment(Qt.AlignCenter)
        icon_font = QFont("Segoe UI Emoji", 28)
        self.icon.setFont(icon_font)
        layout.addWidget(self.icon)

        self.title = QLabel(title)
        self.title.setAlignment(Qt.AlignCenter)
        title_font = QFont()
        title_font.setPointSize(13)
        title_font.setBold(True)
        self.title.setFont(title_font)
        self.title.setStyleSheet("color: #f1f5f9;")
        layout.addWidget(self.title)

        self.desc = QLabel(description)
        self.desc.setWordWrap(True)
        self.desc.setAlignment(Qt.AlignCenter)
        self.desc.setStyleSheet("color: #94a3b8; font-size: 11px;")
        layout.addWidget(self.desc)

    def _update_style(self):
        """Update card appearance based on state"""
        if not self._enabled:
            # Disabled state
            bg_color = '#0f172a'
            border_color = '#334155'
            hover_border = '#334155'
        elif self._selected:
            # Selected state
            bg_color = '#1e40af'  # Darker blue for selected
            border_color = '#60a5fa'
            hover_border = '#93c5fd'
        else:
            # Normal enabled state
            bg_color = '#1e293b'
            border_color = '#3b82f6'
            hover_border = '#60a5fa'

        self.setStyleSheet(f"""
            IntentCard {{
                background-color: {bg_color};
                border: 2px solid {border_color};
                border-radius: 12px;
            }}
            IntentCard:hover {{
                border-color: {hover_border};
            }}
        """)

    def set_selected(self, selected: bool):
        """Set selection state"""
        if self._selected != selected:
            self._selected = selected
            self._update_style()

    def is_selected(self) -> bool:
        """Get selection state"""
        return self._selected

    def set_enabled(self, enabled: bool):
        """Set enabled state"""
        if self._enabled != enabled:
            self._enabled = enabled
            self.setCursor(Qt.PointingHandCursor if enabled else Qt.ArrowCursor)
            self._update_style()

    def is_enabled(self) -> bool:
        """Get enabled state"""
        return self._enabled

    def mousePressEvent(self, event):
        if self._enabled:
            self.clicked.emit()
        super().mousePressEvent(event)