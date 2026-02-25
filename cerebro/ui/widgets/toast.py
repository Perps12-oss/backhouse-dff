# cerebro/ui/widgets/toast.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QWidget, QLabel, QHBoxLayout, QVBoxLayout, QPushButton, QSizePolicy


@dataclass(frozen=True, slots=True)
class ToastAction:
    text: str
    callback_name: str  # consumer decides what to do


class Toast(QWidget):
    """
    Lightweight toast widget (no QGraphicsEffects for performance).
    Use ToastOverlay.show_toast(...).
    """
    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setObjectName("Toast")
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self.setWindowFlags(Qt.SubWindow | Qt.FramelessWindowHint)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

        self._anim = QPropertyAnimation(self, b"windowOpacity", self)
        self._anim.setDuration(180)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)

        self._title = QLabel("")
        self._title.setObjectName("ToastTitle")
        self._title.setFont(QFont("Segoe UI", 10, QFont.DemiBold))
        self._msg = QLabel("")
        self._msg.setObjectName("ToastMsg")
        self._msg.setWordWrap(True)

        self._action_btn = QPushButton("")
        self._action_btn.setVisible(False)
        self._action_btn.setCursor(Qt.PointingHandCursor)
        self._action_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        self._close_btn = QPushButton("✕")
        self._close_btn.setCursor(Qt.PointingHandCursor)
        self._close_btn.setFixedWidth(28)
        self._close_btn.clicked.connect(self.hide)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.addWidget(self._title, 1)
        top.addWidget(self._close_btn, 0, Qt.AlignTop)

        body = QVBoxLayout()
        body.setContentsMargins(12, 10, 12, 10)
        body.setSpacing(6)
        body.addLayout(top)
        body.addWidget(self._msg)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addStretch(1)
        row.addWidget(self._action_btn)
        body.addLayout(row)

        self.setLayout(body)

        self.setStyleSheet("""
        #Toast {
            background: rgba(18, 22, 32, 0.92);
            border: 1px solid rgba(120, 140, 180, 0.25);
            border-radius: 14px;
        }
        #ToastTitle { color: rgba(235, 242, 255, 0.95); }
        #ToastMsg { color: rgba(200, 210, 230, 0.90); }
        QPushButton {
            background: rgba(30, 38, 56, 0.90);
            border: 1px solid rgba(120, 140, 180, 0.25);
            border-radius: 10px;
            padding: 6px 10px;
        }
        QPushButton:hover { border-color: rgba(130, 170, 255, 0.55); }
        """)

        self._action_name: Optional[str] = None

    def set_content(self, title: str, message: str, action: Optional[ToastAction] = None) -> None:
        self._title.setText(title or "")
        self._msg.setText(message or "")
        if action:
            self._action_btn.setText(action.text)
            self._action_btn.setVisible(True)
            self._action_name = action.callback_name
        else:
            self._action_btn.setVisible(False)
            self._action_name = None

    def action_name(self) -> Optional[str]:
        return self._action_name

    def show_for(self, ms: int) -> None:
        self._timer.stop()
        self.setWindowOpacity(0.0)
        self.show()
        self.raise_()

        self._anim.stop()
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.start()

        if ms > 0:
            self._timer.start(ms)


class ToastOverlay(QWidget):
    """
    Overlay pinned to parent widget's bottom-right.
    """
    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setObjectName("ToastOverlay")

        self._toast = Toast(parent)
        self._toast.hide()

        self._action_btn = self._toast._action_btn  # noqa: internal binding
        self._action_btn.clicked.connect(self._on_action_clicked)

        self._last_action_name: Optional[str] = None
        self._action_callback = None

    def bind_action_handler(self, handler):
        """
        handler(action_name: str) -> None
        """
        self._action_callback = handler

    def show_toast(self, title: str, message: str, duration_ms: int = 2600, action: Optional[ToastAction] = None) -> None:
        self._toast.set_content(title, message, action)
        self._last_action_name = self._toast.action_name()

        # Position
        pw = self.parentWidget()
        if not pw:
            return
        margin = 18
        width = min(420, max(320, int(pw.width() * 0.34)))
        self._toast.setFixedWidth(width)
        self._toast.adjustSize()
        x = pw.width() - self._toast.width() - margin
        y = pw.height() - self._toast.height() - margin
        self._toast.move(max(margin, x), max(margin, y))

        self._toast.show_for(duration_ms)

    def _on_action_clicked(self) -> None:
        if self._action_callback and self._last_action_name:
            self._action_callback(self._last_action_name)
