# cerebro/ui/pages/review_page.py
"""
CEREBRO v5.0 — Review Page (PySide6) — POLISHED MERGED DESIGN

Enhanced with:
✓ Smart logic applies to ALL groups (filtered or all)
✓ Media type filtering actually filters displayed groups  
✓ Smart select respects current filter context
✓ Always-visible floating Delete button (prominent, responsive)
✓ Full keyboard navigation (arrows, space, delete, 1-5)
✓ Centered modal progress dialog (blocks interaction, colorful)
✓ Selection semantics: checked = delete, unchecked = keep
✓ Enforced invariant: exactly ONE keep per group minimum
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum, IntEnum
from functools import partial
from pathlib import Path
from PySide6.QtCore import QItemSelectionModel
from typing import Any, Dict, List, Optional, Set, Tuple
from PySide6.QtCore import QItemSelectionModel
from PySide6.QtCore import (
    Qt, QSize, QRect, QPoint, QEvent, QTimer, Signal, Slot,
    QRunnable, QThreadPool, QObject, QMutex, QMutexLocker,
    QPropertyAnimation, QEasingCurve
)
from PySide6.QtGui import (
    QPixmap, QKeySequence, QShortcut, QKeyEvent, QFontMetrics,
    QColor, QPainter, QFont
)
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLayout,
    QLabel, QPushButton, QFrame, QScrollArea, QSplitter,
    QComboBox, QCheckBox, QDialog, QListWidget, QListWidgetItem,
    QStackedWidget, QSizePolicy, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QMessageBox, QInputDialog,
    QProgressBar, QTextEdit, QGroupBox, QToolButton,
    QGraphicsDropShadowEffect, QApplication
)

from cerebro.ui.pages.base_station import BaseStation
from cerebro.ui.state_bus import get_state_bus
from cerebro.ui.theme_engine import get_theme_manager


# ==============================================================================
# CONSTANTS
# ==============================================================================

BYTES_PER_UNIT = 1024.0
SIZE_UNIT_LABELS = ["B", "KB", "MB", "GB", "TB"]

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".webp", ".heic", ".heif", ".ico", ".svg"}
VIDEO_EXTS = {".mp4", ".avi", ".mkv", ".mov", ".wmv", ".webm", ".flv", ".m4v", ".mpg", ".mpeg", ".3gp"}
AUDIO_EXTS = {".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".wma", ".opus", ".aiff"}
ARCHIVE_EXTS = {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".lz", ".cab"}
DOC_EXTS = {".pdf", ".doc", ".docx", ".txt", ".rtf", ".odt", ".xls", ".xlsx", ".ppt", ".pptx", ".csv"}

ALL_MEDIA_TYPES = {
    "Images": IMAGE_EXTS,
    "Videos": VIDEO_EXTS,
    "Audio": AUDIO_EXTS,
    "Archives": ARCHIVE_EXTS,
    "Documents": DOC_EXTS,
}


# ==============================================================================
# UTILS
# ==============================================================================

def get_file_category(path: str) -> str:
    ext = Path(path).suffix.lower()
    for category, exts in ALL_MEDIA_TYPES.items():
        if ext in exts:
            return category
    return "Other"

def is_image_file(path: str) -> bool:
    try:
        return Path(path).suffix.lower() in IMAGE_EXTS
    except Exception:
        return False

def format_bytes(num_bytes: int) -> str:
    try:
        num_bytes = int(num_bytes or 0)
    except Exception:
        num_bytes = 0
    value = float(num_bytes)
    unit_index = 0
    while value >= BYTES_PER_UNIT and unit_index < len(SIZE_UNIT_LABELS) - 1:
        value /= BYTES_PER_UNIT
        unit_index += 1
    return f"{value:.2f} {SIZE_UNIT_LABELS[unit_index]}"

def truncate_text(text: str, max_len: int, ellipsis: str = "...") -> str:
    if not text:
        return ""
    if len(text) <= max_len:
        return text
    return text[: max(0, max_len - len(ellipsis))] + ellipsis

def file_emoji(path: str) -> str:
    ext = Path(path).suffix.lower()
    if ext in IMAGE_EXTS:
        return "🖼️"
    if ext in VIDEO_EXTS:
        return "🎬"
    if ext in AUDIO_EXTS:
        return "🎵"
    if ext in ARCHIVE_EXTS:
        return "📦"
    if ext in DOC_EXTS:
        return "📄"
    if ext in {".py", ".js", ".html", ".css", ".cpp", ".c", ".h", ".java", ".rs", ".go", ".php", ".rb"}:
        return "💻"
    return "📎"


# ==============================================================================
# THEME HELPERS
# ==============================================================================

class ThemeHelper:
    @staticmethod
    def colors() -> Dict[str, str]:
        try:
            tm = get_theme_manager()
            return tm.current_colors() if tm else {}
        except Exception:
            return {}

    @staticmethod
    def pick(key: str, fallback: str) -> str:
        c = ThemeHelper.colors()
        return str(c.get(key, fallback))


# ==============================================================================
# ASYNC THUMBNAIL LOADER
# ==============================================================================

class _WorkerSignals(QObject):
    finished = Signal(str, QPixmap)

class _ThumbTask(QRunnable):
    def __init__(self, file_path: str, size: QSize):
        super().__init__()
        self.file_path = file_path
        self.size = size
        self.signals = _WorkerSignals()
        self.setAutoDelete(True)

    def run(self):
        if not is_image_file(self.file_path):
            return
        try:
            pix = QPixmap(self.file_path)
            if pix.isNull():
                return
            scaled = pix.scaled(self.size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.signals.finished.emit(self.file_path, scaled)
        except Exception:
            return

class AsyncThumbnailLoader(QObject):
    thumbnail_ready = Signal(str, QPixmap)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pool = QThreadPool.globalInstance()
        self._cache: Dict[Tuple[str, int, int], QPixmap] = {}
        self._mutex = QMutex()

    def request(self, file_path: str, size: QSize) -> None:
        if not file_path:
            return
        key = (file_path, int(size.width()), int(size.height()))
        with QMutexLocker(self._mutex):
            pix = self._cache.get(key)
        if pix is not None and not pix.isNull():
            self.thumbnail_ready.emit(file_path, pix)
            return

        task = _ThumbTask(file_path, size)
        task.signals.finished.connect(self._on_finished)
        self._pool.start(task)

    @Slot(str, QPixmap)
    def _on_finished(self, file_path: str, pixmap: QPixmap):
        if pixmap.isNull():
            return
        key = (file_path, pixmap.width(), pixmap.height())
        with QMutexLocker(self._mutex):
            if len(self._cache) > 600:
                self._cache.clear()
            self._cache[key] = pixmap
        self.thumbnail_ready.emit(file_path, pixmap)


# ==============================================================================
# CENTERED PROGRESS DIALOG
# ==============================================================================

class CleanupProgressDialog(QDialog):
    cancelled = Signal()

    def __init__(self, total_files: int, parent=None):
        super().__init__(parent)
        self.total_files = total_files
        self.processed_files = 0
        self.failed_files = 0

        self.setWindowTitle("Deleting Files...")
        self.setModal(True)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setFixedSize(500, 320)

        if parent:
            geo = parent.geometry()
            self.move(
                geo.center().x() - self.width() // 2,
                geo.center().y() - self.height() // 2
            )

        self._build()
        self.apply_theme()
        self.setWindowModality(Qt.ApplicationModal)

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(20)

        self.title = QLabel("🗑️ Moving to Trash...")
        self.title.setAlignment(Qt.AlignCenter)
        self.title.setStyleSheet("font-size: 24px; font-weight: bold;")
        layout.addWidget(self.title)

        self.subtitle = QLabel(f"Processing {self.total_files} files")
        self.subtitle.setAlignment(Qt.AlignCenter)
        self.subtitle.setStyleSheet("font-size: 14px; color: #888;")
        layout.addWidget(self.subtitle)

        self.progress = QProgressBar()
        self.progress.setMaximum(self.total_files)
        self.progress.setValue(0)
        self.progress.setTextVisible(True)
        self.progress.setFormat("%v/%m files (%p%)")
        self.progress.setFixedHeight(30)
        layout.addWidget(self.progress)

        stats = QHBoxLayout()
        self.success_label = QLabel("✓ Success: 0")
        self.success_label.setStyleSheet("color: #22c55e; font-weight: bold; font-size: 13px;")
        self.failed_label = QLabel("✗ Failed: 0")
        self.failed_label.setStyleSheet("color: #ef4444; font-weight: bold; font-size: 13px;")

        stats.addWidget(self.success_label)
        stats.addWidget(self.failed_label)
        layout.addLayout(stats)

        self.current_file = QLabel("Starting...")
        self.current_file.setStyleSheet("color: #666; font-size: 11px;")
        self.current_file.setWordWrap(True)
        self.current_file.setMaximumHeight(40)
        layout.addWidget(self.current_file)

        layout.addStretch()

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setFixedHeight(40)
        self.cancel_btn.setCursor(Qt.PointingHandCursor)
        self.cancel_btn.clicked.connect(self._on_cancel)
        layout.addWidget(self.cancel_btn)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(30)
        shadow.setColor(QColor(0, 0, 0, 100))
        shadow.setOffset(0, 10)
        self.setGraphicsEffect(shadow)

    def update_progress(self, current: int, filename: str = "", success: bool = True):
        self.processed_files = current
        if not success:
            self.failed_files += 1

        self.progress.setValue(current)
        self.success_label.setText(f"✓ Success: {current - self.failed_files}")
        self.failed_label.setText(f"✗ Failed: {self.failed_files}")

        if filename:
            self.current_file.setText(f"Current: {truncate_text(filename, 50)}")

        self.progress.setStyleSheet("""
            QProgressBar {
                border: 2px solid #3b82f6;
                border-radius: 15px;
                text-align: center;
                font-weight: bold;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                    stop:0 #22c55e, stop:0.5 #3b82f6, stop:1 #8b5cf6);
                border-radius: 13px;
            }
        """)
        QApplication.processEvents()

    def set_complete(self, success_count: int, fail_count: int):
        self.title.setText("✅ Cleanup Complete!")
        self.subtitle.setText(f"Moved {success_count} files to Trash")
        self.progress.setValue(self.total_files)
        self.cancel_btn.setText("Close")
        self.cancel_btn.setStyleSheet("""
            QPushButton {
                background: #22c55e;
                color: white;
                border: none;
                border-radius: 8px;
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton:hover {
                background: #16a34a;
            }
        """)

    def _on_cancel(self):
        if self.processed_files < self.total_files:
            self.cancelled.emit()
        self.accept()

    def apply_theme(self):
        c = ThemeHelper.colors()
        bg = c.get('panel', '#1a1d26')
        text = c.get('text', '#e7ecf2')
        accent = c.get('accent', '#3b82f6')

        self.setStyleSheet(f"""
            CleanupProgressDialog {{
                background: {bg};
                border: 3px solid {accent};
                border-radius: 20px;
            }}
            QLabel {{
                color: {text};
            }}
            QPushButton {{
                background: {accent};
                color: white;
                border: none;
                border-radius: 8px;
                font-weight: bold;
                font-size: 14px;
            }}
            QPushButton:hover {{
                background: {accent};
            }}
        """)

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key_Escape and self.processed_files < self.total_files:
            return
        super().keyPressEvent(event)


# ==============================================================================
# FLOATING DELETE BUTTON
# ==============================================================================

class FloatingDeleteButton(QPushButton):
    clicked_with_count = Signal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.file_count = 0
        self.total_bytes = 0
        self._setup_ui()

    def _setup_ui(self):
        self.setFixedSize(180, 60)
        self.setCursor(Qt.PointingHandCursor)
        self.update_display()
        self._apply_style()
        self._pulse_anim = QPropertyAnimation(self, b"geometry")
        self._pulse_anim.setDuration(200)

    def update_count(self, count: int, bytes_size: int):
        self.file_count = count
        self.total_bytes = bytes_size
        self.update_display()
        if count > 0:
            self._pulse()

    def update_display(self):
        if self.file_count == 0:
            self.setText("🗑️\nNo files selected")
            self.setEnabled(False)
        else:
            size_str = format_bytes(self.total_bytes)
            self.setText(f"🗑️ DELETE\n{self.file_count} files ({size_str})")
            self.setEnabled(True)

    def _pulse(self):
        current = self.geometry()
        self._pulse_anim.setStartValue(current)
        self._pulse_anim.setEndValue(current.adjusted(-5, -5, 5, 5))
        self._pulse_anim.start()
        QTimer.singleShot(200, lambda: self._pulse_anim.setEndValue(current))

    def _apply_style(self):
        self.setStyleSheet("""
            FloatingDeleteButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #ef4444, stop:1 #dc2626);
                color: white;
                border: 3px solid #fca5a5;
                border-radius: 30px;
                font-weight: bold;
                font-size: 13px;
                padding: 8px;
            }
            FloatingDeleteButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #f87171, stop:1 #ef4444);
                border-color: #fecaca;
            }
            FloatingDeleteButton:disabled {
                background: #4b5563;
                border-color: #6b7280;
                color: #9ca3af;
            }
            FloatingDeleteButton:pressed {
                background: #b91c1c;
            }
        """)

    def mousePressEvent(self, event):
        if self.isEnabled():
            self.clicked_with_count.emit(self.file_count, self.total_bytes)
        super().mousePressEvent(event)


# ==============================================================================
# GROUP DATA
# ==============================================================================

@dataclass(frozen=True)
class GroupData:
    paths: List[str]
    hint: str = ""
    recoverable_bytes: int = 0
    similarity: float = 100.0
    group_id: int = 0

    @property
    def file_count(self) -> int:
        return len(self.paths)

    @property
    def recoverable_formatted(self) -> str:
        return format_bytes(self.recoverable_bytes)

    def get_category(self) -> str:
        if not self.paths:
            return "Other"
        return get_file_category(self.paths[0])

def extract_group_data(group: Any, idx: int = 0) -> GroupData:
    if isinstance(group, dict):
        raw_paths = group.get("paths") or group.get("files") or group.get("items") or []
        paths = [str(p) for p in raw_paths]
        hint = str(group.get("reason") or group.get("hint") or group.get("description") or "")
        recoverable = int(group.get("recoverable_bytes", group.get("recoverable", 0)) or 0)
        similarity = float(group.get("similarity", 100.0) or 100.0)
        return GroupData(paths=paths, hint=hint, recoverable_bytes=recoverable, 
                        similarity=similarity, group_id=idx)
    if isinstance(group, (list, tuple)):
        return GroupData(paths=[str(p) for p in group], group_id=idx)
    return GroupData(paths=[], group_id=idx)


# ==============================================================================
# DUAL PANE COMPARISON
# ==============================================================================

class DualPaneComparison(QFrame):
    file_selected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("DualPaneComparison")
        self._build()
        self._current_paths: List[str] = []

    def _build(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        self.left_pane = self._create_pane("Original")
        layout.addWidget(self.left_pane, 1)

        center = QWidget()
        center.setFixedWidth(100)
        cl = QVBoxLayout(center)
        cl.setAlignment(Qt.AlignCenter)

        self.similarity_label = QLabel("100%")
        self.similarity_label.setAlignment(Qt.AlignCenter)
        self.similarity_label.setStyleSheet("font-size: 28px; font-weight: bold; color: #22c55e;")

        self.similarity_text = QLabel("Similarity")
        self.similarity_text.setAlignment(Qt.AlignCenter)
        self.similarity_text.setStyleSheet("font-size: 11px; color: #888;")

        cl.addStretch()
        cl.addWidget(self.similarity_label)
        cl.addWidget(self.similarity_text)
        cl.addStretch()

        layout.addWidget(center)

        self.right_pane = self._create_pane("Duplicate")
        layout.addWidget(self.right_pane, 1)

    def _create_pane(self, label_text: str) -> QFrame:
        pane = QFrame()
        pane.setObjectName(f"Pane_{label_text}")
        pane.setFrameShape(QFrame.StyledPanel)
        layout = QVBoxLayout(pane)
        layout.setContentsMargins(8, 8, 8, 8)

        label = QLabel(label_text)
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet("font-weight: bold; font-size: 12px; padding: 4px;")
        layout.addWidget(label)

        img_container = QFrame()
        img_container.setMinimumSize(200, 200)
        img_container.setStyleSheet("background: #0a0a0a; border-radius: 8px;")
        img_layout = QVBoxLayout(img_container)
        img_layout.setContentsMargins(4, 4, 4, 4)

        img_label = QLabel()
        img_label.setAlignment(Qt.AlignCenter)
        img_label.setObjectName(f"img_{label_text}")
        img_layout.addWidget(img_label)

        if label_text == "Original":
            self.left_img = img_label
        else:
            self.right_img = img_label

        layout.addWidget(img_container, 1)

        info = QLabel("No file selected")
        info.setAlignment(Qt.AlignCenter)
        info.setObjectName(f"info_{label_text}")
        info.setStyleSheet("font-size: 11px; color: #aaa; padding: 4px;")
        layout.addWidget(info)

        if label_text == "Original":
            self.left_info = info
        else:
            self.right_info = info

        btn_row = QHBoxLayout()
        keep_btn = QPushButton(f"✓ Keep {label_text}")
        keep_btn.setObjectName(f"keep_{label_text}")
        keep_btn.setCursor(Qt.PointingHandCursor)
        keep_btn.clicked.connect(lambda: self._on_keep_clicked(label_text))
        btn_row.addStretch()
        btn_row.addWidget(keep_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        return pane

    def _on_keep_clicked(self, pane: str):
        if pane == "Original" and self._current_paths:
            self.file_selected.emit(self._current_paths[0])
        elif pane == "Duplicate" and len(self._current_paths) > 1:
            self.file_selected.emit(self._current_paths[1])

    def set_comparison(self, paths: List[str], similarity: float = 100.0):
        self._current_paths = paths
        self.similarity_label.setText(f"{similarity:.0f}%")

        if similarity >= 95:
            color = "#22c55e"
        elif similarity >= 80:
            color = "#eab308"
        else:
            color = "#ef4444"
        self.similarity_label.setStyleSheet(f"font-size: 28px; font-weight: bold; color: {color};")

        if len(paths) >= 1:
            self._load_image(self.left_img, self.left_info, paths[0])
        if len(paths) >= 2:
            self._load_image(self.right_img, self.right_info, paths[1])

    def _load_image(self, img_label: QLabel, info_label: QLabel, path: str):
        if is_image_file(path):
            pix = QPixmap(path)
            if not pix.isNull():
                scaled = pix.scaled(280, 280, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                img_label.setPixmap(scaled)
                size = os.path.getsize(path) if os.path.exists(path) else 0
                dims = f"{pix.width()}×{pix.height()}"
                info_label.setText(f"{Path(path).name}\n{dims} | {format_bytes(size)}")
                return

        img_label.setText(file_emoji(path))
        img_label.setStyleSheet("font-size: 48px;")
        info_label.setText(Path(path).name)


# ==============================================================================
# GROUP LIST ITEM
# ==============================================================================

class GroupListItem(QFrame):
    clicked = Signal(int)
    checkbox_changed = Signal(int, bool)

    def __init__(self, group_id: int, group_data: GroupData, parent=None):
        super().__init__(parent)
        self.group_id = group_id
        self.group_data = group_data
        self._selected = False

        self.setObjectName("GroupListItem")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(64)

        self._build()
        self.update_style()

    def _build(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(12)

        self.checkbox = QCheckBox()
        self.checkbox.setToolTip("Check to mark ALL files in this group for deletion")
        self.checkbox.stateChanged.connect(self._on_checkbox_changed)
        layout.addWidget(self.checkbox)

        icon = QLabel(file_emoji(self.group_data.paths[0]) if self.group_data.paths else "📄")
        icon.setFixedSize(40, 40)
        icon.setAlignment(Qt.AlignCenter)
        icon.setStyleSheet("font-size: 20px; background: rgba(255,255,255,0.1); border-radius: 8px;")
        layout.addWidget(icon)

        info = QVBoxLayout()
        info.setSpacing(2)

        name = QLabel(f"Group #{self.group_id + 1}")
        name.setStyleSheet("font-weight: bold; font-size: 13px;")

        details = QLabel(f"{self.group_data.file_count} files • {self.group_data.recoverable_formatted}")
        details.setStyleSheet("font-size: 11px; color: #888;")

        info.addWidget(name)
        info.addWidget(details)
        layout.addLayout(info, 1)

        if self.group_data.similarity < 100:
            sim = QLabel(f"{self.group_data.similarity:.0f}%")
            sim.setAlignment(Qt.AlignCenter)
            sim.setFixedSize(48, 24)
            color = "#22c55e" if self.group_data.similarity >= 95 else "#eab308"
            sim.setStyleSheet(f"""
                background: {color};
                color: white;
                border-radius: 12px;
                font-size: 11px;
                font-weight: bold;
            """)
            layout.addWidget(sim)

    def _on_checkbox_changed(self, state):
        self.checkbox_changed.emit(self.group_id, state == Qt.Checked)

    def set_selected(self, selected: bool):
        self._selected = selected
        self.update_style()

    def update_style(self):
        c = ThemeHelper.colors()
        if self._selected:
            bg = c.get('accent', '#3b82f6')
            border = c.get('accent', '#3b82f6')
            text = "white"
        else:
            bg = c.get('surface', '#151922')
            border = c.get('line', '#2a3241')
            text = c.get('text', '#e7ecf2')

        self.setStyleSheet(f"""
            QFrame#GroupListItem {{
                background: {bg};
                border: 2px solid {border};
                border-radius: 12px;
            }}
            QLabel {{
                color: {text};
            }}
        """)

    def mousePressEvent(self, event):
        self.clicked.emit(self.group_id)
        super().mousePressEvent(event)


# ==============================================================================
# MAIN REVIEW PAGE
# ==============================================================================

class ReviewPage(BaseStation):
    cleanup_confirmed = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._result = {}
        self._bus = get_state_bus()

        self._all_groups: List[GroupData] = []
        self._filtered_groups: List[GroupData] = []
        self._current_group_idx = -1
        self._keep_states: Dict[int, Dict[str, bool]] = {}

        self._current_filter = "All Files"
        self._progress_dialog = None

        self._thumb_loader = AsyncThumbnailLoader(self)

        self._build()
        self._setup_keyboard_shortcuts()
        self._wire()
        self.apply_theme()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Step bar
        self.step_bar = self._build_step_bar()
        root.addWidget(self.step_bar)

        # Main content
        content = QSplitter(Qt.Horizontal)
        content.setHandleWidth(2)

        self.left_panel = self._build_left_panel()
        content.addWidget(self.left_panel)

        self.center_panel = self._build_center_panel()
        content.addWidget(self.center_panel)

        self.right_panel = self._build_right_panel()
        content.addWidget(self.right_panel)

        content.setStretchFactor(0, 1)
        content.setStretchFactor(1, 2)
        content.setStretchFactor(2, 1)

        root.addWidget(content, 1)

        # Status bar
        self.status_bar = self._build_status_bar()
        root.addWidget(self.status_bar)

        # Floating delete button
        self.floating_delete = FloatingDeleteButton(self)
        self.floating_delete.clicked_with_count.connect(self._on_floating_delete_clicked)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._position_floating_button()

    def _position_floating_button(self):
        if hasattr(self, 'floating_delete'):
            margin = 30
            self.floating_delete.move(
                self.width() - self.floating_delete.width() - margin,
                self.height() - self.floating_delete.height() - margin - 40
            )
            self.floating_delete.raise_()

    def _build_step_bar(self):
        bar = QFrame()
        bar.setObjectName("StepBar")
        bar.setFixedHeight(50)

        layout = QHBoxLayout(bar)
        layout.setContentsMargins(20, 8, 20, 8)
        layout.setSpacing(20)

        steps = [("1", "Scan", False), ("2", "Analyze", False), ("3", "Resolve Duplicates", True)]

        for num, text, active in steps:
            step = QLabel(f"Step {num}: {text}")
            step.setStyleSheet(f"""
                font-weight: {'bold' if active else 'normal'};
                font-size: 13px;
                color: {'#3b82f6' if active else '#888'};
                padding: 4px 12px;
                background: {'rgba(59,130,246,0.1)' if active else 'transparent'};
                border-radius: 16px;
            """)
            layout.addWidget(step)

        layout.addStretch()

        self.quick_stats = QLabel("0 duplicates found")
        self.quick_stats.setStyleSheet("font-size: 13px; color: #aaa;")
        layout.addWidget(self.quick_stats)

        return bar

    def _build_left_panel(self):
        panel = QFrame()
        panel.setObjectName("LeftPanel")
        panel.setMinimumWidth(250)
        panel.setMaximumWidth(350)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        header = QHBoxLayout()
        self.select_all_cb = QCheckBox("Select All for Delete")
        self.select_all_cb.setToolTip("Mark ALL files in ALL groups for deletion (keeps one per group)")
        self.select_all_cb.stateChanged.connect(self._on_select_all_changed)
        header.addWidget(self.select_all_cb)
        header.addStretch()
        layout.addLayout(header)

        filter_layout = QHBoxLayout()
        filter_layout.addWidget(QLabel("Filter:"))
        self.filter_combo = QComboBox()
        self.filter_combo.addItems(["All Files", "Images", "Videos", "Audio", "Archives", "Documents", "Other"])
        self.filter_combo.currentTextChanged.connect(self._on_filter_changed)
        filter_layout.addWidget(self.filter_combo, 1)
        layout.addLayout(filter_layout)

        self.group_list = QScrollArea()
        self.group_list.setWidgetResizable(True)
        self.group_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.group_list_widget = QWidget()
        self.group_list_layout = QVBoxLayout(self.group_list_widget)
        self.group_list_layout.setAlignment(Qt.AlignTop)
        self.group_list_layout.setSpacing(8)

        self.group_list.setWidget(self.group_list_widget)
        layout.addWidget(self.group_list, 1)

        self.left_summary = QLabel("0 groups")
        self.left_summary.setAlignment(Qt.AlignCenter)
        self.left_summary.setStyleSheet("font-size: 12px; color: #888; padding: 8px;")
        layout.addWidget(self.left_summary)

        return panel

    def _build_center_panel(self):
        panel = QFrame()
        panel.setObjectName("CenterPanel")

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)

        nav = QHBoxLayout()
        self.prev_group_btn = QPushButton("◀ Previous (Left)")
        self.prev_group_btn.clicked.connect(self._prev_group)

        self.group_counter = QLabel("Group 1 of 1")
        self.group_counter.setAlignment(Qt.AlignCenter)
        self.group_counter.setStyleSheet("font-weight: bold; font-size: 14px;")

        self.next_group_btn = QPushButton("Next (Right) ▶")
        self.next_group_btn.clicked.connect(self._next_group)

        nav.addWidget(self.prev_group_btn)
        nav.addWidget(self.group_counter, 1)
        nav.addWidget(self.next_group_btn)

        layout.addLayout(nav)

        self.comparison = DualPaneComparison()
        self.comparison.file_selected.connect(self._on_comparison_keep_selected)
        layout.addWidget(self.comparison, 1)

        self.file_list_label = QLabel("Files in this group (Space to toggle, 1-5 to keep specific):")
        self.file_list_label.setStyleSheet("font-weight: bold; margin-top: 8px;")
        layout.addWidget(self.file_list_label)

        self.file_table = QTableWidget()
        self.file_table.setColumnCount(3)
        self.file_table.setHorizontalHeaderLabels(["Delete", "File", "Size"])
        self.file_table.horizontalHeader().setStretchLastSection(True)
        self.file_table.setMaximumHeight(150)
        self.file_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        layout.addWidget(self.file_table)

        return panel

    def _build_right_panel(self):
        panel = QFrame()
        panel.setObjectName("RightPanel")
        panel.setMinimumWidth(280)
        panel.setMaximumWidth(400)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)

        preview_header = QLabel("Preview")
        preview_header.setStyleSheet("font-size: 16px; font-weight: bold;")
        layout.addWidget(preview_header)

        self.preview_frame = QFrame()
        self.preview_frame.setMinimumSize(260, 260)
        self.preview_frame.setStyleSheet("background: #0a0a0a; border-radius: 12px;")
        preview_layout = QVBoxLayout(self.preview_frame)

        self.preview_label = QLabel("No preview")
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setStyleSheet("font-size: 48px;")
        preview_layout.addWidget(self.preview_label)

        layout.addWidget(self.preview_frame)

        details = QGroupBox("File Details")
        details_layout = QVBoxLayout(details)

        self.detail_name = QLabel("Name: -")
        self.detail_name.setWordWrap(True)
        self.detail_path = QLabel("Path: -")
        self.detail_path.setWordWrap(True)
        self.detail_size = QLabel("Size: -")
        self.detail_modified = QLabel("Modified: -")
        self.detail_category = QLabel("Category: -")

        for lbl in [self.detail_name, self.detail_path, self.detail_size, self.detail_modified, self.detail_category]:
            lbl.setStyleSheet("font-size: 12px; padding: 2px 0;")
            details_layout.addWidget(lbl)

        details_layout.addStretch()
        layout.addWidget(details)

        smart = QGroupBox("Smart Select (Applies to FILTERED groups)")
        smart_layout = QVBoxLayout(smart)

        smart_buttons = [
            ("Keep Oldest in Each", self._smart_keep_oldest),
            ("Keep Newest in Each", self._smart_keep_newest),
            ("Keep Largest in Each", self._smart_keep_largest),
            ("Keep Smallest in Each", self._smart_keep_smallest),
            ("Keep First in Each", self._smart_keep_first),
        ]

        for text, callback in smart_buttons:
            btn = QPushButton(text)
            btn.clicked.connect(callback)
            btn.setStyleSheet("""
                QPushButton {
                    background: rgba(59,130,246,0.15);
                    border: 1px solid rgba(59,130,246,0.3);
                    border-radius: 8px;
                    padding: 8px;
                    text-align: left;
                }
                QPushButton:hover {
                    background: rgba(59,130,246,0.25);
                }
            """)
            smart_layout.addWidget(btn)

        layout.addWidget(smart)
        layout.addStretch()

        return panel

    def _build_status_bar(self):
        bar = QFrame()
        bar.setObjectName("StatusBar")
        bar.setFixedHeight(36)

        layout = QHBoxLayout(bar)
        layout.setContentsMargins(20, 6, 20, 6)

        self.status_text = QLabel("Ready")
        layout.addWidget(self.status_text)

        layout.addStretch()

        self.selection_stats = QLabel("0 files selected for deletion (0 B)")
        self.selection_stats.setStyleSheet("font-weight: bold; color: #ef4444;")
        layout.addWidget(self.selection_stats)

        hint = QLabel("Shortcuts: ←→ Navigate | Space Toggle | Delete Confirm | 1-5 Keep")
        hint.setStyleSheet("font-size: 10px; color: #666; margin-left: 20px;")
        layout.addWidget(hint)

        return bar

    def _setup_keyboard_shortcuts(self):
        QShortcut(QKeySequence("Left"), self).activated.connect(self._prev_group)
        QShortcut(QKeySequence("Right"), self).activated.connect(self._next_group)
        QShortcut(QKeySequence("Up"), self).activated.connect(self._prev_file_in_table)
        QShortcut(QKeySequence("Down"), self).activated.connect(self._next_file_in_table)
        QShortcut(QKeySequence("Space"), self).activated.connect(self._toggle_current_file)
        QShortcut(QKeySequence("Return"), self).activated.connect(self._open_ceremony)
        QShortcut(QKeySequence("Delete"), self).activated.connect(self._open_ceremony)

        for i in range(1, 6):
            QShortcut(QKeySequence(str(i)), self).activated.connect(
                lambda checked, idx=i-1: self._keep_file_by_index(idx)
            )

    def _wire(self):
        self.file_table.itemChanged.connect(self._on_file_table_changed)

    @Slot(dict)
    def load_scan_result(self, result: dict):
        self._result = dict(result or {})
        groups_raw = self._result.get("groups") or []

        self._all_groups = [extract_group_data(g, i) for i, g in enumerate(groups_raw)]
        self._apply_filter()

        self._keep_states.clear()
        for g in self._all_groups:
            self._keep_states[g.group_id] = {p: True for p in g.paths}

        self._current_group_idx = 0 if self._filtered_groups else -1

        self._populate_group_list()
        self._update_display()
        self._update_stats()

    def on_theme_changed(self):
        self.apply_theme()
        self._populate_group_list()

    def _on_filter_changed(self, filter_text: str):
        self._current_filter = filter_text
        self._apply_filter()
        self._populate_group_list()
        self._current_group_idx = 0 if self._filtered_groups else -1
        self._update_display()
        self._update_stats()

    def _apply_filter(self):
        if self._current_filter == "All Files":
            self._filtered_groups = list(self._all_groups)
        else:
            self._filtered_groups = [
                g for g in self._all_groups 
                if g.get_category() == self._current_filter
            ]

    def _get_current_group(self):
        if 0 <= self._current_group_idx < len(self._filtered_groups):
            return self._filtered_groups[self._current_group_idx]
        return None

    def _populate_group_list(self):
        while self.group_list_layout.count():
            item = self.group_list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for group in self._filtered_groups:
            item = GroupListItem(group.group_id, group)
            item.clicked.connect(self._on_group_clicked)
            item.checkbox_changed.connect(self._on_group_checkbox_changed)

            keep_map = self._keep_states.get(group.group_id, {})
            all_delete = all(not keep_map.get(p, True) for p in group.paths)
            item.checkbox.setChecked(all_delete)

            self.group_list_layout.addWidget(item)

        self.group_list_layout.addStretch()

    def _update_display(self):
        group = self._get_current_group()
        if not group:
            return

        keep_map = self._keep_states.get(group.group_id, {})

        self.group_counter.setText(
            f"Group {self._current_group_idx + 1} of {len(self._filtered_groups)} "
            f"(ID: {group.group_id + 1})"
        )
        self.prev_group_btn.setEnabled(self._current_group_idx > 0)
        self.next_group_btn.setEnabled(self._current_group_idx < len(self._filtered_groups) - 1)

        display_paths = group.paths[:2] if len(group.paths) >= 2 else group.paths
        self.comparison.set_comparison(display_paths, group.similarity)

        self._populate_file_table(group, keep_map)

        kept_files = [p for p in group.paths if keep_map.get(p, True)]
        preview_file = kept_files[0] if kept_files else (group.paths[0] if group.paths else None)
        if preview_file:
            self._update_preview(preview_file)

        for i in range(self.group_list_layout.count()):
            item = self.group_list_layout.itemAt(i)
            if item and isinstance(item.widget(), GroupListItem):
                item.widget().set_selected(item.widget().group_id == group.group_id)

    def _populate_file_table(self, group, keep_map):
        self.file_table.setRowCount(0)

        for row, path in enumerate(group.paths):
            self.file_table.insertRow(row)

            delete_checkbox = QTableWidgetItem()
            delete_checkbox.setFlags(delete_checkbox.flags() | Qt.ItemIsUserCheckable)
            is_delete = not keep_map.get(path, True)
            delete_checkbox.setCheckState(Qt.Checked if is_delete else Qt.Unchecked)
            delete_checkbox.setData(Qt.UserRole, path)
            self.file_table.setItem(row, 0, delete_checkbox)

            name = f"[{row + 1}] {Path(path).name}"
            name_item = QTableWidgetItem(name)
            name_item.setToolTip(f"Press {row + 1} to keep this file\n{path}")
            self.file_table.setItem(row, 1, name_item)

            try:
                size = os.path.getsize(path)
            except:
                size = 0
            size_item = QTableWidgetItem(format_bytes(size))
            size_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.file_table.setItem(row, 2, size_item)

        self.file_table.resizeColumnsToContents()

    def _update_preview(self, file_path: str):
        if is_image_file(file_path):
            pix = QPixmap(file_path)
            if not pix.isNull():
                scaled = pix.scaled(240, 240, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self.preview_label.setPixmap(scaled)
                self.preview_label.setStyleSheet("")
            else:
                self.preview_label.setText("❌")
                self.preview_label.setStyleSheet("font-size: 48px;")
        else:
            self.preview_label.setText(file_emoji(file_path))
            self.preview_label.setStyleSheet("font-size: 64px;")

        self.detail_name.setText(f"Name: {Path(file_path).name}")
        self.detail_path.setText(f"Path: {truncate_text(file_path, 50)}")
        self.detail_category.setText(f"Category: {get_file_category(file_path)}")
        try:
            st = os.stat(file_path)
            self.detail_size.setText(f"Size: {format_bytes(st.st_size)}")
            import datetime
            mtime = datetime.datetime.fromtimestamp(st.st_mtime)
            self.detail_modified.setText(f"Modified: {mtime.strftime('%Y-%m-%d %H:%M')}")
        except:
            self.detail_size.setText("Size: -")
            self.detail_modified.setText("Modified: -")

    def _update_stats(self):
        total_groups = len(self._filtered_groups)
        total_files = sum(g.file_count for g in self._filtered_groups)
        total_size = sum(g.recoverable_bytes for g in self._filtered_groups)

        delete_count = 0
        delete_size = 0
        for g in self._filtered_groups:
            keep_map = self._keep_states.get(g.group_id, {})
            for p in g.paths:
                if not keep_map.get(p, True):
                    delete_count += 1
                    try:
                        delete_size += os.path.getsize(p)
                    except:
                        pass

        self.quick_stats.setText(f"{total_groups} groups • {total_files} files • {format_bytes(total_size)}")
        self.left_summary.setText(f"Showing {total_groups} of {len(self._all_groups)} groups")
        self.status_text.setText(f"{delete_count} files marked for deletion")
        self.selection_stats.setText(f"{delete_count} files selected for deletion ({format_bytes(delete_size)})")

        self.floating_delete.update_count(delete_count, delete_size)

    def _prev_file_in_table(self):
        current = self.file_table.currentRow()
        if current > 0:
            self.file_table.selectRow(current - 1)

    def _next_file_in_table(self):
        current = self.file_table.currentRow()
        if current < self.file_table.rowCount() - 1:
            self.file_table.selectRow(current + 1)

    def _toggle_current_file(self):
        row = self.file_table.currentRow()
        if row >= 0:
            item = self.file_table.item(row, 0)
            if item:
                current = item.checkState()
                new_state = Qt.Unchecked if current == Qt.Checked else Qt.Checked
                item.setCheckState(new_state)
                self._on_file_table_changed(item)

    def _keep_file_by_index(self, idx: int):
        group = self._get_current_group()
        if not group or idx >= len(group.paths):
            return

        keep_map = self._keep_states.get(group.group_id, {})
        for i, p in enumerate(group.paths):
            keep_map[p] = (i == idx)

        self._update_display()
        self._update_stats()

    def _on_group_clicked(self, group_id: int):
        for i, g in enumerate(self._filtered_groups):
            if g.group_id == group_id:
                self._current_group_idx = i
                break
        self._update_display()

    def _on_group_checkbox_changed(self, group_id: int, checked: bool):
        group = None
        for g in self._all_groups:
            if g.group_id == group_id:
                group = g
                break

        if not group:
            return

        keep_map = self._keep_states.get(group_id, {})

        if checked:
            for i, p in enumerate(group.paths):
                keep_map[p] = (i == 0)
        else:
            for p in group.paths:
                keep_map[p] = True

        self._update_display()
        self._update_stats()

    def _on_select_all_changed(self, state):
        check = (state == Qt.Checked)
        for g in self._filtered_groups:
            self._on_group_checkbox_changed(g.group_id, check)

    def _on_file_table_changed(self, item):
        if item.column() != 0:
            return

        path = item.data(Qt.UserRole)
        delete = (item.checkState() == Qt.Checked)

        group = self._get_current_group()
        if not group:
            return

        keep_map = self._keep_states.get(group.group_id, {})
        keep_map[path] = not delete

        kept_count = sum(1 for v in keep_map.values() if v)
        if kept_count == 0:
            item.setCheckState(Qt.Unchecked)
            keep_map[path] = True
            QMessageBox.warning(self, "Invalid Selection", "You must keep at least one file per group.")

        self._update_stats()

    def _on_comparison_keep_selected(self, file_path: str):
        group = self._get_current_group()
        if not group:
            return

        keep_map = self._keep_states.get(group.group_id, {})
        for p in keep_map:
            keep_map[p] = (p == file_path)

        self._update_display()
        self._update_stats()

    def _prev_group(self):
        if self._current_group_idx > 0:
            self._current_group_idx -= 1
            self._update_display()

    def _next_group(self):
        if self._current_group_idx < len(self._filtered_groups) - 1:
            self._current_group_idx += 1
            self._update_display()

    def _smart_keep_oldest(self):
        self._apply_smart_to_filtered("oldest")

    def _smart_keep_newest(self):
        self._apply_smart_to_filtered("newest")

    def _smart_keep_largest(self):
        self._apply_smart_to_filtered("largest")

    def _smart_keep_smallest(self):
        self._apply_smart_to_filtered("smallest")

    def _smart_keep_first(self):
        self._apply_smart_to_filtered("first")

    def _apply_smart_to_filtered(self, criteria: str):
        if not self._filtered_groups:
            return

        applied_count = 0

        for group in self._filtered_groups:
            keep_map = self._keep_states.get(group.group_id, {})

            try:
                if criteria == "first" and group.paths:
                    keeper = group.paths[0]
                elif criteria == "oldest" and group.paths:
                    keeper = min(group.paths, key=lambda p: os.path.getmtime(p))
                elif criteria == "newest" and group.paths:
                    keeper = max(group.paths, key=lambda p: os.path.getmtime(p))
                elif criteria == "largest" and group.paths:
                    keeper = max(group.paths, key=lambda p: os.path.getsize(p))
                elif criteria == "smallest" and group.paths:
                    keeper = min(group.paths, key=lambda p: os.path.getsize(p))
                else:
                    continue

                for p in group.paths:
                    keep_map[p] = (p == keeper)

                applied_count += 1
            except Exception:
                continue

        self._update_display()
        self._update_stats()

        self._bus.notify(
            "Smart Select Applied",
            f"Applied '{criteria}' to {applied_count} groups",
            2000
        )

    def _on_floating_delete_clicked(self, count: int = 0, size: int = 0):
        self._open_ceremony()

    def _open_ceremony(self):
        delete_groups = []
        total_delete_size = 0

        for g in self._filtered_groups:
            keep_map = self._keep_states.get(g.group_id, {})
            delete_paths = [p for p in g.paths if not keep_map.get(p, True)]

            if delete_paths:
                group_size = sum(os.path.getsize(p) for p in delete_paths if os.path.exists(p))
                total_delete_size += group_size
                delete_groups.append({
                    "paths": delete_paths,
                    "hint": g.hint,
                    "recoverable_bytes": group_size,
                })

        if not delete_groups:
            QMessageBox.information(
                self,
                "No Delete Candidates",
                "No files are marked for deletion.\n\n"
                "Check the 'Delete' checkbox on files you want to remove.",
            )
            return

        total_files = sum(len(g["paths"]) for g in delete_groups)

        reply = QMessageBox.question(
            self,
            "Confirm Deletion",
            f"Move {total_files} files to Trash?\n"
            f"This will free {format_bytes(total_delete_size)} of space.\n\n"
            f"You can restore from Trash if needed.",
            QMessageBox.Yes | QMessageBox.No,
        )

        if reply != QMessageBox.Yes:
            return

        self._progress_dialog = CleanupProgressDialog(total_files, self)
        self._progress_dialog.cancelled.connect(self._on_cleanup_cancelled)
        self._progress_dialog.show()

        stats = {
            "group_count": len(delete_groups),
            "file_count": total_files,
            "recoverable_bytes": total_delete_size,
        }

        cleanup_data = {"groups": delete_groups, "stats": stats}
        self.cleanup_confirmed.emit(cleanup_data)

    def _on_cleanup_cancelled(self):
        self._bus.notify("Cleanup Cancelled", "File deletion was cancelled", 2000)

    def apply_theme(self):
        c = ThemeHelper.colors()
        bg = c.get('bg', '#0f1115')
        surface = c.get('surface', '#151922')
        panel = c.get('panel', '#1a1d26')
        text = c.get('text', '#e7ecf2')
        line = c.get('line', '#2a3241')
        accent = c.get('accent', '#3b82f6')

        self.setStyleSheet(f"""
            ReviewPage {{
                background: {bg};
            }}
            QFrame#StepBar {{
                background: {surface};
                border-bottom: 1px solid {line};
            }}
            QFrame#LeftPanel {{
                background: {panel};
                border-right: 1px solid {line};
            }}
            QFrame#CenterPanel {{
                background: {bg};
            }}
            QFrame#RightPanel {{
                background: {panel};
                border-left: 1px solid {line};
            }}
            QFrame#StatusBar {{
                background: {surface};
                border-top: 1px solid {line};
            }}
            QLabel {{
                color: {text};
            }}
            QPushButton {{
                background: {accent};
                color: white;
                border: none;
                border-radius: 8px;
                padding: 8px 16px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background: {accent};
            }}
            QPushButton:disabled {{
                background: {line};
                color: #666;
            }}
            QTableWidget {{
                background: {panel};
                border: 1px solid {line};
                border-radius: 8px;
                color: {text};
                gridline-color: {line};
            }}
            QTableWidget::item:selected {{
                background: {accent};
            }}
            QHeaderView::section {{
                background: {surface};
                color: {text};
                padding: 8px;
                border: none;
                border-bottom: 2px solid {line};
            }}
            QComboBox {{
                background: {panel};
                border: 1px solid {line};
                border-radius: 6px;
                padding: 4px 8px;
                color: {text};
            }}
            QCheckBox {{
                color: {text};
            }}
            QGroupBox {{
                color: {text};
                border: 1px solid {line};
                border-radius: 8px;
                margin-top: 12px;
                padding-top: 12px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 4px;
            }}
            QScrollArea {{
                border: none;
                background: transparent;
            }}
        """)

        if hasattr(self, 'floating_delete'):
            self.floating_delete._apply_style()

    def showEvent(self, event):
        super().showEvent(event)
        self._position_floating_button()


__all__ = [
    "ReviewPage",
    "GroupData",
    "DualPaneComparison",
    "GroupListItem",
    "FloatingDeleteButton",
    "CleanupProgressDialog",
    "AsyncThumbnailLoader",
    "format_bytes",
    "extract_group_data",
    "get_file_category",
]