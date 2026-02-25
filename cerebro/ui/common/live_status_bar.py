# cerebro/ui/common/live_status_bar.py

from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QFrame
)
from PySide6.QtCore import Signal, Qt, QTimer, Property
from enum import Enum
from typing import Optional


class StatusType(Enum):
    """Enumeration for different status types with their associated colors."""
    DEFAULT = "#bbb"
    INFO = "#3b82f6"
    SUCCESS = "#10b981"
    WARNING = "#f59e0b"
    ERROR = "#ef4444"


class LiveStatusBar(QWidget):
    """
    An enhanced status bar widget that displays system status, progress, and quick actions.
    
    Features:
    - Dynamic status updates with color-coded types
    - Progress display with percentage
    - Quick action buttons
    - Performance metrics display
    - Auto-hide temporary messages
    - Clean, modern styling
    """
    
    # Signals
    quick_action_triggered = Signal(str)
    metric_clicked = Signal(str)
    status_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("LiveStatusBar")
        
        # Internal state
        self._status_text = "Ready"
        self._status_type = StatusType.DEFAULT
        self._progress_visible = False
        self._temp_message_timer = QTimer(self)
        self._temp_message_timer.setSingleShot(True)
        self._temp_message_timer.timeout.connect(self._restore_persistent_status)
        
        # Setup UI
        self._setup_ui()
        self._setup_styles()
        
    def _setup_ui(self):
        """Initialize the UI components."""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(12)

        # Main status label
        self.status_label = QLabel(self._status_text)
        self.status_label.setObjectName("LiveStatusLabel")
        self.status_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.status_label.mousePressEvent = lambda e: self.status_clicked.emit()
        layout.addWidget(self.status_label)

        # Progress label (initially hidden)
        self.progress_label = QLabel("")
        self.progress_label.setObjectName("ProgressLabel")
        self.progress_label.setVisible(False)
        layout.addWidget(self.progress_label)

        # Performance metrics label (initially hidden)
        self.metrics_label = QLabel("")
        self.metrics_label.setObjectName("MetricsLabel")
        self.metrics_label.setVisible(False)
        layout.addWidget(self.metrics_label)

        # Quick action buttons container
        self.actions_frame = QFrame()
        self.actions_frame.setObjectName("ActionsFrame")
        actions_layout = QHBoxLayout(self.actions_frame)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(8)
        
        # Details button
        self.details_button = QPushButton("Details")
        self.details_button.setObjectName("DetailsButton")
        self.details_button.setCursor(Qt.PointingHandCursor)
        self.details_button.setVisible(False)
        self.details_button.clicked.connect(
            lambda: self.quick_action_triggered.emit("details")
        )
        actions_layout.addWidget(self.details_button)

        # Settings button
        self.settings_button = QPushButton("⚙")
        self.settings_button.setObjectName("SettingsButton")
        self.settings_button.setCursor(Qt.PointingHandCursor)
        self.settings_button.setFixedSize(24, 24)
        self.settings_button.setVisible(False)
        self.settings_button.clicked.connect(
            lambda: self.quick_action_triggered.emit("settings")
        )
        actions_layout.addWidget(self.settings_button)
        
        layout.addWidget(self.actions_frame)
        layout.addStretch()

    def _setup_styles(self):
        """Apply modern styling to the widget."""
        self.setStyleSheet("""
            QWidget#LiveStatusBar {
                background-color: rgba(255, 255, 255, 0.03);
                border-top: 1px solid rgba(255, 255, 255, 0.08);
            }
            QLabel#LiveStatusLabel {
                color: #bbb;
                font-size: 12px;
                padding: 2px;
            }
            QLabel#LiveStatusLabel:hover {
                color: #fff;
            }
            QLabel#ProgressLabel {
                color: #60a5fa;
                font-size: 11px;
                font-weight: 500;
            }
            QLabel#MetricsLabel {
                color: #94a3b8;
                font-size: 11px;
                font-family: monospace;
            }
            QPushButton {
                background-color: rgba(255, 255, 255, 0.05);
                border: 1px solid rgba(255, 255, 255, 0.1);
                color: #94a3b8;
                padding: 4px 12px;
                border-radius: 4px;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 0.1);
                border-color: rgba(255, 255, 255, 0.2);
                color: #cbd5e1;
            }
            QPushButton#SettingsButton {
                padding: 2px;
                font-size: 14px;
            }
        """)

    def set_status(self, text: str, status_type: StatusType = StatusType.DEFAULT, 
                   temporary: bool = False, timeout_ms: int = 3000) -> None:
        """
        Update the primary status text.
        
        Args:
            text: The status message to display
            status_type: The type/color of the status
            temporary: If True, the message will revert after timeout_ms
            timeout_ms: Duration in milliseconds for temporary messages
        """
        if temporary:
            self._temp_message_timer.start(timeout_ms)
        else:
            self._temp_message_timer.stop()
            self._status_text = text
            self._status_type = status_type
            
        self.status_label.setText(text)
        self.status_label.setStyleSheet(f"color: {status_type.value};")

    def _restore_persistent_status(self) -> None:
        """Restore the last persistent status after a temporary message."""
        self.set_status(self._status_text, self._status_type)

    def show_progress(self, percent: int, message: str = "") -> None:
        """
        Display progress information.
        
        Args:
            percent: Progress percentage (0-100)
            message: Optional progress message
        """
        self._progress_visible = True
        self.progress_label.setText(f"{percent}%")
        self.progress_label.setVisible(True)
        
        if message:
            self.set_status(message, StatusType.INFO)

    def hide_progress(self) -> None:
        """Hide the progress display."""
        self._progress_visible = False
        self.progress_label.setVisible(False)
        self.progress_label.setText("")

    def update_performance(self, fps: Optional[int] = None, 
                          memory_mb: Optional[int] = None,
                          cpu_percent: Optional[int] = None) -> None:
        """
        Update performance metrics display.
        
        Args:
            fps: Frames per second
            memory_mb: Memory usage in MB
            cpu_percent: CPU usage percentage
        """
        metrics = []
        if fps is not None:
            metrics.append(f"{fps} FPS")
        if memory_mb is not None:
            metrics.append(f"{memory_mb} MB")
        if cpu_percent is not None:
            metrics.append(f"{cpu_percent}% CPU")
            
        if metrics:
            self.metrics_label.setText(" | ".join(metrics))
            self.metrics_label.setVisible(True)
        else:
            self.metrics_label.setVisible(False)

    def show_quick_action(self, action: str, visible: bool = True) -> None:
        """
        Show or hide a quick action button.
        
        Args:
            action: The action identifier ('details' or 'settings')
            visible: Whether to show or hide the button
        """
        if action == "details":
            self.details_button.setVisible(visible)
        elif action == "settings":
            self.settings_button.setVisible(visible)

    def show_temporary_message(self, message: str, 
                              status_type: StatusType = StatusType.INFO,
                              timeout_ms: int = 3000) -> None:
        """
        Convenience method to show a temporary status message.
        
        Args:
            message: The temporary message
            status_type: The type/color of the message
            timeout_ms: Duration before reverting to previous status
        """
        self.set_status(message, status_type, temporary=True, timeout_ms=timeout_ms)

    def clear(self) -> None:
        """Reset the status bar to its default state."""
        self.set_status("Ready", StatusType.DEFAULT)
        self.hide_progress()
        self.metrics_label.setVisible(False)
        self.details_button.setVisible(False)
        self.settings_button.setVisible(False)

    # Backward compatibility methods
    def set_system_status(self, text: str, color: str = "#10b981"):
        """Backward compatibility method for setting system status."""
        # Convert color string to StatusType if possible
        status_type = StatusType.DEFAULT
        if color == "#10b981":  # green
            status_type = StatusType.SUCCESS
        elif color == "#f59e0b":  # yellow/orange
            status_type = StatusType.WARNING
        elif color == "#ef4444":  # red
            status_type = StatusType.ERROR
        elif color == "#3b82f6":  # blue
            status_type = StatusType.INFO
            
        self.set_status(text, status_type)

    def add_metric(self, metric):
        """Backward compatibility stub method."""
        # This can be enhanced later to actually add metrics
        pass

    # Property getters for external access
    @Property(str)
    def statusText(self) -> str:
        """Get the current status text."""
        return self._status_text

    @Property(bool)
    def progressVisible(self) -> bool:
        """Check if progress is visible."""
        return self._progress_visible