# cerebro/ui/pages/review_page.py
"""
CEREBRO — Review Page (Gemini 2 Edition)
Exact MacPaw Gemini 2 look & feel on Windows + all original powerful features preserved.
"""

from __future__ import annotations

import hashlib
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
    QPropertyAnimation, QEasingCurve, QThread
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
    QHeaderView, QAbstractItemView, QMessageBox, QInputDialog, QFileDialog,
    QProgressBar, QTextEdit, QGroupBox, QToolButton,
    QGraphicsDropShadowEffect, QApplication
)

from cerebro.ui.components.modern import ContentCard, PageScaffold, StickyActionBar
from cerebro.ui.components.modern._tokens import token as theme_token
from cerebro.ui.pages.base_station import BaseStation
from cerebro.ui.pages.delete_confirm_dialog import DeletionPolicyChooserDialog, DeletionPolicyChoice
from cerebro.ui.state_bus import get_state_bus
from cerebro.ui.theme_engine import get_theme_manager, current_colors
from cerebro.services.logger import log_info, log_debug


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

def _norm_path(p: Optional[str]) -> str:
    """Normalize path for use as keep_map key so lookups work across filter changes."""
    return os.path.normpath(os.path.normcase(str(p or "")))


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
        """Return current theme colors (always from theme manager, so light/dark persists)."""
        try:
            from cerebro.ui.theme_engine import current_colors
            return current_colors()
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
            w, h = int(self.size.width()), int(self.size.height())
            thumb_dir = None
            thumb_path = None
            try:
                from cerebro.services.cache_manager import get_cache_manager
                thumb_dir = Path(get_cache_manager().cache_dir) / "thumbnails"
                cache_key = hashlib.sha256(f"{self.file_path}_{w}_{h}".encode()).hexdigest()[:20]
                thumb_path = thumb_dir / f"{cache_key}.png"
                if thumb_path.exists():
                    pix = QPixmap(str(thumb_path))
                    if not pix.isNull():
                        self.signals.finished.emit(self.file_path, pix)
                        return
            except Exception:
                pass
            pix = QPixmap(self.file_path)
            if pix.isNull():
                return
            scaled = pix.scaled(self.size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            if thumb_dir is not None and thumb_path is not None:
                try:
                    thumb_dir.mkdir(parents=True, exist_ok=True)
                    scaled.save(str(thumb_path), "PNG")
                except Exception:
                    pass
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
        """Gemini-styled progress dialog: panel bg, accent border and buttons."""
        from cerebro.ui.theme_engine import current_colors
        c = current_colors()
        panel = c.get("panel", "#1a1d26")
        text = c.get("text", "#e7ecf2")
        accent = c.get("accent", "#00C4B4")
        self.setStyleSheet(f"""
            QDialog {{
                background: {panel};
                border: 3px solid {accent};
                border-radius: 20px;
            }}
            QLabel {{ color: {text}; }}
            QProgressBar::chunk {{ background: {accent}; }}
            QPushButton {{
                background: {accent};
                color: white;
                border-radius: 12px;
                font-weight: bold;
                font-size: 14px;
            }}
            QPushButton:hover {{ background: {accent}; }}
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
        self._apply_gemini_style()
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

    def _apply_gemini_style(self):
        """Gemini 2: red delete button with teal accent border."""
        from cerebro.ui.theme_engine import current_colors
        c = current_colors()
        accent = c.get("accent", "#00C4B4")
        self.setStyleSheet(f"""
            FloatingDeleteButton {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #ef4444, stop:1 #dc2626);
                color: white;
                border: 3px solid {accent};
                border-radius: 30px;
                font-weight: bold;
                font-size: 13px;
                padding: 8px;
            }}
            FloatingDeleteButton:hover {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #f87171, stop:1 #ef4444);
                border-color: {accent};
            }}
            FloatingDeleteButton:disabled {{
                background: #4b5563;
                border-color: #6b7280;
                color: #9ca3af;
            }}
            FloatingDeleteButton:pressed {{
                background: #b91c1c;
            }}
        """)

    def _apply_style(self):
        """Alias for theme refresh."""
        self._apply_gemini_style()

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

def _compute_group_size(paths: List[str]) -> int:
    total = 0
    for p in paths:
        try:
            total += os.path.getsize(p)
        except Exception:
            pass
    return total


def extract_group_data(group: Any, idx: int = 0) -> GroupData:
    if isinstance(group, dict):
        raw_paths = group.get("paths") or group.get("files") or group.get("items") or []
        paths = [str(p) for p in raw_paths]
        hint = str(group.get("reason") or group.get("hint") or group.get("description") or "")
        recoverable = int(group.get("recoverable_bytes", group.get("recoverable", 0)) or 0)
        if recoverable == 0 and paths:
            recoverable = _compute_group_size(paths)
        similarity = float(group.get("similarity", 100.0) or 100.0)
        return GroupData(paths=paths, hint=hint, recoverable_bytes=recoverable,
                        similarity=similarity, group_id=idx)
    if isinstance(group, (list, tuple)):
        paths = [str(p) for p in group]
        return GroupData(paths=paths, group_id=idx, recoverable_bytes=_compute_group_size(paths) if paths else 0)
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
        keep_btn = QPushButton(f"✔ Keep {label_text}")
        keep_btn.setObjectName(f"keep_{label_text}")
        keep_btn.setCursor(Qt.PointingHandCursor)
        keep_btn.clicked.connect(lambda: self._on_keep_clicked(label_text))
        btn_row.addStretch()
        btn_row.addWidget(keep_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)
        if label_text == "Original":
            self.left_keep_btn = keep_btn
        else:
            self.right_keep_btn = keep_btn

        return pane

    def set_kept_path(self, kept_path: Optional[str]) -> None:
        """Highlight only the Keep button for the given path; unhighlight the other."""
        try:
            kept_norm = os.path.normpath(os.path.normcase(str(kept_path or "")))
            highlight = "background: #3b82f6; color: white; font-weight: bold; border-radius: 8px; padding: 8px;"
            neutral = "background: transparent; color: #94a3b8; border: 1px solid #475569; border-radius: 8px; padding: 8px;"
            if len(self._current_paths) >= 1 and os.path.normpath(os.path.normcase(self._current_paths[0])) == kept_norm:
                self.left_keep_btn.setStyleSheet(highlight)
                if len(self._current_paths) >= 2:
                    self.right_keep_btn.setStyleSheet(neutral)
            elif len(self._current_paths) >= 2 and os.path.normpath(os.path.normcase(self._current_paths[1])) == kept_norm:
                self.right_keep_btn.setStyleSheet(highlight)
                self.left_keep_btn.setStyleSheet(neutral)
            else:
                self.left_keep_btn.setStyleSheet(neutral)
                if len(self._current_paths) >= 2:
                    self.right_keep_btn.setStyleSheet(neutral)
        except Exception:
            pass

    def set_compare_mode(self, on: bool) -> None:
        """Toggle side-by-side compare visibility (already dual-pane)."""
        self.setVisible(True)

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
        self.checkbox.setTristate(True)
        self.checkbox.setToolTip(
            "Unchecked: keep all • Checked: mark all for deletion (keep one) • Partially checked: mixed"
        )
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

        gate_badge = QLabel("Safe")
        gate_badge.setToolTip("Deletion Gate — Safe: keeps at least one copy.")
        gate_badge.setStyleSheet("""
            background: rgba(0,196,180,0.25);
            color: #00C4B4;
            border-radius: 8px;
            padding: 2px 6px;
            font-size: 10px;
            font-weight: bold;
        """)
        layout.addWidget(gate_badge)

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
        if state == Qt.PartiallyChecked:
            self.checkbox.blockSignals(True)
            self.checkbox.setCheckState(Qt.Checked)
            self.checkbox.blockSignals(False)
            self.checkbox_changed.emit(self.group_id, True)
        else:
            self.checkbox_changed.emit(self.group_id, state == Qt.Checked)

    def set_selected(self, selected: bool):
        self._selected = selected
        self.update_style()

    def update_style(self):
        """Gemini 2 card style: panel background, border."""
        c = ThemeHelper.colors()
        if self._selected:
            bg = c.get("accent", "#00C4B4")
            border = c.get("accent", "#00C4B4")
            text = "white"
        else:
            bg = c.get("panel", c.get("surface", "#151922"))
            border = c.get("border", c.get("line", "#2a3241"))
            text = c.get("text", "#e7ecf2")

        self.setStyleSheet(f"""
            QFrame#GroupListItem {{
                background: {bg};
                border: 1px solid {border};
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
# SMART SELECT WORKER (runs off main thread to avoid UI freeze on 500k+ files)
# ==============================================================================

