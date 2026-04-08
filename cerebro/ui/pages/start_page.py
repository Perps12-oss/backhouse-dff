from pathlib import Path
from PySide6.QtCore import Qt, Signal, QMimeData
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame, QListWidget,
    QListWidgetItem, QToolButton, QScrollArea
)
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from cerebro.ui.pages.base_station import BaseStation
from cerebro.ui.theme_engine import ThemeEngine
from cerebro.ui.state_bus import get_state_bus
from cerebro.ui.ui_state import load_locations, save_locations, load_sidebar_collapsed, save_sidebar_collapsed
from dataclasses import dataclass, field
from typing import List, Optional

@dataclass
class StartScanConfig:
    """Backward-compatible config expected by StationNavigator/pages package.

    Keep this minimal; ScanPage/Controller can expand it later.
    """
    roots: List[str] = field(default_factory=list)
    mode: str = "turbo"  # turbo/ultra/quantum/etc (string for compatibility)
    include_hidden: bool = False
    follow_symlinks: bool = False
    file_globs: Optional[List[str]] = None


class StartPage(BaseStation):
    station_id = "mission"
    station_title = "Home"
    navigate_requested = Signal(str)
    folder_added = Signal(str)  # new for sidebar

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self._build_gemini_ui()

    def _build_gemini_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(0)

        # LEFT SIDEBAR — Collapsible Locations (persistent via ui_state)
        self._sidebar_container = QFrame()
        self._sidebar_container.setObjectName("LocationsSidebar")
        self._sidebar_container.setMinimumWidth(0)
        self._sidebar_container.setMaximumWidth(320)
        sb_main = QVBoxLayout(self._sidebar_container)
        sb_main.setContentsMargins(0, 0, 0, 0)
        sb_main.setSpacing(0)
        header = QHBoxLayout()
        self._collapse_btn = QToolButton()
        self._collapse_btn.setCheckable(True)
        self._collapse_btn.setChecked(load_sidebar_collapsed())
        self._collapse_btn.setToolTip("Collapse or expand Locations panel")
        self._collapse_btn.toggled.connect(self._on_sidebar_toggled)
        header.addWidget(self._collapse_btn)
        loc_label = QLabel("Locations")
        loc_label.setToolTip("Recently added scan roots. Click + Add Folder to start a scan.")
        header.addWidget(loc_label)
        sb_main.addLayout(header)
        self._locations_widget = QWidget()
        sb_inner = QVBoxLayout(self._locations_widget)
        sb_inner.setContentsMargins(10, 10, 10, 10)
        sb_inner.setSpacing(8)
        self.locations_list = QListWidget()
        self.locations_list.setToolTip("Double-click a location to scan again. Folder icon = saved location.")
        self.locations_list.itemDoubleClicked.connect(self._on_location_double_clicked)
        sb_inner.addWidget(self.locations_list)
        add_btn = QPushButton("+ Add Folder")
        add_btn.setToolTip("Choose a folder to scan for duplicates (opens Scan page)")
        add_btn.clicked.connect(lambda: self.navigate_requested.emit("scan"))
        sb_inner.addWidget(add_btn)
        sb_main.addWidget(self._locations_widget)
        self._update_collapse_ui()
        layout.addWidget(self._sidebar_container)

        # CENTER HERO — Gemini drag-drop (12px rounded, teal accent feel)
        hero = QFrame()
        hero.setObjectName("HeroDropZone")
        hero.setStyleSheet("""
            QFrame#HeroDropZone {
                background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #151922, stop:1 #0f1115);
                border: 2px dashed #262c3a;
                border-radius: 20px;
            }
            QFrame#HeroDropZone:hover { border-color: #00C4B4; }
        """)
        hero.setToolTip("Drop folders here to add them for scanning, or click Browse Computer")
        h_layout = QVBoxLayout(hero)
        h_layout.setContentsMargins(16, 16, 16, 16)
        h_layout.setAlignment(Qt.AlignCenter)
        icon = QLabel("[Folder]")
        icon.setStyleSheet("font-size: 72px; color: #00C4B4;")
        h_layout.addWidget(icon)
        h_layout.addWidget(QLabel("Drop folders or files here"))
        h_layout.addWidget(QLabel("or"))
        btn = QPushButton("Browse Computer")
        btn.setToolTip("Open Scan page to choose a folder and start duplicate scan")
        btn.clicked.connect(lambda: self.navigate_requested.emit("scan"))
        h_layout.addWidget(btn)
        layout.addWidget(hero, 1)

    def _on_sidebar_toggled(self, checked: bool) -> None:
        save_sidebar_collapsed(checked)
        self._update_collapse_ui()

    def _update_collapse_ui(self) -> None:
        collapsed = self._collapse_btn.isChecked()
        self._collapse_btn.setText("[+]" if collapsed else "[-]")
        self._locations_widget.setVisible(not collapsed)
        if collapsed:
            self._sidebar_container.setMaximumWidth(56)
            self._sidebar_container.setMinimumWidth(56)
        else:
            self._sidebar_container.setMaximumWidth(320)
            self._sidebar_container.setMinimumWidth(200)

    def _on_location_double_clicked(self, item: QListWidgetItem) -> None:
        path = item.data(Qt.ItemDataRole.UserRole) or item.text()
        if path and Path(path).is_dir():
            bus = get_state_bus()
            if hasattr(bus, "resume_scan_requested"):
                bus.resume_scan_requested.emit({"root": path})
            self.navigate_requested.emit("scan")

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._load_locations()

    def _load_locations(self) -> None:
        self.locations_list.clear()
        for path in load_locations():
            item = QListWidgetItem(f"  [Folder]  {Path(path).name}")
            item.setData(Qt.ItemDataRole.UserRole, path)
            item.setToolTip(path)
            self.locations_list.addItem(item)
        if self._collapse_btn.isChecked():
            self._update_collapse_ui()

    def add_location(self, path: str) -> None:
        paths = load_locations()
        path = str(Path(path).resolve())
        if path not in paths:
            paths.insert(0, path)
            save_locations(paths)
        self._load_locations()

    # OPTIONAL: basic drop handlers (safe defaults)
    def dragEnterEvent(self, event: QDragEnterEvent):
        event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        if event.mimeData() and event.mimeData().hasUrls():
            url = event.mimeData().urls()[0]
            path = url.toLocalFile()
            if path and Path(path).is_dir():
                self.add_location(path)
        event.acceptProposedAction()
