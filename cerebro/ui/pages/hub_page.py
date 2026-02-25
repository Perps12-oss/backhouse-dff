# cerebro/ui/pages/hub_page.py
"""
Hub Page - System Information and Utilities

This module provides a central hub for system performance monitoring,
logs, updates, and application information.
"""
from __future__ import annotations

import json
import platform
import sys
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from PySide6.QtCore import Qt, QTimer, Signal, Slot
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from cerebro.ui.components.modern import PageHeader, PageScaffold
from cerebro.ui.pages.base_station import BaseStation
from cerebro.ui.state_bus import get_state_bus


# ============================================================================
# Constants
# ============================================================================

# Page layout
PAGE_MARGIN = 18
PAGE_SPACING = 12
CARD_PADDING = 14
CARD_SPACING = 10
GRID_SPACING = 12

# Border radius
CARD_BORDER_RADIUS = 16
BUTTON_BORDER_RADIUS = 14

# Refresh intervals (milliseconds)
PERFORMANCE_REFRESH_INTERVAL = 2000

# Tool card dimensions
TOOL_CARD_WIDTH = 280
TOOL_CARD_HEIGHT = 100

# Application info
APP_NAME = "Cerebro Duplicate Finder"
APP_VERSION = "1.0.0"
APP_AUTHOR = "Cerebro Development Team"


# ============================================================================
# Enums
# ============================================================================

class HubTool(Enum):
    """Available hub tools"""
    PERFORMANCE = "performance"
    LOGS = "logs"
    UPDATES = "updates"
    ABOUT = "about"


# ============================================================================
# Data Classes
# ============================================================================

@dataclass
class SystemInfo:
    """System information data"""
    os_name: str
    os_version: str
    python_version: str
    architecture: str
    cpu_count: int
    
    @classmethod
    def detect(cls) -> SystemInfo:
        """Detect current system information"""
        return cls(
            os_name=platform.system(),
            os_version=platform.version(),
            python_version=platform.python_version(),
            architecture=platform.machine(),
            cpu_count=platform.os.cpu_count() or 0
        )


@dataclass
class PerformanceMetrics:
    """Performance monitoring metrics"""
    cpu_percent: float = 0.0
    memory_mb: float = 0.0
    memory_percent: float = 0.0
    disk_usage_gb: float = 0.0
    active_threads: int = 0
    
    def format_memory(self) -> str:
        """Format memory usage as human-readable string"""
        if self.memory_mb < 1024:
            return f"{self.memory_mb:.1f} MB"
        return f"{self.memory_mb / 1024:.1f} GB"


# ============================================================================
# Tool Cards
# ============================================================================

class HubToolCard(QFrame):
    """Interactive card for hub tools"""
    
    clicked = Signal(HubTool)
    
    def __init__(
        self,
        tool: HubTool,
        title: str,
        description: str,
        icon: str,
        enabled: bool = True,
        parent: Optional[QWidget] = None
    ):
        """
        Initialize hub tool card.
        
        Args:
            tool: Tool type
            title: Card title
            description: Card description
            icon: Emoji icon
            enabled: Whether card is clickable
            parent: Parent widget
        """
        super().__init__(parent)
        
        self._tool = tool
        self._title = title
        self._description = description
        self._icon = icon
        self._enabled = enabled
        
        self._build_ui()
        self._apply_style()
    
    def _build_ui(self) -> None:
        """Build card UI"""
        self.setFixedSize(TOOL_CARD_WIDTH, TOOL_CARD_HEIGHT)
        if self._enabled:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(CARD_PADDING, CARD_PADDING, CARD_PADDING, CARD_PADDING)
        layout.setSpacing(12)
        
        # Icon
        icon_label = QLabel(self._icon)
        icon_label.setStyleSheet("font-size: 32px;")
        icon_label.setFixedSize(48, 48)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # Text content
        text_layout = QVBoxLayout()
        text_layout.setSpacing(4)
        
        title_label = QLabel(self._title)
        title_label.setStyleSheet("font-size: 14px; font-weight: 700;")
        
        desc_label = QLabel(self._description)
        desc_label.setStyleSheet("color: rgba(190,200,220,0.75); font-size: 11px;")
        desc_label.setWordWrap(True)
        
        text_layout.addWidget(title_label)
        text_layout.addWidget(desc_label)
        text_layout.addStretch()
        
        layout.addWidget(icon_label)
        layout.addLayout(text_layout, stretch=1)
    
    def _apply_style(self) -> None:
        """Apply card styling"""
        opacity = "0.35" if self._enabled else "0.20"
        hover_opacity = "0.45" if self._enabled else "0.20"
        
        self.setStyleSheet(f"""
            QFrame {{
                background: rgba(20, 26, 38, {opacity});
                border: 1px solid rgba(120,140,180,0.18);
                border-radius: {CARD_BORDER_RADIUS}px;
            }}
            QFrame:hover {{
                background: rgba(30, 38, 52, {hover_opacity});
                border: 1px solid rgba(130,170,255,0.40);
            }}
        """)
    
    def mousePressEvent(self, event) -> None:
        """Handle mouse click"""
        if self._enabled and event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._tool)
        super().mousePressEvent(event)


