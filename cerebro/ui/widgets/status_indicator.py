# cerebro/ui/components/status_indicator.py

from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel
from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QColor, QBrush, QPen
from cerebro.ui.theme_engine import ThemeMixin


class StatusIndicator(QWidget, ThemeMixin):
    """Circular status indicator for scan operations."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(16, 16)
        
        self._state = 'idle'  # idle, scanning, paused, success, error
        self._states = {
            'idle': ('#94a3b8', False),
            'scanning': ('#3b82f6', True),  # Blue with animation
            'paused': ('#f59e0b', False),   # Amber
            'success': ('#10b981', False),  # Green
            'error': ('#ef4444', False)     # Red
        }
        
    def set_state(self, state: str):
        """Set the indicator state."""
        if state in self._states:
            self._state = state
            self.update()
            
    def paintEvent(self, event):
        """Draw the status indicator."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # Get color for current state
        color_hex, animated = self._states.get(self._state, ('#94a3b8', False))
        color = QColor(color_hex)
        
        # Draw background
        painter.setBrush(QBrush(color))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(2, 2, 12, 12)
        
        # Add animation effect for scanning state
        if animated and self._state == 'scanning':
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(color.lighter(150), 2))
            painter.drawEllipse(0, 0, 16, 16)