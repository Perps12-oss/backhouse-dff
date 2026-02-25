# cerebro/ui/components/modern/folder_picker.py – Drag-drop folder picker (theme tokens only)
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QWidget

from ._tokens import RADIUS_MD, SPACE_UNIT, token


def _extract_path(mime_data) -> Optional[str]:
    if not mime_data or not mime_data.hasUrls():
        return None
    urls = mime_data.urls()
    if not urls:
        return None
    return urls[0].toLocalFile() or None


class ModernFolderPicker(QFrame):
    """Single folder path with Browse; accepts drag-and-drop. Theme tokens only."""

    path_changed = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("ModernFolderPicker")
        self.setAcceptDrops(True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(SPACE_UNIT * 2, SPACE_UNIT * 2, SPACE_UNIT * 2, SPACE_UNIT * 2)
        layout.setSpacing(SPACE_UNIT * 2)

        layout.addWidget(QLabel("Folder:"), 0)
        self._edit = QLineEdit()
        self._edit.setPlaceholderText("Drop a folder here, or click Browse…")
        self._edit.setClearButtonEnabled(True)
        self._edit.textChanged.connect(self.path_changed.emit)
        layout.addWidget(self._edit, 1)

        self._browse = QPushButton("Browse")
        self._browse.setCursor(Qt.CursorShape.PointingHandCursor)
        self._browse.clicked.connect(self._on_browse)
        layout.addWidget(self._browse, 0)

        self._hint = QLabel("Tip: drag & drop a folder onto this card.")
        self._hint.setObjectName("FolderPickerHint")
        layout.addWidget(self._hint, 0)

        self._apply_theme()

    def _apply_theme(self) -> None:
        panel = token("panel")
        line = token("line")
        text = token("text")
        muted = token("muted")
        self.setStyleSheet(f"""
            ModernFolderPicker {{
                background: {panel};
                border: 1px solid {line};
                border-radius: {RADIUS_MD}px;
            }}
            QLineEdit {{ padding: {SPACE_UNIT}px {SPACE_UNIT*2}px; border-radius: {RADIUS_MD}px; color: {text}; }}
            QPushButton {{ color: {text}; padding: {SPACE_UNIT}px {SPACE_UNIT*2}px; }}
            QLabel#FolderPickerHint {{ color: {muted}; font-size: 12px; }}
        """)

    def _on_browse(self) -> None:
        from PySide6.QtWidgets import QFileDialog
        path = QFileDialog.getExistingDirectory(self, "Select folder to scan")
        if path:
            self.set_path(path)

    def set_path(self, path: str) -> None:
        self._edit.setText(path or "")

    def path(self) -> str:
        return (self._edit.text() or "").strip()

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if _extract_path(event.mimeData()):
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        path = _extract_path(event.mimeData())
        if path:
            from pathlib import Path
            p = Path(path)
            if p.is_dir():
                self.set_path(str(p))
            event.acceptProposedAction()
