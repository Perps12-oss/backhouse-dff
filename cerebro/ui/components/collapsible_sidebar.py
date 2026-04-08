# cerebro/ui/components/collapsible_sidebar.py
"""
Collapsible Sidebar Component

Auto-collapse left panel post-scan and expand pre-scan with toggle button.
Results get full width after scan starts, improving UX and addressing Ashisoft parity issues.

R-06: Auto-collapse left panel
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from cerebro.ui.components.modern._tokens import SPACE_UNIT, RADIUS_MD, token


class CollapsibleSidebar(QFrame):
    """
    Collapsible sidebar panel that auto-collapses during scanning.

    Features:
    - Auto-collapse when scan starts (results get full width)
    - Toggle button to manually expand/collapse
    - Smooth transitions and theme-aware styling
    - State signals for parent components
    """

    # Signals
    collapse_requested = Signal()
    expand_requested = Signal()
    state_changed = Signal(bool)  # True = expanded, False = collapsed

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("CollapsibleSidebar")

        # State
        self._expanded = True
        self._content_widget: Optional[QWidget] = None

        # Build UI
        self._build_ui()
        self._apply_theme()

    def _build_ui(self) -> None:
        """Build the collapsible sidebar."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Toggle button bar
        toggle_bar = QFrame()
        toggle_bar.setObjectName("SidebarToggleBar")
        toggle_layout = QHBoxLayout(toggle_bar)
        toggle_layout.setContentsMargins(SPACE_UNIT, SPACE_UNIT, SPACE_UNIT, SPACE_UNIT)
        toggle_layout.setSpacing(SPACE_UNIT)

        self._toggle_btn = QPushButton("◀")
        self._toggle_btn.setObjectName("SidebarToggleBtn")
        self._toggle_btn.setFixedWidth(30)
        self._toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._toggle_btn.clicked.connect(self._toggle_expansion)
        toggle_layout.addWidget(self._toggle_btn)

        self._title_label = QLabel("Folders")
        self._title_label.setObjectName("SidebarTitle")
        toggle_layout.addWidget(self._title_label, 1)

        toggle_layout.addStretch()

        layout.addWidget(toggle_bar)

        # Content area with scroll
        self._scroll = QScrollArea()
        self._scroll.setObjectName("SidebarScroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)

        self._content_container = QWidget()
        self._content_layout = QVBoxLayout(self._content_container)
        self._content_layout.setContentsMargins(SPACE_UNIT * 2, SPACE_UNIT * 2, SPACE_UNIT * 2, SPACE_UNIT * 2)
        self._content_layout.setSpacing(SPACE_UNIT)

        self._scroll.setWidget(self._content_container)
        layout.addWidget(self._scroll, 1)

        # Set minimum/maximum widths
        self._min_width = 50  # Collapsed width
        self._max_width = 300  # Expanded width
        self.setFixedWidth(self._max_width)

    def _toggle_expansion(self) -> None:
        """Toggle sidebar expansion."""
        if self._expanded:
            self.collapse()
        else:
            self.expand()

    def _update_toggle_button(self) -> None:
        """Update toggle button icon based on state."""
        if self._expanded:
            self._toggle_btn.setText("◀")  # Collapse arrow
        else:
            self._toggle_btn.setText("▶")  # Expand arrow

    def _update_title_visibility(self) -> None:
        """Update title label visibility based on state."""
        self._title_label.setVisible(self._expanded)

    def _update_scroll_visibility(self) -> None:
        """Update scroll area visibility based on state."""
        self._scroll.setVisible(self._expanded)

    def set_content(self, widget: QWidget) -> None:
        """Set the main content widget."""
        # Remove old content
        if self._content_widget:
            self._content_layout.removeWidget(self._content_widget)
            self._content_widget.deleteLater()

        # Add new content
        self._content_widget = widget
        self._content_layout.addWidget(widget, 1)

    def expand(self) -> None:
        """Expand the sidebar."""
        if not self._expanded:
            self._expanded = True
            self.setFixedWidth(self._max_width)
            self._update_toggle_button()
            self._update_title_visibility()
            self._update_scroll_visibility()
            self.state_changed.emit(True)
            self.expand_requested.emit()

    def collapse(self) -> None:
        """Collapse the sidebar."""
        if self._expanded:
            self._expanded = False
            self.setFixedWidth(self._min_width)
            self._update_toggle_button()
            self._update_title_visibility()
            self._update_scroll_visibility()
            self.state_changed.emit(False)
            self.collapse_requested.emit()

    def is_expanded(self) -> bool:
        """Return True if sidebar is expanded."""
        return self._expanded

    def _apply_theme(self) -> None:
        """Apply theme styling."""
        panel = token("panel")
        line = token("line")
        accent = token("accent")
        text = token("text")
        hover = token("hover_bg")

        self.setStyleSheet(f"""
            CollapsibleSidebar {{
                background: {panel};
                border-right: 1px solid {line};
            }}
            QFrame#SidebarToggleBar {{
                background: {token("bg_elevated")};
                border-bottom: 1px solid {line};
                padding: {SPACE_UNIT}px;
            }}
            QPushButton#SidebarToggleBtn {{
                background: transparent;
                border: none;
                color: {text};
                font-size: 14px;
                padding: 0;
            }}
            QPushButton#SidebarToggleBtn:hover {{
                color: {accent};
            }}
            QLabel#SidebarTitle {{
                color: {text};
                font-weight: bold;
                font-size: 14px;
            }}
            QScrollArea#SidebarScroll {{
                border: none;
                background: transparent;
            }}
        """)


# Backward compatibility alias
FolderSidebar = CollapsibleSidebar