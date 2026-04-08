# cerebro/ui/components/empty_state_panel.py
"""
Empty State Panel Component

Pre-scan empty state view with 'Add folders and click Search Now' messaging
and numbered steps. Addresses User Wants W-12, W-35 - critical for first
impression and premium feel.

R-07: Build empty state view
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from cerebro.ui.components.modern._tokens import SPACE_UNIT, RADIUS_LG, token


class EmptyStatePanel(QFrame):
    """
    Pre-scan empty state view with clear instructions and numbered steps.

    Replaces blank/broken-looking area with professional "getting started"
    messaging that guides users through the scan process.
    """

    # Signals
    add_folder_clicked = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("EmptyStatePanel")

        self._build_ui()
        self._apply_theme()

    def _build_ui(self) -> None:
        """Build the empty state panel."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACE_UNIT * 4, SPACE_UNIT * 4, SPACE_UNIT * 4, SPACE_UNIT * 4)
        layout.setSpacing(SPACE_UNIT * 2)

        # Center content
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setSpacing(SPACE_UNIT * 2)

        # Icon/Emoji
        icon_label = QLabel("📁")
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_label.setStyleSheet("font-size: 48px;")
        content_layout.addWidget(icon_label)

        # Main message
        message = QLabel("Add folders and click Search Now")
        message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        message.setObjectName("EmptyStateMessage")
        content_layout.addWidget(message)

        # Subtitle
        subtitle = QLabel("Select folders to scan for duplicate files")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setObjectName("EmptyStateSubtitle")
        content_layout.addWidget(subtitle)

        # Numbered steps
        steps = QWidget()
        steps_layout = QVBoxLayout(steps)
        steps_layout.setSpacing(SPACE_UNIT)

        step_1 = QLabel("1. Add folders to scan")
        step_1.setObjectName("EmptyStateStep")
        steps_layout.addWidget(step_1)

        step_2 = QLabel("2. Configure scan options (optional)")
        step_2.setObjectName("EmptyStateStep")
        steps_layout.addWidget(step_2)

        step_3 = QLabel("3. Click 'Search Now' to begin")
        step_3.setObjectName("EmptyStateStep")
        steps_layout.addWidget(step_3)

        content_layout.addWidget(steps)

        # Add folder button
        add_folder_btn = QPushButton("Add Folders")
        add_folder_btn.setObjectName("EmptyStateButton")
        add_folder_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        add_folder_btn.clicked.connect(self.add_folder_clicked.emit)
        content_layout.addWidget(add_folder_btn)

        # Center everything
        content_layout.addStretch()
        layout.addWidget(content)
        layout.addStretch()

    def _apply_theme(self) -> None:
        """Apply theme styling."""
        panel = token("panel")
        accent = token("accent")
        text = token("text")
        muted = token("muted")
        hover = token("hover_bg")

        self.setStyleSheet(f"""
            EmptyStatePanel {{
                background: {panel};
                border: 1px solid {token("line")};
                border-radius: {RADIUS_LG}px;
            }}
            QLabel#EmptyStateMessage {{
                color: {text};
                font-size: 18px;
                font-weight: bold;
                padding: {SPACE_UNIT}px;
            }}
            QLabel#EmptyStateSubtitle {{
                color: {muted};
                font-size: 14px;
                padding: {SPACE_UNIT}px;
            }}
            QLabel#EmptyStateStep {{
                color: {text};
                font-size: 14px;
                padding: {SPACE_UNIT}px {SPACE_UNIT * 2}px;
                border-left: 3px solid {accent};
                margin: {SPACE_UNIT}px 0;
            }}
            QPushButton#EmptyStateButton {{
                background: {accent};
                color: white;
                border: none;
                border-radius: {RADIUS_LG}px;
                padding: {SPACE_UNIT * 3}px {SPACE_UNIT * 4}px;
                font-size: 16px;
                font-weight: bold;
            }}
            QPushButton#EmptyStateButton:hover {{
                background: {hover};
            }}
        """)


# Backward compatibility alias
EmptyStateView = EmptyStatePanel