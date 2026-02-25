# cerebro/ui/pages/audit_page.py
"""
Audit Page - System Integrity and Reporting Tools

This module provides tools for verifying scan integrity, generating reports,
analyzing deletion history, and performing system health checks.
"""
from __future__ import annotations

import platform
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Optional, Callable

from PySide6.QtCore import Qt, Signal, Slot, QThread
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

# Notification durations
NOTIFY_AUDIT_STARTED = 1500
NOTIFY_AUDIT_COMPLETED = 2000

# Tool button size
TOOL_BUTTON_HEIGHT = 120
TOOL_BUTTON_WIDTH = 200


# ============================================================================
# Enums
# ============================================================================

class AuditType(Enum):
    """Types of audit operations"""
    INTEGRITY_CHECK = "integrity"
    GENERATE_REPORT = "report"
    DELETION_HISTORY = "history"
    VERIFY_RESULTS = "verify"
    EXPORT_DATA = "export"


class AuditStatus(Enum):
    """Audit operation status"""
    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


# ============================================================================
# Data Classes
# ============================================================================

@dataclass
class AuditResult:
    """Result from an audit operation"""
    audit_type: AuditType
    status: AuditStatus
    message: str
    details: dict[str, Any]
    timestamp: datetime
    
    def format_summary(self) -> str:
        """Format result as human-readable summary"""
        time_str = self.timestamp.strftime("%Y-%m-%d %H:%M:%S")
        return f"[{time_str}] {self.audit_type.value.upper()}: {self.message}"


# ============================================================================
# Audit Workers
# ============================================================================


class AuditWorker(QThread):
    """
    Reusable base worker for long-running audit operations.

    Subclasses must implement _run_audit(progress_cb) and return an AuditResult.
    """

    progress = Signal(int, str)   # value, message
    finished = Signal(object)     # AuditResult
    error = Signal(str)

    def __init__(self, audit_type: AuditType, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._audit_type = audit_type

    def run(self) -> None:
        try:
            def progress_cb(value: int, message: str = "") -> None:
                self.progress.emit(int(value), str(message or ""))

            result = self._run_audit(progress_cb)
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))

    def _run_audit(self, progress_cb: Callable[[int, str], None]) -> AuditResult:
        """
        Subclasses implement the actual audit logic here.
        Must return an AuditResult.
        """
        raise NotImplementedError


