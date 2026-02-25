# cerebro/ui/components/modern/history_card.py
from __future__ import annotations

from typing import Optional, Callable

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QVBoxLayout, QLabel, QPushButton

from ._tokens import RADIUS_MD, SPACE_UNIT, token


class HistoryCard(QFrame):
    """Per-entry card: timestamp, mode badge, deleted/failed counts, bytes, actions (Open, Export, Resume)."""

    open_clicked = Signal()
    export_clicked = Signal()
    resume_clicked = Signal()

    def __init__(
        self,
        timestamp: str,
        mode: str,
        deleted: int,
        failed: int,
        bytes_reclaimed: str,
        parent=None,
        resumable: bool = False,
    ):
        super().__init__(parent)
        self.setObjectName("HistoryCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACE_UNIT * 2, SPACE_UNIT * 2, SPACE_UNIT * 2, SPACE_UNIT * 2)
        layout.setSpacing(SPACE_UNIT)

        row1 = QHBoxLayout()
        self._ts_label = QLabel(timestamp)
        self._ts_label.setObjectName("historyCardTs")
        row1.addWidget(self._ts_label, 0)
        self._mode_badge = QLabel(mode)
        self._mode_badge.setObjectName("historyCardMode")
        row1.addWidget(self._mode_badge, 0)
        row1.addStretch(1)
        layout.addLayout(row1)

        self._stats_label = QLabel(f"{deleted} deleted, {failed} failed · {bytes_reclaimed}")
        self._stats_label.setObjectName("historyCardStats")
        layout.addWidget(self._stats_label, 0)

        actions = QHBoxLayout()
        open_btn = QPushButton("Open in Review")
        open_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        open_btn.clicked.connect(self.open_clicked.emit)
        actions.addWidget(open_btn, 0)
        export_btn = QPushButton("Export")
        export_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        export_btn.clicked.connect(self.export_clicked.emit)
        actions.addWidget(export_btn, 0)
        if resumable:
            resume_btn = QPushButton("Resume")
            resume_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            resume_btn.clicked.connect(self.resume_clicked.emit)
            actions.addWidget(resume_btn, 0)
        actions.addStretch(1)
        layout.addLayout(actions)

        self._apply_theme()

    def _apply_theme(self) -> None:
        panel = token("panel")
        line = token("line")
        text = token("text")
        muted = token("muted")
        accent = token("accent")
        self.setStyleSheet(f"""
            HistoryCard {{
                background: {panel};
                border-radius: {RADIUS_MD}px;
                border: 1px solid {line};
            }}
            QLabel#historyCardTs {{ font-size: 12px; color: {muted}; }}
            QLabel#historyCardMode {{ font-size: 11px; padding: 2px 6px; border-radius: 4px; background: {accent}; color: white; }}
            QLabel#historyCardStats {{ font-size: 13px; color: {text}; }}
            QPushButton {{ padding: 4px 10px; border-radius: 4px; }}
        """)
