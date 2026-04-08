# cerebro/ui/widgets/live_scan_panel.py
"""
LiveScanPanel - Visualizes scan progress.

This widget supports two update mechanisms:
1. (Preferred) A single `update_from_snapshot(LiveScanSnapshot)` call for
   comprehensive, validated telemetry.
2. (Legacy) Individual methods like `set_phase()`, `set_progress()` for
   backward compatibility with existing code.
"""
from __future__ import annotations

import math
from typing import Optional

from PySide6.QtCore import Qt, Slot, QTimer, QRectF, QPoint
from PySide6.QtGui import (
    QFont, QColor, QPainter, QPen, QBrush, QRadialGradient
)
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QFrame, QProgressBar, QScrollArea, QGridLayout
)

# Assuming these paths are correct in your project structure
from cerebro.ui.models.live_scan_snapshot import LiveScanSnapshot, ScanPhase
from cerebro.ui.theme_engine import current_colors


class SkeletonLabel(QLabel):
    """Label that shows skeleton placeholders for unknown data."""
    
    def __init__(self, text: str = "", parent: Optional[QWidget] = None):
        super().__init__(text, parent)
        self._skeleton_text = text
        self._show_skeleton = False
        self._update_display()
    
    def set_skeleton(self, show: bool) -> None:
        """Toggle skeleton display."""
        if self._show_skeleton != show:
            self._show_skeleton = show
            self._update_display()
    
    def setText(self, text: str) -> None:
        """Set text and store for skeleton mode."""
        self._skeleton_text = text
        self._update_display()
    
    def _update_display(self) -> None:
        """Update displayed text based on skeleton mode."""
        if self._show_skeleton and self._skeleton_text:
            placeholder = ""
            for char in self._skeleton_text:
                if char.isspace():
                    placeholder += char
                else:
                    placeholder += "▯"
            super().setText(placeholder)
            self.setStyleSheet("color: rgba(190,200,220,0.4);")
        else:
            super().setText(self._skeleton_text)
            self.setStyleSheet("") # Clear skeleton style


