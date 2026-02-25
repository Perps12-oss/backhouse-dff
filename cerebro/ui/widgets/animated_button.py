# cerebro/ui/widgets/animated_button.py

from PySide6.QtWidgets import QPushButton, QGraphicsOpacityEffect
from PySide6.QtCore import (
    Qt, QPropertyAnimation, QEasingCurve, 
    QParallelAnimationGroup, QSequentialAnimationGroup,
    Signal, Property
)
from PySide6.QtGui import QColor, QPalette, QLinearGradient, QPainter
from cerebro.ui.theme_engine import ThemeMixin


class AnimatedButton(QPushButton, ThemeMixin):
    """Advanced button with multiple animation effects and states."""
    
    hover_changed = Signal(bool)  # Emitted when hover state changes
    active_changed = Signal(bool)  # Emitted when active state changes
    
    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        
        self._hover = False
        self._active = False
        self._pressed = False
        self._loading = False
        
        # Animation effects
        self._opacity_effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._opacity_effect)
        
        # Animation group for hover effects
        self.hover_animation = QPropertyAnimation(self, b"color_offset")
        self.hover_animation.setDuration(200)
        self.hover_animation.setEasingCurve(QEasingCurve.OutCubic)
        
        # Pulse animation for loading state
        self.pulse_animation = QPropertyAnimation(self._opacity_effect, b"opacity")
        self.pulse_animation.setDuration(1000)
        self.pulse_animation.setStartValue(1.0)
        self.pulse_animation.setEndValue(0.6)
        self.pulse_animation.setLoopCount(-1)  # Infinite loop
        
        # Click animation
        self.click_animation_group = QParallelAnimationGroup(self)
        
        # Size animation
        self.size_animation = QPropertyAnimation(self, b"geometry")
        self.size_animation.setDuration(150)
        
        # Color animation
        self.color_animation = QPropertyAnimation(self, b"base_color")
        self.color_animation.setDuration(200)
        
        self.click_animation_group.addAnimation(self.size_animation)
        self.click_animation_group.addAnimation(self.color_animation)
        
        self._setup_ui()
        self._setup_animations()
        
    def _setup_ui(self):
        """Set up initial button appearance."""
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(40)
        self.setMinimumWidth(120)
        
        # Initial colors
        self._base_color = QColor(59, 130, 246)  # Blue
        self._hover_color = QColor(37, 99, 235)   # Darker blue
        self._active_color = QColor(29, 78, 216)  # Even darker blue
        self._text_color = QColor(255, 255, 255)  # White
        
        # Gradient offsets for animation
        self._color_offset = 0.0
        self._gradient_stops = []
        
        self._update_palette()
        
    def _setup_animations(self):
        """Set up animation connections."""
        # Connect button events to animations
        self.pressed.connect(self._on_pressed)
        self.released.connect(self._on_released)
        
    def _on_pressed(self):
        """Handle button press animation."""
        self._pressed = True
        self._animate_press()
        
    def _on_released(self):
        """Handle button release animation."""
        self._pressed = False
        self._animate_release()
        
    def _animate_press(self):
        """Animate button press."""
        # Scale down slightly
        geom = self.geometry()
        self.size_animation.setStartValue(geom)
        self.size_animation.setEndValue(geom.adjusted(1, 1, -1, -1))
        
        # Darken color
        self.color_animation.setStartValue(self._base_color)
        self.color_animation.setEndValue(self._active_color)
        
        self.click_animation_group.start()
        
    def _animate_release(self):
        """Animate button release."""
        # Restore size
        geom = self.geometry()
        self.size_animation.setStartValue(geom)
        self.size_animation.setEndValue(geom.adjusted(-1, -1, 1, 1))
        
        # Restore color
        self.color_animation.setStartValue(self._active_color)
        self.color_animation.setEndValue(self._base_color if not self._hover else self._hover_color)
        
        self.click_animation_group.start()
        
    def enterEvent(self, event):
        """Handle mouse enter."""
        self._hover = True
        self.hover_changed.emit(True)
        
        # Start hover animation
        self.hover_animation.stop()
        self.hover_animation.setStartValue(self._color_offset)
        self.hover_animation.setEndValue(1.0)
        self.hover_animation.start()
        
        self._update_palette()
        super().enterEvent(event)
        
    def leaveEvent(self, event):
        """Handle mouse leave."""
        self._hover = False
        self.hover_changed.emit(False)
        
        # Reverse hover animation
        self.hover_animation.stop()
        self.hover_animation.setStartValue(self._color_offset)
        self.hover_animation.setEndValue(0.0)
        self.hover_animation.start()
        
        self._update_palette()
        super().leaveEvent(event)
        
    def set_loading(self, loading: bool):
        """Set loading state with pulse animation."""
        self._loading = loading
        
        if loading:
            self.setEnabled(False)
            self.pulse_animation.start()
            
            # Update text to show loading
            if not self.text().endswith("..."):
                self._original_text = self.text()
                self.setText(self._original_text + "...")
        else:
            self.setEnabled(True)
            self.pulse_animation.stop()
            self._opacity_effect.setOpacity(1.0)
            
            # Restore original text
            if hasattr(self, '_original_text'):
                self.setText(self._original_text)
                
    def set_active(self, active: bool):
        """Set active/selected state."""
        self._active = active
        self.active_changed.emit(active)
        self._update_palette()
        
    def _update_palette(self):
        """Update button palette based on current state."""
        palette = self.palette()
        
        # Determine background color
        if self._pressed:
            bg_color = self._active_color
        elif self._hover:
            bg_color = self._hover_color
        else:
            bg_color = self._base_color
            
        if self._active:
            # Add a border for active state
            bg_color = bg_color.darker(110)
            
        palette.setColor(QPalette.Button, bg_color)
        palette.setColor(QPalette.ButtonText, self._text_color)
        
        # Set text color with contrast
        if bg_color.lightness() > 128:
            palette.setColor(QPalette.ButtonText, QColor(0, 0, 0))
        else:
            palette.setColor(QPalette.ButtonText, QColor(255, 255, 255))
            
        self.setPalette(palette)
        self.update()
        
    def paintEvent(self, event):
        """Custom paint event for gradient and rounded corners."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # Create gradient based on hover state
        gradient = QLinearGradient(0, 0, self.width(), self.height())
        
        # Calculate gradient stops with animation offset
        if self._hover or self._color_offset > 0:
            offset = self._color_offset
            stops = [
                (0.0, self._base_color),
                (offset, self._hover_color.lighter(120)),
                (1.0, self._hover_color)
            ]
        else:
            stops = [(0.0, self._base_color), (1.0, self._base_color.darker(110))]
            
        # Apply gradient stops
        for pos, color in stops:
            gradient.setColorAt(pos, color)
            
        # Draw rounded rectangle background
        painter.setBrush(gradient)
        painter.setPen(Qt.NoPen)
        
        rect = self.rect().adjusted(1, 1, -1, -1)
        painter.drawRoundedRect(rect, 6, 6)
        
        # Draw border if active
        if self._active:
            painter.setPen(QPen(self._active_color.lighter(150), 2))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(rect, 6, 6)
            
        # Draw text
        painter.setPen(self.palette().color(QPalette.ButtonText))
        painter.drawText(rect, Qt.AlignCenter, self.text())
        
    # Property for color animation
    def get_color_offset(self) -> float:
        return self._color_offset
        
    def set_color_offset(self, offset: float):
        self._color_offset = offset
        self.update()
        
    color_offset = Property(float, get_color_offset, set_color_offset)
    
    # Property for base color animation
    def get_base_color(self) -> QColor:
        return self._base_color
        
    def set_base_color(self, color: QColor):
        self._base_color = color
        self._update_palette()
        
    base_color = Property(QColor, get_base_color, set_base_color)
    
    def apply_theme(self, theme: dict):
        """Apply theme colors to button."""
        if "primary" in theme:
            self._base_color = QColor(theme["primary"])
            self._hover_color = QColor(theme.get("primary_hover", self._base_color.darker(115)))
            self._active_color = QColor(theme.get("primary_active", self._hover_color.darker(115)))
            
        if "text_primary" in theme:
            self._text_color = QColor(theme["text_primary"])
            
        self._update_palette()