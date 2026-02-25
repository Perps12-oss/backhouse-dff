# cerebro/ui/widgets/visualization_widget.py
"""
Visualization widgets for strategy analysis - Timeline, Size Comparison, Path Analysis, Quality
"""
from __future__ import annotations

from typing import List, Optional, Dict
from datetime import datetime
from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, 
    QGraphicsView, QGraphicsScene, QGraphicsRectItem, 
    QGraphicsTextItem, QGraphicsLineItem, QGraphicsDropShadowEffect,
    QScrollArea, QSizePolicy
)
from PySide6.QtCore import Qt, QRectF, QSize, QTimer
from PySide6.QtGui import QColor, QBrush, QPen, QFont, QLinearGradient, QPainter, QPaintEvent

from cerebro.ui.widgets.glass_panel import GlassPanel


class BaseVisualization(GlassPanel):
    """Base class for strategy visualizations"""
    
    def __init__(self, groups: List, parent=None):
        super().__init__(parent)
        self.groups = groups
        self.setMinimumHeight(200)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)


class TimelineVisualization(BaseVisualization):
    """
    Timeline visualization showing file modification dates
    Useful for KEEP_NEWEST/KEEP_OLDEST strategies
    """
    
    def __init__(self, groups: List, parent=None):
        super().__init__(groups, parent)
        self._setup_ui()
        self._render_timeline()
    
    def _setup_ui(self):
        """Setup the timeline view"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # Header
        header = QLabel("📅 Timeline View - Modification Dates")
        header_font = QFont()
        header_font.setPointSize(14)
        header_font.setBold(True)
        header.setFont(header_font)
        header.setStyleSheet("color: #f1f5f9; margin-bottom: 10px;")
        layout.addWidget(header)
        
        # Graphics view for timeline
        self.graphics_view = QGraphicsView()
        self.graphics_view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.graphics_view.setStyleSheet("""
            QGraphicsView {
                border: none;
                background: transparent;
            }
        """)
        
        self.scene = QGraphicsScene()
        self.graphics_view.setScene(self.scene)
        layout.addWidget(self.graphics_view)
    
    def _render_timeline(self):
        """Render the timeline visualization"""
        self.scene.clear()
        
        if not self.groups:
            return
        
        # Collect all files with dates
        all_files = []
        for group in self.groups[:5]:  # Show first 5 groups
            for file_info in group.files:
                all_files.append({
                    'path': file_info.path,
                    'date': file_info.modified,
                    'size': file_info.size,
                    'group_id': group.id,
                    'is_best': group.best_file == file_info if group.best_file else False
                })
        
        if not all_files:
            return
        
        # Sort by date
        all_files.sort(key=lambda x: x['date'])
        
        # Calculate timeline range
        min_date = min(f['date'] for f in all_files)
        max_date = max(f['date'] for f in all_files)
        date_range = (max_date - min_date).total_seconds() if min_date != max_date else 1
        
        # Draw timeline
        y_pos = 50
        bar_height = 30
        spacing = 10
        
        for i, file_data in enumerate(all_files):
            # Calculate position based on date
            if date_range > 0:
                x_pos = 50 + ((file_data['date'] - min_date).total_seconds() / date_range) * 600
            else:
                x_pos = 50
            
            # Color based on selection status
            if file_data['is_best']:
                color = QColor("#22c55e")  # Green for kept
                label = "KEEP"
            else:
                color = QColor("#ef4444")  # Red for delete
                label = "DELETE"
            
            # Draw bar
            rect = QGraphicsRectItem(x_pos, y_pos + i * (bar_height + spacing), 120, bar_height)
            rect.setBrush(QBrush(color))
            rect.setPen(QPen(Qt.PenStyle.NoPen))
            rect.setOpacity(0.7)
            self.scene.addItem(rect)
            
            # Add label
            text = QGraphicsTextItem(f"{label}\n{file_data['path'].name[:15]}")
            text.setPos(x_pos + 5, y_pos + i * (bar_height + spacing) + 2)
            text.setDefaultTextColor(QColor("#ffffff"))
            font = QFont()
            font.setPointSize(8)
            text.setFont(font)
            self.scene.addItem(text)
            
            # Add date label
            date_text = QGraphicsTextItem(file_data['date'].strftime("%m/%d/%Y"))
            date_text.setPos(x_pos, y_pos + i * (bar_height + spacing) - 20)
            date_text.setDefaultTextColor(QColor("#94a3b8"))
            date_font = QFont()
            date_font.setPointSize(7)
            date_text.setFont(date_font)
            self.scene.addItem(date_text)
        
        # Add timeline axis
        axis = QGraphicsLineItem(50, y_pos - 10, 650, y_pos - 10)
        axis.setPen(QPen(QColor("#3b82f6"), 2))
        self.scene.addItem(axis)
        
        # Scene bounds
        self.scene.setSceneRect(0, 0, 700, y_pos + len(all_files) * (bar_height + spacing) + 50)


class SizeComparisonVisualization(BaseVisualization):
    """
    Bar chart comparing file sizes
    Useful for KEEP_LARGEST/KEEP_SMALLEST strategies
    """
    
    def __init__(self, groups: List, strategy, parent=None):
        super().__init__(groups, parent)
        self.strategy = strategy
        self._setup_ui()
        self._render_chart()
    
    def _setup_ui(self):
        """Setup the chart view"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # Header
        icon = "📈" if "LARGEST" in self.strategy.name else "📉"
        header = QLabel(f"{icon} Size Comparison - {'Largest' if 'LARGEST' in self.strategy.name else 'Smallest'} Files")
        header_font = QFont()
        header_font.setPointSize(14)
        header_font.setBold(True)
        header.setFont(header_font)
        header.setStyleSheet("color: #f1f5f9; margin-bottom: 10px;")
        layout.addWidget(header)
        
        # Chart area
        self.chart_widget = QWidget()
        self.chart_layout = QVBoxLayout(self.chart_widget)
        self.chart_layout.setSpacing(8)
        layout.addWidget(self.chart_widget)
    
    def _render_chart(self):
        """Render size comparison bars"""
        # Clear existing
        while self.chart_layout.count():
            item = self.chart_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        if not self.groups:
            return
        
        # Get max size for scaling
        max_size = max(
            max(f.size for f in group.files) 
            for group in self.groups[:3]
        )
        
        for group in self.groups[:3]:  # Show first 3 groups
            group_frame = QFrame()
            group_frame.setStyleSheet("""
                QFrame {
                    background: rgba(255, 255, 255, 0.03);
                    border-radius: 8px;
                    padding: 8px;
                }
            """)
            group_layout = QVBoxLayout(group_frame)
            
            # Group label
            group_label = QLabel(f"📁 {group.name}")
            group_label.setStyleSheet("color: #94a3b8; font-size: 11px; margin-bottom: 4px;")
            group_layout.addWidget(group_label)
            
            # Size bars
            for file_info in sorted(group.files, key=lambda x: x.size, reverse=True):
                bar_container = QWidget()
                bar_layout = QHBoxLayout(bar_container)
                bar_layout.setContentsMargins(0, 0, 0, 0)
                bar_layout.setSpacing(8)
                
                # Size bar
                bar = QFrame()
                bar.setFixedHeight(24)
                width_pct = (file_info.size / max_size) * 100
                bar.setFixedWidth(int(width_pct * 3))  # Scale factor
                
                # Color based on strategy and if it's best
                is_best = group.best_file == file_info
                if is_best:
                    bg = "qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #22c55e, stop:1 #16a34a)"
                    border = "#22c55e"
                else:
                    bg = "rgba(239, 68, 68, 0.3)"
                    border = "#ef4444"
                
                bar.setStyleSheet(f"""
                    QFrame {{
                        background: {bg};
                        border: 1px solid {border};
                        border-radius: 4px;
                    }}
                """)
                
                # Filename label
                name_label = QLabel(file_info.path.name[:20])
                name_label.setStyleSheet("color: #e2e8f0; font-size: 10px;")
                name_label.setFixedWidth(150)
                
                # Size label
                size_label = QLabel(self._format_size(file_info.size))
                size_label.setStyleSheet("color: #94a3b8; font-size: 10px;")
                size_label.setFixedWidth(60)
                
                bar_layout.addWidget(name_label)
                bar_layout.addWidget(bar)
                bar_layout.addWidget(size_label)
                bar_layout.addStretch()
                
                group_layout.addWidget(bar_container)
            
            self.chart_layout.addWidget(group_frame)
    
    def _format_size(self, size: int) -> str:
        """Format bytes"""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"


