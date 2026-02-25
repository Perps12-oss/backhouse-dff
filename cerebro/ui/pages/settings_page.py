# cerebro/ui/pages/settings_page.py
"""
Settings Page - Comprehensive Application Configuration

This module provides a centralized settings interface for all application
configuration including scan options, exclusions, performance tuning,
and UI preferences.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from cerebro.ui.components.modern import ContentCard, PageHeader, PageScaffold, SidebarNav, SidebarNavItem
from cerebro.ui.components.modern._tokens import token as theme_token
from cerebro.ui.pages.base_station import BaseStation
from cerebro.ui.state_bus import get_state_bus
from cerebro.ui.widgets.scan_options_panel import ScanOptionsPanel


# ============================================================================
# Constants
# ============================================================================

# Page layout
PAGE_MARGIN = 18
PAGE_SPACING = 12
CARD_PADDING = 14
CARD_SPACING = 10
GROUP_SPACING = 8
GRID_SPACING = 12

# Border radius
CARD_BORDER_RADIUS = 16
BUTTON_BORDER_RADIUS = 14
INPUT_BORDER_RADIUS = 12

# Notification durations
NOTIFY_SAVE_SUCCESS = 2000
NOTIFY_LOAD_ERROR = 3000

# Default values
DEFAULT_MIN_FILE_SIZE = 0
DEFAULT_MAX_FILE_SIZE = 0
DEFAULT_MIN_DUPLICATES = 2
DEFAULT_THREAD_COUNT = 4
DEFAULT_CHUNK_SIZE = 8192

# Limits
MAX_THREAD_COUNT = 32
MAX_CHUNK_SIZE_KB = 65536


# ============================================================================
# Enums
# ============================================================================

class ScanMode(Enum):
    """Available scan modes"""
    STANDARD = "standard"
    FAST = "fast"
    THOROUGH = "thorough"
    
    @property
    def display_name(self) -> str:
        """Human-readable display name"""
        return self.value.capitalize()


class HashAlgorithm(Enum):
    """Available hashing algorithms"""
    MD5 = "md5"
    SHA1 = "sha1"
    SHA256 = "sha256"
    XXHASH = "xxhash"
    
    @property
    def display_name(self) -> str:
        """Human-readable display name"""
        names = {
            "md5": "MD5 (Fast)",
            "sha1": "SHA-1",
            "sha256": "SHA-256 (Secure)",
            "xxhash": "xxHash (Fastest)"
        }
        return names.get(self.value, self.value.upper())


# ============================================================================
# Data Classes
# ============================================================================

@dataclass
class ScanSettings:
    """Scan-related settings"""
    mode: str = ScanMode.STANDARD.value
    hash_algorithm: str = HashAlgorithm.SHA256.value
    min_file_size: int = DEFAULT_MIN_FILE_SIZE
    max_file_size: int = DEFAULT_MAX_FILE_SIZE
    min_duplicates: int = DEFAULT_MIN_DUPLICATES
    follow_symlinks: bool = False
    check_hidden_files: bool = False
    check_system_files: bool = False


@dataclass
class PerformanceSettings:
    """Performance-related settings"""
    thread_count: int = DEFAULT_THREAD_COUNT
    chunk_size_kb: int = DEFAULT_CHUNK_SIZE // 1024
    enable_caching: bool = True
    memory_limit_mb: int = 0  # 0 = unlimited


@dataclass
class UISettings:
    """UI-related settings"""
    excluded_dirs: list[str] = field(default_factory=list)
    auto_open_results: bool = True
    show_notifications: bool = True
    dark_mode: bool = True


@dataclass
class AppConfig:
    """Complete application configuration"""
    scan: ScanSettings = field(default_factory=ScanSettings)
    performance: PerformanceSettings = field(default_factory=PerformanceSettings)
    ui: UISettings = field(default_factory=UISettings)


# ============================================================================
# Utility Functions
# ============================================================================

def parse_excluded_dirs(text: str) -> list[str]:
    """
    Parse comma-separated excluded directories.
    
    Args:
        text: Comma-separated directory list
        
    Returns:
        List of cleaned directory paths
    """
    return [
        s.strip()
        for s in text.split(",")
        if s.strip()
    ]


def format_excluded_dirs(dirs: list[str]) -> str:
    """
    Format excluded directories as comma-separated string.
    
    Args:
        dirs: List of directory paths
        
    Returns:
        Comma-separated string
    """
    return ", ".join(str(d) for d in dirs)


def validate_positive_int(value: int, default: int = 0) -> int:
    """
    Validate and constrain integer to positive values.
    
    Args:
        value: Value to validate
        default: Default value if invalid
        
    Returns:
        Valid positive integer
    """
    try:
        val = int(value)
        return max(0, val)
    except (ValueError, TypeError):
        return default


# ============================================================================
# Settings Groups
# ============================================================================

class ScanSettingsGroup(QGroupBox):
    """Group box for scan-related settings"""
    
    def __init__(self, parent: Optional[QWidget] = None):
        """
        Initialize scan settings group.
        
        Args:
            parent: Parent widget
        """
        super().__init__("🔍 Scan Settings", parent)
        self._build_ui()
    
    def _build_ui(self) -> None:
        """Build the group UI"""
        layout = QGridLayout(self)
        layout.setSpacing(GRID_SPACING)
        layout.setContentsMargins(CARD_PADDING, CARD_PADDING, CARD_PADDING, CARD_PADDING)
        
        row = 0
        
        # Scan mode
        layout.addWidget(QLabel("Scan Mode:"), row, 0)
        self._mode = QComboBox()
        for mode in ScanMode:
            self._mode.addItem(mode.display_name, mode.value)
        layout.addWidget(self._mode, row, 1)
        row += 1
        
        # Hash algorithm
        layout.addWidget(QLabel("Hash Algorithm:"), row, 0)
        self._hash = QComboBox()
        for algo in HashAlgorithm:
            self._hash.addItem(algo.display_name, algo.value)
        layout.addWidget(self._hash, row, 1)
        row += 1
        
        # Min file size
        layout.addWidget(QLabel("Min File Size (bytes):"), row, 0)
        self._min_size = QSpinBox()
        self._min_size.setRange(0, 2**31 - 1)
        self._min_size.setSuffix(" bytes")
        self._min_size.setToolTip("Ignore files smaller than this size (0 = no limit)")
        layout.addWidget(self._min_size, row, 1)
        row += 1
        
        # Max file size
        layout.addWidget(QLabel("Max File Size (bytes):"), row, 0)
        self._max_size = QSpinBox()
        self._max_size.setRange(0, 2**31 - 1)
        self._max_size.setSuffix(" bytes")
        self._max_size.setToolTip("Ignore files larger than this size (0 = no limit)")
        layout.addWidget(self._max_size, row, 1)
        row += 1
        
        # Min duplicates
        layout.addWidget(QLabel("Min Duplicate Count:"), row, 0)
        self._min_dupes = QSpinBox()
        self._min_dupes.setRange(2, 1000)
        self._min_dupes.setToolTip("Minimum number of duplicates to report")
        layout.addWidget(self._min_dupes, row, 1)
        row += 1
        
        # Follow symlinks
        self._follow_symlinks = QCheckBox("Follow symbolic links")
        self._follow_symlinks.setToolTip("Follow symlinks during scan (may cause loops)")
        layout.addWidget(self._follow_symlinks, row, 0, 1, 2)
        row += 1
        
        # Check hidden files
        self._check_hidden = QCheckBox("Include hidden files")
        self._check_hidden.setToolTip("Scan hidden files and folders")
        layout.addWidget(self._check_hidden, row, 0, 1, 2)
        row += 1
        
        # Check system files
        self._check_system = QCheckBox("Include system files")
        self._check_system.setToolTip("Scan system files (use with caution)")
        layout.addWidget(self._check_system, row, 0, 1, 2)
    
    def load(self, settings: ScanSettings) -> None:
        """
        Load settings into UI.
        
        Args:
            settings: Scan settings to load
        """
        # Set mode
        index = self._mode.findData(settings.mode)
        if index >= 0:
            self._mode.setCurrentIndex(index)
        
        # Set hash algorithm
        index = self._hash.findData(settings.hash_algorithm)
        if index >= 0:
            self._hash.setCurrentIndex(index)
        
        # Set numeric values
        self._min_size.setValue(settings.min_file_size)
        self._max_size.setValue(settings.max_file_size)
        self._min_dupes.setValue(settings.min_duplicates)
        
        # Set checkboxes
        self._follow_symlinks.setChecked(settings.follow_symlinks)
        self._check_hidden.setChecked(settings.check_hidden_files)
        self._check_system.setChecked(settings.check_system_files)
    
    def save(self) -> ScanSettings:
        """
        Save current UI values to settings.
        
        Returns:
            Current scan settings
        """
        return ScanSettings(
            mode=self._mode.currentData() or ScanMode.STANDARD.value,
            hash_algorithm=self._hash.currentData() or HashAlgorithm.SHA256.value,
            min_file_size=self._min_size.value(),
            max_file_size=self._max_size.value(),
            min_duplicates=self._min_dupes.value(),
            follow_symlinks=self._follow_symlinks.isChecked(),
            check_hidden_files=self._check_hidden.isChecked(),
            check_system_files=self._check_system.isChecked()
        )


class PerformanceSettingsGroup(QGroupBox):
    """Group box for performance-related settings"""
    
    def __init__(self, parent: Optional[QWidget] = None):
        """
        Initialize performance settings group.
        
        Args:
            parent: Parent widget
        """
        super().__init__("⚡ Performance Settings", parent)
        self._build_ui()
    
    def _build_ui(self) -> None:
        """Build the group UI"""
        layout = QGridLayout(self)
        layout.setSpacing(GRID_SPACING)
        layout.setContentsMargins(CARD_PADDING, CARD_PADDING, CARD_PADDING, CARD_PADDING)
        
        row = 0
        
        # Thread count
        layout.addWidget(QLabel("Thread Count:"), row, 0)
        self._threads = QSpinBox()
        self._threads.setRange(1, MAX_THREAD_COUNT)
        self._threads.setToolTip("Number of parallel threads (higher = faster but more CPU)")
        layout.addWidget(self._threads, row, 1)
        row += 1
        
        # Chunk size
        layout.addWidget(QLabel("Read Chunk Size (KB):"), row, 0)
        self._chunk_size = QSpinBox()
        self._chunk_size.setRange(1, MAX_CHUNK_SIZE_KB)
        self._chunk_size.setSuffix(" KB")
        self._chunk_size.setToolTip("Size of file chunks to read at once")
        layout.addWidget(self._chunk_size, row, 1)
        row += 1
        
        # Memory limit
        layout.addWidget(QLabel("Memory Limit (MB):"), row, 0)
        self._memory_limit = QSpinBox()
        self._memory_limit.setRange(0, 16384)
        self._memory_limit.setSuffix(" MB")
        self._memory_limit.setToolTip("Maximum memory usage (0 = unlimited)")
        layout.addWidget(self._memory_limit, row, 1)
        row += 1
        
        # Enable caching
        self._enable_cache = QCheckBox("Enable result caching")
        self._enable_cache.setToolTip("Cache scan results for faster subsequent scans")
        layout.addWidget(self._enable_cache, row, 0, 1, 2)
    
    def load(self, settings: PerformanceSettings) -> None:
        """
        Load settings into UI.
        
        Args:
            settings: Performance settings to load
        """
        self._threads.setValue(settings.thread_count)
        self._chunk_size.setValue(settings.chunk_size_kb)
        self._memory_limit.setValue(settings.memory_limit_mb)
        self._enable_cache.setChecked(settings.enable_caching)
    
    def save(self) -> PerformanceSettings:
        """
        Save current UI values to settings.
        
        Returns:
            Current performance settings
        """
        return PerformanceSettings(
            thread_count=self._threads.value(),
            chunk_size_kb=self._chunk_size.value(),
            enable_caching=self._enable_cache.isChecked(),
            memory_limit_mb=self._memory_limit.value()
        )


class UISettingsGroup(QGroupBox):
    """Group box for UI-related settings"""
    
    def __init__(self, parent: Optional[QWidget] = None):
        """
        Initialize UI settings group.
        
        Args:
            parent: Parent widget
        """
        super().__init__("🎨 Interface Settings", parent)
        self._build_ui()
    
    def _build_ui(self) -> None:
        """Build the group UI"""
        layout = QVBoxLayout(self)
        layout.setSpacing(GROUP_SPACING)
        layout.setContentsMargins(CARD_PADDING, CARD_PADDING, CARD_PADDING, CARD_PADDING)
        
        # Excluded directories
        dir_label = QLabel("Excluded Directories:")
        dir_label.setToolTip("Comma-separated list of directories to ignore")
        layout.addWidget(dir_label)
        
        self._excluded = QLineEdit()
        self._excluded.setPlaceholderText(
            r"e.g. C:\Windows, C:\Program Files, .git, node_modules"
        )
        layout.addWidget(self._excluded)
        
        # Auto-open results
        self._auto_open = QCheckBox("Auto-open results in Review page")
        self._auto_open.setToolTip("Automatically switch to Review page after scan")
        layout.addWidget(self._auto_open)
        
        # Show notifications
        self._show_notifs = QCheckBox("Show scan notifications")
        self._show_notifs.setToolTip("Display toast notifications for scan events")
        layout.addWidget(self._show_notifs)
        
        # Dark mode
        self._dark_mode = QCheckBox("Dark mode")
        self._dark_mode.setToolTip("Use dark color scheme (requires restart)")
        layout.addWidget(self._dark_mode)
    
    def load(self, settings: UISettings) -> None:
        """
        Load settings into UI.
        
        Args:
            settings: UI settings to load
        """
        self._excluded.setText(format_excluded_dirs(settings.excluded_dirs))
        self._auto_open.setChecked(settings.auto_open_results)
        self._show_notifs.setChecked(settings.show_notifications)
        self._dark_mode.setChecked(settings.dark_mode)
    
    def save(self) -> UISettings:
        """
        Save current UI values to settings.
        
        Returns:
            Current UI settings
        """
        return UISettings(
            excluded_dirs=parse_excluded_dirs(self._excluded.text()),
            auto_open_results=self._auto_open.isChecked(),
            show_notifications=self._show_notifs.isChecked(),
            dark_mode=self._dark_mode.isChecked()
        )


# ============================================================================
# Main Settings Page
# ============================================================================

class SettingsPage(BaseStation):
    """
    Comprehensive settings page for application configuration.
    
    Provides organized settings for:
    - Scan behavior and options
    - Performance tuning
    - UI preferences
    - Directory exclusions
    
    Settings are persisted via cerebro.services.config module.
    
    Attributes:
        station_id: Unique identifier for navigation
        station_title: Display title in navigation
    """
    
    station_id = "settings"
    station_title = "Settings"

    def __init__(self, parent: Optional[QWidget] = None):
        """
        Initialize settings page.
        
        Args:
            parent: Parent widget
        """
        super().__init__(parent)
        
        self._bus = get_state_bus()
        self._config = AppConfig()
        
        self._build_ui()
        self._load_settings()
    
    # ========================================================================
    # UI Construction
    # ========================================================================
    
    def _build_ui(self) -> None:
        """Build the main UI layout with PageScaffold and SidebarNav."""
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._scaffold = PageScaffold(self, show_sidebar=True, show_sticky_action=False)
        root.addWidget(self._scaffold)

        self._header = PageHeader("Settings", "Configure scan behavior, performance, and UI preferences.")
        self._scaffold.set_header(self._header)

        nav_items = [
            SidebarNavItem("general", "🎨", "General", 0),
            SidebarNavItem("scanning", "🔍", "Scanning", 0),
            SidebarNavItem("cleanup", "🗑️", "Cleanup", 0),
            SidebarNavItem("performance", "⚡", "Performance", 0),
            SidebarNavItem("advanced", "🔧", "Advanced", 0),
        ]
        self._sidebar = SidebarNav(nav_items)
        self._sidebar.item_clicked.connect(self._on_nav_clicked)
        self._sidebar.set_active("general")
        self._scaffold.set_sidebar(self._sidebar)

        self._scan_group = ScanSettingsGroup()
        self._perf_group = PerformanceSettingsGroup()
        self._ui_group = UISettingsGroup()
        self._scan_options_panel = ScanOptionsPanel()
        self._scan_options_panel.config_changed.connect(self._on_scan_options_changed)
        self._bus.set_scan_options(self._scan_options_panel.get_config_dict())
        self._style_groups()

        general_card = ContentCard()
        general_card.set_content(self._ui_group)
        scanning_card = ContentCard()
        scan_scroll = QScrollArea()
        scan_scroll.setWidgetResizable(True)
        scan_scroll.setFrameShape(QFrame.Shape.NoFrame)
        scan_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        scan_scroll.setWidget(self._scan_options_panel)
        scanning_card.set_content(scan_scroll)
        cleanup_placeholder = QLabel("Cleanup options (e.g. default trash vs permanent) can be added here.")
        cleanup_placeholder.setWordWrap(True)
        cleanup_card = ContentCard()
        cleanup_card.set_content(cleanup_placeholder)
        performance_card = ContentCard()
        performance_card.set_content(self._perf_group)
        advanced_placeholder = QLabel("Advanced options (e.g. debug logging, paths) can be added here.")
        advanced_placeholder.setWordWrap(True)
        advanced_card = ContentCard()
        advanced_card.set_content(advanced_placeholder)

        self._stack = QStackedWidget()
        self._stack.addWidget(general_card)
        self._stack.addWidget(scanning_card)
        self._stack.addWidget(cleanup_card)
        self._stack.addWidget(performance_card)
        self._stack.addWidget(advanced_card)

        content_wrap = QWidget()
        content_layout = QVBoxLayout(content_wrap)
        content_layout.setContentsMargins(PAGE_MARGIN, PAGE_MARGIN, PAGE_MARGIN, PAGE_MARGIN)
        content_layout.addWidget(self._stack, 1)
        content_layout.addLayout(self._create_actions())
        self._scaffold.set_content(content_wrap)

        self._nav_to_index = {"general": 0, "scanning": 1, "cleanup": 2, "performance": 3, "advanced": 4}

    def _on_nav_clicked(self, item_id: str) -> None:
        idx = self._nav_to_index.get(item_id, 0)
        self._stack.setCurrentIndex(idx)
        self._sidebar.set_active(item_id)

    @Slot(dict)
    def _on_scan_options_changed(self, options: dict) -> None:
        """Sync scan options to StateBus so Scan page uses them."""
        self._bus.set_scan_options(options or {})

    def _style_groups(self) -> None:
        panel = theme_token("panel")
        line = theme_token("line")
        for group in (self._scan_group, self._perf_group, self._ui_group):
            group.setStyleSheet(f"""
                QGroupBox {{
                    background: {panel};
                    border: 1px solid {line};
                    border-radius: {CARD_BORDER_RADIUS}px;
                    font-weight: bold;
                    font-size: 14px;
                    padding-top: 16px;
                    margin-top: 8px;
                }}
                QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 8px; }}
                QLineEdit {{ border-radius: {INPUT_BORDER_RADIUS}px; padding: 8px 10px; }}
                QSpinBox {{ border-radius: {INPUT_BORDER_RADIUS}px; padding: 6px 8px; }}
                QComboBox {{ border-radius: {INPUT_BORDER_RADIUS}px; padding: 6px 8px; }}
            """)

    def _create_actions(self) -> QHBoxLayout:
        """Create action buttons layout"""
        layout = QHBoxLayout()
        layout.setSpacing(CARD_SPACING)
        
        layout.addStretch()
        
        # Reset button
        self._reset_btn = QPushButton("↩ Reset")
        self._reset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._reset_btn.setToolTip("Reload settings from disk")
        self._reset_btn.clicked.connect(self._load_settings)
        self._style_button(self._reset_btn, primary=False)
        layout.addWidget(self._reset_btn)
        
        # Save button
        self._save_btn = QPushButton("💾 Save")
        self._save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._save_btn.setToolTip("Save all settings to disk")
        self._save_btn.clicked.connect(self._save_settings)
        self._style_button(self._save_btn, primary=True)
        layout.addWidget(self._save_btn)
        
        return layout
    
    def _style_button(self, button: QPushButton, primary: bool = False) -> None:
        accent = theme_token("accent")
        line = theme_token("line")
        text = theme_token("text")
        panel = theme_token("panel")
        if primary:
            button.setStyleSheet(f"""
                QPushButton {{
                    border-radius: {BUTTON_BORDER_RADIUS}px;
                    padding: 10px 18px;
                    background: {panel};
                    border: 1px solid {accent};
                    color: {accent};
                    font-weight: 600;
                }}
                QPushButton:hover {{ border-color: {accent}; }}
            """)
        else:
            button.setStyleSheet(f"""
                QPushButton {{
                    border-radius: {BUTTON_BORDER_RADIUS}px;
                    padding: 10px 18px;
                    background: {panel};
                    border: 1px solid {line};
                    color: {text};
                }}
                QPushButton:hover {{ border-color: {accent}; }}
            """)
    
    # ========================================================================
    # Settings Persistence
    # ========================================================================
    
    @Slot()
    def _load_settings(self) -> None:
        """Load settings from configuration file"""
        try:
            # Import config module
            from cerebro.services.config import load_config  # type: ignore
            
            config = load_config()
            
            # Load scan settings
            if hasattr(config, 'scan'):
                scan_cfg = config.scan
                self._config.scan = ScanSettings(
                    mode=getattr(scan_cfg, 'mode', ScanMode.STANDARD.value),
                    hash_algorithm=getattr(scan_cfg, 'hash_algorithm', HashAlgorithm.SHA256.value),
                    min_file_size=getattr(scan_cfg, 'min_file_size', DEFAULT_MIN_FILE_SIZE),
                    max_file_size=getattr(scan_cfg, 'max_file_size', DEFAULT_MAX_FILE_SIZE),
                    min_duplicates=getattr(scan_cfg, 'min_duplicates', DEFAULT_MIN_DUPLICATES),
                    follow_symlinks=getattr(scan_cfg, 'follow_symlinks', False),
                    check_hidden_files=getattr(scan_cfg, 'check_hidden_files', False),
                    check_system_files=getattr(scan_cfg, 'check_system_files', False)
                )
            
            # Load performance settings
            if hasattr(config, 'performance'):
                perf_cfg = config.performance
                self._config.performance = PerformanceSettings(
                    thread_count=getattr(perf_cfg, 'thread_count', DEFAULT_THREAD_COUNT),
                    chunk_size_kb=getattr(perf_cfg, 'chunk_size_kb', DEFAULT_CHUNK_SIZE // 1024),
                    enable_caching=getattr(perf_cfg, 'enable_caching', True),
                    memory_limit_mb=getattr(perf_cfg, 'memory_limit_mb', 0)
                )
            
            # Load UI settings
            if hasattr(config, 'ui'):
                ui_cfg = config.ui
                excluded = getattr(ui_cfg, 'excluded_dirs', [])
                if isinstance(excluded, (list, tuple)):
                    excluded = list(map(str, excluded))
                else:
                    excluded = []
                
                self._config.ui = UISettings(
                    excluded_dirs=excluded,
                    auto_open_results=getattr(ui_cfg, 'auto_open_results', True),
                    show_notifications=getattr(ui_cfg, 'show_notifications', True),
                    dark_mode=getattr(ui_cfg, 'dark_mode', True)
                )
            
            # Update UI
            self._scan_group.load(self._config.scan)
            self._perf_group.load(self._config.performance)
            self._ui_group.load(self._config.ui)
            
        except Exception as e:
            # Don't crash on load failure, use defaults
            self._scan_group.load(ScanSettings())
            self._perf_group.load(PerformanceSettings())
            self._ui_group.load(UISettings())
    
    @Slot()
    def _save_settings(self) -> None:
        """Save current settings to configuration file"""
        try:
            # Collect settings from UI
            self._config.scan = self._scan_group.save()
            self._config.performance = self._perf_group.save()
            self._config.ui = self._ui_group.save()
            
            # Import config module
            from cerebro.services.config import load_config, save_config  # type: ignore
            
            config = load_config()
            
            # Update config object
            if hasattr(config, 'scan'):
                scan_cfg = config.scan
                for key, value in vars(self._config.scan).items():
                    setattr(scan_cfg, key, value)
            
            if hasattr(config, 'performance'):
                perf_cfg = config.performance
                for key, value in vars(self._config.performance).items():
                    setattr(perf_cfg, key, value)
            
            if hasattr(config, 'ui'):
                ui_cfg = config.ui
                for key, value in vars(self._config.ui).items():
                    setattr(ui_cfg, key, value)
            
            # Save to disk
            save_config(config)
            
            self._bus.notify(
                "Settings saved",
                "Configuration updated successfully.",
                NOTIFY_SAVE_SUCCESS
            )
            
        except Exception as e:
            QMessageBox.warning(
                self,
                "Save failed",
                f"Could not save configuration:\n\n{e}"
            )

    def reset(self) -> None:
        """Clear internal state; no workers."""
        pass

    def reset_for_new_scan(self) -> None:
        """No scan-specific state."""
        pass
