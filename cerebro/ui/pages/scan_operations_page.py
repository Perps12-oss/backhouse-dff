# cerebro/ui/pages/scan_operations_page.py (updated)
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List, Optional, Dict, Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QListWidget,
    QListWidgetItem,
    QFileDialog,
    QFrame,
    QMessageBox,
)

from cerebro.ui.components import CollapsibleSection, StatusIndicator


@dataclass
class ScanPreset:
    key: str
    title: str
    subtitle: str
    config: Dict[str, Any]


class FolderDropZone(QFrame):
    folders_dropped = Signal(list)  # list[str]

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setObjectName("FolderDropZone")
        self.setMinimumHeight(90)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(6)

        self.title = QLabel("Drop a folder here")
        self.title.setStyleSheet("font-size: 14px; font-weight: 700; color: #e2e8f0;")
        self.subtitle = QLabel("…or click \"Choose Folder\"")
        self.subtitle.setStyleSheet("font-size: 12px; color: #94a3b8;")

        lay.addWidget(self.title)
        lay.addWidget(self.subtitle)

        self.setStyleSheet(
            """
            QFrame#FolderDropZone{
                border: 1px dashed rgba(148,163,184,0.35);
                border-radius: 12px;
                background: rgba(15,23,42,0.35);
            }
            QFrame#FolderDropZone:hover{
                border: 1px dashed rgba(148,163,184,0.65);
                background: rgba(15,23,42,0.5);
            }
            """
        )

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:
        urls = event.mimeData().urls()
        paths: List[str] = []
        for u in urls:
            p = u.toLocalFile()
            if p and os.path.isdir(p):
                paths.append(p)
        if paths:
            self.folders_dropped.emit(paths)
        event.acceptProposedAction()


