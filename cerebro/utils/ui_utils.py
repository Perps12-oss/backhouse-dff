"""
UI utility functions for CEREBRO.
"""

from typing import Optional, Tuple
from PySide6.QtCore import Qt, QRect, QPoint, QByteArray
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QWidget, QApplication, QMainWindow


def _clamp_rect_to_screen(
    window: QMainWindow,
    rect: QRect,
    avail: QRect,
) -> QRect:
    """Clamp a window rect to available screen geometry respecting min/max size."""
    min_w = window.minimumWidth()
    min_h = window.minimumHeight()
    max_w = window.maximumWidth()
    max_h = window.maximumHeight()
    if max_w <= 0:
        max_w = 99999
    if max_h <= 0:
        max_h = 99999
    w = max(min_w, min(rect.width(), avail.width(), max_w))
    h = max(min_h, min(rect.height(), avail.height(), max_h))
    x = max(avail.left(), min(rect.x(), avail.right() - w))
    y = max(avail.top(), min(rect.y(), avail.bottom() - h))
    return QRect(x, y, w, h)


def clamp_window_to_screen(window: QMainWindow, cap_max_size: bool = False) -> None:
    """
    Move and resize the window so it fits within the current screen's available
    geometry. Ensures the title bar and close button stay visible. Call after
    restoreGeometry or on first show so the window never exceeds the visible area.

    If cap_max_size is True, also sets the window maximum size to the available
    geometry so it cannot grow off-screen (e.g. after switching to a page with
    large layout like Review).
    """
    screen = window.screen() or QApplication.primaryScreen()
    if not screen:
        return
    avail = screen.availableGeometry()
    if window.windowState() & Qt.WindowState.WindowMaximized:
        window.setWindowState(window.windowState() & ~Qt.WindowState.WindowMaximized)
    fr = window.frameGeometry()
    clamped = _clamp_rect_to_screen(window, QRect(fr.x(), fr.y(), fr.width(), fr.height()), avail)
    window.setGeometry(clamped)
    if cap_max_size:
        window.setMaximumSize(avail.width(), avail.height())


def ensure_window_on_screen(window: QMainWindow) -> None:
    """
    Clamp window position and size so it fits within the current screen's
    available geometry (title bar and controls stay visible). Does not set
    maximum size so the window remains fully resizable and maximize works
    normally. Use after restore, on first show, and after navigation.
    """
    clamp_window_to_screen(window, cap_max_size=False)


def restore_main_window_geometry(
    window: QMainWindow,
    geometry: Optional[bytes] = None,
    state: Optional[bytes] = None,
) -> None:
    """
    Restore main window geometry and state from saved bytes, clamping to the
    current screen and window min/max so the platform never receives an
    invalid geometry (avoids QWindowsWindow::setGeometry warnings).
    """
    if state:
        try:
            window.restoreState(QByteArray(state))
        except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
            pass
    if geometry:
        # Decode geometry using a temporary window so we never call
        # restoreGeometry on the real window with an invalid rect.
        try:
            temp = QMainWindow()
            if temp.restoreGeometry(QByteArray(geometry)):
                decoded = temp.frameGeometry()
            else:
                decoded = None
            del temp
        except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
            decoded = None
        if decoded is not None:
            screen = window.screen() or QApplication.primaryScreen()
            if screen:
                avail = screen.availableGeometry()
                clamped = _clamp_rect_to_screen(
                    window,
                    QRect(decoded.x(), decoded.y(), decoded.width(), decoded.height()),
                    avail,
                )
                window.setGeometry(clamped)
    else:
        ensure_window_on_screen(window)


def center_widget_on_screen(widget: QWidget) -> None:
    """
    Center a widget on the screen.
    
    Args:
        widget: Widget to center
    """
    frame_geometry = widget.frameGeometry()
    screen_center = QApplication.primaryScreen().availableGeometry().center()
    frame_geometry.moveCenter(screen_center)
    widget.move(frame_geometry.topLeft())


def get_widget_center(widget: QWidget) -> QPoint:
    """
    Get the center point of a widget.
    
    Args:
        widget: Widget to get center of
        
    Returns:
        Center point of the widget
    """
    return QPoint(widget.width() // 2, widget.height() // 2)


def set_widget_opacity(widget: QWidget, opacity: float) -> None:
    """
    Set the opacity of a widget.
    
    Args:
        widget: Widget to set opacity for
        opacity: Opacity value (0.0 to 1.0)
    """
    # This is a workaround for the QPropertyAnimation error
    # Instead of animating the opacity property directly, we'll use setWindowOpacity
    widget.setWindowOpacity(opacity)


def create_color_palette(primary: Optional[Tuple[int, int, int]] = None,
                        secondary: Optional[Tuple[int, int, int]] = None) -> QPalette:
    """
    Create a color palette for the application.
    
    Args:
        primary: RGB tuple for primary color
        secondary: RGB tuple for secondary color
        
    Returns:
        QPalette with the specified colors
    """
    palette = QApplication.palette()
    
    if primary:
        primary_color = QColor(*primary)
        palette.setColor(QPalette.ColorRole.Window, primary_color.lighter())
        palette.setColor(QPalette.ColorRole.WindowText, primary_color.darker())
    
    if secondary:
        secondary_color = QColor(*secondary)
        palette.setColor(QPalette.ColorRole.Button, secondary_color)
        palette.setColor(QPalette.ColorRole.ButtonText, secondary_color.darker())
    
    return palette


def fade_widget(widget: QWidget, start_opacity: float, end_opacity: float, duration: int = 300) -> None:
    """
    Fade a widget from one opacity to another.
    
    Args:
        widget: Widget to fade
        start_opacity: Starting opacity (0.0 to 1.0)
        end_opacity: Ending opacity (0.0 to 1.0)
        duration: Duration of the fade in milliseconds
    """
    from PySide6.QtCore import QPropertyAnimation, QEasingCurve
    
    # Set initial opacity
    widget.setWindowOpacity(start_opacity)
    
    # Create animation
    animation = QPropertyAnimation(widget, b"windowOpacity")
    animation.setDuration(duration)
    animation.setStartValue(start_opacity)
    animation.setEndValue(end_opacity)
    animation.setEasingCurve(QEasingCurve.Type.InOutQuad)
    animation.start()