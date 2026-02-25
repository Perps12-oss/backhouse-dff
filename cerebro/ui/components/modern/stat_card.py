# cerebro/ui/components/modern/stat_card.py
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QPropertyAnimation, QEasingCurve, Property
from PySide6.QtWidgets import QFrame, QVBoxLayout, QLabel

from ._tokens import RADIUS_MD, SPACE_UNIT, token


class StatCard(QFrame):
    """Label + value (+ optional delta, icon). Min-width 120px, hover lift."""

    def __init__(
        self,
        label: str,
        value: str,
        delta: Optional[str] = None,
        icon: Optional[str] = None,
        parent=None,
    ):
        super().__init__(parent)
        self.setObjectName("StatCard")
        self.setMinimumWidth(120)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACE_UNIT * 2, SPACE_UNIT * 2, SPACE_UNIT * 2, SPACE_UNIT * 2)
        layout.setSpacing(SPACE_UNIT)

        if icon:
            self._icon_label = QLabel(icon)
            self._icon_label.setObjectName("statCardIcon")
            layout.addWidget(self._icon_label, 0)
        else:
            self._icon_label = None

        self._value_label = QLabel(value)
        self._value_label.setObjectName("statCardValue")
        layout.addWidget(self._value_label, 0)

        self._label_label = QLabel(label)
        self._label_label.setObjectName("statCardLabel")
        layout.addWidget(self._label_label, 0)

        self._delta_label = QLabel(delta or "") if delta else None
        if self._delta_label:
            self._delta_label.setObjectName("statCardDelta")
            layout.addWidget(self._delta_label, 0)

        layout.addStretch(1)
        self._apply_theme()

    def _apply_theme(self) -> None:
        text = token("text")
        muted = token("muted")
        panel = token("panel")
        line = token("line")
        self.setStyleSheet(f"""
            StatCard {{
                background: {panel};
                border-radius: {RADIUS_MD}px;
                border: 1px solid {line};
            }}
            StatCard:hover {{ border-color: {token('accent')}; }}
            QLabel#statCardValue {{ font-size: 32px; font-weight: bold; color: {text}; }}
            QLabel#statCardLabel {{ font-size: 12px; color: {muted}; }}
            QLabel#statCardIcon {{ font-size: 24px; }}
            QLabel#statCardDelta {{ font-size: 12px; color: {token('ok')}; }}
        """)

    def set_value(self, value: str) -> None:
        self._value_label.setText(value)

    def pulse(self) -> None:
        anim = QPropertyAnimation(self, b"windowOpacity")
        anim.setDuration(200)
        anim.setStartValue(1.0)
        anim.setKeyValueAt(0.5, 0.7)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
