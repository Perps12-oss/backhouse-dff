# cerebro/ui/pages/review_page.py
"""
CEREBRO — Review Page (Gemini 2 Edition — Final)
Clean, spacious, minimalistic. Smart Select is now one-click powerful.
All original features preserved and enhanced.
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
    QGraphicsDropShadowEffect, QApplication, QLineEdit, QMenu,
)

from cerebro.ui.components.modern import ContentCard, PageScaffold, StickyActionBar
from cerebro.ui.components.modern._tokens import token as theme_token
from cerebro.ui.pages.base_station import BaseStation
from cerebro.ui.pages.delete_confirm_dialog import DeletionPolicyChooserDialog, DeletionPolicyChoice
from cerebro.ui.state_bus import get_state_bus
from cerebro.ui.theme_engine import get_theme_manager, current_colors
from cerebro.services.logger import log_info, log_debug

# Debug session log (NDJSON) for selection-state verification
_DEBUG_LOG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), "debug-e08e7f.log")

def _debug_log(message: str, data: dict) -> None:
    try:
        import json
        with open(_DEBUG_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps({"sessionId": "e08e7f", "message": message, "data": data, "timestamp": __import__("time").time()}) + "\n")
    except Exception:
        pass


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


def _keep_list_from_raw(raw, group) -> list:
    """Return list of keep bools (one per path). Supports dict or list storage."""
    paths = group.paths or []
    n = len(paths)
    if isinstance(raw, list) and len(raw) >= n:
        return list(raw[:n])
    if isinstance(raw, dict):
        return [raw.get(_norm_path(str(p) if p else ""), True) for p in paths]
    return [True] * n


def _normalize_keep_map(keep_map: dict) -> dict:
    """Return a copy of keep_map with all keys normalized for consistent lookups."""
    if not keep_map:
        return {}
    return {_norm_path(str(k) if k else ""): v for k, v in keep_map.items()}


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
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        self.title = QLabel("🗑️ Moving to Trash...")
        self.title.setAlignment(Qt.AlignCenter)
        self.title.setStyleSheet("font-size: 18px; font-weight: bold;")
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
        self.progress.setFixedHeight(24)
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
        self.cancel_btn.setFixedHeight(34)
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
    file_selected = Signal(str)  # path (legacy)
    pane_keep_index = Signal(int)  # 0=Original, 1=Duplicate; use for keep state by index

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("DualPaneComparison")
        self._build()
        self._current_paths: List[str] = []
        self._keep_index = 0  # which pane is kept (0=left, 1=right)

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
        self.similarity_label.setStyleSheet("font-size: 42px; font-weight: bold; color: #22c55e;")

        self.similarity_text = QLabel("Similarity")
        self.similarity_text.setAlignment(Qt.AlignCenter)
        self.similarity_text.setStyleSheet("font-size: 12px; color: #888;")

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
        """Set which path is kept by path; updates _keep_index and button labels (no pane borders)."""
        try:
            kept_norm = os.path.normpath(os.path.normcase(str(kept_path or "")))
            left_norm = os.path.normpath(os.path.normcase(str(self._current_paths[0]))) if len(self._current_paths) >= 1 else ""
            right_norm = os.path.normpath(os.path.normcase(str(self._current_paths[1]))) if len(self._current_paths) >= 2 else ""
            if left_norm and left_norm == kept_norm:
                self._keep_index = 0
            elif right_norm and right_norm == kept_norm:
                self._keep_index = 1
            self._update_keep_delete_labels()
        except Exception:
            pass

    def set_compare_mode(self, on: bool) -> None:
        """Toggle side-by-side compare visibility (already dual-pane)."""
        self.setVisible(True)

    def _on_keep_clicked(self, pane: str):
        if pane == "Original" and self._current_paths:
            self._keep_index = 0
            self.file_selected.emit(self._current_paths[0])
            self.pane_keep_index.emit(0)
        elif pane == "Duplicate" and len(self._current_paths) > 1:
            self._keep_index = 1
            self.file_selected.emit(self._current_paths[1])
            self.pane_keep_index.emit(1)
        self._update_keep_delete_labels()

    def set_comparison(self, paths: List[str], similarity: float = 100.0, keep_index: int = 0):
        self._current_paths = paths
        self._keep_index = keep_index
        self.similarity_label.setText(f"{similarity:.0f}%")

        if similarity >= 95:
            color = "#22c55e"
        elif similarity >= 80:
            color = "#eab308"
        else:
            color = "#ef4444"
        self.similarity_label.setStyleSheet(f"font-size: 42px; font-weight: bold; color: {color};")

        if len(paths) >= 1:
            self._load_image(self.left_img, self.left_info, paths[0])
        if len(paths) >= 2:
            self._load_image(self.right_img, self.right_info, paths[1])
        self._update_keep_delete_labels()

    def _update_keep_delete_labels(self):
        """Update only button labels (✓ Kept / ✗ Delete). No pane borders."""
        if len(self._current_paths) >= 1:
            self.left_keep_btn.setText("✓ Kept" if self._keep_index == 0 else "✗ Delete")
        if len(self._current_paths) >= 2:
            self.right_keep_btn.setText("✓ Kept" if self._keep_index == 1 else "✗ Delete")

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
        self.setFixedHeight(52)

        self._build()
        self.update_style()

    def _build(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(8)

        self.checkbox = QCheckBox()
        self.checkbox.setTristate(True)
        self.checkbox.setToolTip(
            "Unchecked: keep all • Checked: mark all for deletion (keep one) • Partially checked: mixed"
        )
        self.checkbox.stateChanged.connect(self._on_checkbox_changed)
        layout.addWidget(self.checkbox)

        icon = QLabel(file_emoji(self.group_data.paths[0]) if self.group_data.paths else "📄")
        icon.setFixedSize(32, 32)
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
        log_debug(f"[SmartSelect] algorithm start groups={len(self._groups_data)}")
        result = {}
        for group_id, paths in self._groups_data:
            if not paths:
                continue
            try:
                if self._criteria == "first":
                    keeper = paths[0]
                elif self._criteria == "oldest":
                    keeper = min(paths, key=lambda p: os.path.getmtime(str(p)))
                elif self._criteria == "newest":
                    keeper = max(paths, key=lambda p: os.path.getmtime(str(p)))
                elif self._criteria == "largest":
                    keeper = max(paths, key=lambda p: os.path.getsize(str(p)))
                elif self._criteria == "smallest":
                    keeper = min(paths, key=lambda p: os.path.getsize(str(p)))
                else:
                    continue
                keeper_norm = _norm_path(str(keeper))
                result[group_id] = {_norm_path(str(p)): (_norm_path(str(p)) == keeper_norm) for p in paths}
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
        # UNIFIED: always dict[group_id: int, list[bool]] — keep by index
        self._keep_states: Dict[int, List[bool]] = {}

        self._current_filter = "All Files"
        self._progress_dialog = None
        self._smart_select_worker = None
        self._size_calc_timer = None
        self._pending_size_paths = []
        self._batch_updating = False

        self._thumb_loader = AsyncThumbnailLoader(self)

        self._build_gemini_ui()
        self.left_panel.setMinimumWidth(200)
        self._setup_keyboard_shortcuts()
        self._wire()
        self.apply_theme()

    def _build_gemini_ui(self):
        """Gemini 2 layout: PageScaffold + ContentCard + StickyActionBar."""
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._scaffold = PageScaffold(self, show_sidebar=False, show_sticky_action=False)
        self.step_bar = self._build_step_bar()
        self._scaffold.set_header(self.step_bar)

        # Prominent large delete button (used in bottom bar)
        self._large_delete_btn = QPushButton("Delete (0)")
        self._large_delete_btn.setObjectName("LargeDeleteButton")
        self._large_delete_btn.setMinimumSize(140, 40)
        self._large_delete_btn.setCursor(Qt.PointingHandCursor)
        self._large_delete_btn.setToolTip("Delete selected files. Routes through confirmation.")
        self._large_delete_btn.clicked.connect(self._open_ceremony)
        self._large_delete_btn.setEnabled(False)

        # Main content: splitter left (slim/collapsible) | center (hero)
        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(4)
        splitter.setChildrenCollapsible(False)

        self.left_panel = self._build_left_panel()
        self.center_panel = self._build_center_panel()
        splitter.addWidget(self.left_panel)
        splitter.addWidget(self.center_panel)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        content_wrapper = QWidget()
        wrap_layout = QVBoxLayout(content_wrapper)
        wrap_layout.setContentsMargins(12, 0, 12, 0)
        wrap_layout.setSpacing(0)
        card = ContentCard()
        card.set_content(splitter)
        wrap_layout.addWidget(card, 1)

        self._post_delete_banner = self._build_post_delete_banner()
        wrap_layout.addWidget(self._post_delete_banner)

        self._bottom_bar = self._build_bottom_bar()
        wrap_layout.addWidget(self._bottom_bar)

        self._scaffold.set_content(content_wrapper)

        root.addWidget(self._scaffold, 1)

        # Floating delete button (unchanged behavior/placement)
        self.floating_delete = FloatingDeleteButton(self)
        self.floating_delete.clicked_with_count.connect(self._on_floating_delete_clicked)

        # Smart Select = single FAB + popover menu (5 rules)
        self.smart_select_fab = QPushButton("Smart Select • 0 safe", self)
        self.smart_select_fab.setObjectName("SmartSelectFAB")
        self.smart_select_fab.setMinimumSize(220, 48)
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
        """Open Smart Select popover menu with 5 rules."""
        self._show_smart_select_popover()

    def focus_smart_select(self) -> None:
        """Used by Ctrl+S: open Smart Select popover menu."""
        self._show_smart_select_popover()
        self.setFocus()

    def _show_smart_select_popover(self) -> None:
        """Show popover menu with 5 Smart Select rules."""
        if not hasattr(self, "smart_select_fab") or self.smart_select_fab is None:
            return
        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{ background: {theme_token('panel')}; border: 1px solid {theme_token('line')}; border-radius: 12px; padding: 8px; }}
            QMenu::item {{ padding: 10px 20px; color: {theme_token('text')}; border-radius: 8px; }}
            QMenu::item:selected {{ background: {theme_token('accent')}; color: white; }}
        """)
        # When user chooses a rule, it marks ALL other files as DELETE (one kept per group)
        for text, criteria in [
            ("Keep Oldest in Each", "oldest"),
            ("Keep Newest in Each", "newest"),
            ("Keep Largest in Each", "largest"),
            ("Keep Smallest in Each", "smallest"),
            ("Keep First in Each", "first"),
        ]:
            action = menu.addAction(text)
            action.triggered.connect(lambda checked=False, c=criteria: self._apply_smart_to_filtered(c))
        menu.exec(self.smart_select_fab.mapToGlobal(self.smart_select_fab.rect().bottomLeft()))

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
        bottom_y = self.height() - 60 - margin
        if hasattr(self, 'floating_delete') and self.floating_delete:
            self.floating_delete.move(
                self.width() - self.floating_delete.width() - margin,
                bottom_y
            )
            self.floating_delete.raise_()
        if hasattr(self, 'smart_select_fab') and self.smart_select_fab:
            self.smart_select_fab.show()
            self.smart_select_fab.move(
                self.width() - margin - (self.floating_delete.width() if hasattr(self, 'floating_delete') and self.floating_delete else 180) - self.smart_select_fab.width() - 12,
                bottom_y
            )
            self.smart_select_fab.raise_()

    def _build_step_bar(self):
        bar = QFrame()
        bar.setObjectName("StepBar")
        bar.setFixedHeight(40)

        layout = QHBoxLayout(bar)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(12)

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
        self._left_panel_expanded = True
        panel.setMinimumWidth(80)
        panel.setMaximumWidth(320)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 10, 8, 10)
        layout.setSpacing(8)

        # Collapse toggle "Groups"
        self._groups_toggle_btn = QPushButton("Groups ▼")
        self._groups_toggle_btn.setObjectName("GroupsToggle")
        self._groups_toggle_btn.setCursor(Qt.PointingHandCursor)
        self._groups_toggle_btn.clicked.connect(self._toggle_left_panel)
        layout.addWidget(self._groups_toggle_btn)

        # Jump to group (visible when collapsed)
        self._jump_to_group_edit = QLineEdit()
        self._jump_to_group_edit.setPlaceholderText("Jump to #")
        self._jump_to_group_edit.setMaximumWidth(72)
        self._jump_to_group_edit.returnPressed.connect(self._on_jump_to_group)
        layout.addWidget(self._jump_to_group_edit)

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
        filter_layout.setSpacing(8)
        filter_layout.addWidget(QLabel("Filter:"))
        self.filter_combo = QComboBox()
        self.filter_combo.setMinimumWidth(120)
        self.filter_combo.setMinimumHeight(28)
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
        self.left_summary.setStyleSheet("font-size: 11px; color: #888; padding: 6px;")
        layout.addWidget(self.left_summary)

        self._jump_to_group_edit.hide()
        return panel

    def _toggle_left_panel(self):
        self._left_panel_expanded = not self._left_panel_expanded
        if self._left_panel_expanded:
            self.left_panel.setMaximumWidth(320)
            self._groups_toggle_btn.setText("Groups ▼")
            for i in [self.select_all_cb, self.filter_combo, self.group_list, self.left_summary]:
                i.show()
            self._jump_to_group_edit.hide()
        else:
            self.left_panel.setMaximumWidth(100)
            self._groups_toggle_btn.setText("Groups ▶")
            for i in [self.select_all_cb, self.filter_combo, self.group_list, self.left_summary]:
                i.hide()
            self._jump_to_group_edit.show()

    def _on_jump_to_group(self):
        try:
            text = (self._jump_to_group_edit.text() or "").strip()
            if not text:
                return
            num = int(text)
            if 1 <= num <= len(self._filtered_groups):
                self._current_group_idx = num - 1
                self._update_display()
            self._jump_to_group_edit.clear()
        except ValueError:
            pass

    def _build_center_panel(self):
        panel = QFrame()
        panel.setObjectName("CenterPanel")

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 14, 12, 14)
        layout.setSpacing(14)

        # Slim nav: subtle arrows + group counter (wrapped so we can hide when empty)
        nav_widget = QWidget()
        nav = QHBoxLayout(nav_widget)
        nav.setContentsMargins(0, 0, 0, 0)
        self.prev_group_btn = QPushButton("◀")
        self.prev_group_btn.setObjectName("NavArrowBtn")
        self.prev_group_btn.setFixedSize(36, 30)
        self.prev_group_btn.setCursor(Qt.PointingHandCursor)
        self.prev_group_btn.clicked.connect(self._prev_group)

        self.group_counter = QLabel("Group 1 of 1")
        self.group_counter.setAlignment(Qt.AlignCenter)
        self.group_counter.setStyleSheet("font-weight: 600; font-size: 14px; color: #e7ecf2;")

        self.next_group_btn = QPushButton("▶")
        self.next_group_btn.setObjectName("NavArrowBtn")
        self.next_group_btn.setFixedSize(36, 30)
        self.next_group_btn.setCursor(Qt.PointingHandCursor)
        self.next_group_btn.clicked.connect(self._next_group)

        nav.addWidget(self.prev_group_btn)
        nav.addWidget(self.group_counter, 1)
        nav.addWidget(self.next_group_btn)
        layout.addWidget(nav_widget)

        # Hero: DualPaneComparison (generous space)
        self.comparison = DualPaneComparison()
        self.comparison.pane_keep_index.connect(self._on_comparison_keep_by_index)
        layout.addWidget(self.comparison, 1)

        # One-line file detail (replaces right-panel preview)
        self.center_detail_line = QLabel("")
        self.center_detail_line.setStyleSheet("font-size: 12px; color: #94a3b8; padding: 4px 0;")
        self.center_detail_line.setWordWrap(True)
        layout.addWidget(self.center_detail_line)

        # File table behind "Show all files in group" expander (default hidden)
        self._files_expander_btn = QPushButton("Show all files in group")
        self._files_expander_btn.setCheckable(True)
        self._files_expander_btn.setChecked(False)
        self._files_expander_btn.setCursor(Qt.PointingHandCursor)
        self._files_expander_btn.toggled.connect(self._on_files_expander_toggled)
        layout.addWidget(self._files_expander_btn)

        self.file_table = QTableWidget()
        self.file_table.setColumnCount(3)
        self.file_table.setHorizontalHeaderLabels(["Delete", "File", "Size"])
        self.file_table.horizontalHeader().setStretchLastSection(True)
        self.file_table.setMaximumHeight(140)
        self.file_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        layout.addWidget(self.file_table)
        self.file_table.setVisible(False)

        # Empty state: big centered message (hidden by default)
        empty_msg = (
            "No files could be deleted. Selected paths may have been moved or deleted, "
            "or may point to the same file as the kept copy."
        )
        self._empty_state_label = QLabel(empty_msg)
        self._empty_state_label.setObjectName("EmptyStateLabel")
        self._empty_state_label.setAlignment(Qt.AlignCenter)
        self._empty_state_label.setWordWrap(True)
        self._empty_state_label.setStyleSheet(
            "font-size: 18px; font-weight: 600; color: #00C4B4; padding: 24px;"
        )
        self._empty_state_label.setMinimumWidth(280)
        self._empty_state_container = QWidget()
        empty_layout = QVBoxLayout(self._empty_state_container)
        empty_layout.setContentsMargins(0, 0, 0, 0)
        empty_layout.addStretch()
        empty_layout.addWidget(self._empty_state_label)
        empty_layout.addStretch()
        layout.addWidget(self._empty_state_container)
        self._empty_state_container.setVisible(False)

        # Widgets to hide when showing empty state (so we can toggle)
        self._center_content_widgets = [
            nav_widget,
            self.comparison,
            self.center_detail_line,
            self._files_expander_btn,
            self.file_table,
        ]

        return panel

    def _on_files_expander_toggled(self, checked: bool):
        if hasattr(self, "file_table"):
            self.file_table.setVisible(checked)
        if hasattr(self, "_files_expander_btn"):
            self._files_expander_btn.setText("Hide files in group" if checked else "Show all files in group")

    def _show_empty_state(self, message: Optional[str] = None) -> None:
        """Show big centered empty-state message; hide left panel, comparison, file table, floating delete."""
        default_msg = (
            "No files could be deleted. Selected paths may have been moved or deleted, "
            "or may point to the same file as the kept copy."
        )
        if hasattr(self, "_empty_state_label") and self._empty_state_label is not None:
            self._empty_state_label.setText(message if message else default_msg)
        if hasattr(self, "_empty_state_container") and self._empty_state_container is not None:
            self._empty_state_container.setVisible(True)
        if hasattr(self, "_center_content_widgets"):
            for w in self._center_content_widgets:
                if w is not None:
                    w.setVisible(False)
        if hasattr(self, "left_panel") and self.left_panel is not None:
            self.left_panel.setVisible(False)
        if hasattr(self, "floating_delete") and self.floating_delete is not None:
            self.floating_delete.update_count(0, 0)
            self.floating_delete.setEnabled(False)

    def _hide_empty_state(self) -> None:
        """Show comparison/content; hide empty-state message; show left panel."""
        if hasattr(self, "_empty_state_container") and self._empty_state_container is not None:
            self._empty_state_container.setVisible(False)
        if hasattr(self, "_center_content_widgets"):
            for w in self._center_content_widgets:
                if w is not None:
                    w.setVisible(True)
        if hasattr(self, "file_table") and self.file_table is not None:
            self.file_table.setVisible(getattr(self, "_files_expander_btn", None) and self._files_expander_btn.isChecked())
        if hasattr(self, "left_panel") and self.left_panel is not None:
            self.left_panel.setVisible(True)

    def _build_bottom_bar(self):
        """Clean bottom bar: status text (stretch) | spacing | Export | Delete | hint. Spacious, premium layout."""
        bar = QFrame()
        bar.setObjectName("StatusBar")
        bar.setFixedHeight(52)

        layout = QHBoxLayout(bar)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(12)

        self.status_text = QLabel("Ready")
        self.status_text.setStyleSheet(f"font-size: 13px; color: {theme_token('muted')};")
        layout.addWidget(self.status_text, 1)

        layout.addStretch(1)

        self.selection_stats = QLabel("")
        self.selection_stats.setStyleSheet("font-size: 12px; color: #94a3b8;")
        layout.addWidget(self.selection_stats)

        self.export_list_btn = QPushButton("Export List")
        self.export_list_btn.setToolTip("Export current duplicate list to CSV or JSON.")
        self.export_list_btn.setMinimumSize(140, 40)
        self.export_list_btn.setCursor(Qt.PointingHandCursor)
        self.export_list_btn.clicked.connect(self._on_export_list)
        layout.addWidget(self.export_list_btn)

        if hasattr(self, "_large_delete_btn") and self._large_delete_btn:
            layout.addWidget(self._large_delete_btn)

        self._status_hint = QLabel("←→ Navigate | Space Toggle | Del Confirm | 1-5 Keep")
        self._status_hint.setStyleSheet(f"font-size: 10px; color: {theme_token('muted')}; margin-left: 12px;")
        layout.addWidget(self._status_hint)

        return bar

    def _build_post_delete_banner(self):
        """Non-blocking banner: 'Deleted X files. [Refresh] [Rescan]' — hidden by default."""
        bar = QFrame()
        bar.setObjectName("PostDeleteBanner")
        bar.setFixedHeight(36)
        bar.setVisible(False)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(12, 4, 12, 4)
        layout.setSpacing(8)
        self._post_delete_label = QLabel("")
        self._post_delete_label.setStyleSheet("font-size: 12px; color: #94a3b8;")
        layout.addWidget(self._post_delete_label)
        layout.addStretch(1)
        self._post_delete_refresh_btn = QPushButton("Refresh")
        self._post_delete_refresh_btn.setToolTip("Reconcile list with filesystem (remove missing paths). No full scan.")
        self._post_delete_refresh_btn.setCursor(Qt.PointingHandCursor)
        self._post_delete_refresh_btn.clicked.connect(self._on_post_delete_refresh)
        layout.addWidget(self._post_delete_refresh_btn)
        self._post_delete_rescan_btn = QPushButton("Rescan")
        self._post_delete_rescan_btn.setToolTip("Re-run scan with last config and replace results.")
        self._post_delete_rescan_btn.setCursor(Qt.PointingHandCursor)
        self._post_delete_rescan_btn.clicked.connect(self._on_post_delete_rescan)
        layout.addWidget(self._post_delete_rescan_btn)
        bar.setStyleSheet("""
            QFrame#PostDeleteBanner {
                background: rgba(0, 196, 180, 0.12);
                border: 1px solid rgba(0, 196, 180, 0.35);
                border-radius: 8px;
            }
            QPushButton { background: rgba(0, 196, 180, 0.25); color: #e7ecf2; border: none; border-radius: 6px; padding: 6px 12px; }
            QPushButton:hover { background: rgba(0, 196, 180, 0.4); }
        """)
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
            idx = i - 1
            QShortcut(QKeySequence(str(i)), self).activated.connect(
                lambda _idx=idx: self._keep_file_by_index(_idx)
            )

    def _wire(self):
        self.file_table.itemChanged.connect(self._on_file_table_changed)
        self.file_table.cellClicked.connect(self._on_file_table_cell_clicked)
        try:
            if hasattr(self._bus, "deletion_completed"):
                self._bus.deletion_completed.connect(self._on_deletion_completed)
        except Exception:
            pass
        # Note: MainWindow always calls review.refresh_after_deletion() directly after delete,
        # so the UI refreshes even if the signal connection above fails or is missing.

    @Slot(dict)
    def load_scan_result(self, result: dict):
        self._result = dict(result or {})
        if hasattr(self, "_post_delete_banner") and self._post_delete_banner is not None:
            self._post_delete_banner.setVisible(False)
        groups_raw = self._result.get("groups")
        if not isinstance(groups_raw, list):
            groups_raw = []

        self._all_groups = []
        for i, g in enumerate(groups_raw):
            try:
                self._all_groups.append(extract_group_data(g, i))
            except Exception:
                continue
        self._apply_filter()

        self._keep_states.clear()
        for g in self._all_groups:
            try:
                self._keep_states[int(g.group_id)] = [True] * len(g.paths or [])
            except Exception:
                continue

        self._current_group_idx = 0 if self._filtered_groups else -1

        self._populate_group_list()
        self._update_display()
        self._update_stats()
        self._refresh_delete_button()

    def refresh_theme(self) -> None:
        """Gemini 2 full theme refresh — scaffold, panels, FAB, floating delete, bottom bar."""
        super().refresh_theme()
        self.apply_theme()
        c = current_colors()
        panel = c.get("panel", "#151922")
        line = c.get("line", "#2a3241")
        accent = c.get("accent", "#00C4B4")
        if hasattr(self, "left_panel") and self.left_panel:
            self.left_panel.setStyleSheet(f"QFrame#LeftPanel {{ background: {panel}; border-radius: 12px; border-right: 1px solid {line}; }}")
        if hasattr(self, "center_panel") and self.center_panel:
            self.center_panel.setStyleSheet(f"QFrame#CenterPanel {{ background: {c.get('bg', '#0f1115')}; border-radius: 12px; }}")
        if hasattr(self, "smart_select_fab") and self.smart_select_fab:
            self.smart_select_fab.setStyleSheet(f"""
                QPushButton#SmartSelectFAB {{ background: {accent}; color: white; border-radius: 12px; font-weight: bold; }}
                QPushButton#SmartSelectFAB:hover {{ opacity: 0.9; }}
            """)
        if hasattr(self, "floating_delete") and self.floating_delete and hasattr(self.floating_delete, "_apply_gemini_style"):
            self.floating_delete._apply_gemini_style()
        if hasattr(self, "_scaffold") and self._scaffold and hasattr(self._scaffold, "refresh_theme"):
            self._scaffold.refresh_theme()
        if hasattr(self, "_bottom_bar") and self._bottom_bar:
            self._bottom_bar.setStyleSheet(f"QFrame#StatusBar {{ background: {panel}; border-top: 1px solid {line}; border-radius: 0; }}")
        self.update()
        self.repaint()

    def on_theme_changed(self):
        self.apply_theme()
        self._populate_group_list()

    def _on_filter_changed(self, filter_text: str):
        # #region agent log
        _debug_log("category changed", {"old": getattr(self, "_current_filter", ""), "new": filter_text or ""})
        # #endregion
        self._current_filter = filter_text or "All Files"
        self._apply_filter()
        if hasattr(self, "filter_combo") and self.filter_combo is not None and self.filter_combo.currentText() != self._current_filter:
            self.filter_combo.blockSignals(True)
            self.filter_combo.setCurrentText(self._current_filter)
            self.filter_combo.blockSignals(False)
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

    def _apply_keep_map_for_group(self, group_id: int, keep_map: dict) -> None:
        """Write _keep_states for group_id from a path->bool map. Normalizes all keys so selection model stays consistent."""
        g = next((x for x in self._all_groups if int(x.group_id) == int(group_id)), None)
        if not g or not (g.paths or []):
            return
        norm_map = _normalize_keep_map(keep_map or {})
        keep_list = [norm_map.get(_norm_path(str(p) if p else ""), True) for p in (g.paths or [])]
        self._keep_states[int(group_id)] = keep_list

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
            keep_list = _keep_list_from_raw(self._keep_states.get(int(group.group_id)), group)
            delete_count = sum(1 for i, p in enumerate(group.paths or []) if not (keep_list[i] if i < len(keep_list) else True))
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
            keep_list = _keep_list_from_raw(self._keep_states.get(int(group_id)), group)
            delete_count = sum(1 for i, p in enumerate(group.paths or []) if not (keep_list[i] if i < len(keep_list) else True))
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
            keep_list = _keep_list_from_raw(self._keep_states.get(int(group_id)), group)
            delete_count = sum(1 for i, p in enumerate(group.paths or []) if not (keep_list[i] if i < len(keep_list) else True))
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
        """Sync group checkboxes, current group display, stats, and delete button (call once after batch updates)."""
        self._sync_group_checkboxes()
        self._update_display()
        self._update_stats()
        self._refresh_delete_button()

    def _update_display(self):
        if len(self._filtered_groups) == 0:
            self._show_empty_state()
            return
        self._hide_empty_state()
        group = self._get_current_group()
        if not group:
            return

        keep_list = _keep_list_from_raw(self._keep_states.get(int(group.group_id)), group)
        keep_map = {_norm_path(str(p) if p else ""): (keep_list[i] if i < len(keep_list) else True) for i, p in enumerate(group.paths or [])}

        self.group_counter.setText(
            f"Group {self._current_group_idx + 1} of {len(self._filtered_groups)} "
            f"(ID: {group.group_id + 1})"
        )
        self.prev_group_btn.setEnabled(self._current_group_idx > 0)
        self.next_group_btn.setEnabled(self._current_group_idx < len(self._filtered_groups) - 1)

        display_paths = group.paths[:2] if len(group.paths) >= 2 else group.paths
        keep_index_display = 0
        for i in range(min(2, len(keep_list))):
            if keep_list[i]:
                keep_index_display = i
                break
        self.comparison.set_comparison(display_paths, group.similarity, keep_index=keep_index_display)
        kept_files = [p for p in group.paths if keep_map.get(_norm_path(p), True)]
        kept_path = kept_files[0] if kept_files else (group.paths[0] if group.paths else None)
        if hasattr(self.comparison, "set_kept_path") and kept_path:
            self.comparison.set_kept_path(kept_path)

        self._populate_file_table(group, keep_map)

        if kept_path:
            self._update_preview(kept_path)
        elif hasattr(self, "center_detail_line") and self.center_detail_line is not None:
            self.center_detail_line.setText("")

        for i in range(self.group_list_layout.count()):
            item = self.group_list_layout.itemAt(i)
            if item and isinstance(item.widget(), GroupListItem):
                item.widget().set_selected(item.widget().group_id == group.group_id)

    def _populate_file_table(self, group, keep_map):
        """keep_map: path (normalized) -> bool (True = keep). Can be built from keep_list as {_norm_path(p): keep_list[i]}."""
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
        """Update center one-line detail (right panel removed)."""
        if not hasattr(self, "center_detail_line") or self.center_detail_line is None:
            return
        try:
            st = os.stat(file_path)
            size_str = format_bytes(st.st_size)
            import datetime
            mtime = datetime.datetime.fromtimestamp(st.st_mtime)
            mod_str = mtime.strftime("%Y-%m-%d %H:%M")
        except Exception:
            size_str = "-"
            mod_str = "-"
        self.center_detail_line.setText(f"{Path(file_path).name}  •  {size_str}  •  {mod_str}")

    def _compute_delete_count(self):
        """Single source of truth: count paths marked for delete from _keep_states + _filtered_groups. Supports list (by index) or dict (by path) storage."""
        delete_count = 0
        delete_paths = []
        for g in self._filtered_groups:
            keep_list = _keep_list_from_raw(self._keep_states.get(int(g.group_id)), g)
            for i, p in enumerate(g.paths or []):
                if not (keep_list[i] if i < len(keep_list) else True):
                    delete_count += 1
                    delete_paths.append(p)
        return delete_count, delete_paths

    def _update_selection_state_ui(self, override_count: Optional[int] = None, override_size: Optional[int] = None) -> None:
        """Single recompute: derive delete count/size from _keep_states + _filtered_groups and update bottom label + both delete buttons. Call after any selection-affecting action."""
        if override_count is not None and override_size is not None:
            delete_count, delete_size = override_count, override_size
        else:
            delete_count, delete_paths = self._compute_delete_count()
            delete_size = 0
            if len(delete_paths) <= STATS_SIZE_CHUNK:
                for p in delete_paths:
                    try:
                        delete_size += os.path.getsize(p)
                    except Exception:
                        pass
        # #region agent log
        _debug_log("recompute ran", {"active_filter": getattr(self, "_current_filter", ""), "delete_count": delete_count})
        # #endregion
        log_debug(f"[SmartSelect] recompute delete_count={delete_count}")
        if hasattr(self, "selection_stats") and self.selection_stats is not None:
            self.selection_stats.setText(f"{delete_count} files selected for deletion ({format_bytes(delete_size)})")
        if hasattr(self, "status_text") and self.status_text is not None:
            self.status_text.setText(f"{delete_count} files marked for deletion")
        if hasattr(self, "floating_delete") and self.floating_delete is not None:
            self.floating_delete.update_count(delete_count, delete_size)
            self.floating_delete.setEnabled(delete_count > 0)
            self.floating_delete.update()
            self.floating_delete.repaint()
        if hasattr(self, "_large_delete_btn") and self._large_delete_btn is not None:
            self._large_delete_btn.setText(f"Delete ({delete_count})")
            self._large_delete_btn.setEnabled(delete_count > 0)
            log_debug(f"[SmartSelect] Delete button enabled={delete_count > 0} count={delete_count}")
            # #region agent log
            _debug_log("Delete button state", {"enabled": delete_count > 0, "count": delete_count})
            # #endregion

    def _refresh_delete_button(self) -> None:
        """Thin wrapper: all selection UI (bottom label + both buttons) updated from one recompute."""
        self._update_selection_state_ui()

    def _update_stats(self):
        total_groups = len(self._filtered_groups)
        total_files = sum(g.file_count for g in self._filtered_groups)
        total_size = sum(g.recoverable_bytes for g in self._filtered_groups)

        delete_count, delete_paths = self._compute_delete_count()
        n_none = 0
        n_full = 0
        for g in self._filtered_groups:
            keep_list = _keep_list_from_raw(self._keep_states.get(int(g.group_id)), g)
            delete_in_group = sum(1 for i, p in enumerate(g.paths or []) if not (keep_list[i] if i < len(keep_list) else True))
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
        """Update group/file summary and Smart Select label only. Delete count/buttons come from _update_selection_state_ui()."""
        self.quick_stats.setText(f"{total_groups} groups • {total_files} files • {format_bytes(total_size)}")
        self.left_summary.setText(f"Showing {total_groups} of {len(self._all_groups)} groups")
        safe_count = total_files - delete_count
        if hasattr(self, "smart_select_fab"):
            self.smart_select_fab.setText(f"Smart Select • {safe_count} safe")

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
            self._update_selection_state_ui(override_count=cnt, override_size=self._pending_size_total)
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

        gid = int(group.group_id)
        keep_list = [ (i == idx) for i in range(len(group.paths or [])) ]
        self._keep_states[gid] = keep_list
        self._update_display()
        self._update_stats()
        self._update_group_list_item(gid)
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

        gid = int(group_id)
        n = len(group.paths or [])
        if checked:
            keep_list = [ (i == 0) for i in range(n) ]  # keep first, delete rest
        else:
            keep_list = [ True ] * n
        self._keep_states[gid] = keep_list
        self._update_display()
        self._update_stats()
        self._update_group_list_item(group_id)
        self._refresh_delete_button()

    def _on_select_all_changed(self, state):
        check = (state == Qt.Checked)
        self._batch_updating = True
        try:
            for g in self._filtered_groups:
                n = len(g.paths or [])
                keep_list = [ (i == 0) if check else True for i in range(n) ]
                self._keep_states[int(g.group_id)] = keep_list
        finally:
            self._batch_updating = False
        self._refresh_all_ui()

    def _on_file_table_cell_clicked(self, row: int, column: int) -> None:
        """When user clicks a row, set that file as the one to keep (swap selection)."""
        if self._batch_updating:
            return
        group = self._get_current_group()
        if not group or row < 0 or row >= len(group.paths):
            return
        self._keep_file_by_index(row)

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
        path_norm = _norm_path(path)
        row_index = next((i for i, p in enumerate(group.paths or []) if _norm_path(str(p) or "") == path_norm), None)
        if row_index is None:
            return
        gid = int(group.group_id)
        keep_list = _keep_list_from_raw(self._keep_states.get(gid), group)
        keep_list[row_index] = not delete  # True = keep, False = delete
        if sum(keep_list) == 0:
            item.setCheckState(Qt.Unchecked)
            keep_list[row_index] = True
            QMessageBox.warning(self, "Invalid Selection", "You must keep at least one file per group.")
        self._keep_states[gid] = keep_list
        self._update_display()
        self._update_stats()
        self._update_group_list_item(group.group_id)
        self._refresh_delete_button()

    def _on_comparison_keep_by_index(self, pane_index: int):
        """Keep the file at pane_index (0=Original, 1=Duplicate); mark all others in group for delete. Uses list-by-index so duplicate paths work."""
        if self._batch_updating:
            return
        group = self._get_current_group()
        if not group or not group.paths:
            return
        # Clamp to valid index (comparison shows at most first 2 paths)
        idx = max(0, min(pane_index, len(group.paths) - 1))
        gid = int(group.group_id)
        keep_list = [ (i == idx) for i in range(len(group.paths)) ]
        self._keep_states[gid] = keep_list
        # #region agent log
        _debug_log("keep_selected", {"group_id": gid, "pane_index": idx, "delete_count_in_group": sum(1 for v in keep_list if not v)})
        # #endregion
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
        log_info(f"[SmartSelect] trigger criteria={criteria}")
        self._last_smart_select_criteria = criteria

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
        """Apply Smart Select result: one file kept per group, all others marked for deletion. Uses explicit keep_list by index so file table checkboxes and delete count update correctly."""
        result = result or {}
        self._batch_updating = True
        applied_ids = []
        try:
            for group_id, keep_map in result.items():
                group_id = int(group_id)
                g = next((x for x in self._all_groups if int(x.group_id) == group_id), None)
                if not g or not (g.paths or []):
                    continue
                paths = g.paths or []
                keep_map = keep_map or {}
                norm_map = _normalize_keep_map(keep_map)
                # Build keep_list by index: only the chosen file is True, all others False.
                keeper_index = 0
                for i, p in enumerate(paths):
                    if norm_map.get(_norm_path(str(p) if p else ""), False):
                        keeper_index = i
                        break
                keep_list = [False] * len(paths)
                keep_list[keeper_index] = True
                self._keep_states[group_id] = keep_list
                applied_ids.append(group_id)
        finally:
            self._batch_updating = False
        criteria_str = getattr(self, "_last_smart_select_criteria", "?")
        log_info(f"[SmartSelect] groups_applied criteria={criteria_str} groups={applied_ids[:10]}{'...' if len(applied_ids) > 10 else ''} n={len(applied_ids)}")
        delete_count, delete_paths = self._compute_delete_count()
        log_info(f"[SmartSelect] finished groups_modified={len(result)} delete_count={delete_count}")
        self._refresh_all_ui()
        self._update_display()
        self._update_stats()
        self._refresh_delete_button()
        dc_after, _ = self._compute_delete_count()
        log_debug(f"[SmartSelect] after recompute delete_count={dc_after}")
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
        # Use same source of truth as bottom bar: never show "No Delete Candidates" when bar says N files selected
        delete_count_from_ui, _ = self._compute_delete_count()
        if delete_count_from_ui == 0:
            QMessageBox.information(
                self,
                "No Delete Candidates",
                "No files are marked for deletion.\n\n"
                "Check the 'Delete' checkbox on files you want to remove.",
            )
            return

        delete_groups = []
        total_delete_size = 0

        for idx, g in enumerate(self._filtered_groups):
            keep_list = _keep_list_from_raw(self._keep_states.get(int(g.group_id)), g)
            paths = g.paths or []
            kept_paths = [p for i, p in enumerate(paths) if (keep_list[i] if i < len(keep_list) else True)]
            delete_paths = [p for i, p in enumerate(paths) if not (keep_list[i] if i < len(keep_list) else True)]

            if not delete_paths:
                continue
            # Determine the single keeper path first (for excluding from delete list)
            candidates = kept_paths if kept_paths else (g.paths or [])
            keep_path = ""
            for p in candidates:
                s = str(p) if p else ""
                if s and os.path.exists(s):
                    keep_path = s
                    break
            if not keep_path:
                for p in (g.paths or []):
                    s = str(p) if p else ""
                    if s and os.path.exists(s):
                        keep_path = s
                        break
            if not keep_path:
                keep_path = str(kept_paths[0]) if kept_paths and kept_paths[0] is not None else (str(g.paths[0]) if g.paths else "")
            keep_norm = _norm_path(keep_path) if keep_path else ""
            # Explicitly remove keeper from delete list (normalized comparison) so pipeline never sees keeper in delete
            delete_paths = [p for p in delete_paths if _norm_path(str(p)) != keep_norm]
            if not delete_paths:
                continue
            delete_paths_str = [str(p) for p in delete_paths if p]
            if not delete_paths_str:
                continue
            # Size of files we're actually deleting (same list as delete_paths_str; use try/except so path format doesn't yield 0)
            group_size = 0
            for sp in delete_paths_str:
                if not sp:
                    continue
                try:
                    group_size += os.path.getsize(sp)
                except (OSError, TypeError):
                    pass
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
            log_debug("[Delete] No delete groups built (keeper excluded or paths missing/same-file)")
            self._show_empty_state(
                "No files could be deleted. Selected paths may have been moved or deleted, "
                "or may point to the same file as the kept copy."
            )
            if hasattr(self, "status_text") and self.status_text is not None:
                self.status_text.setText("No duplicates remaining")
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
        # Emit a plain dict copy so Signal(object) and receivers get stable data
        cleanup_data = {
            "scan_id": scan_id,
            "groups": [dict(g) for g in delete_groups],
            "stats": dict(stats),
            "policy": {"mode": mode},
            "source": "review_page",
        }
        self.cleanup_confirmed.emit(cleanup_data)

    def _on_cleanup_cancelled(self):
        self._bus.notify("Cleanup Cancelled", "File deletion was cancelled", 2000)

    @Slot(dict)
    def _on_deletion_completed(self, payload: dict) -> None:
        """Single handler for deletion success: refresh UI and show post-delete banner."""
        deleted_paths = list(payload.get("deleted_paths") or [])
        scan_id = str(payload.get("scan_id") or "")
        deleted_count = int(payload.get("deleted_count") or len(deleted_paths))
        if not deleted_paths:
            return
        groups_before = len(self._all_groups)
        items_before = sum(len(g.paths) for g in self._all_groups)
        log_info(f"[Delete] before refresh_after_deletion: groups={groups_before} items={items_before}")
        self.refresh_after_deletion(deleted_paths)
        groups_after = len(self._all_groups)
        items_after = sum(len(g.paths) for g in self._all_groups)
        log_info(f"[Delete] after refresh_after_deletion: groups={groups_after} items={items_after}")
        self._show_post_delete_banner(deleted_count)

    def _show_post_delete_banner(self, deleted_count: int) -> None:
        """Show 'Deleted X files. [Refresh] [Rescan]' banner."""
        if hasattr(self, "_post_delete_banner") and self._post_delete_banner is not None:
            self._post_delete_label.setText(f"Deleted {deleted_count} file(s).")
            self._post_delete_banner.setVisible(True)

    def _on_post_delete_refresh(self) -> None:
        """Reconcile current review dataset with filesystem (remove non-existent paths). No full scan."""
        log_info("[Delete] Post-delete Refresh triggered")
        self._reconcile_with_filesystem()

    def _on_post_delete_rescan(self) -> None:
        """Re-run scan with last config/locations and replace results."""
        log_info("[Delete] Post-delete Rescan triggered")
        if hasattr(self, "_post_delete_banner") and self._post_delete_banner is not None:
            self._post_delete_banner.setVisible(False)
        root = (self._result or {}).get("root") or ((self._result or {}).get("metadata") or {}).get("root") or ""
        if not root or not os.path.isdir(root):
            self._bus.notify("Rescan skipped", "No previous scan root. Run a scan first.", 3000)
            return
        options = self._bus.get_scan_options() or {}
        config = dict(options, root=root, fast_mode=True, mode="fast")
        config.setdefault("media_type", "all")
        config.setdefault("engine", "simple")
        if hasattr(self._bus, "scan_requested"):
            self._bus.scan_requested.emit(config)

    def _reconcile_with_filesystem(self) -> None:
        """Remove paths that no longer exist from _all_groups; drop empty groups; refresh view."""
        new_all_groups: List[GroupData] = []
        for g in self._all_groups:
            remaining = [p for p in g.paths if os.path.exists(str(p))]
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
            self._keep_states[int(g.group_id)] = [True] * len(g.paths or [])
        self._apply_filter()
        self._current_group_idx = 0 if self._filtered_groups else -1
        self._populate_group_list()
        self._update_display()
        self._update_stats()
        self._refresh_delete_button()
        if hasattr(self, "_post_delete_banner") and self._post_delete_banner is not None:
            self._post_delete_banner.setVisible(False)

    def refresh_after_deletion(self, deleted_paths: list) -> None:
        """Remove all pipeline-reported deleted paths from UI models (do not use os.path.exists; Recycle Bin files still exist). Then refresh; if no groups left, show empty-state message."""
        if not deleted_paths:
            return
        deleted_set = {_norm_path(str(p)) for p in deleted_paths}

        new_all_groups: List[GroupData] = []
        for g in self._all_groups:
            remaining = [p for p in (g.paths or []) if _norm_path(str(p) if p else "") not in deleted_set]
            if len(remaining) >= 2:
                try:
                    rec = sum(os.path.getsize(p) for p in remaining if os.path.exists(str(p)))
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
            self._keep_states[int(g.group_id)] = [True] * len(g.paths or [])

        self._apply_filter()
        self._current_group_idx = 0 if self._filtered_groups else -1

        if len(self._filtered_groups) == 0:
            self._show_empty_state("No duplicates remaining.")
            if hasattr(self, "status_text") and self.status_text is not None:
                self.status_text.setText("No duplicates remaining")
            if hasattr(self, "comparison") and self.comparison is not None:
                self.comparison.set_comparison([], 100.0, keep_index=0)
            if hasattr(self, "file_table") and self.file_table:
                self.file_table.setRowCount(0)
                self.file_table.clearSelection()
            self._update_stats()
            self._refresh_delete_button()
            return

        self._hide_empty_state()
        self._populate_group_list()
        if hasattr(self, "file_table") and self.file_table:
            self.file_table.clearSelection()
            self.file_table.setCurrentCell(-1, -1)
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
            QPushButton#NavArrowBtn {{
                background: rgba(0,196,180,0.15);
                color: {accent};
                border: 1px solid rgba(0,196,180,0.4);
                border-radius: 8px;
            }}
            QPushButton#NavArrowBtn:hover {{
                background: rgba(0,196,180,0.25);
            }}
            QPushButton#GroupsToggle {{
                background: {panel};
                color: {text};
                border: 1px solid {line};
                border-radius: 8px;
                padding: 6px;
            }}
            QPushButton#GroupsToggle:hover {{ border-color: {accent}; }}
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
        if getattr(self, "_filtered_groups", None):
            self._refresh_delete_button()


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
