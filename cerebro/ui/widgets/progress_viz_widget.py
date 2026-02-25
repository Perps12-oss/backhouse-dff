# cerebro/ui/widgets/progress_viz_widget.py
from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Optional, Dict, Any

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QPainter, QPen, QFont, QPalette
from PySide6.QtWidgets import QWidget


@dataclass(slots=True)
class ProgressState:
    percent: int = 0
    message: str = ""
    stats: Optional[Dict[str, Any]] = None


class ProgressVizWidget(QWidget):
    """
    Lightweight progress ring widget.
    - set_state(percent, message, stats)
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._state = ProgressState()
        self.setMinimumSize(220, 220)

    def set_state(self, percent: int, message: str = "", stats: Optional[Dict[str, Any]] = None):
        self._state.percent = max(0, min(100, int(percent)))
        self._state.message = str(message or "")
        self._state.stats = dict(stats or {})
        self.update()

    def paintEvent(self, event):
        # FIX 1: Use a context manager for QPainter to prevent QBackingStore errors
        with QPainter(self) as p:
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

            rect = self.rect()
            size = min(rect.width(), rect.height())
            pad = max(10, int(size * 0.08))

            ring = QRectF(
                rect.center().x() - (size - 2 * pad) / 2,
                rect.center().y() - (size - 2 * pad) / 2,
                size - 2 * pad,
                size - 2 * pad,
            )

            # colors from palette (theme-friendly)
            base = self.palette().color(QPalette.ColorRole.Window)
            text = self.palette().color(QPalette.ColorRole.WindowText)
            
            # FIX 2: Correctly access the highlight color role in PySide6
            accent = self.palette().color(QPalette.ColorRole.Highlight)

            # ring background
            bg_pen = QPen(text)
            bg_pen.setWidthF(max(8.0, size * 0.06))
            bg_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            # The original code had redundant setColor calls, cleaning them up.
            bg_pen.setColor(text)
            bg_pen.setStyle(Qt.PenStyle.SolidLine)

            # tone down background ring using alpha
            c = bg_pen.color()
            c.setAlpha(50)
            bg_pen.setColor(c)

            p.setPen(bg_pen)
            p.drawArc(ring, 90 * 16, -360 * 16)

            # progress ring
            fg_pen = QPen(accent)
            fg_pen.setWidthF(bg_pen.widthF())
            fg_pen.setCapStyle(Qt.PenCapStyle.RoundCap)

            p.setPen(fg_pen)
            span = int(-360 * 16 * (self._state.percent / 100.0))
            p.drawArc(ring, 90 * 16, span)

            # center text
            p.setPen(text)

            f = QFont()
            f.setPointSize(max(12, int(size * 0.09)))
            f.setBold(True)
            p.setFont(f)
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, f"{self._state.percent}%")

            # message below
            msg_rect = QRectF(rect.left() + 10, rect.bottom() - 54, rect.width() - 20, 44)
            f2 = QFont()
            f2.setPointSize(max(9, int(size * 0.045)))
            f2.setBold(False)
            p.setFont(f2)

            msg = self._state.message
            if len(msg) > 70:
                msg = msg[:67] + "…"
            p.drawText(msg_rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter, msg)
    def set_progress(self, progress):
        """
        Set progress visualization.
        
        Args:
            progress: ScanProgress object or progress value
        """
        try:
            if hasattr(progress, 'percent'):
                # It's a ScanProgress object
                self._progress = progress.percent
                self._files_scanned = getattr(progress, 'scanned_files', 0)
            elif isinstance(progress, (int, float)):
                # It's a numeric value
                self._progress = float(progress)
            self.update()
        except Exception as e:
            logging.getLogger(__name__).debug(f"Error in set_progress: {e}")
    
    def set_phase(self, phase):
        """
        Set current phase for visualization.
        
        Args:
            phase: Phase name as string
        """
        try:
            self._current_phase = str(phase)
            self.update()
        except Exception as e:
            logging.getLogger(__name__).debug(f"Error in set_phase: {e}")