class ProgressRing(QWidget):
    """Custom progress ring for scan visualization."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setFixedSize(80, 80)
        
        self._progress = 0.0
        self._phase = ScanPhase.READY
        self._is_pulsing = False
        self._pulse_phase = 0.0
        
        # Pulse animation timer
        self._pulse_timer = QTimer(self)
        self._pulse_timer.timeout.connect(self._update_pulse)
        self._pulse_timer.start(50)  # 20 FPS
    
    def set_progress(self, progress: float) -> None:
        """Set progress (0.0 to 1.0)."""
        self._progress = max(0.0, min(1.0, progress))
        self.update()
    
    def set_phase(self, phase: ScanPhase) -> None:
        """Set current scan phase."""
        self._phase = phase
        self._is_pulsing = phase.is_active
        self.update()
    
    def _update_pulse(self) -> None:
        """Update pulse animation."""
        if self._is_pulsing:
            self._pulse_phase = (self._pulse_phase + 0.1) % (2 * math.pi)
            self.update()

    def paintEvent(self, event) -> None:
        """Paint the progress ring."""
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.Antialiasing)
            
            colors = current_colors()
            center = self.rect().center()
            radius = min(self.width(), self.height()) // 2 - 6
            
            # Background ring
            painter.setPen(QPen(QColor(colors.get('muted', '#4A5568')), 4))
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(center, radius, radius)
            
            # --- FIX IS HERE ---
            # Initialize arc_color to a default value to prevent UnboundLocalError
            # when the pulse effect runs at 0% progress.
            arc_color = QColor(colors.get('primary', '#4299E1'))
            
            # Progress arc
            if self._progress > 0:
                # Color based on phase
                arc_color = QColor(colors.get('primary', '#4299E1'))
                if self._phase == ScanPhase.FAILED:
                    arc_color = QColor(colors.get('error', '#FC8181'))
                elif self._phase == ScanPhase.CANCELLED:
                    arc_color = QColor(colors.get('warning', '#F6AD55'))
                elif self._progress >= 1.0:
                    arc_color = QColor(colors.get('success', '#68D391'))
                elif self._phase == ScanPhase.HASHING:
                    arc_color = QColor(colors.get('info', '#63B3ED'))
                
                pen = QPen(arc_color, 4)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                painter.setPen(pen)
                
                span_angle = int(self._progress * 360 * 16)
                painter.drawArc(
                    center.x() - radius, center.y() - radius,
                    radius * 2, radius * 2,
                    90 * 16,  # Start at top
                    -span_angle  # Clockwise
                )
            
            # Center text
            painter.setPen(QPen(QColor(colors.get('text', '#E2E8F0'))))
            font = QFont("Segoe UI", 10, QFont.Weight.Bold)
            painter.setFont(font)
            
            if self._progress >= 1.0:
                text = "✓"
            elif self._progress > 0:
                text = f"{int(self._progress * 100)}%"
            else:
                text = "—"
            
            text_rect = painter.boundingRect(self.rect(), Qt.AlignmentFlag.AlignCenter, text)
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, text)
            
            # Pulse effect
            if self._is_pulsing and self._progress < 1.0:
                pulse_radius = radius + 6 + math.sin(self._pulse_phase) * 2
                gradient = QRadialGradient(center, pulse_radius)
                # Now arc_color is guaranteed to exist
                gradient.setColorAt(0, QColor(arc_color.red(), arc_color.green(), arc_color.blue(), 50))
                gradient.setColorAt(1, QColor(arc_color.red(), arc_color.green(), arc_color.blue(), 0))
                
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(gradient))
                painter.drawEllipse(center, pulse_radius, pulse_radius)

        finally:
            painter.end()


class LiveScanPanel(QFrame):
    """
    Main panel that visualizes scan progress.
    
    Supports both snapshot-based updates (preferred) and legacy granular updates.
    """
    
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        
        # Current snapshot
        self._snapshot: Optional[LiveScanSnapshot] = None
        
        self._build_ui()
        self._apply_theme()
        
        # Start with empty state
        self.reset()
    
    def _build_ui(self) -> None:
        """Build the UI layout."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        
        # Header with phase and live indicator
        header = QHBoxLayout()
        self._phase_label = QLabel("Ready")
        self._phase_label.setObjectName("PhaseLabel")
        header.addWidget(self._phase_label)
        self._live_indicator = QLabel("")
        self._live_indicator.setObjectName("LiveIndicator")
        header.addWidget(self._live_indicator)
        header.addStretch()
        self._progress_ring = ProgressRing()
        header.addWidget(self._progress_ring, 0, Qt.AlignmentFlag.AlignRight)
        layout.addLayout(header)
        self._live_blink_timer = QTimer(self)
        self._live_blink_timer.timeout.connect(self._on_live_blink)
        self._live_blink_visible = True
        
        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setObjectName("Separator") # For stylesheet
        layout.addWidget(sep)
        
        # Progress bar
        self._progress_bar = QProgressBar()
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setFixedHeight(4)
        self._progress_bar.setObjectName("ProgressBar") # For stylesheet
        layout.addWidget(self._progress_bar)
        
        # Progress percentage
        progress_layout = QHBoxLayout()
        self._progress_label = QLabel("—")
        self._progress_label.setObjectName("ProgressLabel")
        progress_layout.addWidget(self._progress_label)
        
        self._eta_label = QLabel("—")
        self._eta_label.setObjectName("EtaLabel")
        progress_layout.addWidget(self._eta_label, 0, Qt.AlignmentFlag.AlignRight)
        
        layout.addLayout(progress_layout)
        
        # Advanced details section (Files/Speed/Size/Throughput, Current file, Warnings) — hidden in Simple mode
        self._advanced_details_section = QWidget()
        self._advanced_details_section.setObjectName("AdvancedDetailsSection")
        adv_layout = QVBoxLayout(self._advanced_details_section)
        adv_layout.setContentsMargins(0, 0, 0, 0)
        adv_layout.setSpacing(8)
        
        # Statistics grid
        stats_grid = QGridLayout()
        stats_grid.setSpacing(8)
        
        self._files_label = self._create_stat_label("Files:")
        self._size_label = self._create_stat_label("Size:")
        self._speed_label = self._create_stat_label("Speed:")
        self._throughput_label = self._create_stat_label("Throughput:")
        
        stats_grid.addWidget(QLabel("Files:"), 0, 0)
        stats_grid.addWidget(self._files_label, 0, 1)
        stats_grid.addWidget(QLabel("Size:"), 0, 2)
        stats_grid.addWidget(self._size_label, 0, 3)
        stats_grid.addWidget(QLabel("Speed:"), 1, 0)
        stats_grid.addWidget(self._speed_label, 1, 1)
        stats_grid.addWidget(QLabel("Throughput:"), 1, 2)
        stats_grid.addWidget(self._throughput_label, 1, 3)
        
        stats_widget = QWidget()
        stats_widget.setLayout(stats_grid)
        adv_layout.addWidget(stats_widget)
        
        # Current file section
        adv_layout.addWidget(QLabel("Current file:"))
        
        self._current_file_frame = QFrame()
        self._current_file_frame.setObjectName("CurrentFileFrame")
        
        file_layout = QVBoxLayout(self._current_file_frame)
        file_layout.setContentsMargins(8, 6, 8, 6)
        
        self._current_file_label = QLabel("—")
        self._current_file_label.setWordWrap(True)
        self._current_file_label.setObjectName("CurrentFileLabel")
        self._current_file_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        
        file_layout.addWidget(self._current_file_label)
        adv_layout.addWidget(self._current_file_frame)
        
        # Warnings section
        adv_layout.addWidget(QLabel("Warnings:"))
        
        warning_scroll = QScrollArea()
        warning_scroll.setWidgetResizable(True)
        warning_scroll.setMinimumHeight(56)
        warning_scroll.setMaximumHeight(140)
        warning_scroll.setObjectName("WarningScrollArea")

        warning_container = QWidget()
        self._warning_layout = QVBoxLayout(warning_container)
        self._warning_layout.setContentsMargins(8, 8, 8, 8)
        self._warning_layout.setSpacing(4)

        self._warning_placeholder = QLabel("No warnings")
        self._warning_placeholder.setObjectName("WarningPlaceholder")
        self._warning_placeholder.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._warning_layout.addWidget(self._warning_placeholder)

        warning_scroll.setWidget(warning_container)
        adv_layout.addWidget(warning_scroll)
        
        layout.addWidget(self._advanced_details_section)
        
        # Results section (Groups found, Duplicates) — always visible on main view
        results_layout = QHBoxLayout()
        results_layout.setSpacing(16)
        
        self._groups_frame = self._create_result_frame("Groups found", "0")
        self._dupes_frame = self._create_result_frame("Duplicates", "0")
        
        results_layout.addWidget(self._groups_frame)
        results_layout.addWidget(self._dupes_frame)
        
        layout.addLayout(results_layout)

    def _on_live_blink(self) -> None:
        """Toggle live indicator dot for animation."""
        self._live_blink_visible = not self._live_blink_visible
        self._update_live_indicator()

    def _update_live_indicator(self) -> None:
        """Set live indicator text and style (pulsing dot when active)."""
        colors = current_colors()
        dot = "●" if self._live_blink_visible else "◦"
        self._live_indicator.setText(f"  {dot} Live")
        self._live_indicator.setStyleSheet(
            f"color: {colors.get('success', '#68D391')}; font-size: 12px; font-weight: 600;"
        )

    def _create_stat_label(self, name):
        label = SkeletonLabel("—")
        label.setObjectName(f"StatLabel_{name.replace(':', '')}")
        return label

    def _create_result_frame(self, title, value):
        frame = QFrame()
        frame.setObjectName("ResultFrame")
        
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(8, 6, 8, 6)
        
        layout.addWidget(QLabel(title))
        value_label = QLabel(value)
        value_label.setObjectName("ResultValueLabel")
        layout.addWidget(value_label)
        
        # Store reference for easy access
        if "Groups" in title:
            self._groups_label = value_label
        else:
            self._dupes_label = value_label
            
        return frame

    def set_show_advanced_details(self, show: bool) -> None:
        """Show or hide Files/Speed/Size/Throughput, Current file, and Warnings (Advanced mode only)."""
        if hasattr(self, "_advanced_details_section") and self._advanced_details_section is not None:
            self._advanced_details_section.setVisible(show)

    def _apply_theme(self) -> None:
        """Apply theme colors via stylesheet."""
        colors = current_colors()
        self.setStyleSheet(f"""
            LiveScanPanel {{
                background: {colors.get('panel', '#1A202C')};
                border: 1px solid {colors.get('border', '#2D3748')};
                border-radius: 12px;
            }}
            #PhaseLabel {{
                color: {colors.get('text', '#E2E8F0')};
                font-size: 16px;
                font-weight: 600;
            }}
            #Separator {{
                border: 1px solid {colors.get('line', '#4A5568')};
            }}
            #ProgressBar {{
                border: none;
                border-radius: 3px;
                background: {colors.get('muted', '#2D3748')};
            }}
            #ProgressBar::chunk {{
                border-radius: 3px;
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:0,
                    stop:0 {colors.get('info', '#63B3ED')},
                    stop:1 {colors.get('primary', '#4299E1')}
                );
            }}
            #ProgressLabel {{
                color: {colors.get('text', '#E2E8F0')};
                font-size: 13px;
                font-weight: 500;
            }}
            #EtaLabel {{
                color: {colors.get('text_secondary', '#A0AEC0')};
                font-size: 12px;
            }}
            #CurrentFileFrame {{
                background: {colors.get('surface', '#2D3748')};
                border: 1px solid {colors.get('border', '#4A5568')};
                border-radius: 8px;
            }}
            #CurrentFileLabel {{
                color: {colors.get('text', '#E2E8F0')};
                font-family: 'Consolas', 'Monaco', monospace;
                font-size: 11px;
            }}
            #ResultFrame {{
                background: {colors.get('surface', '#2D3748')};
                border: 1px solid {colors.get('border', '#4A5568')};
                border-radius: 10px;
            }}
            #ResultValueLabel {{
                color: {colors.get('text', '#E2E8F0')};
                font-size: 20px;
                font-weight: 700;
            }}
            #WarningScrollArea {{
                border: 1px solid {colors.get('border', '#4A5568')};
                border-radius: 8px;
                background: {colors.get('surface', '#2D3748')};
            }}
            #WarningScrollArea > QWidget > QWidget {{
                background: transparent;
            }}
            #WarningPlaceholder {{
                color: {colors.get('text_secondary', '#A0AEC0')};
                font-style: italic;
            }}
            #WarningLabel {{
                color: rgba(245, 101, 101, 0.9);
                font-size: 11px;
                padding: 2px 0px;
            }}
        """)

    def refresh_theme(self) -> None:
        """Re-apply theme so panel colors update on light/dark switch."""
        self._apply_theme()
        self.update()

    # ------------------------------------------------------------------------
    # Public API - Single update method from snapshot (Preferred)
    # ------------------------------------------------------------------------
    
    @Slot(object)
    def update_from_snapshot(self, snapshot: Optional[LiveScanSnapshot]) -> None:
        """
        Update the entire panel from a LiveScanSnapshot.
        This is the preferred way to update telemetry.
        """
        self._snapshot = snapshot
        if not snapshot:
            self.reset()
            return

        # Update phase and progress; never leave "Discovering…" after completion
        if snapshot.phase == ScanPhase.COMPLETED or snapshot.progress_weighted >= 1.0:
            self._phase_label.setText("Scan complete")
            self._progress_ring.set_progress(1.0)
            self._progress_ring.set_phase(ScanPhase.COMPLETED)
        else:
            self._phase_label.setText(snapshot.format_phase_display())
            self._progress_ring.set_progress(snapshot.progress_weighted)
            self._progress_ring.set_phase(snapshot.phase)
        # Live activity indicator (animated when active)
        if snapshot.is_active and not getattr(snapshot, "is_cancelling", False):
            if not self._live_blink_timer.isActive():
                self._live_blink_timer.start(450)
            self._update_live_indicator()
        else:
            self._live_blink_timer.stop()
            self._live_indicator.setText("")
            self._live_indicator.setStyleSheet("")
        
        # Progress bar and labels
        progress_percent = int(snapshot.progress_weighted * 100)
        self._progress_bar.setValue(progress_percent)
        self._progress_label.setText(snapshot.format_progress_percentage())
        
        # ETA
        if snapshot.phase.is_active and snapshot.throughput.eta_seconds:
            self._eta_label.setText(f"ETA: {snapshot.throughput.format_eta()}")
        else:
            self._eta_label.setText("—")
        
        # Statistics with skeleton placeholders
        self._files_label.setText(snapshot.format_files_processed())
        self._files_label.set_skeleton(
            snapshot.validity.show_skeleton_for_totals and 
            not snapshot.validity.has_file_counts
        )
        
        self._size_label.setText(snapshot.format_bytes_processed())
        self._size_label.set_skeleton(
            snapshot.validity.show_skeleton_for_totals and 
            not snapshot.validity.has_byte_counts
        )
        
        # Speed and throughput
        if snapshot.validity.is_initial_warmup:
            self._speed_label.setText("Measuring…")
            self._throughput_label.setText("Measuring…")
            self._speed_label.set_skeleton(False)
            self._throughput_label.set_skeleton(False)
        elif snapshot.phase.is_active:
            self._speed_label.setText(snapshot.throughput.format_files_per_second())
            self._throughput_label.setText(snapshot.throughput.format_throughput())
            self._speed_label.set_skeleton(False)
            self._throughput_label.set_skeleton(False)
        else:
            self._speed_label.setText("—")
            self._throughput_label.setText("—")
            self._speed_label.set_skeleton(False)
            self._throughput_label.set_skeleton(False)
        
        # Current file
        self._current_file_label.setText(snapshot.format_current_file_display())
        
        # Results
        self._groups_label.setText(f"{snapshot.groups_found:,}")
        self._dupes_label.setText(f"{snapshot.duplicates_found:,}")
        
        # Warnings
        self._clear_warnings()
        if snapshot.warnings:
            self._warning_placeholder.hide()
            for warning in snapshot.warnings[-5:]:  # Show last 5 warnings
                warning_label = QLabel(warning)
                warning_label.setObjectName("WarningLabel")
                warning_label.setWordWrap(True)
                warning_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                self._warning_layout.addWidget(warning_label)
        else:
            self._warning_placeholder.show()
            self._warning_placeholder.setText("No warnings")

    # ------------------------------------------------------------------------
    # Legacy API (for backward compatibility)
    # ------------------------------------------------------------------------
    
    def set_phase(self, phase: str) -> None:
        """Legacy method - updates phase directly."""
        # Map "complete" -> COMPLETED for display and ring
        phase_upper = (phase or "").strip().upper()
        if phase_upper in ("COMPLETE", "COMPLETED"):
            self._phase_label.setText("Scan complete")
            self._progress_ring.set_phase(ScanPhase.COMPLETED)
        else:
            self._phase_label.setText(phase or "Ready")
            try:
                phase_enum = ScanPhase(phase_upper) if phase_upper else ScanPhase.READY
                self._progress_ring.set_phase(phase_enum)
            except (ValueError, AttributeError):
                self._progress_ring.set_phase(ScanPhase.READY)

    def set_phase_display(self, text: str) -> None:
        """Set phase label text only (e.g. 'Scan complete')."""
        self._phase_label.setText(text or "Ready")

    def set_current_path(self, path: str) -> None:
        """Legacy method - updates current file path directly."""
        self._current_file_label.setText(path if path else "—")

    def set_progress(self, progress: float) -> None:
        """Legacy method - updates progress directly."""
        progress = max(0.0, min(1.0, progress))
        self._progress_bar.setValue(int(progress * 100))
        self._progress_ring.set_progress(progress)
        self._progress_label.setText(f"{int(progress * 100)}%")

    def set_group_count(self, count: int) -> None:
        """Legacy method - updates group count directly."""
        self._groups_label.setText(f"{count:,}")

    def append_warning(self, message: str) -> None:
        """Legacy method - appends a warning directly."""
        # Hide placeholder if it's visible
        if self._warning_placeholder.isVisible():
            self._warning_placeholder.hide()
        
        warning_label = QLabel(message)
        warning_label.setObjectName("WarningLabel")  # Use same style
        warning_label.setWordWrap(True)
        warning_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._warning_layout.addWidget(warning_label)

    def reset(self) -> None:
        """Legacy method - resets the panel."""
        self._live_blink_timer.stop()
        self._live_indicator.setText("")
        self._live_indicator.setStyleSheet("")
        self._phase_label.setText("Ready")
        self._progress_ring.set_progress(0.0)
        self._progress_ring.set_phase(ScanPhase.READY)
        self._progress_bar.setValue(0)
        self._progress_label.setText("—")
        self._eta_label.setText("—")
        
        self._files_label.setText("—")
        self._files_label.set_skeleton(False)
        self._size_label.setText("—")
        self._size_label.set_skeleton(False)
        self._speed_label.setText("—")
        self._speed_label.set_skeleton(False)
        self._throughput_label.setText("—")
        self._throughput_label.set_skeleton(False)
        
        self._current_file_label.setText("—")
        self._groups_label.setText("0")
        self._dupes_label.setText("0")
        
        self._clear_warnings()
        self._warning_placeholder.setText("No warnings")
        self._warning_placeholder.show()
    
    def _clear_warnings(self) -> None:
        """Clear all warning labels except placeholder."""
        while self._warning_layout.count() > 1:
            item = self._warning_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        if self._warning_layout.indexOf(self._warning_placeholder) == -1:
            self._warning_layout.addWidget(self._warning_placeholder)

    def closeEvent(self, event) -> None:
        """Clean up timers when closing."""
        self._progress_ring._pulse_timer.stop()
        super().closeEvent(event)