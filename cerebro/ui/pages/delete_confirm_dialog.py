# path: cerebro/ui/pages/delete_confirm_dialog.py
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt, QEasingCurve, QPropertyAnimation
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QLabel,
    QLineEdit,
    QHBoxLayout,
    QPushButton,
    QMessageBox,
    QFrame,
    QGraphicsOpacityEffect,
)


@dataclass(frozen=True, slots=True)
class DeleteConfirmResult:
    confirmed: bool
    typed: str


class DeleteConfirmDialog(QDialog):
    """Large-delete ceremony (only used when deleting > threshold).

    Not strict:
    - user types *last 8* chars of token (or full token).
    """

    def __init__(self, *, token: str, count: int, parent=None):
        super().__init__(parent)
        self.setModal(True)
        self.setWindowTitle("Sacred Deletion Ceremony")
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)

        self._token = (token or "").strip()
        self._tail = self._token[-8:].upper()
        self._result = DeleteConfirmResult(confirmed=False, typed="")

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(12)

        card = QFrame()
        card.setObjectName("Card")
        l = QVBoxLayout(card)
        l.setContentsMargins(16, 16, 16, 16)
        l.setSpacing(10)

        title = QLabel("A large release requires intention.")
        title.setObjectName("H2")
        l.addWidget(title)

        info = QLabel(
            f"You are about to delete <b>{count}</b> files.\n"
            "To proceed, type the last 8 characters of the plan token."
        )
        info.setWordWrap(True)
        l.addWidget(info)

        hint = QLabel(f"Token tail: <code>{self._tail}</code>")
        hint.setTextInteractionFlags(Qt.TextSelectableByMouse)
        l.addWidget(hint)

        self.txt = QLineEdit()
        self.txt.setPlaceholderText("Type last 8 chars (or full token)")
        self.txt.textChanged.connect(self._sync)
        l.addWidget(self.txt)

        root.addWidget(card)

        btns = QHBoxLayout()
        btns.addStretch(1)

        self.btn_cancel = QPushButton("Back")
        self.btn_cancel.clicked.connect(self.reject)
        btns.addWidget(self.btn_cancel)

        self.btn_ok = QPushButton("Release")
        self.btn_ok.setObjectName("DangerButton")
        self.btn_ok.clicked.connect(self._confirm)
        self.btn_ok.setEnabled(False)
        btns.addWidget(self.btn_ok)

        root.addLayout(btns)

        eff = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(eff)
        eff.setOpacity(0.0)
        anim = QPropertyAnimation(eff, b"opacity", self)
        anim.setDuration(220)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.start()
        self._anim = anim

    def result_data(self) -> DeleteConfirmResult:
        return self._result

    def _sync(self):
        s = (self.txt.text() or "").strip().upper()
        ok = bool(s) and (s == self._token.upper() or s == self._tail)
        self.btn_ok.setEnabled(ok)

    def _confirm(self):
        s = (self.txt.text() or "").strip().upper()
        ok = (s == self._token.upper() or s == self._tail)
        if not ok:
            QMessageBox.warning(self, "Token mismatch", "Incorrect token tail.")
            return
        self._result = DeleteConfirmResult(confirmed=True, typed=s)
        self.accept()
