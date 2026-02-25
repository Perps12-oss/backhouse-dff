# cerebro/ui/components/collapsible_section.py
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal, QPropertyAnimation, QEasingCurve
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame, QSizePolicy
)


class CollapsibleSection(QFrame):
    """
    Reusable collapsible container.
    Public API (kept stable):
      - set_content(widget: QWidget) -> None
      - set_collapsed(bool) -> None
      - is_collapsed() -> bool
      - toggle() -> None

    Notes:
      - This fixes the recursion bug in the previous version.
      - Uses height animation on the body wrapper.
    """
    toggled = Signal(bool)  # collapsed state

    def __init__(
        self,
        title: str = "Section",
        subtitle: str = "",
        collapsed: bool = False,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.setObjectName("CollapsibleSection")
        self.setFrameShape(QFrame.NoFrame)

        self._collapsed = bool(collapsed)
        self._content: Optional[QWidget] = None

        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(0, 0, 0, 0)
        self._root.setSpacing(8)

        # Header
        self._header = QFrame(self)
        self._header.setObjectName("CollapsibleHeader")
        self._header.setStyleSheet("""
            #CollapsibleHeader {
                background: rgba(20, 26, 38, 0.35);
                border: 1px solid rgba(120,140,180,0.18);
                border-radius: 14px;
            }
            QLabel#CollapsibleTitle { font-weight: 800; font-size: 13px; }
            QLabel#CollapsibleSubtitle { color: rgba(185,195,215,0.85); }
            QPushButton {
                border-radius: 10px;
                padding: 6px 10px;
                border: 1px solid rgba(120,140,180,0.18);
                background: rgba(18, 22, 32, 0.45);
            }
            QPushButton:hover { border-color: rgba(130,170,255,0.55); }
        """)

        hl = QHBoxLayout(self._header)
        hl.setContentsMargins(12, 10, 12, 10)
        hl.setSpacing(10)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(2)

        self._title = QLabel(title)
        self._title.setObjectName("CollapsibleTitle")

        self._subtitle = QLabel(subtitle)
        self._subtitle.setObjectName("CollapsibleSubtitle")
        self._subtitle.setVisible(bool(subtitle))

        text_col.addWidget(self._title)
        text_col.addWidget(self._subtitle)

        self._toggle_btn = QPushButton("▾")
        self._toggle_btn.setCursor(Qt.PointingHandCursor)
        self._toggle_btn.setFixedWidth(40)
        self._toggle_btn.clicked.connect(self.toggle)

        hl.addLayout(text_col, 1)
        hl.addWidget(self._toggle_btn, 0, Qt.AlignRight)

        self._root.addWidget(self._header)

        # Body wrapper (animated)
        self._body = QFrame(self)
        self._body.setObjectName("CollapsibleBody")
        self._body.setStyleSheet("""
            #CollapsibleBody {
                background: rgba(18, 22, 32, 0.22);
                border: 1px solid rgba(120,140,180,0.12);
                border-radius: 14px;
            }
        """)
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(12, 12, 12, 12)
        self._body_layout.setSpacing(8)

        self._root.addWidget(self._body)

        # Animation
        self._anim = QPropertyAnimation(self._body, b"maximumHeight", self)
        self._anim.setDuration(180)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)

        # Init collapsed state
        self.set_collapsed(self._collapsed, animate=False)

    # ----------------------------
    # Public API
    # ----------------------------

    def set_title(self, title: str) -> None:
        self._title.setText(title or "Section")

    def set_subtitle(self, subtitle: str) -> None:
        self._subtitle.setText(subtitle or "")
        self._subtitle.setVisible(bool(subtitle))

    def is_collapsed(self) -> bool:
        return self._collapsed

    def set_collapsed(self, collapsed: bool, animate: bool = True) -> None:
        collapsed = bool(collapsed)
        if collapsed == self._collapsed and animate:
            return
        self._collapsed = collapsed

        # Update chevron
        self._toggle_btn.setText("▸" if self._collapsed else "▾")

        if self._collapsed:
            if animate:
                self._animate_to(0)
            else:
                self._body.setMaximumHeight(0)
            self._body.setVisible(False if not animate else True)
        else:
            # ensure visible to measure content
            self._body.setVisible(True)
            target = self._measure_body_height()
            if animate:
                self._animate_to(target)
            else:
                self._body.setMaximumHeight(target)

        self.toggled.emit(self._collapsed)

    def toggle(self) -> None:
        self.set_collapsed(not self._collapsed)

    def set_content(self, widget: QWidget) -> None:
        """
        Replace the body content with a new widget.
        FIXED: no recursion; properly swaps widgets in layout.
        """
        if widget is None:
            return

        # Remove old content
        if self._content is not None:
            self._content.setParent(None)
            self._content.deleteLater()
            self._content = None

        # Add new content
        self._content = widget
        self._content.setParent(self._body)
        self._content.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        self._body_layout.addWidget(self._content)

        # Recompute size if expanded
        if not self._collapsed:
            target = self._measure_body_height()
            self._body.setMaximumHeight(target)

    # ----------------------------
    # Internals
    # ----------------------------

    def _measure_body_height(self) -> int:
        # Ensure layout is updated
        self._body_layout.activate()
        h = self._body_layout.sizeHint().height()
        # a little padding safety
        return max(40, h + 2)

    def _animate_to(self, target_h: int) -> None:
        self._anim.stop()

        # If collapsing: keep visible during animation then hide
        if self._collapsed:
            self._body.setVisible(True)

        start = self._body.maximumHeight()
        if start < 0:
            start = self._measure_body_height()

        self._anim.setStartValue(int(start))
        self._anim.setEndValue(int(target_h))

        def on_finished():
            if self._collapsed:
                self._body.setVisible(False)

        try:
            self._anim.finished.disconnect()
        except Exception:
            pass
        self._anim.finished.connect(on_finished)

        self._anim.start()
