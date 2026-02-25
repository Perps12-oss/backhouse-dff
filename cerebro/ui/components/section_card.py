# cerebro/ui/components/section_card.py

from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, 
    QLabel, QWidget, QSizePolicy
)
from PySide6.QtCore import Qt, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QFont, QPalette, QColor
from cerebro.ui.theme_engine import ThemeMixin


class SectionCard(QFrame, ThemeMixin):
    """Card container with header and content area for organized sections."""
    
    def __init__(self, title: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("SectionCard")
        
        self.title = title
        self.content_widget = None
        
        self._setup_ui()
        
    def _setup_ui(self):
        """Set up the card layout and styling."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Header
        self.header_widget = self._create_header()
        layout.addWidget(self.header_widget)
        
        # Content area
        self.content_container = QWidget()
        self.content_container.setObjectName("ContentContainer")
        self.content_container.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.MinimumExpanding
        )
        
        self.content_layout = QVBoxLayout(self.content_container)
        self.content_layout.setContentsMargins(16, 16, 16, 16)
        self.content_layout.setSpacing(8)
        
        layout.addWidget(self.content_container)
        
        # Apply initial styles
        self._apply_styles()
        
    def _create_header(self) -> QWidget:
        """Create the card header with title."""
        widget = QWidget()
        widget.setObjectName("CardHeader")
        widget.setFixedHeight(48)
        
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(16, 0, 16, 0)
        layout.setSpacing(12)
        
        # Title label
        self.title_label = QLabel(self.title)
        self.title_label.setObjectName("CardTitle")
        
        layout.addWidget(self.title_label)
        layout.addStretch()
        
        # Optional: Add action buttons or indicators
        self.actions_widget = QWidget()
        self.actions_layout = QHBoxLayout(self.actions_widget)
        self.actions_layout.setContentsMargins(0, 0, 0, 0)
        self.actions_layout.setSpacing(4)
        
        layout.addWidget(self.actions_widget)
        
        return widget
        
    def set_content(self, widget: QWidget):
        """Set the content widget for this card."""
        if self.content_widget:
            self.content_layout.removeWidget(self.content_widget)
            self.content_widget.deleteLater()
            
        self.content_widget = widget
        self.content_layout.addWidget(widget)
        
    def add_action_widget(self, widget: QWidget):
        """Add a widget to the header actions area."""
        self.actions_layout.addWidget(widget)
        
    def clear_actions(self):
        """Clear all action widgets."""
        while self.actions_layout.count():
            item = self.actions_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
                
    def set_title(self, title: str):
        """Update the card title."""
        self.title = title
        self.title_label.setText(title)
        
    def set_content_margins(self, left: int, top: int, right: int, bottom: int):
        """Set custom margins for the content area."""
        self.content_layout.setContentsMargins(left, top, right, bottom)
        
    def set_content_spacing(self, spacing: int):
        """Set spacing between content widgets."""
        self.content_layout.setSpacing(spacing)
        
    def animate_appearance(self):
        """Animate the card appearance (slide in/fade)."""
        # Fade in animation
        self.setGraphicsEffect(None)  # Remove any existing effect
        
        opacity_effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(opacity_effect)
        
        fade_animation = QPropertyAnimation(opacity_effect, b"opacity")
        fade_animation.setDuration(300)
        fade_animation.setStartValue(0.0)
        fade_animation.setEndValue(1.0)
        fade_animation.setEasingCurve(QEasingCurve.OutCubic)
        fade_animation.start()
        
    def highlight(self, duration: int = 1000):
        """Briefly highlight the card (for new content or updates)."""
        original_style = self.styleSheet()
        
        highlight_color = "#3b82f6"
        
        self.setStyleSheet(f"""
            #SectionCard {{
                border: 2px solid {highlight_color};
                border-radius: 8px;
                background-color: rgba(59, 130, 246, 0.05);
            }}
        """)
        
        # Reset after duration
        QTimer.singleShot(duration, lambda: self._apply_styles())
        
    def _apply_styles(self):
        """Apply the card's default styling."""
        self.setStyleSheet("""
            #SectionCard {
                background-color: #1e293b;
                border: 1px solid #334155;
                border-radius: 8px;
            }
            
            #CardHeader {
                background-color: rgba(30, 41, 59, 0.8);
                border-bottom: 1px solid #334155;
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
            }
            
            QLabel#CardTitle {
                color: #f8fafc;
                font-size: 16px;
                font-weight: bold;
            }
            
            #ContentContainer {
                background-color: transparent;
            }
        """)
        
    def apply_theme(self, theme: dict):
        """Apply theme colors to the card."""
        bg_color = theme.get("background_secondary", "#1e293b")
        border_color = theme.get("border", "#334155")
        text_color = theme.get("text_primary", "#f8fafc")
        
        header_bg = theme.get("background_tertiary", "rgba(30, 41, 59, 0.8)")
        
        self.setStyleSheet(f"""
            #SectionCard {{
                background-color: {bg_color};
                border: 1px solid {border_color};
                border-radius: 8px;
            }}
            
            #CardHeader {{
                background-color: {header_bg};
                border-bottom: 1px solid {border_color};
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
            }}
            
            QLabel#CardTitle {{
                color: {text_color};
                font-size: 16px;
                font-weight: bold;
            }}
            
            #ContentContainer {{
                background-color: transparent;
            }}
        """)
        
        # Apply theme to child widgets
        if self.content_widget and hasattr(self.content_widget, 'apply_theme'):
            self.content_widget.apply_theme(theme)