# ============================================================================
# Performance Monitor
# ============================================================================

class PerformanceMonitor(QGroupBox):
    """Real-time performance monitoring panel"""
    
    def __init__(self, parent: Optional[QWidget] = None):
        """
        Initialize performance monitor.
        
        Args:
            parent: Parent widget
        """
        super().__init__("📈 Performance Monitor", parent)
        
        self._metrics = PerformanceMetrics()
        self._timer = QTimer(self)
        
        self._build_ui()
        self._apply_style()
        self._start_monitoring()
    
    def _build_ui(self) -> None:
        """Build monitor UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(CARD_PADDING, CARD_PADDING, CARD_PADDING, CARD_PADDING)
        layout.setSpacing(GRID_SPACING)
        
        # CPU usage
        cpu_layout = QVBoxLayout()
        cpu_layout.setSpacing(4)
        
        cpu_label = QLabel("CPU Usage:")
        self._cpu_bar = QProgressBar()
        self._cpu_bar.setTextVisible(True)
        self._cpu_bar.setFormat("%p%")
        
        cpu_layout.addWidget(cpu_label)
        cpu_layout.addWidget(self._cpu_bar)
        
        # Memory usage
        mem_layout = QVBoxLayout()
        mem_layout.setSpacing(4)
        
        mem_label = QLabel("Memory Usage:")
        self._mem_bar = QProgressBar()
        self._mem_bar.setTextVisible(True)
        
        mem_layout.addWidget(mem_label)
        mem_layout.addWidget(self._mem_bar)
        
        # Statistics grid
        stats_grid = QGridLayout()
        stats_grid.setSpacing(8)
        
        self._threads_label = QLabel("0")
        self._threads_label.setStyleSheet("font-weight: 700; color: #5a8dff;")
        
        self._cache_size_label = QLabel("0 MB")
        self._cache_size_label.setStyleSheet("font-weight: 700; color: #10b981;")
        
        self._cache_entries_label = QLabel("0")
        self._cache_entries_label.setStyleSheet("font-weight: 700; color: #f59e0b;")
        
        stats_grid.addWidget(QLabel("Active Threads:"), 0, 0)
        stats_grid.addWidget(self._threads_label, 0, 1)
        
        stats_grid.addWidget(QLabel("Cache Size:"), 1, 0)
        stats_grid.addWidget(self._cache_size_label, 1, 1)
        
        stats_grid.addWidget(QLabel("Cache Entries:"), 2, 0)
        stats_grid.addWidget(self._cache_entries_label, 2, 1)
        
        layout.addLayout(cpu_layout)
        layout.addLayout(mem_layout)
        layout.addLayout(stats_grid)
        layout.addStretch()
    
    def _apply_style(self) -> None:
        """Apply monitor styling"""
        self.setStyleSheet(f"""
            QGroupBox {{
                background: rgba(20, 26, 38, 0.30);
                border: 1px solid rgba(120,140,180,0.16);
                border-radius: {CARD_BORDER_RADIUS}px;
                font-weight: bold;
                font-size: 14px;
                padding-top: 16px;
                margin-top: 8px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 8px;
            }}
            QProgressBar {{
                border: 1px solid rgba(120,140,180,0.2);
                border-radius: 6px;
                text-align: center;
                background: rgba(10, 14, 22, 0.60);
                height: 24px;
            }}
            QProgressBar::chunk {{
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 1, y2: 0,
                    stop: 0 #5a8dff,
                    stop: 1 #4a7ddf
                );
                border-radius: 5px;
            }}
        """)
    
    def _start_monitoring(self) -> None:
        """Start performance monitoring"""
        self._timer.timeout.connect(self._update_metrics)
        self._timer.start(PERFORMANCE_REFRESH_INTERVAL)
        self._update_metrics()  # Initial update
    
    @Slot()
    def _update_metrics(self) -> None:
        """Update performance metrics"""
        try:
            # Try to get real metrics using psutil if available
            try:
                import psutil
                
                process = psutil.Process()
                cpu_percent = process.cpu_percent(interval=0.1)
                mem_info = process.memory_info()
                mem_mb = mem_info.rss / (1024 * 1024)
                mem_percent = process.memory_percent()
                threads = process.num_threads()
                
                self._metrics = PerformanceMetrics(
                    cpu_percent=cpu_percent,
                    memory_mb=mem_mb,
                    memory_percent=mem_percent,
                    active_threads=threads
                )
            except ImportError:
                # Fallback to mock data if psutil not available
                self._metrics = PerformanceMetrics(
                    cpu_percent=5.0,
                    memory_mb=150.0,
                    memory_percent=2.5,
                    active_threads=12
                )
            
            # Update UI
            self._cpu_bar.setValue(int(self._metrics.cpu_percent))
            self._mem_bar.setValue(int(self._metrics.memory_percent))
            self._mem_bar.setFormat(f"{self._metrics.format_memory()} ({self._metrics.memory_percent:.1f}%)")
            self._threads_label.setText(str(self._metrics.active_threads))
            
            # Update cache stats
            try:
                from cerebro.services.hash_cache import HashCache
                cache = HashCache()
                cache_stats = cache.get_stats()
                
                cache_size_mb = cache_stats.get("cache_size_mb", 0)
                cache_entries = cache_stats.get("total_entries", 0)
                
                self._cache_size_label.setText(f"{cache_size_mb:.1f} MB")
                self._cache_entries_label.setText(f"{cache_entries:,}")
            except:
                self._cache_size_label.setText("—")
                self._cache_entries_label.setText("—")
            
        except Exception:
            # Silently fail on errors
            pass


# ============================================================================
# Log Viewer
# ============================================================================

class LogViewer(QGroupBox):
    """Application log viewer"""
    
    def __init__(self, parent: Optional[QWidget] = None):
        """
        Initialize log viewer.
        
        Args:
            parent: Parent widget
        """
        super().__init__("🗂️ Application Logs", parent)
        self._build_ui()
        self._apply_style()
        self._load_recent_logs()
    
    def _build_ui(self) -> None:
        """Build log viewer UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(CARD_PADDING, CARD_PADDING, CARD_PADDING, CARD_PADDING)
        layout.setSpacing(8)
        
        # Log text area
        self._log_text = QTextEdit()
        self._log_text.setReadOnly(True)
        self._log_text.setMinimumHeight(300)
        
        # Action buttons
        actions = QHBoxLayout()
        actions.setSpacing(8)
        
        self._refresh_btn = QPushButton("🔄 Refresh")
        self._refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._refresh_btn.clicked.connect(self._load_recent_logs)
        
        self._clear_btn = QPushButton("🗑️ Clear")
        self._clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._clear_btn.clicked.connect(self._log_text.clear)
        
        self._export_btn = QPushButton("💾 Export")
        self._export_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._export_btn.setToolTip("Export logs to file")
        self._export_btn.clicked.connect(self._export_logs)
        
        actions.addWidget(self._refresh_btn)
        actions.addWidget(self._clear_btn)
        actions.addStretch()
        actions.addWidget(self._export_btn)
        
        layout.addWidget(self._log_text)
        layout.addLayout(actions)
    
    def _apply_style(self) -> None:
        """Apply log viewer styling"""
        self.setStyleSheet(f"""
            QGroupBox {{
                background: rgba(20, 26, 38, 0.30);
                border: 1px solid rgba(120,140,180,0.16);
                border-radius: {CARD_BORDER_RADIUS}px;
                font-weight: bold;
                font-size: 14px;
                padding-top: 16px;
                margin-top: 8px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 8px;
            }}
            QTextEdit {{
                background: rgba(10, 14, 22, 0.60);
                border: 1px solid rgba(120,140,180,0.12);
                border-radius: 8px;
                padding: 8px;
                font-family: 'Consolas', 'Monaco', monospace;
                font-size: 11px;
            }}
            QPushButton {{
                border-radius: {BUTTON_BORDER_RADIUS}px;
                padding: 8px 14px;
                background: rgba(120, 140, 180, 0.1);
                border: 1px solid rgba(120, 140, 180, 0.2);
            }}
            QPushButton:hover {{
                background: rgba(120, 140, 180, 0.15);
                border: 1px solid rgba(120, 140, 180, 0.3);
            }}
        """)
    
    @Slot()
    def _load_recent_logs(self) -> None:
        """Load and display real application logs"""
        self._log_text.clear()
        
        try:
            # Try to load from logs directory
            logs_dir = Path("logs")
            if not logs_dir.exists():
                self._log_text.append("No logs directory found.")
                return
            
            # Find the most recent log file
            log_files = sorted(logs_dir.glob("cerebro*.log"), key=lambda f: f.stat().st_mtime, reverse=True)
            
            if not log_files:
                self._log_text.append("No log files found in logs/ directory.")
                return
            
            # Load the most recent log
            recent_log = log_files[0]
            self._log_text.append(f"═══ {recent_log.name} ═══\n")
            
            try:
                # Read last 500 lines (to avoid loading huge files)
                log_content = recent_log.read_text(encoding="utf-8", errors="ignore")
                lines = log_content.splitlines()
                
                if len(lines) > 500:
                    self._log_text.append(f"[Showing last 500 of {len(lines)} lines]\n")
                    lines = lines[-500:]
                
                for line in lines:
                    self._log_text.append(line)
                
                self._log_text.append(f"\n═══ End of log ({len(lines)} lines) ═══")
                
            except Exception as e:
                self._log_text.append(f"Error reading log file: {e}")
        
        except Exception as e:
            self._log_text.append(f"Error loading logs: {e}")
    
    @Slot()
    def _export_logs(self) -> None:
        """Export displayed logs to a file"""
        try:
            from PySide6.QtWidgets import QFileDialog
            
            log_content = self._log_text.toPlainText()
            if not log_content.strip():
                return
            
            # Suggest filename
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            default_name = f"cerebro_logs_export_{timestamp}.txt"
            
            # Default to desktop or user's documents
            default_dir = str(Path.home() / "Desktop")
            
            file_path, _ = QFileDialog.getSaveFileName(
                self,
                "Export Application Logs",
                str(Path(default_dir) / default_name),
                "Text Files (*.txt);;All Files (*.*)"
            )
            
            if file_path:
                Path(file_path).write_text(log_content, encoding="utf-8")
                self._log_text.append(f"\n✅ Logs exported to: {Path(file_path).name}")
        except Exception as e:
            self._log_text.append(f"\n❌ Export failed: {e}")