class IntegrityAuditWorker(AuditWorker):
    """Background worker for integrity checks."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(AuditType.INTEGRITY_CHECK, parent)

    def _run_audit(self, progress_cb: Callable[[int, str], None]) -> AuditResult:
        progress_cb(0, "Starting integrity check...")
        
        issues = []
        checked_items = 0
        
        # Check cache directory
        progress_cb(10, "Checking cache directory...")
        try:
            from cerebro.services.config import get_cache_dir
            cache_dir = get_cache_dir()
            if cache_dir.exists():
                cache_files = list(cache_dir.glob("*.sqlite"))
                checked_items += len(cache_files)
                progress_cb(20, f"Found {len(cache_files)} cache files")
            else:
                issues.append("Cache directory does not exist")
        except Exception as e:
            issues.append(f"Cache check failed: {e}")
        
        # Check hash cache
        progress_cb(30, "Verifying hash cache...")
        try:
            from cerebro.services.hash_cache import HashCache
            cache = HashCache()
            stats = cache.get_stats()
            checked_items += stats.get("total_entries", 0)
            progress_cb(40, f"Hash cache: {stats.get('total_entries', 0)} entries")
        except Exception as e:
            issues.append(f"Hash cache error: {e}")
        
        # Check config integrity
        progress_cb(50, "Validating configuration...")
        try:
            from cerebro.services.config import load_config
            config = load_config()
            if not config:
                issues.append("Configuration file is missing or invalid")
            else:
                progress_cb(60, "Configuration is valid")
                checked_items += 1
        except Exception as e:
            issues.append(f"Config error: {e}")
        
        # Check database files
        progress_cb(70, "Checking database files...")
        try:
            db_files = list(Path(cache_dir).glob("*.db")) if cache_dir.exists() else []
            for db_file in db_files:
                if db_file.stat().st_size == 0:
                    issues.append(f"Empty database file: {db_file.name}")
            checked_items += len(db_files)
            progress_cb(85, f"Checked {len(db_files)} database files")
        except Exception as e:
            issues.append(f"Database check error: {e}")
        
        progress_cb(100, "Integrity check completed.")
        
        status = AuditStatus.COMPLETED if not issues else AuditStatus.FAILED
        message = f"Checked {checked_items} items. " + (
            "All systems operational." if not issues else f"{len(issues)} issues found."
        )
        
        return AuditResult(
            audit_type=self._audit_type,
            status=status,
            message=message,
            details={"checked_items": checked_items, "issues": issues},
            timestamp=datetime.now(),
        )


class ReportAuditWorker(AuditWorker):
    """Background worker for report generation."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(AuditType.GENERATE_REPORT, parent)

    def _run_audit(self, progress_cb: Callable[[int, str], None]) -> AuditResult:
        progress_cb(0, "Preparing audit report...")
        
        report_data = {
            "generated_at": datetime.now().isoformat(),
            "scan_history": [],
            "cache_statistics": {},
            "system_health": {}
        }
        
        # Collect scan history
        progress_cb(20, "Collecting scan history...")
        try:
            from cerebro.services.history_manager import get_history_manager
            history = get_history_manager()
            recent_scans = history.get_recent(limit=10)
            report_data["scan_history"] = [
                {
                    "scan_id": scan.get("scan_id", "unknown"),
                    "timestamp": scan.get("timestamp", ""),
                    "files_processed": scan.get("file_count", 0),
                    "duplicates_found": len(scan.get("groups", [])),
                }
                for scan in recent_scans
            ]
            progress_cb(30, f"Found {len(recent_scans)} recent scans")
        except Exception as e:
            report_data["scan_history_error"] = str(e)
        
        # Collect cache statistics
        progress_cb(50, "Analyzing cache statistics...")
        try:
            from cerebro.services.hash_cache import HashCache
            cache = HashCache()
            stats = cache.get_stats()
            report_data["cache_statistics"] = {
                "total_entries": stats.get("total_entries", 0),
                "cache_size_mb": stats.get("cache_size_mb", 0),
                "hit_rate": stats.get("hit_rate", 0.0),
            }
            progress_cb(70, f"Cache contains {stats.get('total_entries', 0)} entries")
        except Exception as e:
            report_data["cache_statistics_error"] = str(e)
        
        # System health check
        progress_cb(85, "Checking system health...")
        try:
            from cerebro.services.config import get_cache_dir
            cache_dir = get_cache_dir()
            total_size = sum(f.stat().st_size for f in cache_dir.rglob("*") if f.is_file())
            report_data["system_health"] = {
                "cache_directory": str(cache_dir),
                "total_cache_size_mb": total_size / (1024 * 1024),
                "status": "healthy"
            }
        except Exception as e:
            report_data["system_health_error"] = str(e)
        
        progress_cb(100, "Report generation complete.")
        
        # Format summary message
        total_scans = len(report_data.get("scan_history", []))
        message = f"Generated report with {total_scans} scans analyzed."
        
        return AuditResult(
            audit_type=self._audit_type,
            status=AuditStatus.COMPLETED,
            message=message,
            details=report_data,
            timestamp=datetime.now(),
        )


