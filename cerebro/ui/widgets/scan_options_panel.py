"""
cerebro/ui/widgets/scan_options_panel.py
Enhanced scan options panel for CEREBRO v5.0

Professional, performance-focused scan configuration with presets,
real-time feedback, and adaptive options.
"""

from __future__ import annotations

from typing import Optional, Dict, List, Set, Any
from dataclasses import dataclass
from pathlib import Path
from cerebro.core.models import StartScanConfig


from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QCheckBox, QSpinBox, QComboBox, QPushButton, 
    QSizePolicy, QFrame, QGroupBox, QScrollArea,
    QButtonGroup, QRadioButton, QLineEdit, QFileDialog
)
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QFont, QColor, QPalette

class ScanOptionsContainer(QWidget):
    """
    Wrapper around ScanOptionsPanel that emits fully-formed StartScanConfig
    when user confirms a scan.
    """
    scan_requested = Signal(StartScanConfig)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._panel = ScanOptionsPanel(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._panel)

    def emit_scan_request(self):
        """Call when user hits Start Scan."""
        config_dict = self._panel.get_config_dict()
        request = StartScanConfig(
            root=Path("."),
            mode=config_dict.get("mode", "exact"),
            min_size_bytes=config_dict.get("min_size_bytes", 102400),
            hash_bytes=config_dict.get("hash_bytes", 4096),
            max_workers=config_dict.get("max_workers", 8),
            follow_symlinks=config_dict.get("follow_symlinks", False),
            include_hidden=config_dict.get("include_hidden", False),
            exclude_dirs=None,
            fast_mode=config_dict.get("fast_mode", True),
            allowed_extensions=config_dict.get("file_types", []),
        )
        self.scan_requested.emit(request)

    def set_scanning(self, scanning: bool):
        self._panel.set_scanning(scanning)

    def apply_preset(self, preset_id: str):
        if hasattr(self._panel, "_apply_preset"):
            self._panel._apply_preset(preset_id)

    def get_current_config(self) -> dict:
        return self._panel.get_config_dict()


@dataclass
class ScanPreset:
    """Scan configuration preset"""
    id: str
    name: str
    description: str
    icon: str
    config: Dict[str, Any]
    recommended_for: str = ""
    performance_impact: str = "low"  # low/medium/high


class PresetCard(QFrame):
    """Interactive preset card"""
    
    clicked = Signal(str)  # Emits preset id
    
    def __init__(self, preset: ScanPreset, is_active: bool = False, parent=None):
        super().__init__(parent)
        self.preset = preset
        self._is_active = is_active
        
        self.setFixedHeight(90)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(6)
        
        # Header
        header = QHBoxLayout()
        
        icon = QLabel(preset.icon)
        icon.setFont(QFont("Segoe UI Emoji", 16))
        header.addWidget(icon)
        
        text_layout = QVBoxLayout()
        text_layout.setSpacing(2)
        
        name = QLabel(preset.name)
        name_font = QFont()
        name_font.setPointSize(12)
        name_font.setBold(True)
        name.setFont(name_font)
        text_layout.addWidget(name)
        
        desc = QLabel(preset.description)
        desc.setFont(QFont("", 9))
        desc.setStyleSheet("color: #94a3b8;")
        text_layout.addWidget(desc)
        
        header.addLayout(text_layout, 1)
        
        # Performance indicator
        perf_color = {
            "low": "#10b981",
            "medium": "#f59e0b", 
            "high": "#ef4444"
        }.get(preset.performance_impact, "#94a3b8")
        
        perf = QLabel("⚡")
        perf.setToolTip(f"Performance impact: {preset.performance_impact}")
        perf.setStyleSheet(f"color: {perf_color}; font-size: 16px;")
        header.addWidget(perf)
        
        layout.addLayout(header)
        
        # Recommendation (if any)
        if preset.recommended_for:
            rec = QLabel(f"Recommended for: {preset.recommended_for}")
            rec.setFont(QFont("", 8))
            rec.setStyleSheet("color: #8b5cf6; font-style: italic;")
            layout.addWidget(rec)
        
        self._update_style()
    
    def set_active(self, active: bool):
        """Set as active preset"""
        if self._is_active == active:
            return
        
        self._is_active = active
        self._update_style()
    
    def mousePressEvent(self, event):
        """Handle click"""
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.preset.id)
        super().mousePressEvent(event)
    
    def _update_style(self):
        """Update card appearance based on state"""
        if self._is_active:
            self.setStyleSheet("""
                PresetCard {
                    background-color: rgba(59, 130, 246, 0.1);
                    border: 2px solid #3b82f6;
                    border-radius: 8px;
                }
                PresetCard:hover {
                    background-color: rgba(59, 130, 246, 0.15);
                }
            """)
        else:
            self.setStyleSheet("""
                PresetCard {
                    background-color: #1e293b;
                    border: 1px solid #334155;
                    border-radius: 8px;
                }
                PresetCard:hover {
                    background-color: #334155;
                    border-color: #475569;
                }
            """)