class ExpandableSectionCard(SectionCard):
    """Section card that can be expanded/collapsed."""
    
    def __init__(self, title: str = "", parent=None):
        super().__init__(title, parent)
        
        self.expanded = True
        self.content_height = 0
        
        self._setup_expandable()
        
    def _setup_expandable(self):
        """Set up expandable functionality."""
        # Add expand/collapse button
        self.expand_button = QPushButton("▼")
        self.expand_button.setObjectName("ExpandButton")
        self.expand_button.setFixedSize(24, 24)
        self.expand_button.setCheckable(True)
        self.expand_button.setChecked(True)  # Expanded by default
        self.expand_button.clicked.connect(self.toggle_expanded)
        
        self.actions_layout.addWidget(self.expand_button)
        
        # Animation for expansion/collapse
        self.expand_animation = QPropertyAnimation(self.content_container, b"maximumHeight")
        self.expand_animation.setDuration(300)
        self.expand_animation.setEasingCurve(QEasingCurve.InOutCubic)
        
    def toggle_expanded(self):
        """Toggle expanded state."""
        self.expanded = not self.expanded
        
        if self.expanded:
            self.expand()
        else:
            self.collapse()
            
    def expand(self):
        """Expand the card to show content."""
        self.expanded = True
        self.expand_button.setText("▼")
        
        # Store content height if not already known
        if self.content_height == 0:
            self.content_container.setMaximumHeight(16777215)  # Qt's maximum
            self.content_height = self.content_container.sizeHint().height()
            
        # Animate expansion
        self.expand_animation.setStartValue(0)
        self.expand_animation.setEndValue(self.content_height)
        self.expand_animation.start()
        
    def collapse(self):
        """Collapse the card to hide content."""
        self.expanded = False
        self.expand_button.setText("▶")
        
        # Store current height
        current_height = self.content_container.height()
        
        # Animate collapse
        self.expand_animation.setStartValue(current_height)
        self.expand_animation.setEndValue(0)
        self.expand_animation.start()
        
    def set_content(self, widget: QWidget):
        """Set content widget and update height calculations."""
        super().set_content(widget)
        
        # Update content height
        if self.expanded:
            self.content_container.setMaximumHeight(16777215)
            QTimer.singleShot(100, self._update_content_height)
            
    def _update_content_height(self):
        """Update the stored content height."""
        self.content_height = self.content_container.sizeHint().height()
        if not self.expanded:
            self.content_container.setMaximumHeight(0)