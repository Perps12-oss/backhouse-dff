# cerebro/ui/widgets/brand_header.py
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QPixmap, QFont
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QSizePolicy, QFrame
)

from cerebro.ui.widgets.eye_widget import EyeWidget


class BrandHeader(QFrame):
    """
    Persistent header chrome:
      - Left: Logo (top) + small Eye (below logo)  ✅ as requested
      - Center/Right: optional title area (placeholder label you can wire to router)
    """

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)

        self.setObjectName("BrandHeader")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        root = QHBoxLayout(self)
        root.setContentsMargins(18, 12, 18, 10)
        root.setSpacing(16)

        # --- Left brand stack: logo above, eye below ---
        self.brand_stack = QWidget()
        left = QVBoxLayout(self.brand_stack)
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(6)
        left.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self.logo = QLabel("CEREBRO")
        self.logo.setObjectName("BrandLogo")
        self.logo.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        font = QFont()
        font.setPointSize(14)
        font.setBold(True)
        self.logo.setFont(font)

        self.eye = EyeWidget()
        # Compact eye size for header (wide almond)
        self.eye.setFixedSize(120, 72)
        self.eye.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        left.addWidget(self.logo, 0)
        left.addWidget(self.eye, 0)

        root.addWidget(self.brand_stack, 0)

        # --- Center: page title / breadcrumb (optional) ---
        self.page_title = QLabel("")
        self.page_title.setObjectName("PageTitle")
        self.page_title.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        self.page_title.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        root.addWidget(self.page_title, 1)

        # --- Right placeholder (optional actions) ---
        self.right_slot = QWidget()
        self.right_slot.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        root.addWidget(self.right_slot, 0)

        self.apply_default_style()

    # ----------------------------
    # Public API
    # ----------------------------

    def set_logo_text(self, text: str) -> None:
        self.logo.setText(text)

    def set_logo_pixmap(self, pixmap: QPixmap, max_height: int = 28) -> None:
        if pixmap.isNull():
            return
        scaled = pixmap.scaledToHeight(max_height, Qt.TransformationMode.SmoothTransformation)
        self.logo.setPixmap(scaled)
        self.logo.setText("")  # replace text with image

    def set_logo_path(self, path: str | Path, max_height: int = 28) -> None:
        p = QPixmap(str(path))
        if p.isNull():
            return
        self.set_logo_pixmap(p, max_height=max_height)

    def set_page_title(self, title: str) -> None:
        self.page_title.setText(title)

    def set_scanning(self, scanning: bool) -> None:
        """Forward scan state into the eye (glow, dilation, steadier gaze)."""
        self.eye.set_scanning(scanning)

    def apply_theme(self, colors: dict) -> None:
        """
        Hook into your ThemeManager: pass theme['colors'] here.
        Expected keys (best-effort): text_primary, text_secondary, surface, outline_variant
        """
        text_primary = colors.get("text_primary", "#EAEAEA")
        text_secondary = colors.get("text_secondary", "#B8B8B8")
        surface = colors.get("surface", "rgba(20, 22, 28, 0.72)")
        outline = colors.get("outline_variant", "rgba(255,255,255,0.10)")

        self.setStyleSheet(f"""
            QFrame#BrandHeader {{
                background: {surface};
                border-bottom: 1px solid {outline};
                border-radius: 14px;
            }}
            QLabel#BrandLogo {{
                color: {text_primary};
                letter-spacing: 1px;
            }}
            QLabel#PageTitle {{
                color: {text_secondary};
                font-size: 12px;
            }}
        """)

    def apply_default_style(self) -> None:
        # Neutral fallback if theme not ready yet
        self.setStyleSheet("""
            QFrame#BrandHeader {
                background: rgba(20, 22, 28, 0.72);
                border-bottom: 1px solid rgba(255,255,255,0.10);
                border-radius: 14px;
            }
            QLabel#BrandLogo {
                color: rgba(255,255,255,0.92);
                letter-spacing: 1px;
            }
            QLabel#PageTitle {
                color: rgba(255,255,255,0.65);
                font-size: 12px;
            }
        """)
