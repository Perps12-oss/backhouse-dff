# cerebro/ui/widgets/glass_panel.py
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QGraphicsOpacityEffect, QLabel
)
from PySide6.QtCore import Qt, QRect, QPoint
from PySide6.QtGui import (
    QPainter, QColor, QBrush, QLinearGradient,
    QPen, QPainterPath, QRegion, QRadialGradient,
    QPixmap, QTransform, QBrush, QPen, QFont
)
from PySide6.QtWidgets import QGraphicsBlurEffect


class GlassPanel(QWidget):
    """
    A custom panel that simulates a glass morphism effect
    by blurring its background and drawing a semi-transparent
    overlay with subtle borders.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._blur_radius = 20
        self._bg_color = QColor(255, 255, 255, 20)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Capture the background under this widget
        widget_rect = self.rect()
        pixmap = self.grabBackground()
        if not pixmap.isNull():
            # Apply blur effect
            blurred = self.applyBlur(pixmap, self._blur_radius)
            painter.drawPixmap(widget_rect, blurred)

        # Draw semi-transparent overlay
        painter.fillRect(widget_rect, self._bg_color)

        # Draw subtle border
        border_color = QColor(255, 255, 255, 50)
        painter.setPen(QPen(border_color, 1))
        painter.drawRoundedRect(widget_rect, 12, 12)

    def grabBackground(self) -> QPixmap:
        """Grab the background behind this widget."""
        widget_rect = self.rect()
        top_left = self.mapToGlobal(widget_rect.topLeft())
        screen = self.screen().grabWindow(0, top_left.x(), top_left.y(), widget_rect.width(), widget_rect.height())
        return screen

    def applyBlur(self, pixmap: QPixmap, radius: int) -> QPixmap:
        """Apply a blur effect to the given pixmap."""
        blurred = QPixmap(pixmap.size())
        blurred.fill(Qt.GlobalColor.transparent)

        painter = QPainter(blurred)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # QGraphicsBlurEffect requires a QGraphicsScene
        # Here we simulate a simple blur by downscaling and upscaling
        scaled = pixmap.scaled(
            pixmap.width() // radius,
            pixmap.height() // radius,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        scaled = scaled.scaled(
            pixmap.width(),
            pixmap.height(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        painter.drawPixmap(0, 0, scaled)
        painter.end()
        return blurred

    def setBlurRadius(self, radius: int):
        self._blur_radius = radius
        self.update()

    def setBackgroundColor(self, color: QColor):
        self._bg_color = color
        self.update()