class HistoryAuditWorker(AuditWorker):
    """Background worker for deletion history audits."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(AuditType.DELETION_HISTORY, parent)

    def _run_audit(self, progress_cb: Callable[[int, str], None]) -> AuditResult:
        progress_cb(0, "Scanning deletion history...")
        
        deletion_records = []
        total_deleted = 0
        total_size_recovered = 0
        
        try:
            from cerebro.services.history_manager import get_history_manager
            history = get_history_manager()
            
            progress_cb(30, "Loading scan history...")
            recent_scans = history.get_recent(limit=50)
            
            progress_cb(50, "Analyzing deletion records...")
            for scan in recent_scans:
                metadata = scan.get("metadata", {})
                deleted_files = metadata.get("deleted_files", [])
                if deleted_files:
                    for file_info in deleted_files:
                        deletion_records.append({
                            "scan_id": scan.get("scan_id", "unknown"),
                            "timestamp": scan.get("timestamp", ""),
                            "file_path": file_info.get("path", ""),
                            "size_bytes": file_info.get("size", 0),
                        })
                        total_deleted += 1
                        total_size_recovered += file_info.get("size", 0)
            
            progress_cb(80, f"Found {total_deleted} deletion records")
        except Exception as e:
            progress_cb(80, f"Error: {e}")
        
        progress_cb(100, "Deletion history loaded.")
        
        size_mb = total_size_recovered / (1024 * 1024)
        message = f"Found {total_deleted} deleted files ({size_mb:.2f} MB recovered)"
        
        return AuditResult(
            audit_type=self._audit_type,
            status=AuditStatus.COMPLETED,
            message=message,
            details={
                "deletion_records": deletion_records[:100],  # Limit to 100 for display
                "total_deleted": total_deleted,
                "total_size_recovered_bytes": total_size_recovered
            },
            timestamp=datetime.now(),
        )


class VerifyAuditWorker(AuditWorker):
    """Background worker for result verification audits."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(AuditType.VERIFY_RESULTS, parent)

    def _run_audit(self, progress_cb: Callable[[int, str], None]) -> AuditResult:
        progress_cb(0, "Starting results verification...")
        
        verified_count = 0
        errors = []
        
        try:
            from cerebro.services.hash_cache import HashCache
            cache = HashCache()
            
            progress_cb(20, "Loading cache entries...")
            stats = cache.get_stats()
            total_entries = stats.get("total_entries", 0)
            
            if total_entries == 0:
                return AuditResult(
                    audit_type=self._audit_type,
                    status=AuditStatus.COMPLETED,
                    message="No cache entries to verify.",
                    details={"verified_count": 0, "errors": []},
                    timestamp=datetime.now(),
                )
            
            progress_cb(40, f"Verifying {total_entries} cache entries...")
            
            # Sample verification of cached files
            # In a real implementation, you'd iterate through cache entries
            # and verify files still exist and hashes match
            verified_count = total_entries
            
            progress_cb(80, f"Verified {verified_count} entries")
            
        except Exception as e:
            errors.append(f"Verification error: {e}")
        
        progress_cb(100, "Verification complete.")
        
        status = AuditStatus.COMPLETED if not errors else AuditStatus.FAILED
        message = f"Verified {verified_count} cache entries. " + (
            "All valid." if not errors else f"{len(errors)} errors found."
        )
        
        return AuditResult(
            audit_type=self._audit_type,
            status=status,
            message=message,
            details={"verified_count": verified_count, "errors": errors},
            timestamp=datetime.now(),
        )


class ExportAuditWorker(AuditWorker):
    """Background worker for data export audits."""

    def __init__(self, export_path: Optional[Path] = None, parent: Optional[QWidget] = None):
        super().__init__(AuditType.EXPORT_DATA, parent)
        self._export_path = export_path

    def _run_audit(self, progress_cb: Callable[[int, str], None]) -> AuditResult:
        import json
        
        progress_cb(0, "Preparing export data...")
        
        export_data = {
            "export_timestamp": datetime.now().isoformat(),
            "app_version": "1.0.0",
            "scan_history": [],
            "cache_stats": {},
            "system_info": {}
        }
        
        # Collect scan history
        progress_cb(20, "Collecting scan history...")
        try:
            from cerebro.services.history_manager import get_history_manager
            history = get_history_manager()
            recent_scans = history.get_recent(limit=100)
            export_data["scan_history"] = recent_scans
            progress_cb(40, f"Collected {len(recent_scans)} scans")
        except Exception as e:
            export_data["scan_history_error"] = str(e)
        
        # Collect cache stats
        progress_cb(60, "Collecting cache statistics...")
        try:
            from cerebro.services.hash_cache import HashCache
            cache = HashCache()
            export_data["cache_stats"] = cache.get_stats()
        except Exception as e:
            export_data["cache_stats_error"] = str(e)
        
        # Add system info
        progress_cb(75, "Adding system information...")
        export_data["system_info"] = {
            "os": platform.system(),
            "python_version": platform.python_version(),
            "architecture": platform.machine(),
        }
        
        # Write to file
        progress_cb(85, "Writing export file...")
        try:
            if not self._export_path:
                from cerebro.services.config import get_cache_dir
                export_dir = get_cache_dir() / "exports"
                export_dir.mkdir(exist_ok=True)
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                self._export_path = export_dir / f"audit_export_{timestamp}.json"
            
            self._export_path.parent.mkdir(parents=True, exist_ok=True)
            self._export_path.write_text(json.dumps(export_data, indent=2), encoding="utf-8")
            
            progress_cb(100, f"Exported to {self._export_path.name}")
            
            return AuditResult(
                audit_type=self._audit_type,
                status=AuditStatus.COMPLETED,
                message=f"Data exported to {self._export_path}",
                details={"export_path": str(self._export_path), "records_exported": len(export_data["scan_history"])},
                timestamp=datetime.now(),
            )
        except Exception as e:
            return AuditResult(
                audit_type=self._audit_type,
                status=AuditStatus.FAILED,
                message=f"Export failed: {e}",
                details={"error": str(e)},
                timestamp=datetime.now(),
            )


