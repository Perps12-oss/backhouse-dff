# cerebro/ui/widgets/orb_widget.py
import math
from dataclasses import dataclass, field
from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, Property, QTimer, QPointF, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QPainter, QColor, QRadialGradient, QBrush, QPen


@dataclass(frozen=True, slots=True)
class OrbStyle:
    base_alpha: int = 26
    rim_alpha: int = 90
    pupil_alpha: int = 220
    glow_alpha: int = 40
    idle_accent: QColor = None
    scan_accent: QColor = field(default_factory=lambda: QColor(59, 130, 246))


class OrbWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setMinimumSize(280, 280)
        
        # v2 additions
        # The custom _opacity property and its setter have been removed.
        # We will use Qt's built-in windowOpacity property instead.
        
        self._scanning = False
        self._pulsing = True
        
        # Animation setup (v1 style)
        self._pulse = 0.0
        self._target = QPointF(0.0, 0.0)
        self._pupil = QPointF(0.0, 0.0)
        
        # This animation is for the 'pulse' property, which is correct.
        self._anim = QPropertyAnimation(self, b"pulse")
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setDuration(3800)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutSine)
        self._anim.setLoopCount(-1)
        
        if self._pulsing:
            self._anim.start()

        self._tick = QTimer(self)
        self._tick.setInterval(16)
        self._tick.timeout.connect(self._step)
        self._tick.start()

    # The custom @Property for 'opacity' has been REMOVED.
    # We will use the built-in 'windowOpacity' property for opacity animations.

    def set_scanning(self, scanning: bool):
        """Switch between idle (theme color) and scanning (blue) modes."""
        self._scanning = scanning
        self.update()

    def set_pulsing(self, pulsing: bool):
        """Start/stop the breathing animation."""
        self._pulsing = pulsing
        if pulsing and self._anim.state() != QPropertyAnimation.State.Running:
            self._anim.start()
        elif not pulsing:
            self._anim.stop()
        self.update()

    def sizeHint(self):
        return self.minimumSize()

    def get_pulse(self) -> float:
        return float(self._pulse)

    def set_pulse(self, v: float) -> None:
        self._pulse = float(v)
        self.update()

    pulse = Property(float, get_pulse, set_pulse)

    def mouseMoveEvent(self, e) -> None:
        c = QPointF(self.width() / 2.0, self.height() / 2.0)
        p = QPointF(float(e.position().x()), float(e.position().y()))
        v = p - c
        r = min(self.width(), self.height()) * 0.22
        d = math.hypot(v.x(), v.y())
        if d > 1e-6:
            s = min(1.0, r / d)
            v *= s
        self._target = v
        super().mouseMoveEvent(e)

    def leaveEvent(self, _e) -> None:
        self._target = QPointF(0.0, 0.0)
        super().leaveEvent(_e)

    def _step(self) -> None:
        k = 0.12
        self._pupil = self._pupil * (1.0 - k) + self._target * k
        self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        # The line p.setOpacity(self._opacity) has been REMOVED.
        # The painter now correctly inherits the widget's opacity from the built-in property.

        w, h = self.width(), self.height()
        c = QPointF(w / 2.0, h / 2.0)
        r0 = min(w, h) * 0.36

        breathe = 1.0 + 0.018 * math.sin(self._pulse * 2.0 * math.pi)
        r = r0 * breathe

        if self._scanning:
            accent = QColor(59, 130, 246)
        else:
            accent = self.palette().highlight().color()
            
        bg = self.palette().window().color()
        style = OrbStyle()

        glow = QColor(accent)
        glow.setAlpha(style.glow_alpha)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(glow))
        p.drawEllipse(c, r * 1.07, r * 1.07)

        body = QColor(bg)
        body.setAlpha(style.base_alpha)
        p.setBrush(QBrush(body))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(c, r, r)

        rim = QColor(accent)
        rim.setAlpha(style.rim_alpha)
        pen = QPen(rim, max(2.0, r * 0.05))
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(c, r, r)

        pupil = QColor(accent)
        pupil.setAlpha(style.pupil_alpha)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(pupil))
        pr = r * 0.22
        pc = c + self._pupil
        p.drawEllipse(pc, pr, pr)

        hi = QColor(255, 255, 255, 70)
        p.setBrush(QBrush(hi))
        p.drawEllipse(c + QPointF(-r * 0.25, -r * 0.25), r * 0.22, r * 0.22)
