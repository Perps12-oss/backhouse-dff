# cerebro/ui/components/modern/page_scaffold.py
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QVBoxLayout, QHBoxLayout, QWidget, QSplitter, QScrollArea

from ._tokens import (
    RADIUS_MD,
    SPACE_UNIT,
    SIDEBAR_WIDTH,
    HEADER_HEIGHT,
    STICKY_BAR_HEIGHT,
    token,
)


class PageScaffold(QFrame):
    """
    Card-based page skeleton: Header | Sidebar + Content | optional StickyActionBar.
    Slots: set_header(), set_sidebar(), set_content(), set_sticky_action().
    """

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        show_sidebar: bool = True,
        show_sticky_action: bool = True,
        sidebar_width: int = SIDEBAR_WIDTH,
    ):
        super().__init__(parent)
        self._show_sidebar = show_sidebar
        self._show_sticky_action = show_sticky_action
        self._sidebar_width = sidebar_width
        self._header_widget: Optional[QWidget] = None
        self._sidebar_widget: Optional[QWidget] = None
        self._content_widget: Optional[QWidget] = None
        self._sticky_widget: Optional[QWidget] = None
        self._main_layout = QVBoxLayout(self)
        self._main_layout.setContentsMargins(0, 0, 0, 0)
        self._main_layout.setSpacing(0)
        self._build()

    def _build(self) -> None:
        bg = token("bg")
        self.setStyleSheet(f"PageScaffold {{ background: {bg}; }}")

        # Header slot (fixed height)
        self._header_placeholder = QFrame()
        self._header_placeholder.setFixedHeight(HEADER_HEIGHT)
        self._header_placeholder.setObjectName("pageScaffoldHeader")
        self._header_layout = QVBoxLayout(self._header_placeholder)
        self._header_layout.setContentsMargins(SPACE_UNIT * 2, 0, SPACE_UNIT * 2, 0)
        self._header_layout.setSpacing(0)
        self._main_layout.addWidget(self._header_placeholder)

        # Center: sidebar + content
        self._center = QFrame()
        self._center_layout = QHBoxLayout(self._center)
        self._center_layout.setContentsMargins(0, 0, 0, 0)
        self._center_layout.setSpacing(0)

        if self._show_sidebar:
            self._sidebar_placeholder = QFrame()
            self._sidebar_placeholder.setFixedWidth(self._sidebar_width)
            self._sidebar_placeholder.setObjectName("pageScaffoldSidebar")
            self._sidebar_layout = QVBoxLayout(self._sidebar_placeholder)
            self._sidebar_layout.setContentsMargins(SPACE_UNIT, SPACE_UNIT * 2, SPACE_UNIT, SPACE_UNIT * 2)
            self._sidebar_layout.setSpacing(SPACE_UNIT)
            self._center_layout.addWidget(self._sidebar_placeholder)
        else:
            self._sidebar_placeholder = None
            self._sidebar_layout = None

        self._content_placeholder = QFrame()
        self._content_placeholder.setObjectName("pageScaffoldContent")
        self._content_layout = QVBoxLayout(self._content_placeholder)
        self._content_layout.setContentsMargins(SPACE_UNIT * 2, SPACE_UNIT * 2, SPACE_UNIT * 2, SPACE_UNIT * 2)
        self._content_layout.setSpacing(SPACE_UNIT * 2)
        self._center_layout.addWidget(self._content_placeholder, 1)

        self._main_layout.addWidget(self._center, 1)

        # Sticky action bar (optional)
        if self._show_sticky_action:
            self._sticky_placeholder = QFrame()
            self._sticky_placeholder.setFixedHeight(STICKY_BAR_HEIGHT)
            self._sticky_placeholder.setObjectName("pageScaffoldSticky")
            self._sticky_layout = QVBoxLayout(self._sticky_placeholder)
            self._sticky_layout.setContentsMargins(SPACE_UNIT * 2, 0, SPACE_UNIT * 2, 0)
            self._sticky_layout.setSpacing(0)
            self._main_layout.addWidget(self._sticky_placeholder)
        else:
            self._sticky_placeholder = None
            self._sticky_layout = None

        self._apply_theme()

    def _apply_theme(self) -> None:
        line = token("line")
        panel = token("panel")
        sheet = (
            f"#pageScaffoldHeader {{ border-bottom: 1px solid {line}; background: {panel}; }}"
            f"#pageScaffoldSidebar {{ border-right: 1px solid {line}; background: {panel}; }}"
            f"#pageScaffoldContent {{ background: transparent; }}"
            f"#pageScaffoldSticky {{ border-top: 1px solid {line}; background: {panel}; }}"
        )
        self._header_placeholder.setStyleSheet(sheet)
        if self._sidebar_placeholder:
            self._sidebar_placeholder.setStyleSheet(sheet)
        if self._sticky_placeholder:
            self._sticky_placeholder.setStyleSheet(sheet)

    def set_header(self, widget: QWidget) -> None:
        self._clear_layout(self._header_layout)
        self._header_widget = widget
        self._header_layout.addWidget(widget)

    def set_sidebar(self, widget: QWidget) -> None:
        if self._sidebar_layout is None:
            return
        self._clear_layout(self._sidebar_layout)
        self._sidebar_widget = widget
        self._sidebar_layout.addWidget(widget)

    def set_content(self, widget: QWidget) -> None:
        self._clear_layout(self._content_layout)
        self._content_widget = widget
        self._content_layout.addWidget(widget, 1)

    def set_sticky_action(self, widget: QWidget) -> None:
        if self._sticky_layout is None:
            return
        self._clear_layout(self._sticky_layout)
        self._sticky_widget = widget
        self._sticky_layout.addWidget(widget)

    def _clear_layout(self, layout: QVBoxLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().setParent(None)