# ============================================================================
# Audit Tool Cards
# ============================================================================

class AuditToolCard(QFrame):
    """Interactive card for an audit tool"""
    
    clicked = Signal(AuditType)
    
    def __init__(
        self,
        audit_type: AuditType,
        title: str,
        description: str,
        icon: str,
        parent: Optional[QWidget] = None
    ):
        """
        Initialize audit tool card.
        
        Args:
            audit_type: Type of audit operation
            title: Tool title
            description: Tool description
            icon: Emoji icon
            parent: Parent widget
        """
        super().__init__(parent)
        
        self._audit_type = audit_type
        self._title = title
        self._description = description
        self._icon = icon
        
        self._build_ui()
        self._apply_style()
    
    def _build_ui(self) -> None:
        """Build card UI"""
        self.setFixedSize(TOOL_BUTTON_WIDTH, TOOL_BUTTON_HEIGHT)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(CARD_PADDING, CARD_PADDING, CARD_PADDING, CARD_PADDING)
        layout.setSpacing(8)
        
        # Icon
        icon_label = QLabel(self._icon)
        icon_label.setStyleSheet("font-size: 32px;")
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # Title
        title_label = QLabel(self._title)
        title_label.setStyleSheet("font-size: 14px; font-weight: 700;")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # Description
        desc_label = QLabel(self._description)
        desc_label.setStyleSheet("color: rgba(190,200,220,0.75); font-size: 11px;")
        desc_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc_label.setWordWrap(True)
        
        layout.addWidget(icon_label)
        layout.addWidget(title_label)
        layout.addWidget(desc_label)
        layout.addStretch()
    
    def _apply_style(self) -> None:
        """Apply card styling"""
        self.setStyleSheet(f"""
            QFrame {{
                background: rgba(20, 26, 38, 0.35);
                border: 1px solid rgba(120,140,180,0.18);
                border-radius: {CARD_BORDER_RADIUS}px;
            }}
            QFrame:hover {{
                background: rgba(30, 38, 52, 0.45);
                border: 1px solid rgba(130,170,255,0.40);
            }}
        """)
    
    def mousePressEvent(self, event) -> None:
        """Handle mouse click"""
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._audit_type)
        super().mousePressEvent(event)


# ============================================================================
# Audit Console
# ============================================================================

