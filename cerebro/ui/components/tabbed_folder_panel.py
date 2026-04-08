# cerebro/ui/components/tabbed_folder_panel.py
"""
Tabbed Folder Panel Component

2-tab layout (Scan Folders / Protect Folders) to eliminate cramped sections.
Addresses User Wants W-12, W-16, W-23 and improves Ashisoft parity.

R-05: Rewrite left panel as 2-tab layout
"""
from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from cerebro.ui.components.modern.folder_picker import ModernFolderPicker
from cerebro.ui.components.modern._tokens import SPACE_UNIT, RADIUS_MD, token


class TabbedFolderPanel(QFrame):
    """
    2-tab folder panel for Scan Folders and Protect Folders.

    Replaces the previous 3-section cramped layout with a clean tabbed interface
    that matches Ashisoft parity and addresses user complaints about cramped UI.
    """

    # Signals
    scan_folders_changed = Signal(list)  # List of scan folder paths
    protect_folders_changed = Signal(list)  # List of protect folder paths

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("TabbedFolderPanel")

        # Folder lists
        self._scan_folders: List[str] = []
        self._protect_folders: List[str] = []

        # Build UI
        self._build_ui()
        self._apply_theme()

    def _build_ui(self) -> None:
        """Build the 2-tab folder panel."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE_UNIT)

        # Create tab widget
        self._tabs = QTabWidget()
        self._tabs.setObjectName("FolderPanelTabs")

        # Create tabs
        self._scan_tab = self._create_scan_tab()
        self._protect_tab = self._create_protect_tab()

        self._tabs.addTab(self._scan_tab, "Scan Folders")
        self._tabs.addTab(self._protect_tab, "Protect Folders")

        layout.addWidget(self._tabs)

        # Add scan button
        self._scan_button = QPushButton("Start Scan")
        self._scan_button.setObjectName("FolderPanelScanButton")
        self._scan_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._scan_button.clicked.connect(self._on_scan_clicked)

        button_layout = QHBoxLayout()
        button_layout.setContentsMargins(SPACE_UNIT * 2, SPACE_UNIT * 2, SPACE_UNIT * 2, SPACE_UNIT * 2)
        button_layout.addWidget(self._scan_button)

        layout.addLayout(button_layout)

    def _create_scan_tab(self) -> QWidget:
        """Create the Scan Folders tab."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(SPACE_UNIT * 2, SPACE_UNIT * 2, SPACE_UNIT * 2, SPACE_UNIT * 2)
        layout.setSpacing(SPACE_UNIT * 2)

        # Scan folder picker
        self._scan_picker = ModernFolderPicker()
        self._scan_picker.path_changed.connect(self._on_scan_folder_changed)
        layout.addWidget(self._scan_picker)

        # Scan folders list
        self._scan_folders_label = QLabel("Scan Folders:")
        layout.addWidget(self._scan_folders_label)

        self._scan_folders_list = QLabel("No folders selected")
        self._scan_folders_list.setObjectName("FolderListLabel")
        layout.addWidget(self._scan_folders_list)

        layout.addStretch()
        return tab

    def _create_protect_tab(self) -> QWidget:
        """Create the Protect Folders tab."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(SPACE_UNIT * 2, SPACE_UNIT * 2, SPACE_UNIT * 2, SPACE_UNIT * 2)
        layout.setSpacing(SPACE_UNIT * 2)

        # Protect folder picker
        self._protect_picker = ModernFolderPicker()
        self._protect_picker.path_changed.connect(self._on_protect_folder_changed)
        layout.addWidget(self._protect_picker)

        # Protect folders list
        self._protect_folders_label = QLabel("Protect Folders:")
        layout.addWidget(self._protect_folders_label)

        self._protect_folders_list = QLabel("No folders protected")
        self._protect_folders_list.setObjectName("FolderListLabel")
        layout.addWidget(self._protect_folders_list)

        layout.addStretch()
        return tab

    def _on_scan_folder_changed(self, path: str) -> None:
        """Handle scan folder path change."""
        if path and path not in self._scan_folders:
            self._scan_folders.append(path)
            self._update_scan_folders_display()
            self.scan_folders_changed.emit(self._scan_folders)

    def _on_protect_folder_changed(self, path: str) -> None:
        """Handle protect folder path change."""
        if path and path not in self._protect_folders:
            self._protect_folders.append(path)
            self._update_protect_folders_display()
            self.protect_folders_changed.emit(self._protect_folders)

    def _update_scan_folders_display(self) -> None:
        """Update the scan folders list display."""
        if not self._scan_folders:
            self._scan_folders_list.setText("No folders selected")
        else:
            text = "\n".join(f"• {folder}" for folder in self._scan_folders)
            self._scan_folders_list.setText(text)

    def _update_protect_folders_display(self) -> None:
        """Update the protect folders list display."""
        if not self._protect_folders:
            self._protect_folders_list.setText("No folders protected")
        else:
            text = "\n".join(f"🔒 {folder}" for folder in self._protect_folders)
            self._protect_folders_list.setText(text)

    def _on_scan_clicked(self) -> None:
        """Handle scan button click."""
        # Signal will be connected by parent
        pass

    def get_scan_folders(self) -> List[str]:
        """Return list of scan folders."""
        return self._scan_folders.copy()

    def get_protect_folders(self) -> List[str]:
        """Return list of protect folders."""
        return self._protect_folders.copy()

    def clear_scan_folders(self) -> None:
        """Clear all scan folders."""
        self._scan_folders.clear()
        self._update_scan_folders_display()
        self.scan_folders_changed.emit(self._scan_folders)

    def clear_protect_folders(self) -> None:
        """Clear all protect folders."""
        self._protect_folders.clear()
        self._update_protect_folders_display()
        self.protect_folders_changed.emit(self._protect_folders)

    def _apply_theme(self) -> None:
        """Apply theme styling."""
        panel = token("panel")
        line = token("line")
        accent = token("accent")
        text = token("text")
        hover = token("hover_bg")

        self.setStyleSheet(f"""
            TabbedFolderPanel {{
                background: {panel};
                border: 1px solid {line};
                border-radius: {RADIUS_MD}px;
            }}
            QTabWidget#FolderPanelTabs::pane {{
                border: 1px solid {line};
                border-radius: {RADIUS_MD}px;
                background: {panel};
            }}
            QTabWidget#FolderPanelTabs::tab-bar {{
                left: 5px;
            }}
            QTabWidget#FolderPanelTabs::tab {{
                background: {panel};
                color: {text};
                padding: {SPACE_UNIT * 2}px;
                border: 1px solid {line};
                border-bottom-left-radius: 0px;
                border-bottom-right-radius: 0px;
                min-width: 120px;
            }}
            QTabWidget#FolderPanelTabs::tab:selected {{
                background: {accent};
                color: white;
                border-bottom: 1px solid {accent};
            }}
            QTabWidget#FolderPanelTabs::tab:hover:!selected {{
                background: {hover};
            }}
            QPushButton#FolderPanelScanButton {{
                background: {accent};
                color: white;
                border: none;
                border-radius: {RADIUS_MD}px;
                padding: {SPACE_UNIT * 2}px;
                font-weight: bold;
            }}
            QPushButton#FolderPanelScanButton:hover {{
                background: {hover};
            }}
            QLabel#FolderListLabel {{
                color: {text};
                background: transparent;
                padding: {SPACE_UNIT}px;
            }}
        """)


# Backward compatibility alias
FolderPanel = TabbedFolderPanel