class SmartSelectWorker(QThread):
    """Computes keep/delete per group in background; emits result for main thread to apply."""
    finished_result = Signal(object)  # group_id -> {path: bool}; use object to avoid Shiboken dict copy-convert

    def __init__(self, groups_data: List[tuple], criteria: str, parent=None):
        super().__init__(parent)
        self._groups_data = groups_data  # list of (group_id, paths)
        self._criteria = criteria

    def run(self):
        result = {}
        for group_id, paths in self._groups_data:
            if not paths:
                continue
            try:
                if self._criteria == "first":
                    keeper = paths[0]
                elif self._criteria == "oldest":
                    keeper = min(paths, key=lambda p: os.path.getmtime(p))
                elif self._criteria == "newest":
                    keeper = max(paths, key=lambda p: os.path.getmtime(p))
                elif self._criteria == "largest":
                    keeper = max(paths, key=lambda p: os.path.getsize(p))
                elif self._criteria == "smallest":
                    keeper = min(paths, key=lambda p: os.path.getsize(p))
                else:
                    continue
                result[group_id] = {p: (p == keeper) for p in paths}
            except Exception:
                continue
        self.finished_result.emit(result)


# Max group list widgets to create (avoids freeze with 100k+ groups)
MAX_GROUP_LIST_ITEMS = 500

# Chunk size for lazy delete_size calculation
STATS_SIZE_CHUNK = 250


# ==============================================================================
# MAIN REVIEW PAGE
# ==============================================================================

