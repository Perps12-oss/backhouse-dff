# cerebro/ui/widgets/hover_button.py
"""
hover_button.py — Button with hover effects and animations
"""

from PySide6.QtWidgets import QPushButton
from PySide6.QtCore import Qt, QPropertyAnimation, QEasingCurve, QRect
from PySide6.QtGui import QPainter, QColor, QLinearGradient


class HoverButton(QPushButton):
    """Button with enhanced hover effects and animations"""
    
    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self._setup_ui()
        self._setup_animations()
    
    def _setup_ui(self):
        """Setup basic button appearance"""
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        
        # Set default style
        self.setStyleSheet("""
            HoverButton {
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 rgba(59, 130, 246, 0.1),
                    stop: 1 rgba(59, 130, 246, 0.05)
                );
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 8px;
                padding: 10px 20px;
                color: #e2e8f0;
                font-weight: 500;
                font-size: 13px;
                text-align: center;
            }
            
            HoverButton:hover {
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 rgba(59, 130, 246, 0.2),
                    stop: 1 rgba(59, 130, 246, 0.1)
                );
                border: 1px solid rgba(59, 130, 246, 0.3);
            }
            
            HoverButton:pressed {
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 rgba(59, 130, 246, 0.3),
                    stop: 1 rgba(59, 130, 246, 0.2)
                );
                padding: 11px 20px 9px 20px;
            }
        """)
    
    def _setup_animations(self):
        """Setup hover animations"""
        # Scale animation
        self._scale_animation = QPropertyAnimation(self, b"geometry")
        self._scale_animation.setDuration(150)
        self._scale_animation.setEasingCurve(QEasingCurve.Type.OutQuad)
        
        # Opacity animation
        self._opacity_effect = self.graphicsEffect()
        self._opacity_animation = QPropertyAnimation(self, b"windowOpacity")
        self._opacity_animation.setDuration(100)
    
    def enterEvent(self, event):
        """Handle mouse enter event"""
        # Animate slight scale up
        geom = self.geometry()
        new_geom = QRect(
            geom.x() - 2, geom.y() - 2,
            geom.width() + 4, geom.height() + 4
        )
        
        self._scale_animation.setStartValue(geom)
        self._scale_animation.setEndValue(new_geom)
        self._scale_animation.start()
        
        super().enterEvent(event)
    
    def leaveEvent(self, event):
        """Handle mouse leave event"""
        # Animate back to original size
        geom = self.geometry()
        original_geom = QRect(
            geom.x() + 2, geom.y() + 2,
            geom.width() - 4, geom.height() - 4
        )
        
        self._scale_animation.setStartValue(geom)
        self._scale_animation.setEndValue(original_geom)
        self._scale_animation.start()
        
        super().leaveEvent(event)
    
    def set_accent_color(self, color: str):
        """Set accent color for the button"""
        self.setStyleSheet(f"""
            HoverButton {{
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 {color}20,
                    stop: 1 {color}10
                );
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 8px;
                padding: 10px 20px;
                color: #e2e8f0;
                font-weight: 500;
                font-size: 13px;
                text-align: center;
            }}
            
            HoverButton:hover {{
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 {color}40,
                    stop: 1 {color}20
                );
                border: 1px solid {color}50;
            }}
            
            HoverButton:pressed {{
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 {color}60,
                    stop: 1 {color}40
                );
                padding: 11px 20px 9px 20px;
            }}
        """)


class IconHoverButton(HoverButton):
    """Hover button with icon support"""
    
    def __init__(self, text: str = "", icon: str = "", parent=None):
        super().__init__(text, parent)
        self._icon = icon
        self._setup_icon()
    
    def _setup_icon(self):
        """Setup icon display"""
        if self._icon:
            self.setText(f"{self._icon} {self.text()}")


class GhostButton(HoverButton):
    """Button with ghost/outline style"""
    
    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self._setup_ghost_style()
    
    def _setup_ghost_style(self):
        """Setup ghost button style"""
        self.setStyleSheet("""
            HoverButton {
                background: transparent;
                border: 1px solid rgba(255, 255, 255, 0.2);
                border-radius: 8px;
                padding: 8px 16px;
                color: #e2e8f0;
                font-weight: 500;
                font-size: 12px;
                text-align: center;
            }
            
            HoverButton:hover {
                background: rgba(255, 255, 255, 0.1);
                border: 1px solid rgba(255, 255, 255, 0.3);
            }
            
            HoverButton:pressed {
                background: rgba(255, 255, 255, 0.2);
                padding: 9px 16px 7px 16px;
            }
        """)


# Update widgets __init__.py
"""
Add to cerebro/ui/widgets/__init__.py:
"""

# In cerebro/ui/widgets/__init__.py, add:
from .hover_button import HoverButton, IconHoverButton, GhostButton