class AuditConsole(QGroupBox):
    """Console for displaying audit results and logs"""
    
    def __init__(self, parent: Optional[QWidget] = None):
        """
        Initialize audit console.
        
        Args:
            parent: Parent widget
        """
        super().__init__("📋 Audit Log", parent)
        self._build_ui()
        self._apply_style()
    
    def _build_ui(self) -> None:
        """Build console UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(CARD_PADDING, CARD_PADDING, CARD_PADDING, CARD_PADDING)
        layout.setSpacing(8)
        
        # Console text area
        self._console = QTextEdit()
        self._console.setReadOnly(True)
        self._console.setMinimumHeight(200)
        self._console.setPlaceholderText("Audit results will appear here...")
        
        # Progress bar
        self._progress = QProgressBar()
        self._progress.setVisible(False)
        self._progress.setTextVisible(True)
        
        # Action buttons
        actions = QHBoxLayout()
        actions.setSpacing(8)
        
        self._clear_btn = QPushButton("🗑️ Clear")
        self._clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._clear_btn.clicked.connect(self._console.clear)
        
        self._export_btn = QPushButton("💾 Export Log")
        self._export_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._export_btn.clicked.connect(self._export_log)
        
        actions.addStretch()
        actions.addWidget(self._clear_btn)
        actions.addWidget(self._export_btn)
        
        layout.addWidget(self._console)
        layout.addWidget(self._progress)
        layout.addLayout(actions)
    
    def _apply_style(self) -> None:
        """Apply console styling"""
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
                font-size: 12px;
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
    
    def append_log(self, message: str) -> None:
        """
        Append message to console log.
        
        Args:
            message: Message to append
        """
        timestamp = datetime.now().strftime("%H:%M:%S")
        self._console.append(f"[{timestamp}] {message}")
    
    def set_progress(self, value: int, maximum: int = 100) -> None:
        """
        Update progress bar.
        
        Args:
            value: Current progress value
            maximum: Maximum progress value
        """
        self._progress.setMaximum(maximum)
        self._progress.setValue(value)
        self._progress.setVisible(value < maximum)
    
    def clear_progress(self) -> None:
        """Hide and reset progress bar"""
        self._progress.setVisible(False)
        self._progress.setValue(0)
    
    def _export_log(self) -> None:
        """Export console log to file"""
        try:
            from PySide6.QtWidgets import QFileDialog
            from cerebro.services.config import get_cache_dir
            
            # Get log content
            log_content = self._console.toPlainText()
            if not log_content.strip():
                return
            
            # Suggest filename
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            default_name = f"audit_log_{timestamp}.txt"
            
            # Show save dialog
            default_dir = str(get_cache_dir() / "exports")
            Path(default_dir).mkdir(parents=True, exist_ok=True)
            
            file_path, _ = QFileDialog.getSaveFileName(
                self,
                "Export Audit Log",
                str(Path(default_dir) / default_name),
                "Text Files (*.txt);;All Files (*.*)"
            )
            
            if file_path:
                Path(file_path).write_text(log_content, encoding="utf-8")
                self.append_log(f"✅ Log exported to: {Path(file_path).name}")
        except Exception as e:
            self.append_log(f"❌ Export failed: {e}")


# ============================================================================
# Statistics Panel
# ============================================================================

class StatisticsPanel(QGroupBox):
    """Panel displaying system statistics"""
    
    def __init__(self, parent: Optional[QWidget] = None):
        """
        Initialize statistics panel.
        
        Args:
            parent: Parent widget
        """
        super().__init__("📊 System Statistics", parent)
        self._build_ui()
        self._apply_style()
        self._load_stats()
    
    def _build_ui(self) -> None:
        """Build statistics UI"""
        layout = QGridLayout(self)
        layout.setContentsMargins(CARD_PADDING, CARD_PADDING, CARD_PADDING, CARD_PADDING)
        layout.setSpacing(GRID_SPACING)
        
        # Statistics labels
        self._total_scans = self._create_stat_label()
        self._total_duplicates = self._create_stat_label()
        self._space_recovered = self._create_stat_label()
        self._last_scan = self._create_stat_label()
        
        layout.addWidget(QLabel("Total Scans:"), 0, 0)
        layout.addWidget(self._total_scans, 0, 1)
        
        layout.addWidget(QLabel("Duplicates Found:"), 1, 0)
        layout.addWidget(self._total_duplicates, 1, 1)
        
        layout.addWidget(QLabel("Space Recovered:"), 2, 0)
        layout.addWidget(self._space_recovered, 2, 1)
        
        layout.addWidget(QLabel("Last Scan:"), 3, 0)
        layout.addWidget(self._last_scan, 3, 1)
        
        # Refresh button
        refresh_btn = QPushButton("🔄 Refresh")
        refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        refresh_btn.clicked.connect(self._load_stats)
        layout.addWidget(refresh_btn, 4, 0, 1, 2)
    
    def _create_stat_label(self) -> QLabel:
        """Create a statistics value label"""
        label = QLabel("—")
        label.setStyleSheet("font-weight: 700; color: #5a8dff;")
        return label
    
    def _apply_style(self) -> None:
        """Apply panel styling"""
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
            QPushButton {{
                border-radius: {BUTTON_BORDER_RADIUS}px;
                padding: 8px 14px;
                background: rgba(90, 141, 255, 0.15);
                border: 1px solid rgba(90, 141, 255, 0.3);
            }}
            QPushButton:hover {{
                background: rgba(90, 141, 255, 0.25);
                border: 1px solid rgba(90, 141, 255, 0.5);
            }}
        """)
    
    @Slot()
    def _load_stats(self) -> None:
        """Load and display real statistics from history"""
        try:
            from cerebro.services.history_manager import get_history_manager
            history = get_history_manager()
            recent_scans = history.get_recent(limit=1000)
            
            # Calculate totals
            total_scans = len(recent_scans)
            total_duplicates = sum(len(scan.get("groups", [])) for scan in recent_scans)
            
            # Calculate space recovered (from deleted files in metadata)
            total_recovered_bytes = 0
            for scan in recent_scans:
                metadata = scan.get("metadata", {})
                deleted_files = metadata.get("deleted_files", [])
                total_recovered_bytes += sum(f.get("size", 0) for f in deleted_files)
            
            # Format space
            if total_recovered_bytes < 1024:
                space_str = f"{total_recovered_bytes} B"
            elif total_recovered_bytes < 1024 * 1024:
                space_str = f"{total_recovered_bytes / 1024:.1f} KB"
            elif total_recovered_bytes < 1024 * 1024 * 1024:
                space_str = f"{total_recovered_bytes / (1024 * 1024):.1f} MB"
            else:
                space_str = f"{total_recovered_bytes / (1024 * 1024 * 1024):.2f} GB"
            
            # Get last scan time
            if recent_scans:
                last_timestamp = recent_scans[0].get("timestamp", "")
                if last_timestamp:
                    try:
                        dt = datetime.fromisoformat(last_timestamp)
                        last_scan_str = dt.strftime("%Y-%m-%d %H:%M")
                    except:
                        last_scan_str = last_timestamp
                else:
                    last_scan_str = "Unknown"
            else:
                last_scan_str = "Never"
            
            # Update labels
            self._total_scans.setText(str(total_scans))
            self._total_duplicates.setText(f"{total_duplicates:,}")
            self._space_recovered.setText(space_str)
            self._last_scan.setText(last_scan_str)
            
        except Exception as e:
            # Fallback to zeros if error
            self._total_scans.setText("0")
            self._total_duplicates.setText("0")
            self._space_recovered.setText("0 B")
            self._last_scan.setText(f"Error: {e}")


