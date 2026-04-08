# cerebro/ui/components/scanning_state_panel.py
"""
Scanning State Panel Component

Shows progress bar, filename, and live counters in the results area
during active scans. Addresses User Wants W-12, W-36 - provides user
feedback during active scans.

R-08: Build scanning state view
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from cerebro.ui.components.modern._tokens import SPACE_UNIT, RADIUS_MD, token


class ScanningStatePanel(QFrame):
    """
    Scanning state panel that displays progress, current file, and live counters.

    Provides real-time feedback during active scans, replacing blank/broken
    looking areas with professional progress indicators.
    """

    # Signals
    cancel_requested = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("ScanningStatePanel")

        # Scan state
        self._is_scanning = False
        self._current_file = ""
        self._files_scanned = 0
        self._total_files = 0
        self._duplicates_found = 0
        self._groups_found = 0
        self._progress_percent = 0

        # Build UI
        self._build_ui()
        self._apply_theme()
        self._update_display()

    def _build_ui(self) -> None:
        """Build the scanning state panel."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACE_UNIT * 3, SPACE_UNIT * 3, SPACE_UNIT * 3, SPACE_UNIT * 3)
        layout.setSpacing(SPACE_UNIT * 2)

        # Progress bar
        self._progress_bar = QProgressBar()
        self._progress_bar.setObjectName("ScanProgressBar")
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._progress_bar.setTextVisible(True)
        self._progress_bar.setFormat("Scanning... %p%")
        layout.addWidget(self._progress_bar)

        # Current file
        self._current_file_label = QLabel("Ready to scan")
        self._current_file_label.setObjectName("CurrentFileLabel")
        self._current_file_label.setWordWrap(True)
        layout.addWidget(self._current_file_label)

        # Stats row
        stats_row = QWidget()
        stats_layout = QHBoxLayout(stats_row)
        stats_layout.setSpacing(SPACE_UNIT * 3)

        # Files scanned
        self._files_scanned_label = QLabel("Files: 0")
        self._files_scanned_label.setObjectName("StatsLabel")
        stats_layout.addWidget(self._files_scanned_label)

        # Duplicates found
        self._duplicates_label = QLabel("Duplicates: 0")
        self._duplicates_label.setObjectName("StatsLabel")
        stats_layout.addWidget(self._duplicates_label)

        # Groups found
        self._groups_label = QLabel("Groups: 0")
        self._groups_label.setObjectName("StatsLabel")
        stats_layout.addWidget(self._groups_label)

        stats_layout.addStretch()
        layout.addWidget(stats_row)

        # Cancel button
        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setObjectName("ScanCancelButton")
        self._cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._cancel_btn.clicked.connect(self.cancel_requested.emit)
        self._cancel_btn.setEnabled(False)
        layout.addWidget(self._cancel_btn)

    def _apply_theme(self) -> None:
        """Apply theme styling."""
        panel = token("panel")
        accent = token("accent")
        text = token("text")
        muted = token("muted")
        hover = token("hover_bg")
        line = token("line")
        bg_base = token("bg_base")
        bg_elevated = token("bg_elevated")

        # Calculate chunk border radius
        chunk_radius = RADIUS_MD - 1 if RADIUS_MD > 1 else 0
        padding_val = SPACE_UNIT * 2
        half_padding = SPACE_UNIT // 2

        stylesheet = f"""
            ScanningStatePanel {{
                background: {panel};
                border: 1px solid {line};
                border-radius: {RADIUS_MD}px;
            }}
            QProgressBar#ScanProgressBar {{
                border: 1px solid {line};
                border-radius: {RADIUS_MD}px;
                text-align: center;
                color: white;
                background: {bg_base};
            }}
            QProgressBar#ScanProgressBar::chunk {{
                background: {accent};
                border-radius: {chunk_radius}px;
            }}
            QLabel#CurrentFileLabel {{
                color: {text};
                font-size: 13px;
                padding: {SPACE_UNIT}px;
            }}
            QLabel#StatsLabel {{
                color: {muted};
                font-size: 12px;
                padding: {half_padding}px;
            }}
            QPushButton#ScanCancelButton {{
                background: {bg_elevated};
                color: {text};
                border: 1px solid {line};
                border-radius: {RADIUS_MD}px;
                padding: {padding_val}px;
            }}
            QPushButton#ScanCancelButton:hover {{
                background: {hover};
            }}
            QPushButton#ScanCancelButton:disabled {{
                color: {muted};
            }}
        """
        self.setStyleSheet(stylesheet)

    def _update_display(self) -> None:
        """Update the display based on current state."""
        if not self._is_scanning:
            self._current_file_label.setText("Ready to scan")
            self._progress_bar.setValue(0)
            self._progress_bar.setFormat("Ready to scan")
            self._cancel_btn.setEnabled(False)
        else:
            if self._current_file:
                self._current_file_label.setText(f"Scanning: {self._current_file}")
            else:
                self._current_file_label.setText("Scanning...")

            self._progress_bar.setValue(int(self._progress_percent))
            self._progress_bar.setFormat(f"Scanning... {int(self._progress_percent)}%")
            self._cancel_btn.setEnabled(True)

        # Update stats
        self._files_scanned_label.setText(f"Files: {self._files_scanned}")
        self._duplicates_label.setText(f"Duplicates: {self._duplicates_found}")
        self._groups_label.setText(f"Groups: {self._groups_found}")

    def set_scanning_state(self, is_scanning: bool) -> None:
        """Set the scanning state."""
        self._is_scanning = is_scanning
        self._update_display()

    def update_progress(
        self,
        files_scanned: int,
        total_files: int,
        current_file: str,
        duplicates_found: int,
        groups_found: int
    ) -> None:
        """Update scan progress information."""
        self._files_scanned = files_scanned
        self._total_files = total_files
        self._current_file = current_file
        self._duplicates_found = duplicates_found
        self._groups_found = groups_found

        # Calculate progress percentage
        if self._total_files > 0:
            self._progress_percent = (self._files_scanned / self._total_files) * 100
        else:
            self._progress_percent = 0

        self._update_display()

    def reset(self) -> None:
        """Reset the panel to initial state."""
        self._is_scanning = False
        self._current_file = ""
        self._files_scanned = 0
        self._total_files = 0
        self._duplicates_found = 0
        self._groups_found = 0
        self._progress_percent = 0
        self._update_display()

    def is_scanning(self) -> bool:
        """Return True if currently scanning."""
        return self._is_scanning


# Backward compatibility alias
ScanProgressPanel = ScanningStatePanel