class FileTypeFilterWidget(QWidget):
    """Advanced file type filter widget"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        
        # Header
        header = QHBoxLayout()
        header.addWidget(QLabel("📁 File Types"))
        
        self.btn_select_all = QPushButton("All")
        self.btn_select_all.setFixedSize(40, 24)
        self.btn_select_all.setStyleSheet("""
            QPushButton {
                font-size: 10px;
                padding: 2px 6px;
                background: #334155;
                border: none;
                border-radius: 4px;
            }
            QPushButton:hover {
                background: #475569;
            }
        """)
        header.addWidget(self.btn_select_all)
        
        self.btn_select_none = QPushButton("None")
        self.btn_select_none.setFixedSize(40, 24)
        self.btn_select_none.setStyleSheet("""
            QPushButton {
                font-size: 10px;
                padding: 2px 6px;
                background: #334155;
                border: none;
                border-radius: 4px;
            }
            QPushButton:hover {
                background: #475569;
            }
        """)
        header.addWidget(self.btn_select_none)
        
        header.addStretch()
        layout.addLayout(header)
        
        # File type categories
        self.categories = {
            "Images": [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff", ".heic", ".raw"],
            "Videos": [".mp4", ".mov", ".avi", ".mkv", ".wmv", ".flv", ".webm", ".m4v"],
            "Documents": [".pdf", ".doc", ".docx", ".txt", ".rtf", ".md", ".odt", ".pages"],
            "Audio": [".mp3", ".wav", ".flac", ".aac", ".m4a", ".ogg", ".wma"],
            "Archives": [".zip", ".rar", ".7z", ".tar", ".gz", ".bz2"],
            "Code": [".py", ".js", ".html", ".css", ".json", ".xml", ".java", ".cpp"],
        }
        
        self.checkboxes: Dict[str, QCheckBox] = {}
        
        grid = QHBoxLayout()
        for category, extensions in self.categories.items():
            col = QVBoxLayout()
            col.setSpacing(4)
            
            cb = QCheckBox(f"{category} ({len(extensions)})")
            cb.setProperty("category", category)
            cb.setStyleSheet("""
                QCheckBox {
                    font-size: 12px;
                    padding: 4px;
                }
                QCheckBox::indicator {
                    width: 16px;
                    height: 16px;
                }
            """)
            col.addWidget(cb)
            self.checkboxes[category] = cb
            
            # Show first few extensions
            ext_text = ", ".join(extensions[:3])
            if len(extensions) > 3:
                ext_text += f" +{len(extensions)-3} more"
            
            ext_label = QLabel(ext_text)
            ext_label.setFont(QFont("", 9))
            ext_label.setStyleSheet("color: #64748b; margin-left: 20px;")
            col.addWidget(ext_label)
            
            grid.addLayout(col)
        
        layout.addLayout(grid)
        
        # Custom extensions input
        custom_row = QHBoxLayout()
        custom_row.addWidget(QLabel("Custom:"))
        
        self.custom_input = QLineEdit()
        self.custom_input.setPlaceholderText(".ext1, .ext2, ...")
        self.custom_input.setStyleSheet("""
            QLineEdit {
                padding: 6px;
                background: #1e293b;
                border: 1px solid #334155;
                border-radius: 6px;
            }
        """)
        custom_row.addWidget(self.custom_input, 1)
        layout.addLayout(custom_row)
    
    def get_selected_extensions(self) -> List[str]:
        """Get all selected file extensions"""
        extensions = []
        
        for category, cb in self.checkboxes.items():
            if cb.isChecked():
                extensions.extend(self.categories[category])
        
        # Parse custom extensions
        custom_text = self.custom_input.text().strip()
        if custom_text:
            custom_exts = [ext.strip() for ext in custom_text.split(",") if ext.strip()]
            extensions.extend(ext for ext in custom_exts if ext.startswith("."))
        
        return list(set(extensions))  # Remove duplicates


class ScanOptionsPanel(QWidget):
    """
    Enhanced scan options panel with presets, real-time feedback,
    and adaptive configuration.
    """
    
    config_changed = Signal(dict)  # Emits current config
    preset_applied = Signal(str)   # Emits preset id
    
    # Built-in presets
    PRESETS = [
        ScanPreset(
            id="quick_scan",
            name="Quick Scan",
            icon="⚡",
            description="Fast scan for recent duplicates",
            config={
                "mode": "exact",
                "min_size_kb": 100,
                "hash_bytes": 1024 * 4,  # 4KB samples
                "max_workers": 8,
                "fast_mode": True,
                "include_hidden": False,
                "follow_symlinks": False,
            },
            recommended_for="Recent cleanup",
            performance_impact="low"
        ),
        ScanPreset(
            id="deep_clean",
            name="Deep Clean",
            icon="🔍",
            description="Comprehensive duplicate detection",
            config={
                "mode": "exact",
                "min_size_kb": 1,  # All files
                "hash_bytes": 1024 * 1024,  # 1MB samples
                "max_workers": 4,
                "fast_mode": False,
                "include_hidden": True,
                "follow_symlinks": True,
            },
            recommended_for="System cleanup",
            performance_impact="high"
        ),
        ScanPreset(
            id="media_library",
            name="Media Library",
            icon="🎬",
            description="Optimized for photos & videos",
            config={
                "mode": "visual",
                "min_size_kb": 100,
                "hash_bytes": 1024 * 64,  # 64KB for perceptual hashing
                "max_workers": 6,
                "fast_mode": True,
                "include_hidden": False,
                "follow_symlinks": False,
                "file_types": [".jpg", ".jpeg", ".png", ".mp4", ".mov"]
            },
            recommended_for="Photo/video libraries",
            performance_impact="medium"
        ),
        ScanPreset(
            id="dev_workspace",
            name="Developer Workspace",
            icon="💻",
            description="Scan code and project files",
            config={
                "mode": "exact",
                "min_size_kb": 1,
                "hash_bytes": 1024 * 16,
                "max_workers": 12,
                "fast_mode": True,
                "include_hidden": True,
                "follow_symlinks": True,
                "file_types": [".py", ".js", ".java", ".cpp", ".html", ".css", ".json"]
            },
            recommended_for="Development projects",
            performance_impact="medium"
        ),
    ]
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_preset: Optional[str] = None
        self._preset_cards: Dict[str, PresetCard] = {}
        
        self.setObjectName("ScanOptionsPanel")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.MinimumExpanding)
        
        self._setup_ui()
        self._apply_styles()
        
        # Set default preset
        self._apply_preset("quick_scan")
    
    def _setup_ui(self):
        """Setup the enhanced UI"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(16)
        
        # 1. PRESETS SECTION
        presets_group = QGroupBox("⚡ Scan Presets")
        presets_group.setObjectName("PresetsGroup")
        presets_layout = QVBoxLayout(presets_group)
        presets_layout.setContentsMargins(12, 12, 12, 12)
        presets_layout.setSpacing(8)
        
        # Preset cards in a scrollable area
        presets_scroll = QScrollArea()
        presets_scroll.setWidgetResizable(True)
        presets_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        presets_scroll.setStyleSheet("""
            QScrollArea {
                border: none;
                background: transparent;
            }
            QScrollBar:vertical {
                background: #1e293b;
                width: 6px;
                border-radius: 3px;
            }
            QScrollBar::handle:vertical {
                background: #475569;
                border-radius: 3px;
                min-height: 30px;
            }
        """)
        
        presets_container = QWidget()
        presets_container_layout = QVBoxLayout(presets_container)
        presets_container_layout.setSpacing(8)
        presets_container_layout.setContentsMargins(0, 0, 8, 0)
        
        for preset in self.PRESETS:
            card = PresetCard(preset)
            card.clicked.connect(self._apply_preset)
            presets_container_layout.addWidget(card)
            self._preset_cards[preset.id] = card
        
        presets_container_layout.addStretch()
        presets_scroll.setWidget(presets_container)
        presets_layout.addWidget(presets_scroll)
        
        main_layout.addWidget(presets_group)
        
        # 2. ADVANCED OPTIONS SECTION
        advanced_group = QGroupBox("🔧 Advanced Options")
        advanced_group.setObjectName("AdvancedGroup")
        advanced_layout = QVBoxLayout(advanced_group)
        advanced_layout.setContentsMargins(16, 12, 16, 12)
        advanced_layout.setSpacing(12)
        
        # Mode selector
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Scan Mode:"))
        
        self.mode_combo = QComboBox()
        self.mode_combo.addItems([
            "Exact Match (MD5/SHA)",
            "Visual Similarity (Perceptual Hash)", 
            "Fuzzy Match (Content-aware)"
        ])
        self.mode_combo.setStyleSheet("""
            QComboBox {
                padding: 8px;
                background: #1e293b;
                border: 1px solid #334155;
                border-radius: 6px;
            }
        """)
        mode_row.addWidget(self.mode_combo, 1)
        advanced_layout.addLayout(mode_row)
        
        # File size and hashing
        grid = QHBoxLayout()
        
        # Left column
        left_col = QVBoxLayout()
        left_col.setSpacing(8)
        
        # Minimum file size
        size_row = QHBoxLayout()
        size_row.addWidget(QLabel("Min Size:"))
        
        self.min_size_spin = QSpinBox()
        self.min_size_spin.setRange(0, 1024 * 1024)  # Up to 1GB
        self.min_size_spin.setValue(100)
        self.min_size_spin.setSuffix(" KB")
        size_row.addWidget(self.min_size_spin, 1)
        left_col.addLayout(size_row)
        
        # Hash sample size
        hash_row = QHBoxLayout()
        hash_row.addWidget(QLabel("Hash Sample:"))
        
        self.hash_sample_combo = QComboBox()
        self.hash_sample_combo.addItems([
            "Fast (4KB)",
            "Balanced (16KB)", 
            "Accurate (64KB)",
            "Full File (Exact)"
        ])
        hash_row.addWidget(self.hash_sample_combo, 1)
        left_col.addLayout(hash_row)
        
        grid.addLayout(left_col, 1)
        
        # Right column
        right_col = QVBoxLayout()
        right_col.setSpacing(8)
        
        # Worker threads
        worker_row = QHBoxLayout()
        worker_row.addWidget(QLabel("Workers:"))
        
        self.worker_spin = QSpinBox()
        self.worker_spin.setRange(1, 64)
        self.worker_spin.setValue(8)
        self.worker_spin.setSuffix(" threads")
        worker_row.addWidget(self.worker_spin, 1)
        right_col.addLayout(worker_row)
        
        # Cache mode
        cache_row = QHBoxLayout()
        cache_row.addWidget(QLabel("Cache:"))
        
        self.cache_combo = QComboBox()
        self.cache_combo.addItems([
            "Use Cache (Fastest)",
            "Verify Cache", 
            "Ignore Cache"
        ])
        cache_row.addWidget(self.cache_combo, 1)
        right_col.addLayout(cache_row)
        
        grid.addLayout(right_col, 1)
        advanced_layout.addLayout(grid)
        
        # File type filter
        self.file_type_filter = FileTypeFilterWidget()
        advanced_layout.addWidget(self.file_type_filter)
        
        # Checkboxes
        checkboxes = QHBoxLayout()
        
        self.follow_symlinks = self._create_checkbox("Follow Symlinks")
        self.include_hidden = self._create_checkbox("Include Hidden Files")
        self.skip_system = self._create_checkbox("Skip System Folders")
        
        for cb in [self.follow_symlinks, self.include_hidden, self.skip_system]:
            checkboxes.addWidget(cb)
        
        checkboxes.addStretch()
        advanced_layout.addLayout(checkboxes)
        
        main_layout.addWidget(advanced_group)
        
        # 3. PERFORMANCE INDICATOR
        perf_frame = QFrame()
        perf_frame.setObjectName("PerformanceFrame")
        perf_layout = QHBoxLayout(perf_frame)
        perf_layout.setContentsMargins(12, 8, 12, 8)
        
        self.perf_indicator = QLabel("⚡ Performance: Optimal")
        self.perf_indicator.setStyleSheet("""
            QLabel {
                color: #10b981;
                font-weight: bold;
                font-size: 12px;
            }
        """)
        perf_layout.addWidget(self.perf_indicator)
        
        perf_layout.addStretch()
        
        self.estimated_time = QLabel("Estimated: < 1 min")
        self.estimated_time.setStyleSheet("color: #94a3b8; font-size: 11px;")
        perf_layout.addWidget(self.estimated_time)
        
        main_layout.addWidget(perf_frame)
        
        # Connect signals
        self._connect_signals()
    
    def _create_checkbox(self, text: str) -> QCheckBox:
        """Create a styled checkbox"""
        cb = QCheckBox(text)
        cb.setCursor(Qt.CursorShape.PointingHandCursor)
        cb.setStyleSheet("""
            QCheckBox {
                font-size: 12px;
                padding: 6px 8px;
                background: #1e293b;
                border: 1px solid #334155;
                border-radius: 6px;
            }
            QCheckBox:hover {
                background: #334155;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
            }
        """)
        return cb
    
    def _apply_styles(self):
        """Apply professional styles"""
        self.setStyleSheet("""
            ScanOptionsPanel {
                background: transparent;
            }
            QGroupBox {
                font-weight: bold;
                font-size: 14px;
                color: #f1f5f9;
                border: 2px solid #334155;
                border-radius: 8px;
                margin-top: 12px;
                padding-top: 8px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 6px;
            }
            #PresetsGroup {
                border-color: #3b82f6;
            }
            #AdvancedGroup {
                border-color: #10b981;
            }
            #PerformanceFrame {
                background: #1e293b;
                border: 1px solid #334155;
                border-radius: 8px;
            }
            QSpinBox, QComboBox {
                background: #1e293b;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 6px;
                color: #f1f5f9;
            }
            QSpinBox:hover, QComboBox:hover {
                border-color: #475569;
            }
            QSpinBox:focus, QComboBox:focus {
                border-color: #3b82f6;
            }
        """)
    
    def _connect_signals(self):
        """Connect all signals for real-time updates"""
        # Connect all inputs to config update
        inputs = [
            self.mode_combo, self.min_size_spin, self.hash_sample_combo,
            self.worker_spin, self.cache_combo, self.follow_symlinks,
            self.include_hidden, self.skip_system
        ]
        
        for widget in inputs:
            if isinstance(widget, QComboBox):
                widget.currentIndexChanged.connect(self._update_config)
            elif isinstance(widget, QSpinBox):
                widget.valueChanged.connect(self._update_config)
            elif isinstance(widget, QCheckBox):
                widget.stateChanged.connect(self._update_config)
        
        # Update performance indicator when config changes
        self.config_changed.connect(self._update_performance_indicator)
    
    def _apply_preset(self, preset_id: str):
        """Apply a preset configuration"""
        if preset_id not in self._preset_cards:
            return
        
        preset = next((p for p in self.PRESETS if p.id == preset_id), None)
        if not preset:
            return
        
        # Update current preset
        self._current_preset = preset_id
        
        # Update preset cards
        for pid, card in self._preset_cards.items():
            card.set_active(pid == preset_id)
        
        # Apply configuration (block signals temporarily)
        self._block_signals(True)
        
        config = preset.config
        
        # Mode (simplified mapping)
        mode = config.get("mode", "exact")
        if mode == "exact":
            self.mode_combo.setCurrentIndex(0)
        elif mode == "visual":
            self.mode_combo.setCurrentIndex(1)
        
        # Min size
        self.min_size_spin.setValue(config.get("min_size_kb", 100))
        
        # Hash sample (simplified mapping)
        hash_bytes = config.get("hash_bytes", 1024 * 4)
        if hash_bytes <= 1024 * 4:
            self.hash_sample_combo.setCurrentIndex(0)
        elif hash_bytes <= 1024 * 16:
            self.hash_sample_combo.setCurrentIndex(1)
        elif hash_bytes <= 1024 * 64:
            self.hash_sample_combo.setCurrentIndex(2)
        else:
            self.hash_sample_combo.setCurrentIndex(3)
        
        # Workers
        self.worker_spin.setValue(config.get("max_workers", 8))
        
        # Checkboxes
        self.follow_symlinks.setChecked(config.get("follow_symlinks", False))
        self.include_hidden.setChecked(config.get("include_hidden", False))
        self.skip_system.setChecked(True)  # Default for safety
        
        # File types (if specified in preset)
        if "file_types" in config:
            # This would require enhancing FileTypeFilterWidget
            pass
        
        self._block_signals(False)
        
        # Emit signals
        self.preset_applied.emit(preset_id)
        self._update_config()
    
    def _block_signals(self, block: bool):
        """Block/unblock all input signals"""
        widgets = [
            self.mode_combo, self.min_size_spin, self.hash_sample_combo,
            self.worker_spin, self.cache_combo, self.follow_symlinks,
            self.include_hidden, self.skip_system
        ]
        
        for widget in widgets:
            widget.blockSignals(block)
    
    def _update_config(self):
        """Update configuration and emit signal"""
        config = self.get_config_dict()
        self.config_changed.emit(config)
    
    def _update_performance_indicator(self, config: dict):
        """Update performance indicator based on configuration"""
        # Simple performance estimation
        workers = config.get("max_workers", 8)
        hash_sample = config.get("hash_sample", "Fast (4KB)")
        fast_mode = config.get("fast_mode", True)
        
        # Calculate performance score
        score = 0
        if workers >= 8:
            score += 2
        elif workers >= 4:
            score += 1
        
        if hash_sample == "Fast (4KB)":
            score += 2
        elif hash_sample == "Balanced (16KB)":
            score += 1
        
        if fast_mode:
            score += 2
        
        # Update indicator
        if score >= 5:
            self.perf_indicator.setText("⚡ Performance: Optimal")
            self.perf_indicator.setStyleSheet("color: #10b981; font-weight: bold;")
            self.estimated_time.setText("Estimated: < 1 min")
        elif score >= 3:
            self.perf_indicator.setText("⚡ Performance: Balanced")
            self.perf_indicator.setStyleSheet("color: #f59e0b; font-weight: bold;")
            self.estimated_time.setText("Estimated: 1-5 min")
        else:
            self.perf_indicator.setText("⚡ Performance: Thorough")
            self.perf_indicator.setStyleSheet("color: #ef4444; font-weight: bold;")
            self.estimated_time.setText("Estimated: 5+ min")
    
    def get_config_dict(self) -> dict:
        """Get current configuration as dictionary"""
        # Parse hash sample selection
        hash_sample_text = self.hash_sample_combo.currentText()
        hash_bytes_mapping = {
            "Fast (4KB)": 1024 * 4,
            "Balanced (16KB)": 1024 * 16,
            "Accurate (64KB)": 1024 * 64,
            "Full File (Exact)": 0  # 0 means full file
        }
        
        # Parse mode
        mode_text = self.mode_combo.currentText()
        mode_mapping = {
            "Exact Match (MD5/SHA)": "exact",
            "Visual Similarity (Perceptual Hash)": "visual",
            "Fuzzy Match (Content-aware)": "fuzzy"
        }
        
        config = {
            "mode": mode_mapping.get(mode_text, "exact"),
            "min_size_bytes": self.min_size_spin.value() * 1024,
            "hash_bytes": hash_bytes_mapping.get(hash_sample_text, 1024 * 4),
            "max_workers": self.worker_spin.value(),
            "follow_symlinks": self.follow_symlinks.isChecked(),
            "include_hidden": self.include_hidden.isChecked(),
            "skip_system_folders": self.skip_system.isChecked(),
            "cache_mode": self.cache_combo.currentIndex(),  # 0=use, 1=verify, 2=ignore
            "file_types": self.file_type_filter.get_selected_extensions(),
            "fast_mode": True,  # Always enabled in new UI
        }
        
        return config
    
    def set_scanning(self, scanning: bool):
        """Update UI state during scanning"""
        # Disable all inputs while scanning
        widgets = [
            self.mode_combo, self.min_size_spin, self.hash_sample_combo,
            self.worker_spin, self.cache_combo, self.follow_symlinks,
            self.include_hidden, self.skip_system
        ]
        
        for widget in widgets:
            widget.setEnabled(not scanning)
        
        # Update performance indicator
        if scanning:
            self.perf_indicator.setText("🔍 Scanning in progress...")
            self.perf_indicator.setStyleSheet("color: #3b82f6; font-weight: bold;")
            self.estimated_time.setText("Processing...")
        else:
            self._update_performance_indicator(self.get_config_dict())
    
    def save_as_preset(self, name: str, description: str = "") -> str:
        """Save current configuration as a custom preset"""
        preset_id = f"custom_{name.lower().replace(' ', '_')}"
        
        preset = ScanPreset(
            id=preset_id,
            name=name,
            icon="💾",
            description=description or f"Custom preset: {name}",
            config=self.get_config_dict(),
            performance_impact="medium"
        )
        
        # TODO: Save to disk and add to UI
        return preset_id


# Quick test
if __name__ == "__main__":
    import sys
    from PySide6.QtWidgets import QApplication, QMainWindow
    
    app = QApplication(sys.argv)
    window = QMainWindow()
    
    panel = ScanOptionsPanel()
    window.setCentralWidget(panel)
    window.resize(600, 800)
    window.setStyleSheet("background-color: #0b1120;")
    window.show()
    
    sys.exit(app.exec())