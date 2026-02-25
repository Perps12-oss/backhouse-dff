# cerebro/ui/widgets/panel_wrapper.py

"""
PanelWrapper: Optional container for wrapping scan panels with border/title/animation.
"""

from PySide6.QtWidgets import QFrame, QVBoxLayout
from PySide6.QtCore import Qt


class PanelWrapper(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("PanelWrapper")
        self.setFrameShape(QFrame.StyledPanel)
        self.setFrameShadow(QFrame.Raised)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        self.setLayout(layout)

        self.setStyleSheet("""
            QFrame#PanelWrapper {
                border: 1px solid #334155;
                border-radius: 8px;
                background-color: #0f172a;
            }
        """)