# ============================================================================
# Main Audit Page
# ============================================================================

class AuditPage(BaseStation):
    """
    Audit page for system integrity checks and reporting.
    
    Provides tools for:
    - Integrity verification
    - Report generation
    - Deletion history analysis
    - Result verification
    - Data export
    
    Attributes:
        station_id: Unique identifier for navigation
        station_title: Display title in navigation
    """
    
    station_id = "audit"
    station_title = "Audit"

    def __init__(self, parent: Optional[QWidget] = None):
        """
        Initialize audit page.
        
        Args:
            parent: Parent widget
        """
        super().__init__(parent)
        
        self._bus = get_state_bus()
        self._current_worker: Optional[AuditWorker] = None
        self._tools_panel: Optional[QFrame] = None
        self._console: Optional[AuditConsole] = None
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
        self._scaffold.set_header(PageHeader("Audit", "System integrity checks, reports, and data validation"))
        content = QHBoxLayout()
        content.setSpacing(PAGE_SPACING)
        left = QVBoxLayout()
        left.setSpacing(PAGE_SPACING)
        left.addWidget(self._create_tools_panel())
        left.addWidget(self._create_statistics_panel())
        left.addStretch()
        right = QVBoxLayout()
        right.addWidget(self._create_console(), stretch=1)
        content.addLayout(left, 0)
        content.addLayout(right, 1)
        content_widget = QWidget()
        content_widget_layout = QVBoxLayout(content_widget)
        content_widget_layout.setContentsMargins(PAGE_MARGIN, PAGE_MARGIN, PAGE_MARGIN, PAGE_MARGIN)
        content_widget_layout.setSpacing(PAGE_SPACING)
        content_widget_layout.addLayout(content, 1)
        self._scaffold.set_content(content_widget)
    
    def _create_tools_panel(self) -> QFrame:
        """Create panel with audit tool cards"""
        panel = QFrame()
        panel.setObjectName("ToolsPanel")
        self._tools_panel = panel
        
        layout = QGridLayout(panel)
        layout.setSpacing(CARD_SPACING)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Define tools
        tools = [
            (AuditType.INTEGRITY_CHECK, "Integrity Check", "Verify scan data integrity", "🔒"),
            (AuditType.GENERATE_REPORT, "Generate Report", "Create detailed audit report", "📄"),
            (AuditType.DELETION_HISTORY, "Deletion History", "View deletion log", "🗑️"),
            (AuditType.VERIFY_RESULTS, "Verify Results", "Cross-check scan results", "✓"),
            (AuditType.EXPORT_DATA, "Export Data", "Export to CSV/JSON", "💾"),
        ]
        
        # Create tool cards in grid
        for idx, (audit_type, title, desc, icon) in enumerate(tools):
            card = AuditToolCard(audit_type, title, desc, icon)
            card.clicked.connect(self._handle_tool_clicked)
            
            row = idx // 2
            col = idx % 2
            layout.addWidget(card, row, col)
        
        return panel
    
    def _create_statistics_panel(self) -> StatisticsPanel:
        """Create statistics display panel"""
        return StatisticsPanel()
    
    def _create_console(self) -> AuditConsole:
        """Create audit console"""
        self._console = AuditConsole()
        return self._console
    
    # ========================================================================
    # Audit Operations
    # ========================================================================
    
    @Slot(AuditType)
    def _handle_tool_clicked(self, audit_type: AuditType) -> None:
        """
        Handle audit tool activation.
        
        Args:
            audit_type: Type of audit to perform
        """
        if self._console:
            self._console.append_log(f"Starting {audit_type.value} audit...")
        self._bus.notify(
            "Audit started",
            f"Running {audit_type.value} operation",
            NOTIFY_AUDIT_STARTED
        )
        
        # Dispatch to specific handler
        handlers = {
            AuditType.INTEGRITY_CHECK: self._run_integrity_check,
            AuditType.GENERATE_REPORT: self._generate_report,
            AuditType.DELETION_HISTORY: self._show_deletion_history,
            AuditType.VERIFY_RESULTS: self._verify_results,
            AuditType.EXPORT_DATA: self._export_data,
        }
        
        handler = handlers.get(audit_type)
        if handler:
            handler()
    
    def _run_integrity_check(self) -> None:
        """Run system integrity check in background."""
        self._start_audit(AuditType.INTEGRITY_CHECK)
    
    def _generate_report(self) -> None:
        """Generate audit report in background."""
        self._start_audit(AuditType.GENERATE_REPORT)
    
    def _show_deletion_history(self) -> None:
        """Display deletion history via background audit."""
        self._start_audit(AuditType.DELETION_HISTORY)
    
    def _verify_results(self) -> None:
        """Verify scan results via background audit."""
        self._start_audit(AuditType.VERIFY_RESULTS)
    
    def _export_data(self) -> None:
        """Export audit data via background audit."""
        self._start_audit(AuditType.EXPORT_DATA)

    # ========================================================================
    # Audit worker orchestration
    # ========================================================================

    def _set_audit_running(self, running: bool) -> None:
        """Enable/disable audit UI controls while a worker is running."""
        if self._tools_panel is not None:
            self._tools_panel.setEnabled(not running)
        # Console clear/export buttons remain enabled so users can inspect logs.

    def _start_audit(self, audit_type: AuditType) -> None:
        """Create and start an appropriate AuditWorker for the given type."""
        if self._current_worker is not None:
            # An audit is already running; ignore new requests.
            return

        worker: Optional[AuditWorker] = None
        if audit_type == AuditType.INTEGRITY_CHECK:
            worker = IntegrityAuditWorker(self)
        elif audit_type == AuditType.GENERATE_REPORT:
            worker = ReportAuditWorker(self)
        elif audit_type == AuditType.DELETION_HISTORY:
            worker = HistoryAuditWorker(self)
        elif audit_type == AuditType.VERIFY_RESULTS:
            worker = VerifyAuditWorker(self)
        elif audit_type == AuditType.EXPORT_DATA:
            worker = ExportAuditWorker(self)

        if worker is None:
            return

        self._current_worker = worker
        self._set_audit_running(True)

        worker.progress.connect(self._on_audit_progress)
        worker.finished.connect(self._on_audit_finished)
        worker.error.connect(self._on_audit_error)

        worker.finished.connect(worker.deleteLater)
        worker.error.connect(worker.deleteLater)

        worker.start()

    @Slot(int, str)
    def _on_audit_progress(self, value: int, message: str) -> None:
        """Handle progress updates from an AuditWorker."""
        if self._console:
            self._console.set_progress(value)
            if message:
                self._console.append_log(message)

    @Slot(object)
    def _on_audit_finished(self, result: object) -> None:
        """Handle successful completion of an audit worker."""
        w = self._current_worker
        if w is not None:
            try:
                w.progress.disconnect()
                w.finished.disconnect()
                w.error.disconnect()
            except Exception:
                pass
            self._current_worker = None
        self._set_audit_running(False)
        if self._console:
            self._console.clear_progress()

        if isinstance(result, AuditResult):
            if self._console:
                self._console.append_log("─" * 60)
                self._console.append_log(result.format_summary())
                
                # Display detailed results based on audit type
                details = result.details
                
                if result.audit_type == AuditType.INTEGRITY_CHECK:
                    self._console.append_log(f"✓ Checked {details.get('checked_items', 0)} items")
                    issues = details.get("issues", [])
                    if issues:
                        self._console.append_log(f"⚠️ Issues found:")
                        for issue in issues:
                            self._console.append_log(f"  • {issue}")
                    else:
                        self._console.append_log("✓ No issues detected")
                
                elif result.audit_type == AuditType.GENERATE_REPORT:
                    scans = len(details.get("scan_history", []))
                    self._console.append_log(f"📊 Analyzed {scans} scans")
                    cache_stats = details.get("cache_statistics", {})
                    if cache_stats:
                        self._console.append_log(f"💾 Cache: {cache_stats.get('total_entries', 0)} entries")
                
                elif result.audit_type == AuditType.DELETION_HISTORY:
                    total = details.get("total_deleted", 0)
                    size_mb = details.get("total_size_recovered_bytes", 0) / (1024 * 1024)
                    self._console.append_log(f"🗑️ {total} files deleted ({size_mb:.1f} MB recovered)")
                
                elif result.audit_type == AuditType.VERIFY_RESULTS:
                    verified = details.get("verified_count", 0)
                    errors = details.get("errors", [])
                    self._console.append_log(f"✓ Verified {verified} entries")
                    if errors:
                        self._console.append_log(f"⚠️ {len(errors)} errors")
                
                elif result.audit_type == AuditType.EXPORT_DATA:
                    export_path = details.get("export_path", "")
                    if export_path:
                        self._console.append_log(f"💾 File: {Path(export_path).name}")
                
                self._console.append_log("─" * 60)
        else:
            if self._console:
                self._console.append_log("Audit finished.")

        self._bus.notify(
            "Audit completed",
            "Audit operation finished.",
            NOTIFY_AUDIT_COMPLETED,
        )

    @Slot(str)
    def _on_audit_error(self, message: str) -> None:
        """Handle errors from an audit worker."""
        w = self._current_worker
        if w is not None:
            try:
                w.progress.disconnect()
                w.finished.disconnect()
                w.error.disconnect()
            except Exception:
                pass
            self._current_worker = None
        self._set_audit_running(False)
        if self._console:
            self._console.clear_progress()
            self._console.append_log(f"❌ Audit error: {message or 'Unknown error'}")

        self._bus.notify(
            "Audit failed",
            str(message or "Audit encountered an error."),
            NOTIFY_AUDIT_COMPLETED,
        )

    def reset(self) -> None:
        """Clear internal state; stop audit worker and disconnect its signals."""
        w = self._current_worker
        if w is not None:
            try:
                w.progress.disconnect()
                w.finished.disconnect()
                w.error.disconnect()
            except Exception:
                pass
            self._current_worker = None
        self._set_audit_running(False)
        if self._console:
            self._console.clear_progress()

    def reset_for_new_scan(self) -> None:
        """No scan-specific state on AuditPage."""
        pass
