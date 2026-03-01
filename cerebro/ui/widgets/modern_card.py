# cerebro/ui/widgets/modern_card.py
from PySide6.QtWidgets import QFrame
from PySide6.QtCore import Qt, QPropertyAnimation
from PySide6.QtGui import QPainter, QColor, QPen

class ModernCard(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ModernCard")
        # Don't call _setup_ui() here — let child classes decide

    
    def _setup_ui(self):
        self.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Raised)
        self.setStyleSheet("""
            QFrame#ModernCard {
                background: rgba(255, 255, 255, 0.05);
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 12px;
                padding: 16px;
            }
            QFrame#ModernCard:hover {
                background: rgba(255, 255, 255, 0.08);
                border: 1px solid rgba(0, 196, 180, 0.4);
            }
        """)