class ScanOperationsPage(QWidget):
    """
    Embedded scan preset/options panel.

    CRITICAL RULE:
    - This is a QWidget (not QMainWindow, not QDialog)
    - It must NEVER call .show()
    - It is designed to be embedded into ScanPage
    """

    # Signals
    scan_requested = Signal(dict)   # config dict
    roots_changed = Signal(list)    # list[str]
    preset_changed = Signal(str)    # preset key

    # Constants for styles (prevents style stacking bugs)
    _BASE_PRESET_STYLE = """
        QPushButton {
            text-align: left;
            padding: 12px;
            border-radius: 12px;
            background: rgba(15,23,42,0.35);
            border: 1px solid rgba(148,163,184,0.18);
            color: #e2e8f0;
        }
        QPushButton:hover {
            border: 1px solid rgba(148,163,184,0.40);
            background: rgba(15,23,42,0.55);
        }
    """

    _HIGHLIGHT_PRESET_STYLE = """
        QPushButton {
            text-align: left;
            padding: 12px;
            border-radius: 12px;
            background: rgba(34,197,94,0.08);
            border: 1px solid rgba(34,197,94,0.75);
            color: #e2e8f0;
        }
        QPushButton:hover {
            background: rgba(34,197,94,0.15);
        }
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("ScanOperationsPage")

        self._roots: List[str] = []
        self._preset_key: str = "quick"

        self._presets: List[ScanPreset] = [
            ScanPreset(
                key="quick",
                title="Quick Scan",
                subtitle="Fast scan for recent duplicates",
                config={"mode": "fast", "hash_sample": "4kb", "workers": 8},
            ),
            ScanPreset(
                key="deep",
                title="Deep Clean",
                subtitle="Comprehensive detection (slower)",
                config={"mode": "exact", "hash_sample": "full", "workers": 8},
            ),
            ScanPreset(
                key="media",
                title="Media Library",
                subtitle="Optimized for photos & videos",
                config={"mode": "fast", "media": True, "workers": 8},
            ),
            ScanPreset(
                key="dev",
                title="Developer Workspace",
                subtitle="Scan code/projects",
                config={"mode": "exact", "types": ["py", "js", "ts"], "workers": 8},
            ),
        ]

        self._build_ui()
        self._refresh_roots()

    # ----------------------------
    # UI Construction
    # ----------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        # Top Row (Title + Status)
        top_row = QHBoxLayout()
        top_row.setSpacing(10)

        title = QLabel("Scan Presets")
        title.setStyleSheet("font-size: 16px; font-weight: 800; color: #e2e8f0;")

        self.status = StatusIndicator(self)
        self._set_status_text("Idle")
        
        top_row.addWidget(title)
        top_row.addStretch(1)
        top_row.addWidget(self.status)

        root.addLayout(top_row)

        # Drop Zone + Controls
        dz_row = QHBoxLayout()
        dz_row.setSpacing(10)

        self.drop_zone = FolderDropZone(self)
        self.drop_zone.folders_dropped.connect(self._on_folders_dropped)

        self.btn_choose = QPushButton("Choose Folder")
        self.btn_choose.setCursor(Qt.CursorShape.PointingHandCursor)
        # Minimal style for utility buttons
        self.btn_choose.setStyleSheet("""
            QPushButton {
                background: rgba(30, 41, 59, 0.8);
                border: 1px solid rgba(148, 163, 184, 0.3);
                border-radius: 8px;
                padding: 8px 12px;
                color: #e2e8f0;
            }
            QPushButton:hover {
                background: rgba(51, 65, 85, 0.9);
                border-color: rgba(148, 163, 184, 0.6);
            }
        """)
        self.btn_choose.clicked.connect(self._choose_folder)

        dz_row.addWidget(self.drop_zone, 1)

        side = QVBoxLayout()
        side.setSpacing(10)
        side.addWidget(self.btn_choose)

        self.btn_clear = QPushButton("Clear")
        self.btn_clear.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_clear.setStyleSheet(self.btn_choose.styleSheet())
        self.btn_clear.clicked.connect(self._clear_roots)
        side.addWidget(self.btn_clear)

        side.addStretch(1)

        dz_row.addLayout(side)
        root.addLayout(dz_row)

        # Roots List
        self.roots_list = QListWidget(self)
        self.roots_list.setMinimumHeight(90)
        self.roots_list.setStyleSheet(
            """
            QListWidget{
                background: rgba(15,23,42,0.35);
                border: 1px solid rgba(148,163,184,0.20);
                border-radius: 12px;
                padding: 6px;
                color: #e2e8f0;
            }
            """
        )
        root.addWidget(self.roots_list)

        # Presets section (Using your specific snippet structure)
        presets_section = CollapsibleSection("Presets", initially_expanded=True)
        presets_section.toggled.connect(self._on_presets_toggled)

        # Create presets container
        presets_container = QWidget()
        presets_layout = QVBoxLayout(presets_container)
        presets_layout.setContentsMargins(0, 0, 0, 0)
        presets_layout.setSpacing(10)

        for p in self._presets:
            btn = QPushButton(f"{p.title}\n{p.subtitle}")
            btn.setObjectName(f"PresetBtn_{p.key}")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setMinimumHeight(62)
            # Use constant to prevent style stacking
            btn.setStyleSheet(self._BASE_PRESET_STYLE)
            btn.clicked.connect(lambda _=False, key=p.key: self._select_preset(key))
            presets_layout.addWidget(btn)

        # Set the content using the correct API
        presets_section.set_content(presets_container)

        root.addWidget(presets_section)

        # Start Scan Button
        bottom = QHBoxLayout()
        bottom.setSpacing(10)

        self.btn_scan = QPushButton("Start Scan")
        self.btn_scan.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_scan.setMinimumHeight(44)
        self.btn_scan.setStyleSheet(
            """
            QPushButton{
                border-radius: 12px;
                font-weight: 800;
                background: rgba(59,130,246,0.25);
                border: 1px solid rgba(59,130,246,0.55);
                color: #e2e8f0;
                padding: 10px 14px;
            }
            QPushButton:hover{
                background: rgba(59,130,246,0.35);
                border: 1px solid rgba(59,130,246,0.75);
            }
            """
        )
        self.btn_scan.clicked.connect(self._emit_scan_requested)

        bottom.addStretch(1)
        bottom.addWidget(self.btn_scan)

        root.addLayout(bottom)

        self._apply_preset_button_highlight()

    def _on_presets_toggled(self, expanded: bool) -> None:
        """Handle presets section toggle."""
        # Optional: You can add any additional logic here
        pass

    # ----------------------------
    # Roots Handling
    # ----------------------------

    def _on_folders_dropped(self, paths: List[str]) -> None:
        changed = False
        for p in paths:
            if p not in self._roots:
                self._roots.append(p)
                changed = True
        if changed:
            self._refresh_roots()
            self.roots_changed.emit(self._roots)

    def _choose_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select folder to scan")
        if folder:
            if folder not in self._roots:
                self._roots.append(folder)
                self._refresh_roots()
                self.roots_changed.emit(self._roots)

    def _clear_roots(self) -> None:
        self._roots = []
        self._refresh_roots()
        self.roots_changed.emit(self._roots)

    def _refresh_roots(self) -> None:
        self.roots_list.clear()
        if not self._roots:
            item = QListWidgetItem("No folders selected")
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self.roots_list.addItem(item)
            self._set_status_text("Idle")
            return

        for r in self._roots:
            self.roots_list.addItem(QListWidgetItem(r))

        self._set_status_text(f"{len(self._roots)} folder(s) selected")

    def _set_status_text(self, text: str) -> None:
        """Helper to safely set status text regardless of component API."""
        if hasattr(self.status, 'setText'):
            self.status.setText(text)
        elif hasattr(self.status, 'set_text'):
            self.status.set_text(text)
        # Add more API compatibility as needed

    # ----------------------------
    # Presets & Config
    # ----------------------------

    def _select_preset(self, key: str) -> None:
        self._preset_key = key
        self._apply_preset_button_highlight()
        self.preset_changed.emit(key)

    def _apply_preset_button_highlight(self) -> None:
        """
        Highlight the selected preset and reset the others.
        Fixed to prevent style stacking.
        """
        for p in self._presets:
            btn = self.findChild(QPushButton, f"PresetBtn_{p.key}")
            if btn:
                if p.key == self._preset_key:
                    btn.setStyleSheet(self._HIGHLIGHT_PRESET_STYLE)
                else:
                    btn.setStyleSheet(self._BASE_PRESET_STYLE)

    def get_scan_config(self) -> Dict[str, Any]:
        preset = next((p for p in self._presets if p.key == self._preset_key), self._presets[0])
        return {
            "roots": list(self._roots),
            "preset": self._preset_key,
            **preset.config,
        }

    def _emit_scan_requested(self) -> None:
        if not self._roots:
            QMessageBox.information(
                self,
                "Select a folder",
                "Please add at least one folder to scan (drop or choose).",
            )
            return

        cfg = self.get_scan_config()
        self.scan_requested.emit(cfg)