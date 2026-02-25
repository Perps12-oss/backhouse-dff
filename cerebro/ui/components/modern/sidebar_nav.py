# cerebro/ui/components/modern/sidebar_nav.py
from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import QFrame, QVBoxLayout, QPushButton, QLabel

from ._tokens import RADIUS_SM, SPACE_UNIT, NAV_ITEM_HEIGHT, token


class SidebarNavItem:
    id: str
    icon: str
    label: str
    count: int
    badge_color: Optional[str]

    def __init__(
        self,
        id: str,
        icon: str,
        label: str,
        count: int = 0,
        badge_color: Optional[str] = None,
    ):
        self.id = id
        self.icon = icon
        self.label = label
        self.count = count
        self.badge_color = badge_color


class _NavButton(QPushButton):
    def __init__(self, item: SidebarNavItem, parent=None):
        super().__init__(parent)
        self.setObjectName("SidebarNavButton")
        self._item = item
        self._active = False
        self._update_text()

    def _update_text(self) -> None:
        if self._item.count > 0:
            self.setText(f"{self._item.icon}  {self._item.label}  ({self._item.count})")
        else:
            self.setText(f"{self._item.icon}  {self._item.label}")

    def set_active(self, active: bool) -> None:
        self._active = bool(active)
        self._refresh_style()

    def set_count(self, count: int) -> None:
        self._item.count = count
        self._update_text()

    def _refresh_style(self) -> None:
        accent = token("accent")
        bg = token("bg")
        panel = token("panel")
        text = token("text")
        muted = token("muted")
        line = token("line")
        if self._active:
            border = f"3px solid {accent}"
            bg_use = token("hover_bg") if "hover" in str(token("hover_bg")) else accent
        else:
            border = "3px solid transparent"
            bg_use = "transparent"
        self.setStyleSheet(f"""
            QPushButton#SidebarNavButton {{
                text-align: left;
                padding: {SPACE_UNIT}px {SPACE_UNIT * 2}px;
                min-height: {NAV_ITEM_HEIGHT}px;
                border-left: {border};
                border-radius: {RADIUS_SM}px;
                background: {bg_use};
                color: {text};
                font-size: 13px;
            }}
            QPushButton#SidebarNavButton:hover {{ background: {token('hover_bg')}; }}
        """)


class SidebarNav(QFrame):
    item_clicked = Signal(str)

    def __init__(self, items: List[SidebarNavItem], parent=None):
        super().__init__(parent)
        self.setObjectName("SidebarNav")
        self._items = list(items)
        self._buttons: List[_NavButton] = []
        self._active_id: Optional[str] = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE_UNIT)
        for item in self._items:
            btn = _NavButton(item, self)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda checked=False, i=item: self.item_clicked.emit(i.id))
            self._buttons.append(btn)
            layout.addWidget(btn)
        layout.addStretch(1)
        self._apply_theme()

    def _apply_theme(self) -> None:
        for i, btn in enumerate(self._buttons):
            btn.set_active(self._items[i].id == self._active_id)

    def update_count(self, item_id: str, count: int) -> None:
        for i, item in enumerate(self._items):
            if item.id == item_id:
                item.count = count
                if i < len(self._buttons):
                    self._buttons[i].set_count(count)
                return

    def set_active(self, item_id: str) -> None:
        self._active_id = item_id
        self._apply_theme()
