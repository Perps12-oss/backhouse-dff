# cerebro/history/history_page.py
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Optional, Set

from PySide6.QtCore import Qt, Signal, QTimer, QThread, QObject, QRunnable, QThreadPool
from PySide6.QtGui import QFont, QIcon, QAction
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QComboBox, QScrollArea, QFrame, QMessageBox,
    QInputDialog, QSizePolicy, QGroupBox, QGridLayout, QCheckBox,
    QProgressDialog, QFileDialog, QSplitter, QTextEdit, QDialog,
    QDialogButtonBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QMenu
)

from cerebro.ui.theme_engine import ThemeMixin
from .models import ScanHistoryEntry, ScanStatus, ScanHealthSnapshot
from .store import HistoryStore


def _fmt_bytes(n: int) -> str:
    n = int(n or 0)
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(n)
    i = 0
    while size >= 1024 and i < len(units) - 1:
        size /= 1024.0
        i += 1
    if i == 0:
        return f"{int(size)} {units[i]}"
    return f"{size:.1f} {units[i]}"


def _fmt_dt(iso_str: str) -> str:
    if not iso_str:
        return ""
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.astimezone().strftime("%Y-%m-%d %H:%M")
    except Exception:
        return iso_str


def _fmt_duration(ms: int) -> str:
    if ms < 1000:
        return f"{ms}ms"
    elif ms < 60000:
        return f"{ms/1000:.1f}s"
    else:
        minutes = ms // 60000
        seconds = (ms % 60000) // 1000
        return f"{minutes}m {seconds}s"


class HealthPanelWidget(QFrame, ThemeMixin):
    """Re-adding the Health Panel feature from ReviewPage."""
    
    def __init__(self, parent=None):
        ThemeMixin.__init__(self)
        super().__init__(parent)
        self.setObjectName("HealthPanel")
        self.setFrameShape(QFrame.StyledPanel)
        self.setMinimumWidth(300)
        self.setMaximumWidth(400)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        
        title = QLabel("System Health")
        title_font = QFont()
        title_font.setBold(True)
        title_font.setPointSize(12)
        title.setFont(title_font)
        layout.addWidget(title)
        
        self.metrics_grid = QGridLayout()
        self.metrics = {}
        metrics = [
            ("CPU", "cpu_percent", "%"),
            ("Memory", "memory_percent", "%"),
            ("Disk Read", "disk_read_mb", "MB"),
            ("Disk Write", "disk_write_mb", "MB"),
            ("Threads", "thread_count", ""),
            ("File Handles", "open_file_handles", ""),
        ]
        
        for i, (label, key, unit) in enumerate(metrics):
            lbl = QLabel(f"{label}:")
            val = QLabel("--")
            val.setObjectName(f"metric_{key}")
            self.metrics[key] = (val, unit)
            self.metrics_grid.addWidget(lbl, i, 0)
            self.metrics_grid.addWidget(val, i, 1, alignment=Qt.AlignRight)
        
        layout.addLayout(self.metrics_grid)
        layout.addStretch()
        
        self.alert_label = QLabel("")
        self.alert_label.setObjectName("AlertLabel")
        self.alert_label.setWordWrap(True)
        layout.addWidget(self.alert_label)
        
        self.hide()  # Hidden by default
        
    def update_health(self, snapshot: ScanHealthSnapshot):
        self.show()
        for key, (label, unit) in self.metrics.items():
            val = getattr(snapshot, key, 0)
            if isinstance(val, float):
                text = f"{val:.1f}{unit}"
            else:
                text = f"{val}{unit}"
            label.setText(text)
            
        # Alert on high resource usage
        alerts = []
        if snapshot.memory_percent > 80:
            alerts.append("High memory usage!")
        if snapshot.cpu_percent > 90:
            alerts.append("High CPU usage!")
        if alerts:
            self.alert_label.setText("⚠️ " + " ".join(alerts))
            self.alert_label.setStyleSheet("color: #ff6b6b;")
        else:
            self.alert_label.setText("✅ System healthy")
            self.alert_label.setStyleSheet("color: #51cf66;")
            
    def update_styles(self):
        if not self._theme_manager:
            return
        c = self._theme_manager.current_theme['colors']
        self.setStyleSheet(f"""
            QFrame#HealthPanel {{
                background-color: {c['surface']};
                border: 1px solid {c['outline_variant']};
                border-radius: 8px;
            }}
            QLabel {{
                color: {c['text_primary']};
            }}
            QLabel[objectName^="metric_"] {{
                font-family: monospace;
                font-weight: bold;
            }}
        """)


