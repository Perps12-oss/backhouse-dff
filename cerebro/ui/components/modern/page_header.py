# cerebro/ui/components/modern/page_header.py
from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QWidget

from ._tokens import SPACE_UNIT, token


class PageHeader(QFrame):
    """Left: Title (24px bold) + Subtitle (14px muted). Right: set_action_widget() slot."""

    def __init__(self, title: str, subtitle: str = "", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("PageHeader")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE_UNIT * 2)

        self._title_label = QLabel(title)
        self._title_label.setObjectName("pageHeaderTitle")
        self._subtitle_label = QLabel(subtitle)
        self._subtitle_label.setObjectName("pageHeaderSubtitle")

        layout.addWidget(self._title_label, 0)
        layout.addWidget(self._subtitle_label, 1)
        layout.addStretch(1)
        self._action_widget: Optional[QWidget] = None
        self._action_layout_index = -1
        self._apply_theme()

    def _apply_theme(self) -> None:
        text = token("text")
        muted = token("muted")
        self._title_label.setStyleSheet(
            f"#pageHeaderTitle {{ font-size: 24px; font-weight: bold; color: {text}; }}"
        )
        self._subtitle_label.setStyleSheet(
            f"#pageHeaderSubtitle {{ font-size: 14px; color: {muted}; }}"
        )

    def set_subtitle(self, text: str) -> None:
        self._subtitle_label.setText(text)

    def set_title(self, text: str) -> None:
        self._title_label.setText(text)

    def set_action_widget(self, widget: Optional[QWidget]) -> None:
        layout = self.layout()
        if not isinstance(layout, QHBoxLayout):
            return
        if self._action_widget is not None:
            self._action_widget.setParent(None)
            self._action_widget = None
        self._action_widget = widget
        if widget is not None:
            layout.addWidget(widget, 0)
