# cerebro/ui/components/modern/top_toolbar.py
from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLineEdit, QComboBox, QPushButton, QWidget

from ._tokens import TOOLBAR_HEIGHT, SPACE_UNIT, RADIUS_SM, token


class TopToolbar(QFrame):
    search_changed = Signal(str)
    sort_changed = Signal(str)
    view_toggled = Signal(str)

    def __init__(
        self,
        parent=None,
        show_search: bool = True,
        show_sort: bool = True,
        show_view_toggle: bool = True,
        custom_actions: Optional[List[QWidget]] = None,
    ):
        super().__init__(parent)
        self.setObjectName("TopToolbar")
        self.setFixedHeight(TOOLBAR_HEIGHT)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE_UNIT * 2)

        if show_search:
            self._search = QLineEdit()
            self._search.setPlaceholderText("Search…")
            self._search.setObjectName("toolbarSearch")
            self._search.textChanged.connect(self.search_changed.emit)
            layout.addWidget(self._search, 1)
        else:
            self._search = None

        if show_sort:
            self._sort = QComboBox()
            self._sort.addItems(["Default", "Size", "Name", "Date"])
            self._sort.currentTextChanged.connect(self.sort_changed.emit)
            layout.addWidget(self._sort, 0)
        else:
            self._sort = None

        if show_view_toggle:
            self._view_btn = QPushButton("⊞ List")
            self._view_btn.setCheckable(True)
            self._view_btn.clicked.connect(self._on_view_click)
            layout.addWidget(self._view_btn, 0)
        else:
            self._view_btn = None

        for w in (custom_actions or []):
            layout.addWidget(w, 0)

        layout.addStretch(1)
        self._apply_theme()

    def _on_view_click(self) -> None:
        if self._view_btn and self._view_btn.isChecked():
            self.view_toggled.emit("grid")
            self._view_btn.setText("⊟ Grid")
        else:
            self.view_toggled.emit("list")
            if self._view_btn:
                self._view_btn.setText("⊞ List")

    def _apply_theme(self) -> None:
        line = token("line")
        text = token("text")
        muted = token("muted")
        panel = token("panel")
        self.setStyleSheet(f"""
            TopToolbar {{
                border-bottom: 1px solid {line};
                background: {panel};
            }}
            QLineEdit#toolbarSearch {{
                padding: {SPACE_UNIT}px {SPACE_UNIT * 2}px;
                border-radius: {RADIUS_SM}px;
                color: {text};
                background: transparent;
            }}
            QComboBox, QPushButton {{ color: {text}; }}
        """)