class HistoryEntryCard(QFrame, ThemeMixin):
    load_clicked = Signal(str)
    rerun_clicked = Signal(str)
    delete_clicked = Signal(str)
    rename_clicked = Signal(str)
    compare_clicked = Signal(str)  # New
    selection_changed = Signal(str, bool)  # For bulk ops
    
    def __init__(self, store: HistoryStore, entry: ScanHistoryEntry, 
                 selectable: bool = False, parent: Optional[QWidget] = None):
        ThemeMixin.__init__(self)
        super().__init__(parent)
        self.store = store
        self.entry = entry
        self.selectable = selectable
        
        self.setFrameShape(QFrame.StyledPanel)
        self.setObjectName("HistoryEntryCard")
        self.setMinimumHeight(140)
        
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(8)
        
        # Header row with checkbox if selectable
        header = QHBoxLayout()
        
        if selectable:
            self.chk_select = QCheckBox()
            self.chk_select.stateChanged.connect(
                lambda state: self.selection_changed.emit(entry.scan_id, state == Qt.Checked)
            )
            header.addWidget(self.chk_select)
        
        self.lbl_title = QLabel(entry.name)
        self.lbl_title.setObjectName("Title")
        self.lbl_title.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        
        # Color indicator
        if entry.color_code:
            self.color_dot = QLabel("●")
            self.color_dot.setStyleSheet(f"color: {entry.color_code}; font-size: 20px;")
            header.addWidget(self.color_dot)
        
        self.lbl_status = QLabel(self._status_text(entry.status))
        self.lbl_status.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.lbl_status.setObjectName(f"Status{entry.status.value.capitalize()}")
        
        header.addWidget(self.lbl_title, 1)
        header.addWidget(self.lbl_status, 0)
        outer.addLayout(header)
        
        # Meta info
        meta = QVBoxLayout()
        meta.setSpacing(4)
        
        time_text = f"🕒 {_fmt_dt(entry.started_at_iso)}"
        if entry.finished_at_iso:
            time_text += f" ({_fmt_duration(entry.duration_ms)})"
        self.lbl_time = QLabel(time_text)
        self.lbl_time.setObjectName("Meta")
        
        self.lbl_path = QLabel(f"📁 {entry.root_path}")
        self.lbl_path.setObjectName("Meta")
        self.lbl_path.setWordWrap(True)
        
        rs = entry.result_summary
        self.lbl_summary = QLabel(
            f"🧩 {rs.groups} groups • {rs.items} items • 💾 {_fmt_bytes(rs.duplicate_bytes)} • "
            f"📄 {rs.scanned_files} files scanned"
        )
        self.lbl_summary.setObjectName("Meta")
        
        # Efficiency score
        efficiency = entry.get_efficiency_score()
        self.lbl_efficiency = QLabel(f"⚡ Efficiency: {efficiency:.1f}/100")
        self.lbl_efficiency.setObjectName("Meta")
        
        # Health indicator
        if entry.peak_memory_percent > 0:
            health_color = "#ff6b6b" if entry.peak_memory_percent > 80 else "#51cf66"
            self.lbl_health = QLabel(
                f"🖥️ Peak Memory: {entry.peak_memory_percent:.1f}% | CPU: {entry.peak_cpu_percent:.1f}%"
            )
            self.lbl_health.setStyleSheet(f"color: {health_color};")
            meta.addWidget(self.lbl_health)
        
        # Staleness
        stale_level, stale_msg = store.staleness_state(entry)
        self.lbl_stale = QLabel(f"🔎 {stale_msg}")
        self.lbl_stale.setObjectName(f"Status{stale_level.capitalize()}")
        
        # Tags
        if entry.tags:
            self.lbl_tags = QLabel(f"🏷️ {', '.join(entry.tags)}")
            self.lbl_tags.setObjectName("Tags")
            meta.addWidget(self.lbl_tags)
        
        meta.addWidget(self.lbl_time)
        meta.addWidget(self.lbl_path)
        meta.addWidget(self.lbl_summary)
        meta.addWidget(self.lbl_efficiency)
        meta.addWidget(self.lbl_stale)
        outer.addLayout(meta)
        
        # Actions
        actions = QHBoxLayout()
        actions.addStretch(1)
        
        self.btn_load = QPushButton("Load")
        self.btn_compare = QPushButton("Compare")  # New
        self.btn_rerun = QPushButton("Re-run")
        self.btn_rename = QPushButton("Rename")
        self.btn_delete = QPushButton("Delete")
        
        self.btn_load.clicked.connect(lambda: self.load_clicked.emit(entry.scan_id))
        self.btn_compare.clicked.connect(lambda: self.compare_clicked.emit(entry.scan_id))
        self.btn_rerun.clicked.connect(lambda: self.rerun_clicked.emit(entry.scan_id))
        self.btn_rename.clicked.connect(lambda: self.rename_clicked.emit(entry.scan_id))
        self.btn_delete.clicked.connect(lambda: self.delete_clicked.emit(entry.scan_id))
        
        if entry.status != ScanStatus.COMPLETED:
            self.btn_load.setEnabled(False)
            self.btn_compare.setEnabled(False)
        
        actions.addWidget(self.btn_load)
        actions.addWidget(self.btn_compare)
        actions.addWidget(self.btn_rerun)
        actions.addWidget(self.btn_rename)
        actions.addWidget(self.btn_delete)
        
        outer.addLayout(actions)
        
    def _status_text(self, status: ScanStatus) -> str:
        icons = {
            ScanStatus.COMPLETED: "✅",
            ScanStatus.IN_PROGRESS: "⏳",
            ScanStatus.CANCELLED: "🟦",
            ScanStatus.FAILED: "❌",
            ScanStatus.STALLED: "⚠️",
        }
        return f"{icons.get(status, '❓')} {status.value.replace('_', ' ').title()}"
    
    def update_styles(self):
        if not self._theme_manager:
            return
        c = self._theme_manager.current_theme['colors']
        status_colors = {
            'completed': c['accent'],
            'in_progress': c['primary'],
            'failed': c['error'],
            'cancelled': c['secondary'],
            'stalled': '#ffa502',
        }
        
        self.setStyleSheet(f"""
            QFrame#HistoryEntryCard {{
                background-color: {c['surface']};
                border: 1px solid {c['outline_variant']};
                border-radius: 12px;
                padding: 10px;
            }}
            QFrame#HistoryEntryCard:hover {{
                border: 2px solid {c['primary']};
            }}
            QLabel#Title {{
                color: {c['text_primary']};
                font-size: 14px; 
                font-weight: 600; 
            }}
            QLabel#Meta {{
                color: {c['text_secondary']};
                font-size: 12px;
            }}
            QLabel#Tags {{
                color: {c['accent']};
                font-size: 11px;
                font-style: italic;
            }}
            QLabel#StatusCompleted {{ color: {c['accent']}; }}
            QLabel#StatusIn_progress {{ color: {c['primary']}; }}
            QLabel#StatusFailed {{ color: {c['error']}; }}
            QLabel#StatusCancelled {{ color: {c['secondary']}; }}
            QLabel#StatusStalled {{ color: #ffa502; }}
            QLabel#StatusFresh {{ color: {c['accent']}; }}
            QLabel#StatusStale {{ color: {c['secondary']}; }}
            QLabel#StatusInvalid {{ color: {c['error']}; }}
            QPushButton {{
                color: {c['on_secondary']};
                background-color: {c['secondary']};
                border: 1px solid {c['outline_variant']};
                padding: 6px 12px;
                border-radius: 6px;
                font-size: 11px;
            }}
            QPushButton:hover {{
                background-color: {c['primary']};
            }}
            QPushButton:disabled {{
                background-color: {c['surface_variant']};
                color: {c['text_disabled']};
            }}
        """)