class PathVisualization(BaseVisualization):
    """
    Tree/path visualization showing folder organization
    Useful for KEEP_BEST_ORGANIZED strategy
    """
    
    def __init__(self, groups: List, parent=None):
        super().__init__(groups, parent)
        self._setup_ui()
        self._render_paths()
    
    def _setup_ui(self):
        """Setup path view"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        
        header = QLabel("📁 Path Organization Analysis")
        header_font = QFont()
        header_font.setPointSize(14)
        header_font.setBold(True)
        header.setFont(header_font)
        header.setStyleSheet("color: #f1f5f9; margin-bottom: 10px;")
        layout.addWidget(header)
        
        self.paths_container = QWidget()
        self.paths_layout = QVBoxLayout(self.paths_container)
        self.paths_layout.setSpacing(12)
        layout.addWidget(self.paths_container)
    
    def _render_paths(self):
        """Render path tree"""
        if not self.groups:
            return
        
        for group in self.groups[:3]:
            path_frame = QFrame()
            path_frame.setStyleSheet("""
                QFrame {
                    background: rgba(255, 255, 255, 0.03);
                    border-radius: 8px;
                    border-left: 3px solid #3b82f6;
                }
            """)
            path_layout = QVBoxLayout(path_frame)
            path_layout.setContentsMargins(12, 12, 12, 12)
            
            # Group name
            title = QLabel(f"📂 {group.name}")
            title.setStyleSheet("color: #f1f5f9; font-weight: bold; font-size: 12px;")
            path_layout.addWidget(title)
            
            # Path depth indicators
            for file_info in group.files:
                depth = file_info.directory_depth
                path_str = str(file_info.path.parent)
                
                row = QWidget()
                row_layout = QHBoxLayout(row)
                row_layout.setContentsMargins(0, 0, 0, 0)
                row_layout.setSpacing(8)
                
                # Depth indicator
                depth_widget = QLabel("│  " * min(depth, 4) + "📄")
                depth_widget.setStyleSheet("color: #64748b; font-family: monospace; font-size: 11px;")
                row_layout.addWidget(depth_widget)
                
                # Path text
                path_label = QLabel(path_str[-50:])  # Last 50 chars
                path_label.setStyleSheet(
                    "color: #22c55e; font-size: 11px;" if group.best_file == file_info 
                    else "color: #94a3b8; font-size: 11px;"
                )
                row_layout.addWidget(path_label, 1)
                
                # Score
                score_label = QLabel(f"{file_info.organization_score:.0f}/100")
                score_label.setStyleSheet("color: #64748b; font-size: 10px;")
                row_layout.addWidget(score_label)
                
                path_layout.addWidget(row)
            
            self.paths_layout.addWidget(path_frame)


class QualityIndicator(BaseVisualization):
    """
    Quality score visualization with radar/spider chart simulation
    Useful for KEEP_HIGHEST_QUALITY strategy
    """
    
    def __init__(self, groups: List, parent=None):
        super().__init__(groups, parent)
        self._setup_ui()
        self._render_quality()
    
    def _setup_ui(self):
        """Setup quality view"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        
        header = QLabel("⭐ Quality Analysis")
        header_font = QFont()
        header_font.setPointSize(14)
        header_font.setBold(True)
        header.setFont(header_font)
        header.setStyleSheet("color: #f1f5f9; margin-bottom: 10px;")
        layout.addWidget(header)
        
        self.quality_container = QWidget()
        self.quality_layout = QVBoxLayout(self.quality_container)
        self.quality_layout.setSpacing(16)
        layout.addWidget(self.quality_container)
    
    def _render_quality(self):
        """Render quality indicators"""
        if not self.groups:
            return
        
        for group in self.groups[:3]:
            quality_frame = QFrame()
            quality_frame.setStyleSheet("""
                QFrame {
                    background: rgba(255, 255, 255, 0.03);
                    border-radius: 8px;
                }
            """)
            quality_layout = QHBoxLayout(quality_frame)
            
            for file_info in group.files:
                file_widget = QWidget()
                file_layout = QVBoxLayout(file_widget)
                file_layout.setSpacing(4)
                
                # File icon
                icon = QLabel("🏆" if group.best_file == file_info else "📄")
                icon.setStyleSheet("font-size: 24px;")
                icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
                file_layout.addWidget(icon)
                
                # Quality score circle (simulated with label)
                score = int(file_info.quality_score)
                color = "#22c55e" if score > 70 else "#f59e0b" if score > 40 else "#ef4444"
                
                score_label = QLabel(f"{score}%")
                score_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                score_label.setStyleSheet(f"""
                    QLabel {{
                        color: {color};
                        font-size: 16px;
                        font-weight: bold;
                        padding: 8px;
                        background: rgba(255, 255, 255, 0.05);
                        border-radius: 20px;
                        border: 2px solid {color};
                    }}
                """)
                file_layout.addWidget(score_label)
                
                # Filename
                name = QLabel(file_info.path.name[:10] + "...")
                name.setAlignment(Qt.AlignmentFlag.AlignCenter)
                name.setStyleSheet("color: #94a3b8; font-size: 10px;")
                file_layout.addWidget(name)
                
                quality_layout.addWidget(file_widget)
            
            self.quality_layout.addWidget(quality_frame)