class ReviewPage(BaseStation):
    cleanup_confirmed = Signal(object)  # DeletionPlan dict; use object to avoid Shiboken dict copy-convert

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ReviewPage")
        self._result = {}
        self._bus = get_state_bus()

        self._all_groups: List[GroupData] = []
        self._filtered_groups: List[GroupData] = []
        self._current_group_idx = -1
        self._keep_states: Dict[int, Dict[str, bool]] = {}

        self._current_filter = "All Files"
        self._progress_dialog = None
        self._smart_select_worker = None
        self._size_calc_timer = None
        self._pending_size_paths = []
        self._batch_updating = False

        self._thumb_loader = AsyncThumbnailLoader(self)

        self._build_gemini_ui()
        self._setup_keyboard_shortcuts()
        self._wire()
        self.apply_theme()

    def _build_gemini_ui(self):
        """Gemini 2 layout: PageScaffold + ContentCard + StickyActionBar."""
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._scaffold = PageScaffold(self, show_sidebar=False, show_sticky_action=True)
        self.step_bar = self._build_step_bar()
        self._scaffold.set_header(self.step_bar)

        # Main content: card with splitter (left | center | right)
        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(4)
        splitter.setChildrenCollapsible(False)

        self.left_panel = self._build_left_panel()
        self.center_panel = self._build_center_panel()
        self.right_panel = self._build_right_panel()
        splitter.addWidget(self.left_panel)
        splitter.addWidget(self.center_panel)
        splitter.addWidget(self.right_panel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        splitter.setStretchFactor(2, 1)

        # Prominent large delete button (created early for status bar)
        self._large_delete_btn = QPushButton("Delete (0)")
        self._large_delete_btn.setObjectName("LargeDeleteButton")
        self._large_delete_btn.setMinimumHeight(48)
        self._large_delete_btn.setCursor(Qt.PointingHandCursor)
        self._large_delete_btn.setToolTip("Delete selected files. Routes through confirmation.")
        self._large_delete_btn.clicked.connect(self._open_ceremony)
        self._large_delete_btn.setEnabled(False)

        content_wrapper = QWidget()
        wrap_layout = QVBoxLayout(content_wrapper)
        wrap_layout.setContentsMargins(0, 0, 0, 0)
        wrap_layout.setSpacing(0)
        card = ContentCard()
        card.set_content(splitter)
        wrap_layout.addWidget(card, 1)

        self.status_bar = self._build_status_bar()
        wrap_layout.addWidget(self.status_bar)

        self._scaffold.set_content(content_wrapper)

        self._sticky = StickyActionBar()
        self._sticky.set_primary_text("Export List")
        self._sticky.primary_clicked.connect(self._on_export_list)
        self._scaffold.set_sticky_action(self._sticky)

        root.addWidget(self._scaffold, 1)

        # Floating delete button (Gemini teal accent style)
        self.floating_delete = FloatingDeleteButton(self)
        self.floating_delete.clicked_with_count.connect(self._on_floating_delete_clicked)

        # Smart Select FAB (Gemini style)
        self.smart_select_fab = QPushButton("Smart Select\n0 safe", self)
        self.smart_select_fab.setObjectName("SmartSelectFAB")
        self.smart_select_fab.setFixedSize(140, 52)
        self.smart_select_fab.setCursor(Qt.PointingHandCursor)
        self.smart_select_fab.setToolTip("One-click rules: keep newest, oldest, largest, smallest. Deletion Gate keeps at least one copy.")
        self.smart_select_fab.clicked.connect(self._on_smart_select_fab_clicked)
        c = current_colors()
        self.smart_select_fab.setStyleSheet(f"""
            QPushButton#SmartSelectFAB {{
                background: {c.get('accent', '#00C4B4')};
                color: white;
                border: none;
                border-radius: 12px;
                font-weight: bold;
                font-size: 12px;
            }}
            QPushButton#SmartSelectFAB:hover {{ opacity: 0.9; }}
        """)

    def _on_compare_mode_toggled(self, checked: bool) -> None:
        """Toggle side-by-side compare in center panel."""
        if hasattr(self, "comparison"):
            self.comparison.set_compare_mode(checked)

    def _on_smart_select_fab_clicked(self) -> None:
        """Focus Smart Select panel (right side); user can then click a rule."""
        self.focus_smart_select()

    def focus_smart_select(self) -> None:
        """Focus Smart Select panel (used by Ctrl+S). Raises right panel so rules are visible."""
        if hasattr(self, "right_panel") and self.right_panel:
            self.right_panel.raise_()
            self.right_panel.setFocus()
        if hasattr(self, "smart_select_fab") and self.smart_select_fab:
            self.smart_select_fab.setFocus()
        self.setFocus()

    def confirm_delete_selected(self) -> None:
        """Called by global Delete shortcut."""
        self._open_ceremony()

    def on_enter(self) -> None:
        """When Review becomes the current page, refresh stats so the delete button state is correct."""
        super().on_enter()
        self._update_stats()
        self._refresh_delete_button()
        if hasattr(self, "floating_delete") and self.floating_delete:
            self.floating_delete.show()
            self.floating_delete.raise_()
            self.floating_delete.update()
            self.floating_delete.repaint()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._position_floating_button()

    def _position_floating_button(self):
        margin = 30
        if hasattr(self, 'smart_select_fab'):
            self.smart_select_fab.show()
            self.smart_select_fab.move(
                self.width() - self.smart_select_fab.width() - margin - 200,
                self.height() - self.smart_select_fab.height() - margin - 40
            )
            self.smart_select_fab.raise_()
        if hasattr(self, 'floating_delete'):
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

        acc = theme_token("accent")
        muted = theme_token("muted")
        steps = [("1", "Scan", False), ("2", "Analyze", False), ("3", "Resolve Duplicates", True)]
        self._step_labels = []
        for num, text, active in steps:
            step = QLabel(f"Step {num}: {text}")
            step.setStyleSheet(f"""
                font-weight: {'bold' if active else 'normal'};
                font-size: 13px;
                color: {acc if active else muted};
                padding: 4px 12px;
                background: rgba(0,196,180,0.12);
                border-radius: 16px;
            """ if active else f"""
                font-weight: normal;
                font-size: 13px;
                color: {muted};
                padding: 4px 12px;
                background: transparent;
                border-radius: 16px;
            """)
            self._step_labels.append((step, active))
            layout.addWidget(step)

        layout.addStretch()

        self.quick_stats = QLabel("0 duplicates found")
        self.quick_stats.setStyleSheet(f"font-size: 13px; color: {muted};")
        layout.addWidget(self.quick_stats)

        return bar

    def _build_left_panel(self):
        panel = QFrame()
        panel.setObjectName("LeftPanel")
        panel.setMinimumWidth(250)
        panel.setMaximumWidth(350)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        header = QHBoxLayout()
        self.select_all_cb = QCheckBox("Select All for Delete")
        self.select_all_cb.setTristate(True)
        self.select_all_cb.setToolTip(
            "Unchecked: no deletions • Checked: all groups mark for delete (one kept per group) • Partially: mixed. "
            "Deletion Gate = never deletes the last copy."
        )
        self.select_all_cb.stateChanged.connect(self._on_select_all_changed)
        header.addWidget(self.select_all_cb)
        header.addStretch()
        layout.addLayout(header)

        filter_layout = QHBoxLayout()
        filter_layout.setSpacing(12)
        filter_layout.addWidget(QLabel("Filter:"))
        self.filter_combo = QComboBox()
        self.filter_combo.setMinimumWidth(180)
        self.filter_combo.setMinimumHeight(36)
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

        preview_header_row = QHBoxLayout()
        preview_header = QLabel("Preview")
        preview_header.setStyleSheet("font-size: 16px; font-weight: bold;")
        preview_header.setToolTip("Preview selected file. Pane is dockable and resizable; use zoom/compare for images.")
        preview_header_row.addWidget(preview_header)
        self.compare_mode_cb = QCheckBox("Compare")
        self.compare_mode_cb.setToolTip("Side-by-side compare mode for duplicate files in this group.")
        self.compare_mode_cb.toggled.connect(self._on_compare_mode_toggled)
        preview_header_row.addStretch()
        preview_header_row.addWidget(self.compare_mode_cb)
        layout.addLayout(preview_header_row)

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
        smart.setToolTip(
            "One-click rules to auto-pick which file to keep in each duplicate group "
            "(oldest, newest, largest, smallest, or first). Applies only to currently filtered groups."
        )
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
        bar.setFixedHeight(52)

        layout = QHBoxLayout(bar)
        layout.setContentsMargins(20, 8, 20, 8)

        self.status_text = QLabel("Ready")
        layout.addWidget(self.status_text)

        layout.addStretch()

        self.selection_stats = QLabel("0 files selected for deletion (0 B)")
        self.selection_stats.setStyleSheet("font-weight: bold; color: #ef4444;")
        layout.addWidget(self.selection_stats)

        # Prominent large delete button (unified orchestration)
        if hasattr(self, "_large_delete_btn") and self._large_delete_btn:
            layout.addWidget(self._large_delete_btn)

        self.export_list_btn = QPushButton("Export List")
        self.export_list_btn.setToolTip("Export current duplicate list to CSV or JSON.")
        self.export_list_btn.setCursor(Qt.PointingHandCursor)
        self.export_list_btn.clicked.connect(self._on_export_list)
        layout.addWidget(self.export_list_btn)

        self._status_hint = QLabel("Shortcuts: ←→ Navigate | Space Toggle | Delete Confirm | 1-5 Keep")
        self._status_hint.setStyleSheet(f"font-size: 10px; color: {theme_token('muted')}; margin-left: 20px;")
        layout.addWidget(self._status_hint)

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
            self._keep_states[g.group_id] = {_norm_path(p): True for p in g.paths}

        self._current_group_idx = 0 if self._filtered_groups else -1

        self._populate_group_list()
        self._update_display()
        self._update_stats()
        self._refresh_delete_button()

    def refresh_theme(self) -> None:
        """Gemini 2 full theme refresh — scaffold, panels, FAB, floating delete."""
        super().refresh_theme()
        self.apply_theme()
        c = current_colors()
        panel = c.get("panel", "#151922")
        accent = c.get("accent", "#00C4B4")
        if hasattr(self, "left_panel") and self.left_panel:
            self.left_panel.setStyleSheet(f"QFrame#LeftPanel {{ background: {panel}; border-radius: 12px; }}")
        if hasattr(self, "right_panel") and self.right_panel:
            self.right_panel.setStyleSheet(f"QFrame#RightPanel {{ background: {panel}; border-radius: 12px; }}")
        if hasattr(self, "smart_select_fab") and self.smart_select_fab:
            self.smart_select_fab.setStyleSheet(f"""
                QPushButton#SmartSelectFAB {{ background: {accent}; color: white; border-radius: 12px; font-weight: bold; }}
                QPushButton#SmartSelectFAB:hover {{ opacity: 0.9; }}
            """)
        if hasattr(self, "floating_delete") and self.floating_delete and hasattr(self.floating_delete, "_apply_gemini_style"):
            self.floating_delete._apply_gemini_style()
        if hasattr(self, "_scaffold") and self._scaffold and hasattr(self._scaffold, "refresh_theme"):
            self._scaffold.refresh_theme()
        if hasattr(self, "_sticky") and self._sticky and hasattr(self._sticky, "refresh_theme"):
            self._sticky.refresh_theme()
        self.update()
        self.repaint()

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

        total = len(self._filtered_groups)
        cap = min(total, MAX_GROUP_LIST_ITEMS)
        for group in self._filtered_groups[:cap]:
            item = GroupListItem(group.group_id, group)
            item.clicked.connect(self._on_group_clicked)
            item.checkbox_changed.connect(self._on_group_checkbox_changed)
            keep_map = self._keep_states.get(group.group_id, {})
            delete_count = sum(
                1 for p in group.paths if not keep_map.get(_norm_path(str(p) if p else ""), True)
            )
            all_kept = delete_count == 0
            all_delete = delete_count == len(group.paths) - 1 and len(group.paths) >= 2
            item.checkbox.blockSignals(True)
            if all_kept:
                item.checkbox.setCheckState(Qt.Unchecked)
            elif all_delete:
                item.checkbox.setCheckState(Qt.Checked)
            else:
                item.checkbox.setCheckState(Qt.PartiallyChecked)
            item.checkbox.blockSignals(False)
            self.group_list_layout.addWidget(item)

        if total > cap:
            cap_label = QLabel(f"Showing first {cap} of {total} groups. Use Prev/Next to navigate all.")
            cap_label.setStyleSheet("color: #94a3b8; font-size: 11px; padding: 8px;")
            cap_label.setWordWrap(True)
            self.group_list_layout.addWidget(cap_label)
        self.group_list_layout.addStretch()

    def _update_group_list_item(self, group_id: int) -> None:
        """Sync the GroupListItem checkbox for group_id to current keep_map (avoids out-of-sync after file toggles)."""
        for i in range(self.group_list_layout.count()):
            item = self.group_list_layout.itemAt(i)
            if not item:
                continue
            w = item.widget()
            if not isinstance(w, GroupListItem) or w.group_id != group_id:
                continue
            group = next((g for g in self._all_groups if g.group_id == group_id), None)
            if not group:
                return
            keep_map = self._keep_states.get(group_id, {})
            delete_count = sum(
                1 for p in group.paths if not keep_map.get(_norm_path(str(p) if p else ""), True)
            )
            all_kept = delete_count == 0
            all_delete = delete_count == len(group.paths) - 1 and len(group.paths) >= 2
            w.checkbox.blockSignals(True)
            if all_kept:
                w.checkbox.setCheckState(Qt.Unchecked)
            elif all_delete:
                w.checkbox.setCheckState(Qt.Checked)
            else:
                w.checkbox.setCheckState(Qt.PartiallyChecked)
            w.checkbox.blockSignals(False)
            break

    def _sync_group_checkboxes(self) -> None:
        """Set all visible group list item checkboxes from current _keep_states (used after batch updates)."""
        for i in range(self.group_list_layout.count()):
            item = self.group_list_layout.itemAt(i)
            if not item:
                continue
            w = item.widget()
            if not isinstance(w, GroupListItem):
                continue
            group_id = w.group_id
            group = next((g for g in self._all_groups if g.group_id == group_id), None)
            if not group:
                continue
            keep_map = self._keep_states.get(group_id, {})
            delete_count = sum(
                1 for p in group.paths if not keep_map.get(_norm_path(str(p) if p else ""), True)
            )
            all_kept = delete_count == 0
            all_delete = delete_count == len(group.paths) - 1 and len(group.paths) >= 2
            w.checkbox.blockSignals(True)
            if all_kept:
                w.checkbox.setCheckState(Qt.Unchecked)
            elif all_delete:
                w.checkbox.setCheckState(Qt.Checked)
            else:
                w.checkbox.setCheckState(Qt.PartiallyChecked)
            w.checkbox.blockSignals(False)

    def _refresh_all_ui(self) -> None:
        """Sync group checkboxes, current group display, and stats (call once after batch updates)."""
        self._sync_group_checkboxes()
        self._update_display()
        self._update_stats()

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
        kept_files = [p for p in group.paths if keep_map.get(_norm_path(p), True)]
        kept_path = kept_files[0] if kept_files else (group.paths[0] if group.paths else None)
        if hasattr(self.comparison, "set_kept_path") and kept_path:
            self.comparison.set_kept_path(kept_path)

        self._populate_file_table(group, keep_map)

        if kept_path:
            self._update_preview(kept_path)

        for i in range(self.group_list_layout.count()):
            item = self.group_list_layout.itemAt(i)
            if item and isinstance(item.widget(), GroupListItem):
                item.widget().set_selected(item.widget().group_id == group.group_id)

    def _populate_file_table(self, group, keep_map):
        self.file_table.blockSignals(True)
        try:
            self.file_table.setRowCount(0)
            for row, path in enumerate(group.paths):
                self.file_table.insertRow(row)
                delete_checkbox = QTableWidgetItem()
                delete_checkbox.setFlags(delete_checkbox.flags() | Qt.ItemIsUserCheckable)
                is_delete = not keep_map.get(_norm_path(path), True)
                delete_checkbox.setCheckState(Qt.Checked if is_delete else Qt.Unchecked)
                path_str = str(path) if path is not None else ""
                delete_checkbox.setData(Qt.UserRole, path_str)
                self.file_table.setItem(row, 0, delete_checkbox)
                name = f"[{row + 1}] {Path(path).name}"
                name_item = QTableWidgetItem(name)
                name_item.setToolTip(f"Press {row + 1} to keep this file\n{path}")
                self.file_table.setItem(row, 1, name_item)
                try:
                    size = os.path.getsize(path)
                except Exception:
                    size = 0
                size_item = QTableWidgetItem(format_bytes(size))
                size_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.file_table.setItem(row, 2, size_item)
            self.file_table.resizeColumnsToContents()
        finally:
            self.file_table.blockSignals(False)

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

    def _compute_delete_count(self):
        """Single source of truth: count paths marked for delete from _keep_states + _filtered_groups."""
        delete_count = 0
        delete_paths = []
        for g in self._filtered_groups:
            keep_map = self._keep_states.get(g.group_id, {})
            for p in g.paths:
                key = _norm_path(str(p) if p else "")
                if not keep_map.get(key, True):
                    delete_count += 1
                    delete_paths.append(p)
        return delete_count, delete_paths

    def _refresh_delete_button(self) -> None:
        """Force-update floating delete button from current _keep_states (call after any selection change)."""
        delete_count, delete_paths = self._compute_delete_count()
        if not hasattr(self, "floating_delete") or self.floating_delete is None:
            return
        size = 0
        if len(delete_paths) <= STATS_SIZE_CHUNK:
            for p in delete_paths:
                try:
                    size += os.path.getsize(p)
                except Exception:
                    pass
        self.floating_delete.update_count(delete_count, size)
        self.floating_delete.setEnabled(delete_count > 0)
        self.floating_delete.update()
        self.floating_delete.repaint()

    def _update_stats(self):
        total_groups = len(self._filtered_groups)
        total_files = sum(g.file_count for g in self._filtered_groups)
        total_size = sum(g.recoverable_bytes for g in self._filtered_groups)

        delete_count, delete_paths = self._compute_delete_count()
        n_none = 0
        n_full = 0
        for g in self._filtered_groups:
            keep_map = self._keep_states.get(g.group_id, {})
            delete_in_group = sum(
                1 for p in g.paths if not keep_map.get(_norm_path(str(p) if p else ""), True)
            )
            if delete_in_group == 0:
                n_none += 1
            elif delete_in_group == len(g.paths) - 1 and len(g.paths) >= 2:
                n_full += 1

        if hasattr(self, "select_all_cb") and self.select_all_cb is not None:
            self.select_all_cb.blockSignals(True)
            if total_groups == 0:
                self.select_all_cb.setCheckState(Qt.Unchecked)
            elif n_none == total_groups:
                self.select_all_cb.setCheckState(Qt.Unchecked)
            elif n_full == total_groups:
                self.select_all_cb.setCheckState(Qt.Checked)
            else:
                self.select_all_cb.setCheckState(Qt.PartiallyChecked)
            self.select_all_cb.blockSignals(False)

        if len(delete_paths) <= STATS_SIZE_CHUNK:
            delete_size = 0
            for p in delete_paths:
                try:
                    delete_size += os.path.getsize(p)
                except Exception:
                    pass
            self._apply_stats_ui(delete_count, delete_size, total_groups, total_files, total_size)
        else:
            self._apply_stats_ui(delete_count, 0, total_groups, total_files, total_size)
            if self._size_calc_timer is not None:
                try:
                    self._size_calc_timer.stop()
                except Exception:
                    pass
            self._pending_size_paths = delete_paths
            self._pending_size_total = 0
            self._pending_size_count = delete_count
            QTimer.singleShot(0, self._chunked_size_next)
        self._refresh_delete_button()

    def _apply_stats_ui(self, delete_count: int, delete_size: int, total_groups: int,
                        total_files: int, total_size: int):
        self.quick_stats.setText(f"{total_groups} groups • {total_files} files • {format_bytes(total_size)}")
        self.left_summary.setText(f"Showing {total_groups} of {len(self._all_groups)} groups")
        self.status_text.setText(f"{delete_count} files marked for deletion")
        self.selection_stats.setText(f"{delete_count} files selected for deletion ({format_bytes(delete_size)})")
        if hasattr(self, "floating_delete") and self.floating_delete is not None:
            self.floating_delete.update_count(delete_count, delete_size)
            self.floating_delete.setEnabled(delete_count > 0)
            self.floating_delete.update()
            self.floating_delete.repaint()
        if hasattr(self, "_large_delete_btn") and self._large_delete_btn is not None:
            self._large_delete_btn.setText(f"Delete ({delete_count})")
            self._large_delete_btn.setEnabled(delete_count > 0)
        safe_count = total_files - delete_count
        if hasattr(self, "smart_select_fab"):
            self.smart_select_fab.setText(f"Smart Select\n{safe_count} safe")

    def _chunked_size_next(self):
        if not self._pending_size_paths:
            return
        chunk = self._pending_size_paths[:STATS_SIZE_CHUNK]
        self._pending_size_paths = self._pending_size_paths[STATS_SIZE_CHUNK:]
        for p in chunk:
            try:
                self._pending_size_total += os.path.getsize(p)
            except Exception:
                pass
        if not self._pending_size_paths:
            cnt = getattr(self, "_pending_size_count", 0)
            self.selection_stats.setText(f"{cnt} files selected for deletion ({format_bytes(self._pending_size_total)})")
            if hasattr(self, "floating_delete") and self.floating_delete is not None:
                self.floating_delete.update_count(cnt, self._pending_size_total)
                self.floating_delete.setEnabled(cnt > 0)
                self.floating_delete.update()
                self.floating_delete.repaint()
            if hasattr(self, "_large_delete_btn") and self._large_delete_btn is not None:
                self._large_delete_btn.setText(f"Delete ({cnt})")
                self._large_delete_btn.setEnabled(cnt > 0)
            return
        QTimer.singleShot(0, self._chunked_size_next)

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
            keep_map[_norm_path(p)] = (i == idx)
        self._keep_states[group.group_id] = keep_map
        self._update_display()
        self._update_stats()
        self._update_group_list_item(group.group_id)
        self._refresh_delete_button()

    def _on_group_clicked(self, group_id: int):
        for i, g in enumerate(self._filtered_groups):
            if g.group_id == group_id:
                self._current_group_idx = i
                break
        self._update_display()

    def _on_group_checkbox_changed(self, group_id: int, checked: bool):
        if self._batch_updating:
            return
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
                keep_map[_norm_path(p)] = (i == 0)
        else:
            for p in group.paths:
                keep_map[_norm_path(p)] = True

        self._keep_states[group_id] = keep_map
        self._update_display()
        self._update_stats()
        self._update_group_list_item(group_id)
        self._refresh_delete_button()

    def _on_select_all_changed(self, state):
        check = (state == Qt.Checked)
        self._batch_updating = True
        try:
            for g in self._filtered_groups:
                keep_map = {}
                for i, p in enumerate(g.paths):
                    keep_map[_norm_path(p)] = (i == 0) if check else True
                self._keep_states[g.group_id] = keep_map
        finally:
            self._batch_updating = False
        self._refresh_all_ui()

    def _on_file_table_changed(self, item):
        if self._batch_updating:
            return
        if item is None or item.column() != 0:
            return

        path = item.data(Qt.UserRole)
        path = str(path).strip() if path is not None else ""
        delete = (item.checkState() == Qt.Checked)

        group = self._get_current_group()
        if not group or not path:
            return

        keep_map = self._keep_states.get(group.group_id, {})
        if not keep_map:
            keep_map = {_norm_path(str(p) or ""): True for p in group.paths}
        keep_map[_norm_path(path)] = not delete

        kept_count = sum(1 for v in keep_map.values() if v)
        if kept_count == 0:
            item.setCheckState(Qt.Unchecked)
            keep_map[_norm_path(path)] = True
            QMessageBox.warning(self, "Invalid Selection", "You must keep at least one file per group.")

        self._keep_states[group.group_id] = keep_map
        self._update_display()
        self._update_stats()
        self._update_group_list_item(group.group_id)
        self._refresh_delete_button()

    def _on_comparison_keep_selected(self, file_path: str):
        if self._batch_updating:
            return
        group = self._get_current_group()
        if not group:
            return

        file_path_norm = _norm_path(file_path)
        keep_map = self._keep_states.get(group.group_id, {})
        if not keep_map:
            keep_map = {_norm_path(p): True for p in group.paths}
        for p in group.paths:
            keep_map[_norm_path(p)] = (_norm_path(p) == file_path_norm)
        self._keep_states[group.group_id] = keep_map

        self._update_display()
        self._update_stats()
        self._update_group_list_item(group.group_id)
        self._refresh_delete_button()

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
        if self._smart_select_worker is not None and self._smart_select_worker.isRunning():
            self._bus.notify("Busy", "Smart Select already running…", 1500)
            return

        groups_data = [(g.group_id, list(g.paths)) for g in self._filtered_groups]
        self._smart_select_worker = SmartSelectWorker(groups_data, criteria, self)
        self._smart_select_worker.finished_result.connect(self._on_smart_select_finished)
        self._smart_select_worker.finished.connect(self._smart_select_worker.deleteLater)
        self._smart_select_worker.finished.connect(lambda: setattr(self, "_smart_select_worker", None))
        if hasattr(self, "status_text"):
            self.status_text.setText("Applying Smart Select…")
        self._smart_select_worker.start()

    @Slot(object)
    def _on_smart_select_finished(self, result: dict):
        result = result or {}
        self._batch_updating = True
        try:
            for group_id, keep_map in result.items():
                self._keep_states[group_id] = {_norm_path(p): v for p, v in (keep_map or {}).items()}
        finally:
            self._batch_updating = False
        self._refresh_all_ui()
        if hasattr(self, "status_text"):
            self.status_text.setText(f"{len(result)} groups updated")
        self._bus.notify(
            "Smart Select Applied",
            f"Applied to {len(result)} groups",
            2000
        )

    def _on_export_list(self):
        """Export current duplicate list to CSV or JSON."""
        groups = self._filtered_groups or self._all_groups
        if not groups:
            QMessageBox.information(self, "Export List", "No duplicate groups to export.")
            return
        path, selected_filter = QFileDialog.getSaveFileName(
            self, "Export Duplicate List", "", "CSV (*.csv);;JSON (*.json)"
        )
        if not path:
            return
        try:
            if path.endswith(".json") or "JSON" in (selected_filter or ""):
                import json
                data = [
                    {"group_id": g.group_id, "paths": g.paths, "similarity": getattr(g, "similarity", None)}
                    for g in groups
                ]
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
            else:
                with open(path, "w", encoding="utf-8") as f:
                    f.write("group_id,path,similarity\n")
                    for g in groups:
                        sim = getattr(g, "similarity", "") or ""
                        for p in g.paths:
                            f.write(f"{g.group_id},{repr(p)},{sim}\n")
            QMessageBox.information(self, "Export List", f"Exported to {path}")
        except Exception as e:
            QMessageBox.warning(self, "Export Error", str(e))

    def _on_floating_delete_clicked(self, count: int = 0, size: int = 0):
        self._open_ceremony()

    def _open_ceremony(self):
        """Unified deletion orchestration entrypoint. All delete triggers route here."""
        log_debug("[Delete] _open_ceremony triggered")
        delete_groups = []
        total_delete_size = 0

        for idx, g in enumerate(self._filtered_groups):
            keep_map = self._keep_states.get(g.group_id, {})
            kept_paths = [p for p in g.paths if keep_map.get(_norm_path(p), True)]
            delete_paths = [p for p in g.paths if not keep_map.get(_norm_path(p), True)]

            if not delete_paths:
                continue
            # Pipeline requires exactly one "keep" per group; use first kept path (must be str for pipeline)
            keep_path = kept_paths[0] if kept_paths else g.paths[0]
            keep_path = str(keep_path) if keep_path else ""
            delete_paths_str = [str(p) for p in delete_paths if p]
            if not keep_path or not os.path.exists(keep_path):
                continue
            group_size = sum(os.path.getsize(p) for p in delete_paths if os.path.exists(p))
            total_delete_size += group_size
            delete_groups.append({
                "group_index": idx,
                "keep": keep_path,
                "delete": delete_paths_str,
                "paths": delete_paths_str,
                "hint": g.hint,
                "recoverable_bytes": group_size,
            })

        if not delete_groups:
            log_debug("[Delete] No delete candidates")
            QMessageBox.information(
                self,
                "No Delete Candidates",
                "No files are marked for deletion.\n\n"
                "Check the 'Delete' checkbox on files you want to remove.",
            )
            return

        total_files = sum(len(g["delete"]) for g in delete_groups)
        log_info(f"[Delete] {total_files} files selected, {format_bytes(total_delete_size)}")

        dlg = DeletionPolicyChooserDialog(
            file_count=total_files,
            size_bytes=total_delete_size,
            excluded_count=0,
            parent=self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            log_debug("[Delete] User cancelled")
            return

        choice = dlg.result_choice()
        if not choice.confirmed:
            log_debug("[Delete] Dialog rejected")
            return

        mode = choice.mode or "trash"
        log_info(f"[Delete] User confirmed mode={mode}")

        self._progress_dialog = CleanupProgressDialog(total_files, self)
        self._progress_dialog.cancelled.connect(self._on_cleanup_cancelled)
        self._progress_dialog.show()

        stats = {
            "group_count": len(delete_groups),
            "file_count": total_files,
            "recoverable_bytes": total_delete_size,
        }

        scan_id = str(self._result.get("scan_id", "") or "unknown")
        cleanup_data = {
            "scan_id": scan_id,
            "groups": delete_groups,
            "stats": stats,
            "policy": {"mode": mode},
            "source": "review_page",
        }
        self.cleanup_confirmed.emit(cleanup_data)

    def _on_cleanup_cancelled(self):
        self._bus.notify("Cleanup Cancelled", "File deletion was cancelled", 2000)

    def refresh_after_deletion(self, deleted_paths: list) -> None:
        """Remove deleted paths from UI models and refresh. Called by MainWindow after cleanup."""
        if not deleted_paths:
            return
        deleted_set = {os.path.normpath(os.path.normcase(str(p))) for p in deleted_paths}
        log_info(f"[Delete] refresh_after_deletion: {len(deleted_set)} paths removed from UI")

        new_all_groups: List[GroupData] = []
        for g in self._all_groups:
            remaining = [p for p in g.paths if _norm_path(p) not in deleted_set]
            if len(remaining) >= 2:
                try:
                    rec = sum(os.path.getsize(p) for p in remaining if os.path.exists(p))
                except Exception:
                    rec = 0
                new_all_groups.append(GroupData(
                    paths=remaining,
                    hint=g.hint,
                    recoverable_bytes=rec,
                    similarity=g.similarity,
                    group_id=len(new_all_groups),
                ))
        self._all_groups = new_all_groups
        self._keep_states.clear()
        for g in self._all_groups:
            self._keep_states[g.group_id] = {_norm_path(p): True for p in g.paths}

        self._apply_filter()
        self._current_group_idx = 0 if self._filtered_groups else -1
        self._populate_group_list()
        self._update_display()
        self._update_stats()
        self._refresh_delete_button()

    def apply_theme(self):
        from cerebro.ui.theme_engine import current_colors
        c = current_colors()
        bg = c.get('bg', '#0f1115')
        surface = c.get('panel', '#151922')
        panel = c.get('panel', '#1a1d26')
        text = c.get('text', '#e7ecf2')
        line = c.get('line', '#2a3241')
        accent = c.get('accent', '#00C4B4')

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

        if hasattr(self, '_large_delete_btn') and self._large_delete_btn:
            self._large_delete_btn.setStyleSheet(f"""
                QPushButton#LargeDeleteButton {{
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #ef4444, stop:1 #dc2626);
                    color: white;
                    border: 2px solid {accent};
                    border-radius: 12px;
                    padding: 10px 20px;
                    font-weight: bold;
                    font-size: 15px;
                }}
                QPushButton#LargeDeleteButton:hover {{
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #f87171, stop:1 #ef4444);
                }}
                QPushButton#LargeDeleteButton:disabled {{
                    background: #4b5563;
                    border-color: #6b7280;
                    color: #9ca3af;
                }}
            """)
        if hasattr(self, '_step_labels'):
            acc = c.get('accent', '#00C4B4')
            muted = c.get('muted', '#888')
            for step_label, active in self._step_labels:
                step_label.setStyleSheet(f"""
                    font-weight: {'bold' if active else 'normal'};
                    font-size: 13px;
                    color: {acc if active else muted};
                    padding: 4px 12px;
                    background: rgba(0,196,180,0.12);
                    border-radius: 16px;
                """ if active else f"""
                    font-weight: normal;
                    font-size: 13px;
                    color: {muted};
                    padding: 4px 12px;
                    background: transparent;
                    border-radius: 16px;
                """)
        if hasattr(self, 'quick_stats'):
            self.quick_stats.setStyleSheet(f"font-size: 13px; color: {c.get('muted', '#aaa')};")
        if hasattr(self, '_status_hint'):
            self._status_hint.setStyleSheet(f"font-size: 10px; color: {c.get('muted', '#666')}; margin-left: 20px;")
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