class ComparisonDialog(QDialog, ThemeMixin):
    """Dialog to show comparison between two scans."""
    
    def __init__(self, comparison_data: dict, parent=None):
        ThemeMixin.__init__(self)
        super().__init__(parent)
        self.setWindowTitle("Scan Comparison")
        self.setMinimumSize(600, 400)
        
        layout = QVBoxLayout(self)
        
        # Summary
        summary = QLabel(
            f"<h3>Comparing: {comparison_data['baseline_scan']} vs {comparison_data['compare_scan']}</h3>"
            f"<p>New duplicates found: <b>{comparison_data['new_duplicate_groups']}</b> groups "
            f"({comparison_data['new_duplicate_files']} files)<br>"
            f"Resolved duplicates: <b>{comparison_data['resolved_duplicate_groups']}</b> groups<br>"
            f"Space reclaimed: <b>{_fmt_bytes(comparison_data['space_reclaimed'])}</b><br>"
            f"Efficiency change: <b>{comparison_data['efficiency_delta']:+.1f}</b> points</p>"
        )
        summary.setWordWrap(True)
        layout.addWidget(summary)
        
        # Button box
        buttons = QDialogButtonBox(QDialogButtonBox.Ok)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)
        
    def update_styles(self):
        if not self._theme_manager:
            return
        c = self._theme_manager.current_theme['colors']
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {c['background']};
                color: {c['text_primary']};
            }}
            QLabel {{
                color: {c['text_primary']};
            }}
        """)


class HistoryPage(QWidget, ThemeMixin):
    load_scan_requested = Signal(str)
    rerun_scan_requested = Signal(str)
    compare_scans_requested = Signal(str, str)  # baseline, compare
    
    def __init__(self, store: HistoryStore, parent: Optional[QWidget] = None):
        ThemeMixin.__init__(self)
        super().__init__(parent)
        self.store = store
        self._entries: List[ScanHistoryEntry] = []
        self._selected_ids: Set[str] = set()
        self._comparison_mode = False
        self._comparison_baseline: Optional[str] = None
        
        self._setup_ui()
        self.refresh()
        
        # Auto-refresh timer for active scans
        self._refresh_timer = QTimer()
        self._refresh_timer.timeout.connect(self._check_active_scans)
        self._refresh_timer.start(5000)  # Check every 5 seconds
        
    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)
        
        # Top toolbar
        toolbar = QHBoxLayout()
        
        title = QLabel("CEREBRO History")
        f = QFont()
        f.setPointSize(16)
        f.setBold(True)
        title.setFont(f)
        toolbar.addWidget(title)
        
        toolbar.addStretch()
        
        # Bulk operations
        self.btn_bulk_mode = QPushButton("Bulk Select")
        self.btn_bulk_mode.setCheckable(True)
        self.btn_bulk_mode.clicked.connect(self._toggle_bulk_mode)
        toolbar.addWidget(self.btn_bulk_mode)
        
        self.btn_export = QPushButton("Export Selected")
        self.btn_export.clicked.connect(self._export_selected)
        self.btn_export.setEnabled(False)
        toolbar.addWidget(self.btn_export)
        
        self.btn_delete_selected = QPushButton("Delete Selected")
        self.btn_delete_selected.clicked.connect(self._delete_selected)
        self.btn_delete_selected.setEnabled(False)
        toolbar.addWidget(self.btn_delete_selected)
        
        # Statistics button
        self.btn_stats = QPushButton("📊 Statistics")
        self.btn_stats.clicked.connect(self._show_statistics)
        toolbar.addWidget(self.btn_stats)
        
        toolbar.addSpacing(20)
        
        # Filters
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search by name, path, or tag...")
        self.search.setMinimumWidth(250)
        toolbar.addWidget(self.search)
        
        self.status_filter = QComboBox()
        self.status_filter.addItem("All statuses", "")
        for status in ScanStatus:
            self.status_filter.addItem(status.value.replace("_", " ").title(), status.value)
        toolbar.addWidget(self.status_filter)
        
        self.date_filter = QComboBox()
        self.date_filter.addItem("All time", "all")
        self.date_filter.addItem("Today", "today")
        self.date_filter.addItem("Last 7 days", "7d")
        self.date_filter.addItem("Last 30 days", "30d")
        toolbar.addWidget(self.date_filter)
        
        self.btn_refresh = QPushButton("🔄 Refresh")
        self.btn_refresh.clicked.connect(self.refresh)
        toolbar.addWidget(self.btn_refresh)
        
        root.addLayout(toolbar)
        
        # Comparison mode banner (hidden by default)
        self.comparison_banner = QFrame()
        self.comparison_banner.setObjectName("ComparisonBanner")
        self.comparison_banner.hide()
        banner_layout = QHBoxLayout(self.comparison_banner)
        self.lbl_comparison = QLabel("Select a scan to compare with baseline")
        banner_layout.addWidget(self.lbl_comparison)
        btn_cancel_compare = QPushButton("Cancel")
        btn_cancel_compare.clicked.connect(self._cancel_comparison)
        banner_layout.addWidget(btn_cancel_compare)
        root.addWidget(self.comparison_banner)
        
        # Main content splitter
        splitter = QSplitter(Qt.Horizontal)
        
        # Scroll list
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        
        self.list_host = QWidget()
        self.list_layout = QVBoxLayout(self.list_host)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(10)
        self.list_layout.addStretch(1)
        
        self.scroll.setWidget(self.list_host)
        splitter.addWidget(self.scroll)
        
        # Health panel (re-added feature)
        self.health_panel = HealthPanelWidget()
        splitter.addWidget(self.health_panel)
        self.health_panel.hide()  # Only show when viewing active scan
        
        splitter.setSizes([700, 300])
        root.addWidget(splitter)
        
        # Connect signals
        self.search.textChanged.connect(lambda _: self.render())
        self.status_filter.currentIndexChanged.connect(lambda _: self.render())
        self.date_filter.currentIndexChanged.connect(lambda _: self.render())
        
    def update_styles(self):
        if not self._theme_manager:
            return
        c = self._theme_manager.current_theme['colors']
        self.setStyleSheet(f"""
            QWidget {{
                background-color: {c['background']};
                color: {c['text_primary']};
            }}
            QFrame#ComparisonBanner {{
                background-color: {c['primary']};
                color: {c['on_primary']};
                border-radius: 6px;
                padding: 8px;
            }}
            QLabel {{
                color: {c['text_primary']};
            }}
            QLineEdit {{
                background-color: {c['surface_variant']};
                border: 1px solid {c['outline_variant']};
                border-radius: 6px;
                padding: 8px;
                color: {c['text_primary']};
            }}
            QComboBox {{
                background-color: {c['surface_variant']};
                border: 1px solid {c['outline_variant']};
                border-radius: 6px;
                padding: 8px;
                color: {c['text_primary']};
            }}
            QPushButton {{
                color: {c['on_primary']};
                background-color: {c['primary']};
                border: none;
                padding: 8px 16px;
                border-radius: 6px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {c['accent']};
            }}
            QPushButton:disabled {{
                background-color: {c['surface_variant']};
                color: {c['text_disabled']};
            }}
            QPushButton:checked {{
                background-color: {c['accent']};
            }}
        """)
        self.health_panel.update_styles()
        self.render()
        
    def _toggle_bulk_mode(self, enabled: bool):
        self._selected_ids.clear()
        self.btn_export.setEnabled(False)
        self.btn_delete_selected.setEnabled(False)
        self.render()
        
    def _on_selection_changed(self, scan_id: str, selected: bool):
        if selected:
            self._selected_ids.add(scan_id)
        else:
            self._selected_ids.discard(scan_id)
        
        has_selection = len(self._selected_ids) > 0
        self.btn_export.setEnabled(has_selection)
        self.btn_delete_selected.setEnabled(has_selection)
        
    def _export_selected(self):
        if not self._selected_ids:
            return
            
        dialog = QFileDialog(self, "Export Selected Scans")
        dialog.setFileMode(QFileDialog.Directory)
        if dialog.exec():
            export_dir = dialog.selectedFiles()[0]
            paths = []
            for scan_id in self._selected_ids:
                try:
                    path = self.store.export_to_json(scan_id, Path(export_dir) / f"{scan_id}.json")
                    paths.append(path)
                except Exception as e:
                    QMessageBox.warning(self, "Export Error", f"Failed to export {scan_id}: {e}")
            
            QMessageBox.information(self, "Export Complete", f"Exported {len(paths)} scans to {export_dir}")
            
    def _delete_selected(self):
        if not self._selected_ids:
            return
            
        reply = QMessageBox.question(
            self, "Confirm Bulk Delete",
            f"Delete {len(self._selected_ids)} selected scans permanently?",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            success, errors = self.store.bulk_delete(list(self._selected_ids))
            if errors:
                QMessageBox.warning(self, "Partial Failure", f"Deleted {success}, failed:\n" + "\n".join(errors))
            self._selected_ids.clear()
            self.btn_export.setEnabled(False)
            self.btn_delete_selected.setEnabled(False)
            self.refresh()
            
    def _show_statistics(self):
        stats = self.store.get_statistics()
        if not stats:
            QMessageBox.information(self, "Statistics", "No completed scans available for statistics.")
            return
            
        text = f"""
        <h2>Scan Statistics</h2>
        <table>
        <tr><td>Total Scans:</td><td><b>{stats['total_scans']}</b></td></tr>
        <tr><td>Completed:</td><td><b>{stats['completed_scans']}</b></td></tr>
        <tr><td>Files Scanned:</td><td><b>{stats['total_files_scanned']:,}</b></td></tr>
        <tr><td>Data Scanned:</td><td><b>{_fmt_bytes(stats['total_bytes_scanned'])}</b></td></tr>
        <tr><td>Duplicates Found:</td><td><b>{_fmt_bytes(stats['total_duplicate_bytes'])}</b></td></tr>
        <tr><td>Avg Duration:</td><td><b>{_fmt_duration(int(stats['average_scan_duration_ms']))}</b></td></tr>
        <tr><td>Avg Efficiency:</td><td><b>{stats['average_efficiency']:.1f}/100</b></td></tr>
        <tr><td>Peak Memory:</td><td><b>{stats['peak_memory_ever']:.1f}%</b></td></tr>
        </table>
        """
        
        dialog = QDialog(self)
        dialog.setWindowTitle("History Statistics")
        layout = QVBoxLayout(dialog)
        label = QLabel(text)
        label.setWordWrap(True)
        layout.addWidget(label)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok)
        buttons.accepted.connect(dialog.accept)
        layout.addWidget(buttons)
        dialog.exec()
        
    def _check_active_scans(self):
        """Auto-refresh if there are in-progress scans."""
        has_active = any(
            e.status == ScanStatus.IN_PROGRESS for e in self._entries
        )
        if has_active:
            self.refresh()
            
    def refresh(self) -> None:
        self._entries = self.store.list_entries()
        self.render()
        
    def render(self) -> None:
        # Clear current cards
        while self.list_layout.count():
            item = self.list_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
                
        filtered = self._apply_filters(self._entries)
        
        if not filtered:
            empty = QLabel("No scans found.")
            empty.setAlignment(Qt.AlignCenter)
            empty.setStyleSheet("color: rgba(255,255,255,0.7); padding: 40px; font-size: 16px;")
            self.list_layout.addWidget(empty)
            self.list_layout.addStretch(1)
            return
            
        for entry in filtered:
            card = HistoryEntryCard(
                self.store, entry, 
                selectable=self.btn_bulk_mode.isChecked()
            )
            card.set_theme_manager(self._theme_manager)
            card.load_clicked.connect(self._on_load)
            card.rerun_clicked.connect(self._on_rerun)
            card.rename_clicked.connect(self._on_rename)
            card.delete_clicked.connect(self._on_delete)
            card.compare_clicked.connect(self._on_compare_clicked)
            card.selection_changed.connect(self._on_selection_changed)
            
            # Restore selection state
            if self.btn_bulk_mode.isChecked() and entry.scan_id in self._selected_ids:
                card.chk_select.setChecked(True)
                
            self.list_layout.addWidget(card)
            
        self.list_layout.addStretch(1)
        
    def _apply_filters(self, entries: List[ScanHistoryEntry]) -> List[ScanHistoryEntry]:
        q = (self.search.text() or "").strip().lower()
        status_val = self.status_filter.currentData()
        date_mode = self.date_filter.currentData()
        
        now = datetime.now(timezone.utc)
        
        def in_date_range(e: ScanHistoryEntry) -> bool:
            if date_mode == "all":
                return True
            if not e.started_at_iso:
                return False
            try:
                dt = datetime.fromisoformat(e.started_at_iso.replace("Z", "+00:00"))
            except Exception:
                return True
                
            if date_mode == "today":
                return dt.date() == now.date()
            if date_mode == "7d":
                return dt >= now - timedelta(days=7)
            if date_mode == "30d":
                return dt >= now - timedelta(days=30)
            return True
            
        out: List[ScanHistoryEntry] = []
        for e in entries:
            if status_val and e.status.value != status_val:
                continue
            if q:
                hay = f"{e.name} {e.root_path} {' '.join(e.tags)}".lower()
                if q not in hay:
                    continue
            if not in_date_range(e):
                continue
            out.append(e)
        return out
        
    def _on_load(self, scan_id: str) -> None:
        # Show health data if available
        entry = self.store.get_entry(scan_id)
        if entry and entry.health_snapshots:
            # Show latest health snapshot
            self.health_panel.update_health(entry.health_snapshots[-1])
        else:
            self.health_panel.hide()
        self.load_scan_requested.emit(scan_id)
        
    def _on_rerun(self, scan_id: str) -> None:
        self.rerun_scan_requested.emit(scan_id)
        
    def _on_compare_clicked(self, scan_id: str) -> None:
        if not self._comparison_mode:
            # Start comparison mode
            self._comparison_mode = True
            self._comparison_baseline = scan_id
            self.comparison_banner.show()
            self.lbl_comparison.setText(f"Baseline: {self.store.get_entry(scan_id).name} - Select another scan to compare")
            self.btn_bulk_mode.setEnabled(False)
        else:
            # Complete comparison
            if scan_id == self._comparison_baseline:
                return  # Can't compare with self
                
            try:
                result = self.store.compare_scans(self._comparison_baseline, scan_id)
                dialog = ComparisonDialog(result, self)
                dialog.set_theme_manager(self._theme_manager)
                dialog.exec()
            except Exception as e:
                QMessageBox.critical(self, "Comparison Error", str(e))
            finally:
                self._cancel_comparison()
                
    def _cancel_comparison(self):
        self._comparison_mode = False
        self._comparison_baseline = None
        self.comparison_banner.hide()
        self.btn_bulk_mode.setEnabled(True)
        
    def _on_rename(self, scan_id: str) -> None:
        entry = self.store.get_entry(scan_id)
        if not entry:
            return
        new_name, ok = QInputDialog.getText(self, "Rename scan", "New name:", text=entry.name)
        if not ok:
            return
        self.store.rename_scan(scan_id, new_name)
        self.refresh()
        
    def _on_delete(self, scan_id: str) -> None:
        entry = self.store.get_entry(scan_id)
        if not entry:
            return
        resp = QMessageBox.question(
            self,
            "Delete scan",
            f"Delete scan '{entry.name}'?\n\nThis removes it from history and deletes stored results.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if resp != QMessageBox.Yes:
            return
        self.store.delete_scan(scan_id, delete_payload=True)
        self.refresh()