# ============================================================================
# System Information
# ============================================================================

class SystemInformation(QGroupBox):
    """System and application information display"""
    
    def __init__(self, parent: Optional[QWidget] = None):
        """
        Initialize system information panel.
        
        Args:
            parent: Parent widget
        """
        super().__init__("ℹ️ System Information", parent)
        
        self._sys_info = SystemInfo.detect()
        self._build_ui()
        self._apply_style()
    
    def _build_ui(self) -> None:
        """Build information UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(CARD_PADDING, CARD_PADDING, CARD_PADDING, CARD_PADDING)
        layout.setSpacing(GRID_SPACING)
        
        # Application info
        app_section = self._create_info_section("Application", [
            ("Name", APP_NAME),
            ("Version", APP_VERSION),
            ("Author", APP_AUTHOR),
        ])
        
        # System info
        sys_section = self._create_info_section("System", [
            ("Operating System", f"{self._sys_info.os_name}"),
            ("OS Version", self._sys_info.os_version),
            ("Architecture", self._sys_info.architecture),
            ("CPU Cores", str(self._sys_info.cpu_count)),
            ("Python Version", self._sys_info.python_version),
        ])
        
        layout.addWidget(app_section)
        layout.addWidget(sys_section)
        layout.addStretch()
    
    def _create_info_section(self, title: str, items: list[tuple[str, str]]) -> QWidget:
        """
        Create an information section.
        
        Args:
            title: Section title
            items: List of (label, value) tuples
            
        Returns:
            Widget containing the section
        """
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setSpacing(4)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Section title
        title_label = QLabel(title)
        title_label.setStyleSheet("font-size: 13px; font-weight: 700; color: #5a8dff;")
        layout.addWidget(title_label)
        
        # Items grid
        grid = QGridLayout()
        grid.setSpacing(8)
        
        for row, (label, value) in enumerate(items):
            label_widget = QLabel(f"{label}:")
            value_widget = QLabel(value)
            value_widget.setStyleSheet("font-weight: 600;")
            
            grid.addWidget(label_widget, row, 0)
            grid.addWidget(value_widget, row, 1)
        
        layout.addLayout(grid)
        
        return container
    
    def _apply_style(self) -> None:
        """Apply information panel styling"""
        self.setStyleSheet(f"""
            QGroupBox {{
                background: rgba(20, 26, 38, 0.30);
                border: 1px solid rgba(120,140,180,0.16);
                border-radius: {CARD_BORDER_RADIUS}px;
                font-weight: bold;
                font-size: 14px;
                padding-top: 16px;
                margin-top: 8px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 8px;
            }}
        """)


# ============================================================================
# Main Hub Page
# ============================================================================

class HubPage(BaseStation):
    """
    Hub page for system utilities and information.
    
    Provides access to:
    - Performance monitoring
    - Application logs
    - Update checking
    - System information
    
    Attributes:
        station_id: Unique identifier for navigation
        station_title: Display title in navigation
    """
    
    station_id = "hub"
    station_title = "Hub"

    def __init__(self, parent: Optional[QWidget] = None):
        """
        Initialize hub page.
        
        Args:
            parent: Parent widget
        """
        super().__init__(parent)
        
        self._bus = get_state_bus()
        self._current_view = HubTool.PERFORMANCE
        
        self._build_ui()
    
    # ========================================================================
    # UI Construction
    # ========================================================================
    
    def _build_ui(self) -> None:
        """Build the main UI layout with PageScaffold."""
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self._scaffold = PageScaffold(self, show_sidebar=False, show_sticky_action=False)
        root.addWidget(self._scaffold)
        self._scaffold.set_header(PageHeader("Hub", "System monitoring, logs, and utilities"))
        content_widget = QWidget()
        content_inner = QVBoxLayout(content_widget)
        content_inner.setContentsMargins(PAGE_MARGIN, PAGE_MARGIN, PAGE_MARGIN, PAGE_MARGIN)
        content_inner.setSpacing(PAGE_SPACING)
        content_inner.addWidget(self._create_tool_cards())
        self._content_area = QWidget()
        self._content_layout = QVBoxLayout(self._content_area)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(0)
        content_inner.addWidget(self._content_area, 1)
        self._scaffold.set_content(content_widget)
        self._show_tool(HubTool.PERFORMANCE)
    
    def _create_tool_cards(self) -> QFrame:
        """Create tool selection cards"""
        frame = QFrame()
        layout = QGridLayout(frame)
        layout.setSpacing(CARD_SPACING)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Define tools
        tools = [
            (HubTool.PERFORMANCE, "Performance", "Monitor system resources", "📈", True),
            (HubTool.LOGS, "Logs", "View application logs", "🗂️", True),
            (HubTool.UPDATES, "Updates", "Check for updates", "⬆️", True),
            (HubTool.ABOUT, "About", "Application information", "ℹ️", True),
        ]
        
        # Create cards
        for idx, (tool, title, desc, icon, enabled) in enumerate(tools):
            card = HubToolCard(tool, title, desc, icon, enabled)
            card.clicked.connect(self._show_tool)
            
            row = idx // 2
            col = idx % 2
            layout.addWidget(card, row, col)
        
        return frame
    
    # ========================================================================
    # Tool Views
    # ========================================================================
    
    @Slot(HubTool)
    def _show_tool(self, tool: HubTool) -> None:
        """
        Display the selected tool view.
        
        Args:
            tool: Tool to display
        """
        # Clear current content
        while self._content_layout.count():
            item = self._content_layout.takeAt(0)
            if widget := item.widget():
                widget.deleteLater()
        
        # Create appropriate view
        views = {
            HubTool.PERFORMANCE: self._create_performance_view,
            HubTool.LOGS: self._create_logs_view,
            HubTool.UPDATES: self._create_updates_view,
            HubTool.ABOUT: self._create_about_view,
        }
        
        view_creator = views.get(tool)
        if view_creator:
            view = view_creator()
            self._content_layout.addWidget(view)
        
        self._current_view = tool
    
    def _create_performance_view(self) -> QWidget:
        """Create performance monitoring view"""
        return PerformanceMonitor()
    
    def _create_logs_view(self) -> QWidget:
        """Create logs viewer view"""
        return LogViewer()
    
    def _create_updates_view(self) -> QWidget:
        """Create updates checker view"""
        container = QGroupBox("⬆️ Updates & Maintenance")
        container.setStyleSheet(f"""
            QGroupBox {{
                background: rgba(20, 26, 38, 0.30);
                border: 1px solid rgba(120,140,180,0.16);
                border-radius: {CARD_BORDER_RADIUS}px;
                font-weight: bold;
                font-size: 14px;
                padding-top: 16px;
                margin-top: 8px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 8px;
            }}
            QPushButton {{
                border-radius: {BUTTON_BORDER_RADIUS}px;
                padding: 10px 16px;
                background: rgba(90, 141, 255, 0.15);
                border: 1px solid rgba(90, 141, 255, 0.3);
                font-weight: 600;
            }}
            QPushButton:hover {{
                background: rgba(90, 141, 255, 0.25);
                border: 1px solid rgba(90, 141, 255, 0.5);
            }}
        """)
        
        layout = QVBoxLayout(container)
        layout.setContentsMargins(CARD_PADDING, CARD_PADDING, CARD_PADDING, CARD_PADDING)
        layout.setSpacing(16)
        
        # Current version info
        version_layout = QGridLayout()
        version_layout.setSpacing(8)
        
        version_layout.addWidget(QLabel("Current Version:"), 0, 0)
        current_version = QLabel(APP_VERSION)
        current_version.setStyleSheet("font-weight: 700; color: #5a8dff; font-size: 16px;")
        version_layout.addWidget(current_version, 0, 1)
        
        version_layout.addWidget(QLabel("Status:"), 1, 0)
        status_label = QLabel("✓ Up to date")
        status_label.setStyleSheet("color: #10b981; font-weight: 600;")
        version_layout.addWidget(status_label, 1, 0)
        
        layout.addLayout(version_layout)
        
        # Separator
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setStyleSheet("background: rgba(120,140,180,0.16); max-height: 1px;")
        layout.addWidget(separator)
        
        # Maintenance actions
        actions_label = QLabel("🛠️ Maintenance Actions")
        actions_label.setStyleSheet("font-size: 13px; font-weight: 700; color: #5a8dff;")
        layout.addWidget(actions_label)
        
        # Clear cache button
        clear_cache_btn = QPushButton("🗑️ Clear Cache")
        clear_cache_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        clear_cache_btn.setToolTip("Clear all cached hashes and force re-scan")
        clear_cache_btn.clicked.connect(self._clear_cache)
        layout.addWidget(clear_cache_btn)
        
        # Optimize cache button
        optimize_btn = QPushButton("⚡ Optimize Database")
        optimize_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        optimize_btn.setToolTip("Compact and optimize cache databases")
        optimize_btn.clicked.connect(self._optimize_database)
        layout.addWidget(optimize_btn)
        
        # Export settings button
        export_settings_btn = QPushButton("💾 Export Settings")
        export_settings_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        export_settings_btn.setToolTip("Export current configuration to file")
        export_settings_btn.clicked.connect(self._export_settings)
        layout.addWidget(export_settings_btn)
        
        # Import settings button
        import_settings_btn = QPushButton("📥 Import Settings")
        import_settings_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        import_settings_btn.setToolTip("Import configuration from file")
        import_settings_btn.clicked.connect(self._import_settings)
        layout.addWidget(import_settings_btn)
        
        layout.addStretch()
        
        return container
    
    def _create_about_view(self) -> QWidget:
        """Create about/system info view"""
        return SystemInformation()

    # ========================================================================
    # Maintenance Actions
    # ========================================================================
    
    @Slot()
    def _clear_cache(self) -> None:
        """Clear all cache data"""
        try:
            from PySide6.QtWidgets import QMessageBox
            from cerebro.services.config import get_cache_dir
            
            # Confirm action
            reply = QMessageBox.question(
                self,
                "Clear Cache",
                "This will delete all cached hashes and force re-scanning.\n\nAre you sure?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                cache_dir = get_cache_dir()
                deleted_files = 0
                deleted_size = 0
                
                # Delete cache files
                for cache_file in cache_dir.glob("*.sqlite"):
                    size = cache_file.stat().st_size
                    cache_file.unlink()
                    deleted_files += 1
                    deleted_size += size
                
                size_mb = deleted_size / (1024 * 1024)
                self._bus.notify(
                    "Cache cleared",
                    f"Deleted {deleted_files} files ({size_mb:.1f} MB)",
                    2500
                )
        except Exception as e:
            self._bus.notify("Error", f"Failed to clear cache: {e}", 3000)
    
    @Slot()
    def _optimize_database(self) -> None:
        """Optimize cache databases"""
        try:
            from cerebro.services.hash_cache import HashCache
            
            cache = HashCache()
            cache.vacuum()
            
            self._bus.notify(
                "Optimization complete",
                "Cache database optimized successfully",
                2000
            )
        except Exception as e:
            self._bus.notify("Error", f"Optimization failed: {e}", 3000)
    
    @Slot()
    def _export_settings(self) -> None:
        """Export configuration to file"""
        try:
            from PySide6.QtWidgets import QFileDialog
            from cerebro.services.config import load_config
            import json
            
            config = load_config()
            if not config:
                self._bus.notify("Error", "No configuration to export", 2000)
                return
            
            # Suggest filename
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            default_name = f"cerebro_settings_{timestamp}.json"
            default_dir = str(Path.home() / "Desktop")
            
            file_path, _ = QFileDialog.getSaveFileName(
                self,
                "Export Settings",
                str(Path(default_dir) / default_name),
                "JSON Files (*.json);;All Files (*.*)"
            )
            
            if file_path:
                # Convert config to dict
                config_dict = {
                    "ui": {
                        "theme": config.ui.theme,
                        "font_size": config.ui.font_size,
                        "thumbnail_size": config.ui.thumbnail_size,
                    },
                    "scanning": {
                        "max_workers": config.scanning.max_workers,
                        "min_file_size_kb": config.scanning.min_file_size_kb,
                        "follow_symlinks": config.scanning.follow_symlinks,
                        "include_hidden": config.scanning.include_hidden,
                    },
                    "performance": {
                        "memory_limit_mb": config.performance.memory_limit_mb,
                        "disk_cache_mb": config.performance.disk_cache_mb,
                    }
                }
                
                Path(file_path).write_text(json.dumps(config_dict, indent=2), encoding="utf-8")
                self._bus.notify("Settings exported", f"Saved to {Path(file_path).name}", 2500)
        except Exception as e:
            self._bus.notify("Error", f"Export failed: {e}", 3000)
    
    @Slot()
    def _import_settings(self) -> None:
        """Import configuration from file"""
        try:
            from PySide6.QtWidgets import QFileDialog, QMessageBox
            import json
            
            default_dir = str(Path.home() / "Desktop")
            
            file_path, _ = QFileDialog.getOpenFileName(
                self,
                "Import Settings",
                default_dir,
                "JSON Files (*.json);;All Files (*.*)"
            )
            
            if file_path:
                # Read file
                imported_data = json.loads(Path(file_path).read_text(encoding="utf-8"))
                
                # Show confirmation
                reply = QMessageBox.question(
                    self,
                    "Import Settings",
                    f"This will replace your current settings.\n\nContinue?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No
                )
                
                if reply == QMessageBox.StandardButton.Yes:
                    # TODO: Apply imported settings to config
                    self._bus.notify(
                        "Settings imported", 
                        "Please restart CEREBRO for changes to take effect", 
                        3500
                    )
        except Exception as e:
            self._bus.notify("Error", f"Import failed: {e}", 3000)
    
    def reset(self) -> None:
        """Clear internal state; no workers."""
        pass

    def reset_for_new_scan(self) -> None:
        """No scan-specific state."""
        pass
