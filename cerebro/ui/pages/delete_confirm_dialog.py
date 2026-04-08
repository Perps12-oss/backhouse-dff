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


@dataclass(frozen=True, slots=True)
class DeletionPolicyChoice:
    """Result of DeletionPolicyChooserDialog: whether user confirmed and which mode (e.g. 'trash')."""
    confirmed: bool
    mode: str | None  # e.g. "trash", or None if cancelled


class DeletionPolicyChooserDialog(QDialog):
    """Dialog to choose deletion policy (e.g. move to trash) and confirm before cleanup."""

    def __init__(
        self,
        *,
        file_count: int,
        size_bytes: int,
        excluded_count: int = 0,
        parent=None,
    ):
        super().__init__(parent)
        self.setModal(True)
        self.setWindowTitle("Confirm deletion")
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)

        self._choice = DeletionPolicyChoice(confirmed=False, mode=None)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(12)

        card = QFrame()
        card.setObjectName("Card")
        l = QVBoxLayout(card)
        l.setContentsMargins(16, 16, 16, 16)
        l.setSpacing(10)

        size_str = f"{size_bytes / (1024**2):.1f} MB" if size_bytes >= 1024**2 else f"{size_bytes / 1024:.1f} KB"
        title = QLabel("Delete selected files?")
        title.setObjectName("H2")
        l.addWidget(title)

        info = QLabel(
            f"<b>{file_count}</b> file(s) ({size_str}) will be moved to Recycle Bin."
        )
        info.setWordWrap(True)
        l.addWidget(info)

        if excluded_count:
            excl = QLabel(f"{excluded_count} item(s) excluded from selection.")
            excl.setWordWrap(True)
            l.addWidget(excl)

        root.addWidget(card)

        btns = QHBoxLayout()
        btns.addStretch(1)

        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        btns.addWidget(btn_cancel)

        btn_ok = QPushButton("Move to Recycle Bin")
        btn_ok.setObjectName("DangerButton")
        btn_ok.clicked.connect(self._confirm_trash)
        btns.addWidget(btn_ok)

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

    def result_choice(self) -> DeletionPolicyChoice:
        return self._choice

    def _confirm_trash(self):
        self._choice = DeletionPolicyChoice(confirmed=True, mode="trash")
        self.accept()


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
