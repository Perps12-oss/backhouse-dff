"""Animated eye widget with emotions, pupil dynamics, and theme support."""
from __future__ import annotations

import math
import random
import time
from collections import deque
from dataclasses import dataclass
from typing import Optional, List, Tuple, Dict, Any
from enum import Enum, auto

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QObject,
    QPoint,
    QPointF,
    QPropertyAnimation,
    QRectF,
    QSequentialAnimationGroup,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QPainter,
    QBrush,
    QPen,
    QRadialGradient,
    QLinearGradient,
    QImage,
    QCursor,
    QPainterPath,
    QPainterPathStroker,
    QTransform,
)
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLabel,
    QComboBox,
    QSlider,
    QCheckBox,
    QPushButton,
    QFrame,
    QHBoxLayout,
    QGridLayout,
    QGroupBox,
)

# -------------------------------------------------------------------------
# Constants (aligned with eyev_pro where applicable)
# -------------------------------------------------------------------------
DEFAULT_AUTONOMOUS_MOOD_INTERVAL = 8.0
DEFAULT_CONSTRICTION_TIME = 0.15
DEFAULT_DILATION_TIME = 0.4
HIPPUS_MAX_AMPLITUDE = 0.03
HIPPUS_FREQUENCY = 0.5  # Hz, physiological pupil oscillation


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * _clamp(t, 0.0, 1.0)


def _exponential_smooth(current: float, target: float, dt: float, time_constant: float) -> float:
    """Smoothly move current toward target (exponential decay)."""
    if time_constant <= 0:
        return target
    alpha = 1.0 - math.exp(-dt / time_constant)
    return current + (target - current) * _clamp(alpha, 0.0, 1.0)


def _lerp_pt(a: QPointF, b: QPointF, t: float) -> QPointF:
    return QPointF(_lerp(a.x(), b.x(), t), _lerp(a.y(), b.y(), t))


def _mix_color(c1: QColor, c2: QColor, t: float) -> QColor:
    t = _clamp(t, 0.0, 1.0)
    return QColor(
        int(c1.red() + (c2.red() - c1.red()) * t),
        int(c1.green() + (c2.green() - c1.green()) * t),
        int(c1.blue() + (c2.blue() - c1.blue()) * t),
        int(c1.alpha() + (c2.alpha() - c1.alpha()) * t),
    )


@dataclass
class EmotionParams:
    upper_tension: float
    lower_tension: float
    dilation: float
    squint: float
    brow_raise: float


class EyeEmotion(Enum):
    NEUTRAL = "neutral"
    SURPRISED = "surprised"
    SUSPICIOUS = "suspicious"
    TIRED = "tired"
    HAPPY = "happy"
    ANGRY = "angry"
    SAD = "sad"
    FOCUSED = "focused"
    SLEEPY = "sleepy"
    CURIOUS = "curious"
    RELAXED = "relaxed"


class PupilShape(Enum):
    ROUND = "round"
    VERTICAL_SLIT = "vertical_slit"
    HORIZONTAL_SLIT = "horizontal_slit"
    SQUARE = "square"
    DROPLET = "droplet"


class EyeState(Enum):
    IDLE = "idle"
    SCANNING = "scanning"
    FOCUSING = "focusing"
    REVIEWING = "reviewing"
    DECIDING = "deciding"
    RESTING = "resting"
    ERROR = "error"


class EyePalette:
    """Color palette for the eye widget."""
    def __init__(self) -> None:
        self.sclera_base = QColor(255, 248, 240)
        self.sclera_shadow = QColor(240, 220, 210)
        self.scattering_tint = QColor(200, 220, 255, 40)
        self.sclera_vein = QColor(220, 180, 180, 80)
        self.iris_base = QColor(80, 120, 160)
        self.iris_light = QColor(120, 160, 200)
        self.iris_dark = QColor(50, 90, 130)
        self.limbal_ring = QColor(40, 70, 100)
        self.iris_crypt = QColor(100, 140, 180, 60)
        self.pupil = QColor(20, 20, 30)
        self.pupil_border = QColor(15, 15, 25)
        self.highlight_primary = QColor(255, 255, 255, 180)
        self.highlight_secondary = QColor(255, 255, 255, 80)
        self.eyelid_skin = QColor(255, 220, 200)

    @classmethod
    def preset(cls, name: str) -> "EyePalette":
        p = cls()
        # Allow theme overrides; default is current values
        return p


class EyeConfig:
    """Runtime config for pupil and movement (aligned with eyev_pro behavior options)."""
    def __init__(self) -> None:
        self.pupil_shape = PupilShape.ROUND
        self.pupil_constriction_time = DEFAULT_CONSTRICTION_TIME
        self.pupil_dilation_time = DEFAULT_DILATION_TIME
        self.microsaccades_enabled = True
        self.tremor_enabled = True
        self.blink_rate = 0.025  # probability per tick
        # Blink timing (eyev_pro-style, used for animation durations)
        self.blink_interval_min = 2.0
        self.blink_interval_max = 6.0
        self.blink_duration_close = 0.07   # seconds
        self.blink_duration_open = 0.13
        # Saccade timing (eyev_pro-style)
        self.saccade_interval_min = 0.6
        self.saccade_interval_max = 2.0
        self.saccade_interval_focused_min = 0.4
        self.saccade_interval_focused_max = 1.2
        self.saccade_interval_sleepy_min = 0.8
        self.saccade_interval_sleepy_max = 3.0


class MicroMovementGenerator:
    """Generates micro-movement parameters."""
    pass


class PupilDynamics:
    """Pupil dynamics state (eyev_pro-compatible attributes)."""
    def __init__(self) -> None:
        self.light_history: deque = deque(maxlen=100)  # (timestamp, light_level)
        self.hippus_frequency = HIPPUS_FREQUENCY
        self.hippus_phase = random.random() * 2 * math.pi


class EyePhysicsState(QObject):
    """State object emitted via eyeStateChanged."""
    pass


class EyeControlMenu(QWidget):
    """Floating control menu for the eye widget, shown to the right of the eye (eyev_pro-style)."""
    MENU_WIDTH = 220
    MENU_HEIGHT = 320
    GAP_RIGHT = 8

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setFixedSize(self.MENU_WIDTH, self.MENU_HEIGHT)
        self.setStyleSheet("""
            EyeControlMenu, QWidget#eye_control_menu {
                background-color: rgba(30, 30, 40, 245);
                border: 1px solid rgba(255, 255, 255, 120);
                border-radius: 8px;
            }
            QLabel { color: rgba(255,255,255,220); font-size: 11px; }
            QComboBox, QSlider::groove:horizontal { background: rgba(60,60,70,200); border-radius: 4px; }
            QPushButton { background: rgba(80,80,100,200); color: #eee; border-radius: 4px; padding: 4px; }
            QPushButton:hover { background: rgba(100,120,180,220); }
        """)
        self.setObjectName("eye_control_menu")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)

        title = QLabel("Eye controls")
        title.setStyleSheet("font-weight: bold; font-size: 13px;")
        layout.addWidget(title)

        layout.addWidget(QLabel("Emotion:"))
        self.emotion_combo = QComboBox()
        self.emotion_combo.addItems([e.value.capitalize() for e in EyeEmotion])
        self.emotion_combo.currentIndexChanged.connect(self._on_emotion_changed)
        layout.addWidget(self.emotion_combo)

        layout.addWidget(QLabel("Pupil shape:"))
        self.pupil_combo = QComboBox()
        self.pupil_combo.addItems([s.value.replace("_", " ").title() for s in PupilShape])
        self.pupil_combo.currentIndexChanged.connect(self._on_pupil_changed)
        layout.addWidget(self.pupil_combo)

        layout.addWidget(QLabel("Palette:"))
        self.palette_combo = QComboBox()
        self.palette_combo.addItems(["Default", "Blue", "Brown", "Green"])
        self.palette_combo.currentTextChanged.connect(self._on_palette_changed)
        layout.addWidget(self.palette_combo)

        layout.addWidget(QLabel("Blink rate:"))
        self.blink_slider = QSlider(Qt.Orientation.Horizontal)
        self.blink_slider.setRange(5, 80)
        self.blink_slider.setValue(25)
        self.blink_slider.valueChanged.connect(self._on_blink_rate_changed)
        layout.addWidget(self.blink_slider)

        btn_layout = QHBoxLayout()
        self.blink_btn = QPushButton("Blink now")
        self.blink_btn.clicked.connect(self._on_blink_now)
        btn_layout.addWidget(self.blink_btn)
        self.reset_btn = QPushButton("Reset")
        self.reset_btn.clicked.connect(self._on_reset)
        btn_layout.addWidget(self.reset_btn)
        layout.addLayout(btn_layout)

        layout.addStretch()

    def _eye(self):
        return self.parent()

    def _on_emotion_changed(self, index: int) -> None:
        eye = self._eye()
        if eye and 0 <= index < len(EyeEmotion):
            eye.set_emotion(list(EyeEmotion)[index])

    def _on_pupil_changed(self, index: int) -> None:
        eye = self._eye()
        if eye and 0 <= index < len(PupilShape):
            eye.set_pupil_shape(list(PupilShape)[index])

    def _on_palette_changed(self, text: str) -> None:
        eye = self._eye()
        if eye and text:
            eye.set_palette_preset(text.lower())

    def _on_blink_rate_changed(self, value: int) -> None:
        eye = self._eye()
        if eye:
            eye.config.blink_rate = value / 1000.0

    def _on_blink_now(self) -> None:
        eye = self._eye()
        if eye and hasattr(eye, "trigger_blink"):
            eye.trigger_blink()

    def _on_reset(self) -> None:
        eye = self._eye()
        if eye and hasattr(eye, "reset_to_defaults"):
            eye.reset_to_defaults()
        self.emotion_combo.setCurrentIndex(0)
        self.pupil_combo.setCurrentIndex(0)
        self.palette_combo.setCurrentIndex(0)
        self.blink_slider.setValue(25)

    def showEvent(self, event) -> None:
        """Sync combo/slider values from eye when menu is shown."""
        super().showEvent(event)
        eye = self._eye()
        if not eye:
            return
        try:
            idx = list(EyeEmotion).index(eye._target_emotion)
            if 0 <= idx < self.emotion_combo.count():
                self.emotion_combo.setCurrentIndex(idx)
        except (ValueError, AttributeError):
            pass
        try:
            idx = list(PupilShape).index(eye.config.pupil_shape)
            if 0 <= idx < self.pupil_combo.count():
                self.pupil_combo.setCurrentIndex(idx)
        except (ValueError, AttributeError):
            pass
        try:
            br = int(_clamp(eye.config.blink_rate, 0.005, 0.08) * 1000)
            self.blink_slider.setValue(max(5, min(80, br)))
        except AttributeError:
            pass

    def update_position(self, rect) -> None:
        """Position menu to the right of the eye widget (in screen coordinates)."""
        eye = self.parent()
        if not eye or not eye.window():
            return
        # Map eye's right edge to global/screen coordinates
        global_right_top = eye.mapToGlobal(QPoint(int(rect.right()), int(rect.top())))
        x = global_right_top.x() + self.GAP_RIGHT
        y = global_right_top.y()
        self.setGeometry(x, y, self.MENU_WIDTH, self.MENU_HEIGHT)

class EyeWidget(QWidget):
    """Animated eye with emotions and dynamics."""

    blinked = Signal()
    pupil_dilated = Signal(float)
    emotion_changed = Signal(str)
    gaze_target_changed = Signal(QPointF)
    eyeStateChanged = Signal(QObject)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMouseTracking(True)
        self.setMinimumSize(200, 120)

        # --------------------------------------------------------------------
        # Configuration
        # --------------------------------------------------------------------
        self.config = EyeConfig()
        self.palette = EyePalette()
        self._state = EyeState.IDLE
        self._hero_mode = True

        # --------------------------------------------------------------------
        # Physics & State
        # --------------------------------------------------------------------
        self.eye_physics = EyePhysicsState()
        self.micro_movement_gen = MicroMovementGenerator()
        self.pupil_dynamics = PupilDynamics()

        # --------------------------------------------------------------------
        # Movement
        # --------------------------------------------------------------------
        self._look = QPointF(0.0, 0.0)
        self._last_look = QPointF(0.0, 0.0)
        self._saccade = QPointF(0.0, 0.0)
        self._saccade_target = QPointF(0.0, 0.0)
        self._iris_velocity = QPointF(0.0, 0.0)
        self._iris_wobble = QPointF(0.0, 0.0)
        self._cornea_wobble = QPointF(0.0, 0.0)
        self._microsaccade = QPointF(0.0, 0.0)
        self._microsaccade_timer = 0.0
        self._tremor = QPointF(0.0, 0.0)
        self._tremor_phase = [0.0, 0.0, 0.0]
        self._tremor_amplitudes = [0.003, 0.001, 0.0005]
        self._tremor_frequencies = [10.0, 25.0, 50.0]

        # --------------------------------------------------------------------
        # Physiological
        # --------------------------------------------------------------------
        self._blink = 0.0
        self._dilation = 0.4
        self._dilation_target = 0.4
        self._light_level = 0.5
        self._pulse_phase = 0.0
        self._current_emotion = EyeEmotion.NEUTRAL
        self._target_emotion = EyeEmotion.NEUTRAL
        self._emotion_blend = 0.0
        self._emotion_intensity = 1.0
        self._hippus_phase = 0.0

        # --------------------------------------------------------------------
        # Geometry
        # --------------------------------------------------------------------
        self._upper_lid_tension = 0.0
        self._lower_lid_tension = 0.0
        self._target_upper_tension = 0.0
        self._target_lower_tension = 0.0
        self._eye_openness = 1.0
        self._squint = 0.0
        self._brow_raise = 0.0

        # --------------------------------------------------------------------
        # Interaction
        # --------------------------------------------------------------------
        self._scanning = False
        self._hover = False
        self._focused = False
        self._sleepy = False

        # --------------------------------------------------------------------
        # Textures
        # --------------------------------------------------------------------
        self._sclera_texture: Optional[QImage] = None
        self._iris_texture: Optional[QImage] = None
        self._vein_texture: Optional[QImage] = None
        self._cornea_texture: Optional[QImage] = None

        # --------------------------------------------------------------------
        # Age effects
        # --------------------------------------------------------------------
        self._cataract_opacity = 0.0
        self._arcus_opacity = 0.0
        self._redness = 0.0

        # --------------------------------------------------------------------
        # Gaze
        # --------------------------------------------------------------------
        self._gaze_history: List[QPointF] = []
        self._max_gaze_history = 10
        self._last_mouse_pos = QCursor.pos()
        self._mouse_velocity = QPointF(0.0, 0.0)
        self._last_physics_update = time.time()

        # --------------------------------------------------------------------
        # Autonomous Mood
        # --------------------------------------------------------------------
        self._autonomous_mood_enabled = True
        self._mood_timer = QTimer(self)
        self._mood_timer.timeout.connect(self._on_autonomous_mood)
        self._mood_timer.start(int(DEFAULT_AUTONOMOUS_MOOD_INTERVAL * 1000))

        # --------------------------------------------------------------------
        # Animation Initialization
        # --------------------------------------------------------------------
        self._init_timers()
        self._init_animations()
        self._generate_textures()

        # --------------------------------------------------------------------
        # Control Menu Integration
        # --------------------------------------------------------------------
        self._control_menu = EyeControlMenu(self)
        self._menu_btn = QPushButton("⚙️", self)
        self._menu_btn.setFixedSize(36, 36)
        self._menu_btn.setStyleSheet("""
            QPushButton {
                background-color: rgba(0, 0, 0, 150);
                color: rgba(255, 255, 255, 200);
                border-radius: 18px;
                border: 1px solid rgba(255, 255, 255, 100);
                font-size: 18px;
            }
            QPushButton:hover {
                background-color: rgba(59, 130, 246, 200);
                color: white;
            }
        """)
        self._menu_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._menu_btn.clicked.connect(self._toggle_control_menu)
        self._menu_btn.raise_()

        self.set_hero_mode(True)

    # -------------------------------------------------------------------------
    # Properties (Qt Animation Compatible)
    # -------------------------------------------------------------------------
    def get_blink(self) -> float:
        return float(self._blink)

    def set_blink(self, v: float) -> None:
        self._blink = _clamp(float(v), 0.0, 1.0)
        self.eye_physics.blink_factor = self._blink
        if v == 1.0 and self._blink_anim.state() != self._blink_anim.State.Running:
            self.blinked.emit()
        self.update()

    blink = Property(float, get_blink, set_blink)

    def get_dilation(self) -> float:
        return float(self._dilation)

    def set_dilation(self, v: float) -> None:
        old = self._dilation
        self._dilation = _clamp(float(v), 0.15, 0.8)
        self.eye_physics.pupil_size = self._dilation
        if abs(old - self._dilation) > 0.01:
            self.pupil_dilated.emit(self._dilation)
        self.update()

    dilation = Property(float, get_dilation, set_dilation)

    def get_emotion_blend(self) -> float:
        return float(self._emotion_blend)

    def set_emotion_blend(self, v: float) -> None:
        self._emotion_blend = _clamp(float(v), 0.0, 1.0)
        if v >= 0.99:
            self._current_emotion = self._target_emotion
        self.update()

    emotion_blend = Property(float, get_emotion_blend, set_emotion_blend)

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------
    def set_state(self, state: EyeState) -> None:
        """Set authoritative eye state."""
        if state == self._state:
            return
        self._state = state

        if state == EyeState.IDLE:
            self._enter_idle()
        elif state == EyeState.FOCUSING:
            self._enter_focusing()
        elif state == EyeState.SCANNING:
            self._enter_scanning()
        elif state == EyeState.REVIEWING:
            self._enter_reviewing()
        elif state == EyeState.DECIDING:
            self._enter_deciding()
        elif state == EyeState.RESTING:
            self._enter_resting()
        elif state == EyeState.ERROR:
            self._enter_error()

    def _enter_idle(self) -> None:
        self.set_hero_mode(True)
        self.set_emotion(EyeEmotion.RELAXED)
        self.set_focus(False)
        self.set_scanning(False)

    def _enter_focusing(self) -> None:
        self.set_hero_mode(False)
        self.set_emotion(EyeEmotion.FOCUSED)
        self.set_focus(True)
        if hasattr(self, '_focus_anim'):
            self._focus_anim.stop()
            self._focus_anim.setStartValue(self._dilation)
            self._focus_anim.setEndValue(0.3)
            self._focus_anim.setDuration(250)
            self._focus_anim.start()

    def _enter_scanning(self) -> None:
        self.set_hero_mode(False)
        self.set_emotion(EyeEmotion.NEUTRAL)
        self.set_scanning(True)
        self.set_focus(False)

    def _enter_reviewing(self) -> None:
        self.set_hero_mode(False)
        self.set_emotion(EyeEmotion.CURIOUS)
        self.set_scanning(False)
        self.set_focus(True)

    def _enter_deciding(self) -> None:
        self.set_hero_mode(False)
        self.set_emotion(EyeEmotion.SUSPICIOUS)
        self.set_scanning(False)
        self.set_focus(True)
        self._blink_timer.stop()

    def _enter_resting(self) -> None:
        self.set_hero_mode(False)
        self.set_emotion(EyeEmotion.RELAXED)
        self.set_scanning(False)
        self.set_focus(False)
        self._blink_timer.start()

    def _enter_error(self) -> None:
        self.set_hero_mode(False)
        self.set_emotion(EyeEmotion.SUSPICIOUS)
        self.set_scanning(False)
        self.set_focus(False)

    def set_hero_mode(self, enabled: bool) -> None:
        """Switch between HERO (large) and BADGE (small) modes."""
        self._hero_mode = enabled
        if enabled:
            self.setFixedSize(320, 320)
            self.setCursor(Qt.CursorShape.ArrowCursor)
        else:
            self.setFixedSize(48, 48)
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.update()

    def apply_theme(self, theme_data: dict) -> None:
        """Apply theme colors."""
        orb_colors = theme_data.get('orb', {})
        self.palette.iris_base = QColor(orb_colors.get('inner_glow', self.palette.iris_base))
        self.palette.iris_light = QColor(orb_colors.get('pulse_start', self.palette.iris_light))
        self.palette.iris_dark = QColor(orb_colors.get('outer_ring', self.palette.iris_dark))
        self.palette.limbal_ring = QColor(orb_colors.get('outer_ring', self.palette.limbal_ring))
        self.palette.highlight_primary = QColor(orb_colors.get('scanning_glow', self.palette.highlight_primary))
        self._generate_textures()
        self.update()

    def set_emotion(self, emotion: EyeEmotion, intensity: float = 1.0, transition_time: int = 500) -> None:
        """Set eye emotion with smooth transition."""
        if emotion == self._current_emotion and intensity == self._emotion_intensity:
            return

        self._target_emotion = emotion
        self._emotion_intensity = _clamp(intensity, 0.0, 2.0)

        params = self._get_emotion_parameters(emotion)
        self._target_upper_tension = params.upper_tension * intensity
        self._target_lower_tension = params.lower_tension * intensity
        self._dilation_target = params.dilation
        self._squint = params.squint * intensity
        self._brow_raise = params.brow_raise * intensity

        self._emotion_anim.stop()
        self._emotion_anim.setStartValue(0.0)
        self._emotion_anim.setEndValue(1.0)
        self._emotion_anim.setDuration(transition_time)
        self._emotion_anim.start()

        self.emotion_changed.emit(emotion.value)

    def set_palette_preset(self, preset_name: str) -> None:
        """Change eye colors using preset."""
        self.palette = EyePalette.preset(preset_name)
        self._generate_textures()
        self.update()

    def set_pupil_shape(self, shape: PupilShape) -> None:
        """Change pupil shape."""
        self.config.pupil_shape = shape
        self.update()

    # -------------------------------------------------------------------------
    # New Pupil Dynamics Controls
    # -------------------------------------------------------------------------
    def set_pupil_constriction_time(self, seconds: float) -> None:
        """Set time constant for pupil constriction (seconds)."""
        self.config.pupil_constriction_time = max(0.05, seconds)

    def set_pupil_dilation_time(self, seconds: float) -> None:
        """Set time constant for pupil dilation (seconds)."""
        self.config.pupil_dilation_time = max(0.05, seconds)

    def set_hippus_amplitude(self, amplitude: float) -> None:
        """Set amplitude of hippus (pupil micro‑fluctuations)."""
        global HIPPUS_MAX_AMPLITUDE
        HIPPUS_MAX_AMPLITUDE = _clamp(amplitude, 0.0, 0.1)

    # -------------------------------------------------------------------------
    # Autonomous Mood
    # -------------------------------------------------------------------------
    def set_autonomous_mood(self, enabled: bool) -> None:
        """Enable/disable automatic mood changes."""
        self._autonomous_mood_enabled = enabled
        if enabled:
            self._mood_timer.start()
        else:
            self._mood_timer.stop()

    def set_mood_interval(self, seconds: int) -> None:
        """Set interval between autonomous mood changes (seconds)."""
        self._mood_timer.setInterval(seconds * 1000)

    def _on_autonomous_mood(self) -> None:
        """Trigger a random emotion change."""
        if not self._autonomous_mood_enabled or self._state == EyeState.FOCUSING:
            return
        emotions = [e for e in EyeEmotion if e not in (EyeEmotion.NEUTRAL, EyeEmotion.RELAXED)]
        emotion = random.choice(emotions)
        self.set_emotion(emotion, transition_time=800)

    # -------------------------------------------------------------------------
    # Physics Toggles
    # -------------------------------------------------------------------------
    def set_microsaccades_enabled(self, enabled: bool) -> None:
        """Enable/disable microsaccades."""
        self.config.microsaccades_enabled = enabled

    def set_tremor_enabled(self, enabled: bool) -> None:
        """Enable/disable tremor."""
        self.config.tremor_enabled = enabled

    # -------------------------------------------------------------------------
    # Age & Health
    # -------------------------------------------------------------------------
    def set_age_effects(self, age_factor: float, health_factor: float = 1.0) -> None:
        """Apply age and health effects."""
        self._cataract_opacity = age_factor * 0.7
        self._arcus_opacity = age_factor * 0.8
        self._redness = (1.0 - health_factor) * 0.6
        self._generate_textures()
        self.update()

    # -------------------------------------------------------------------------
    # Reset to Defaults
    # -------------------------------------------------------------------------
    def reset_to_defaults(self) -> None:
        """Reset all configurable parameters to factory defaults (eyev_pro-aligned)."""
        self.config.pupil_constriction_time = DEFAULT_CONSTRICTION_TIME
        self.config.pupil_dilation_time = DEFAULT_DILATION_TIME
        self.config.blink_rate = 0.025
        self.config.blink_duration_close = 0.07
        self.config.blink_duration_open = 0.13
        self.config.saccade_interval_min = 0.6
        self.config.saccade_interval_max = 2.0
        self.config.saccade_interval_focused_min = 0.4
        self.config.saccade_interval_focused_max = 1.2
        self.config.saccade_interval_sleepy_min = 0.8
        self.config.saccade_interval_sleepy_max = 3.0
        global HIPPUS_MAX_AMPLITUDE
        HIPPUS_MAX_AMPLITUDE = 0.03
        self.config.microsaccades_enabled = True
        self.config.tremor_enabled = True
        self._autonomous_mood_enabled = True
        self._mood_timer.setInterval(int(DEFAULT_AUTONOMOUS_MOOD_INTERVAL * 1000))
        self.set_emotion(EyeEmotion.NEUTRAL)
        self.set_pupil_shape(PupilShape.ROUND)
        self.set_palette_preset("default")
        if hasattr(self, "_age_slider_setup"):
            self._age_slider_setup(0, 100)

    # -------------------------------------------------------------------------
    # Gaze Control
    # -------------------------------------------------------------------------
    def look_at_point(self, point: QPointF, duration: int = 200) -> None:
        """Make eye look at specific point."""
        target = QPointF(
            _clamp(point.x() * 2.0 - 1.0, -0.8, 0.8),
            _clamp(point.y() * 2.0 - 1.0, -0.8, 0.8)
        )
        self._gaze_history.append(target)
        if len(self._gaze_history) > self._max_gaze_history:
            self._gaze_history.pop(0)
        self.gaze_target_changed.emit(target)

        anim = QPropertyAnimation(self, b"look")
        anim.setDuration(duration)
        anim.setStartValue(self._look)
        anim.setEndValue(target)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.start()

    def set_focus(self, focused: bool) -> None:
        """Set focus state."""
        self._focused = focused
        if focused:
            self._dilation_target = 0.3
            self._scanning = False
        self.update()

    def set_scanning(self, scanning: bool) -> None:
        """Set scanning state."""
        if self._scanning == scanning:
            return
        self._scanning = scanning
        if self._scanning:
            self._new_saccade()

    def trigger_blink(self) -> None:
        """Trigger a manual blink."""
        if self._blink_anim.state() == self._blink_anim.State.Stopped:
            self._blink_state = "closing"
            self._blink_timer = 0.0
            self._blink_anim.start()

    def trigger_startle(self) -> None:
        """Simulate startle response."""
        self._dilation_target = 1.0
        self.trigger_blink()

    # -------------------------------------------------------------------------
    # Control Menu
    # -------------------------------------------------------------------------
    def _toggle_control_menu(self) -> None:
        """Show/hide the control menu, positioned to the right."""
        if self._control_menu.isVisible():
            self._control_menu.hide()
        else:
            self._control_menu.update_position(self.rect())
            self._control_menu.show()

    def resizeEvent(self, event):
        """Update control button position on resize."""
        super().resizeEvent(event)
        self._menu_btn.move(self.width() - 46, 10)
        if self._control_menu.isVisible():
            self._control_menu.update_position(self.rect())

    # -------------------------------------------------------------------------
    # Initialization
    # -------------------------------------------------------------------------
    def _init_timers(self) -> None:
        self._tick = QTimer(self)
        self._tick.timeout.connect(self._on_tick)
        self._tick.start(8)  # ~120 FPS

        self._saccade_timer = QTimer(self)
        self._saccade_timer.timeout.connect(self._new_saccade)
        self._saccade_timer.start(1000)

        self._blink_timer = QTimer(self)
        self._blink_timer.timeout.connect(self._maybe_blink)
        self._blink_timer.start(100)

        self._dilation_timer = QTimer(self)
        self._dilation_timer.timeout.connect(self._update_environmental_dilation)
        self._dilation_timer.start(2000)

        self._micro_expression_timer = QTimer(self)
        self._micro_expression_timer.timeout.connect(self._maybe_micro_expression)
        self._micro_expression_timer.start(3000)

    def _init_animations(self) -> None:
        self._blink_anim = QSequentialAnimationGroup(self)
        self._blink_down = QPropertyAnimation(self, b"blink")
        close_ms = int(self.config.blink_duration_close * 1000) + random.randint(-10, 10)
        open_ms = int(self.config.blink_duration_open * 1000) + random.randint(-20, 20)
        self._blink_down.setDuration(max(30, close_ms))
        self._blink_down.setStartValue(0.0)
        self._blink_down.setEndValue(1.0)
        self._blink_down.setEasingCurve(QEasingCurve.Type.InOutSine)

        self._blink_up = QPropertyAnimation(self, b"blink")
        self._blink_up.setDuration(max(50, open_ms))
        self._blink_up.setStartValue(1.0)
        self._blink_up.setEndValue(0.0)
        self._blink_up.setEasingCurve(QEasingCurve.Type.OutElastic)

        self._blink_anim.addAnimation(self._blink_down)
        self._blink_anim.addAnimation(self._blink_up)

        self._emotion_anim = QPropertyAnimation(self, b"emotion_blend")
        self._emotion_anim.setDuration(500)
        self._emotion_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._focus_anim = QPropertyAnimation(self, b"dilation")
        self._focus_anim.setDuration(300)

    # -------------------------------------------------------------------------
    # Physics & Logic
    # -------------------------------------------------------------------------
    def _on_tick(self) -> None:
        now = time.time()
        dt = max(1e-3, now - self._last_physics_update)
        self._last_physics_update = now

        # 1. Mouse & Gaze
        current_mouse = QCursor.pos()
        self._mouse_velocity = (current_mouse - self._last_mouse_pos) * 0.3
        self._last_mouse_pos = current_mouse

        if not self._focused:
            lp = self.mapFromGlobal(QCursor.pos())
            dx = (lp.x() - self.width() * 0.5) / (self.width() * 0.5)
            dy = (lp.y() - self.height() * 0.5) / (self.height() * 0.5)

            pred_x = self._mouse_velocity.x() / self.width() * 5.0
            pred_y = self._mouse_velocity.y() / self.height() * 5.0

            target = QPointF(
                _clamp(dx * 1.2 + pred_x, -0.6, 0.6),
                _clamp(dy * 1.2 + pred_y, -0.6, 0.6)
            )

            prev_look = self._look
            self._look = _lerp_pt(self._look, target, 0.18)
            look_velocity = (self._look - prev_look) / dt
        else:
            look_velocity = QPointF(0, 0)
            prev_look = self._look

        # 2. Jelly Physics (Wobble)
        k = 120.0 + self._squint * 50.0
        d = 8.0 + self._blink * 4.0

        acceleration = (look_velocity - (self._last_look - prev_look) / dt)
        inertia_force = -acceleration * 0.004

        force = inertia_force - (self._iris_wobble * k) - (self._iris_velocity * d)
        self._iris_velocity += force * dt
        self._iris_wobble += self._iris_velocity * dt

        cornea_force = inertia_force * 0.3 - (self._cornea_wobble * k * 0.7) - (self._cornea_wobble * d * 0.7)
        self._cornea_wobble += cornea_force * dt * 0.5

        self._last_look = prev_look

        # 3. Tremor (if enabled)
        if self.config.tremor_enabled:
            for i in range(len(self._tremor_phase)):
                self._tremor_phase[i] += dt * self._tremor_frequencies[i] * math.pi * 2

            tremor_x = sum(math.sin(self._tremor_phase[i]) * self._tremor_amplitudes[i]
                          for i in range(len(self._tremor_phase))) / len(self._tremor_phase)
            tremor_y = sum(math.cos(self._tremor_phase[i] * 0.8) * self._tremor_amplitudes[i]
                          for i in range(len(self._tremor_phase))) / len(self._tremor_phase)
            self._tremor = QPointF(tremor_x, tremor_y)
        else:
            self._tremor = QPointF(0, 0)

        # 4. Microsaccades (if enabled)
        if self.config.microsaccades_enabled:
            self._microsaccade_timer += dt
            if self._microsaccade_timer > random.uniform(0.5, 2.0):
                self._microsaccade = QPointF(
                    random.uniform(-0.01, 0.01),
                    random.uniform(-0.01, 0.01)
                )
                self._microsaccade_timer = 0.0
            else:
                self._microsaccade = _lerp_pt(self._microsaccade, QPointF(0, 0), 0.1)
        else:
            self._microsaccade = QPointF(0, 0)

        # 5. Pupil Dynamics (Smooth, configurable time constants)
        self._hippus_phase += dt * HIPPUS_FREQUENCY * math.pi * 2
        hippus = math.sin(self._hippus_phase) * HIPPUS_MAX_AMPLITUDE * (1.0 + self._redness * 0.5)

        # Use exponential smoothing with configurable time constants
        time_constant = (self.config.pupil_constriction_time
                        if self._dilation_target < self._dilation
                        else self.config.pupil_dilation_time)
        self._dilation = _exponential_smooth(self._dilation, self._dilation_target, dt, time_constant)
        self._dilation += hippus
        self._dilation = _clamp(self._dilation, 0.15, 0.8)

        self.eye_physics.pupil_size = self._dilation

        # 6. Emotion Blending
        self._emotion_blend = _clamp(self._emotion_blend + dt * 2.0, 0.0, 1.0)
        blend = self._emotion_blend
        self._upper_lid_tension = _lerp(self._upper_lid_tension, self._target_upper_tension, 0.1 * blend)
        self._lower_lid_tension = _lerp(self._lower_lid_tension, self._target_lower_tension, 0.1 * blend)

        # 7. Pulse
        self._pulse_phase = (self._pulse_phase + dt * 1.2 * math.pi * 2) % (math.pi * 2)

        # 8. Eye Openness
        if self._sleepy:
            self._eye_openness = 0.7 + math.sin(time.time() * 0.5) * 0.1
        else:
            self._eye_openness = _lerp(self._eye_openness, 1.0 - self._squint * 0.3, 0.05)

        # Update physics state object
        self.eye_physics.actual_rotation = self._look + self._saccade + self._tremor + self._microsaccade
        self.eye_physics.blink_factor = self._blink
        self.eye_physics.squint_factor = self._squint

        self.update()
        self.eyeStateChanged.emit(self.eye_physics)

    # -------------------------------------------------------------------------
    # Emotion Parameters
    # -------------------------------------------------------------------------
    def _get_emotion_parameters(self, emotion: EyeEmotion) -> EmotionParams:
        """Get physical parameters for the given emotion."""
        params = {
            EyeEmotion.NEUTRAL: EmotionParams(0.0, 0.0, 0.4, 0.0, 0.0),
            EyeEmotion.SURPRISED: EmotionParams(0.8, 0.2, 0.7, -0.3, 0.6),
            EyeEmotion.SUSPICIOUS: EmotionParams(-0.4, -0.3, 0.3, 0.6, -0.2),
            EyeEmotion.TIRED: EmotionParams(-0.3, 0.1, 0.5, 0.4, -0.1),
            EyeEmotion.HAPPY: EmotionParams(0.2, -0.6, 0.5, -0.2, 0.1),
            EyeEmotion.ANGRY: EmotionParams(-0.5, -0.2, 0.3, 0.8, -0.5),
            EyeEmotion.SAD: EmotionParams(-0.2, 0.3, 0.6, 0.2, 0.4),
            EyeEmotion.FOCUSED: EmotionParams(-0.1, -0.1, 0.3, 0.3, 0.0),
            EyeEmotion.SLEEPY: EmotionParams(-0.4, 0.2, 0.6, 0.5, -0.3),
            EyeEmotion.CURIOUS: EmotionParams(0.3, -0.1, 0.5, 0.0, 0.3),
            EyeEmotion.RELAXED: EmotionParams(-0.1, 0.0, 0.6, -0.1, -0.1),
        }
        return params.get(emotion, params[EyeEmotion.NEUTRAL])

    # -------------------------------------------------------------------------
    # Saccades, Blinks, Micro‑expressions
    # -------------------------------------------------------------------------
    def _new_saccade(self) -> None:
        """Generate new saccade."""
        if self._focused:
            scale = 0.005
        elif self._scanning:
            scale = 0.02
        else:
            scale = 0.03 + self._redness * 0.02

        self._saccade_target = QPointF(
            random.uniform(-scale, scale) * (1.0 + self._blink * 0.5),
            random.uniform(-scale, scale) * (1.0 + self._blink * 0.5)
        )

        if self._sleepy:
            interval = random.randint(
                int(self.config.saccade_interval_sleepy_min * 1000),
                int(self.config.saccade_interval_sleepy_max * 1000)
            )
        elif self._focused:
            interval = random.randint(
                int(self.config.saccade_interval_focused_min * 1000),
                int(self.config.saccade_interval_focused_max * 1000)
            )
        else:
            interval = random.randint(
                int(self.config.saccade_interval_min * 1000),
                int(self.config.saccade_interval_max * 1000)
            )

        self._saccade_timer.start(interval)

    def _maybe_blink(self) -> None:
        """Decide whether to blink."""
        if self._blink_anim.state() == self._blink_anim.State.Stopped:
            base_rate = self.config.blink_rate
            if self._sleepy:
                base_rate *= 1.5
            if self._focused:
                base_rate *= 0.7
            if self._redness > 0.3:
                base_rate *= 1.8

            if random.random() < base_rate:
                if self._sleepy and random.random() < 0.3:
                    self._blink_down.setEndValue(0.6)
                else:
                    self._blink_down.setEndValue(1.0)
                self._blink_anim.start()

    def _maybe_micro_expression(self) -> None:
        """Occasional micro-expressions."""
        if (random.random() < 0.2 and
                self._current_emotion == EyeEmotion.NEUTRAL and
                self._state != EyeState.FOCUSING):
            emotions = [EyeEmotion.SURPRISED, EyeEmotion.SUSPICIOUS, EyeEmotion.HAPPY]
            emotion = random.choice(emotions)

            old_upper = self._target_upper_tension
            old_lower = self._target_lower_tension

            params = self._get_emotion_parameters(emotion)
            self._target_upper_tension = params.upper_tension * 0.3
            self._target_lower_tension = params.lower_tension * 0.3

            QTimer.singleShot(150, lambda: [
                setattr(self, '_target_upper_tension', old_upper),
                setattr(self, '_target_lower_tension', old_lower)
            ])

    def _update_environmental_dilation(self) -> None:
        """Update pupil based on simulated light."""
        if not self._hover:
            light_change = random.uniform(-0.15, 0.15)
            if random.random() < 0.1:
                light_change *= 3.0

            self._light_level = _clamp(self._light_level + light_change, 0.1, 0.9)
            self._dilation_target = _lerp(0.25, 0.75, 1.0 - self._light_level)

            if self._current_emotion in (EyeEmotion.SURPRISED, EyeEmotion.SAD):
                self._dilation_target = min(0.8, self._dilation_target + 0.1)
            elif self._current_emotion in (EyeEmotion.ANGRY, EyeEmotion.FOCUSED):
                self._dilation_target = max(0.2, self._dilation_target - 0.1)

    # -------------------------------------------------------------------------
    # Rendering (unchanged from original, except for _mix_color usage)
    # -------------------------------------------------------------------------
    def paintEvent(self, event) -> None:
        """Paint the eye with all effects."""
        painter = QPainter(self)
        painter.setRenderHints(
            QPainter.RenderHint.Antialiasing |
            QPainter.RenderHint.SmoothPixmapTransform |
            QPainter.RenderHint.TextAntialiasing
        )

        w, h = self.width(), self.height()
        rect = QRectF(w * 0.05, h * 0.05, w * 0.9, h * 0.9)

        if getattr(self, "_hero_mode", False):
            painter.save()
            center = rect.center()
            glow_radius = max(rect.width(), rect.height()) * 0.65
            glow = QRadialGradient(center, glow_radius)
            glow.setColorAt(0.0, QColor(120, 160, 255, 28))
            glow.setColorAt(0.4, QColor(80, 120, 220, 12))
            glow.setColorAt(0.7, QColor(60, 100, 200, 4))
            glow.setColorAt(1.0, QColor(0, 0, 0, 0))
            painter.setBrush(glow)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(center, glow_radius, glow_radius * 0.75)
            painter.restore()

        eye_path = self._create_dynamic_eye_shape(rect)

        painter.save()
        painter.setClipPath(eye_path)

        self._draw_enhanced_sclera(painter, rect)

        combined_look = (self._look + self._saccade + self._tremor +
                        self._microsaccade if self._focused else self._look + self._saccade)

        eye_radius = min(rect.width(), rect.height()) * 0.45

        iris_offset = QPointF(
            combined_look.x() * eye_radius * 0.35,
            combined_look.y() * eye_radius * 0.35
        )

        wobble_offset = QPointF(
            self._iris_wobble.x() * eye_radius * 1.8,
            self._iris_wobble.y() * eye_radius * 1.8
        )

        iris_center = rect.center() + iris_offset + wobble_offset

        self._draw_enhanced_iris(painter, iris_center, eye_radius * 0.48)
        self._draw_shaped_pupil(painter, iris_center, eye_radius * 0.48)
        self._draw_enhanced_reflections(painter, iris_center, eye_radius * 0.48,
                                       combined_look, self._iris_wobble)
        self._draw_corneal_effects(painter, iris_center, eye_radius * 0.48)

        if self._cataract_opacity > 0 or self._arcus_opacity > 0:
            self._draw_age_effects(painter, iris_center, eye_radius * 0.48)

        self._draw_tear_film(painter, rect)

        painter.restore()

        opening = (1.0 - self._blink) * self._eye_openness
        self._draw_enhanced_eyelids(painter, rect, eye_path, opening)

    # -------------------------------------------------------------------------
    # Rendering helpers (minimally changed, using _mix_color)
    # -------------------------------------------------------------------------
    def _create_dynamic_eye_shape(self, rect: QRectF) -> QPainterPath:
        path = QPainterPath()
        cx, cy, w, h = rect.center().x(), rect.center().y(), rect.width(), rect.height()

        squint_factor = 1.0 - self._squint * 0.3
        eye_width = w * squint_factor

        inner_corner = QPointF(cx - eye_width * 0.48, cy + h * 0.05)
        outer_corner = QPointF(cx + eye_width * 0.48, cy + h * 0.02)

        upper_tension_y = -0.55 - (self._upper_lid_tension * 0.35) + (self._brow_raise * 0.2)
        upper_cp1 = QPointF(cx - w * 0.25, cy + h * upper_tension_y)
        upper_cp2 = QPointF(cx + w * 0.25, cy + h * upper_tension_y)

        lower_tension_y = 0.45 - (self._lower_lid_tension * 0.35)
        lower_cp1 = QPointF(cx + w * 0.25, cy + h * lower_tension_y)
        lower_cp2 = QPointF(cx - w * 0.25, cy + h * lower_tension_y)

        path.moveTo(inner_corner)
        path.cubicTo(upper_cp1, upper_cp2, outer_corner)
        path.cubicTo(lower_cp1, lower_cp2, inner_corner)
        return path

    def _draw_enhanced_sclera(self, painter: QPainter, rect: QRectF) -> None:
        redness_factor = self._redness
        base_color = _mix_color(self.palette.sclera_base, QColor(255, 200, 200), redness_factor * 0.3)
        shadow_color = _mix_color(self.palette.sclera_shadow, QColor(220, 150, 150), redness_factor * 0.4)

        grad = QRadialGradient(rect.center(), rect.width() * 0.7)
        grad.setColorAt(0.0, base_color)
        grad.setColorAt(0.7, base_color)
        grad.setColorAt(0.85, shadow_color)
        grad.setColorAt(0.95, _mix_color(shadow_color, QColor(180, 120, 120), 0.5))
        grad.setColorAt(1.0, QColor(150, 100, 100, 150))

        painter.fillRect(rect, grad)

        if self._vein_texture:
            painter.setOpacity(0.2 + redness_factor * 0.3)
            painter.drawImage(rect, self._vein_texture)

        painter.setOpacity(0.3)
        rim_grad = QRadialGradient(rect.center(), rect.width() * 0.5)
        rim_grad.setColorAt(0.8, Qt.GlobalColor.transparent)
        rim_grad.setColorAt(1.0, self.palette.scattering_tint)
        painter.fillRect(rect, rim_grad)
        painter.setOpacity(1.0)

    def _draw_enhanced_iris(self, painter: QPainter, center: QPointF, radius: float) -> None:
        painter.save()

        path = QPainterPath()
        path.addEllipse(center, radius, radius)
        painter.setClipPath(path)

        emotion_tint = self._get_emotion_tint()
        iris_base = _mix_color(self.palette.iris_base, emotion_tint, 0.1)
        iris_dark = _mix_color(self.palette.iris_dark, emotion_tint, 0.15)

        iris_grad = QRadialGradient(center, radius)
        iris_grad.setColorAt(0.0, iris_base.lighter(120 + int(self._light_level * 50)))
        iris_grad.setColorAt(0.5, iris_base)
        iris_grad.setColorAt(0.8, iris_dark)
        iris_grad.setColorAt(1.0, self.palette.limbal_ring)

        painter.fillPath(path, iris_grad)

        if not self._iris_texture:
            self._generate_enhanced_iris_texture()

        painter.setOpacity(0.7 - self._light_level * 0.2)
        painter.drawImage(
            QRectF(center.x() - radius, center.y() - radius, radius * 2, radius * 2),
            self._iris_texture
        )

        pulse = (math.sin(self._pulse_phase) + 1) * 0.5
        painter.setOpacity(0.3 + pulse * 0.1)
        painter.setPen(QPen(QColor(255, 255, 200, 100), 1.5 + pulse * 0.5))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(center, radius * 0.42, radius * 0.42)

        painter.setOpacity(0.8)
        painter.setPen(QPen(self.palette.limbal_ring, 1.0))
        painter.drawEllipse(center, radius, radius)

        painter.restore()

    def _draw_shaped_pupil(self, painter: QPainter, center: QPointF, iris_radius: float) -> None:
        pupil_radius = iris_radius * self._dilation
        if pupil_radius <= 0.1:
            return

        painter.save()

        shape = self.config.pupil_shape

        if shape == PupilShape.ROUND:
            path = QPainterPath()
            path.addEllipse(center, pupil_radius, pupil_radius)
        elif shape == PupilShape.VERTICAL_SLIT:
            path = QPainterPath()
            path.addEllipse(center, pupil_radius * 0.3, pupil_radius * 1.2)
        elif shape == PupilShape.HORIZONTAL_SLIT:
            path = QPainterPath()
            path.addEllipse(center, pupil_radius * 1.2, pupil_radius * 0.3)
        elif shape == PupilShape.SQUARE:
            path = QPainterPath()
            path.addRect(QRectF(center.x() - pupil_radius, center.y() - pupil_radius,
                               pupil_radius * 2, pupil_radius * 2))
        elif shape == PupilShape.DROPLET:
            path = QPainterPath()
            path.moveTo(center.x(), center.y() - pupil_radius * 1.2)
            path.quadTo(center.x() + pupil_radius, center.y() - pupil_radius * 0.5,
                       center.x(), center.y() + pupil_radius * 0.8)
            path.quadTo(center.x() - pupil_radius, center.y() - pupil_radius * 0.5,
                       center.x(), center.y() - pupil_radius * 1.2)
            path.closeSubpath()
        else:
            path = QPainterPath()
            path.addEllipse(center, pupil_radius, pupil_radius)

        pupil_grad = QRadialGradient(center, pupil_radius * 1.2)
        pupil_grad.setColorAt(0.0, self.palette.pupil.lighter(110))
        pupil_grad.setColorAt(0.7, self.palette.pupil)
        pupil_grad.setColorAt(1.0, self.palette.pupil_border)

        painter.fillPath(path, pupil_grad)
        painter.setPen(QPen(self.palette.pupil_border, 1.0))
        painter.drawPath(path)

        painter.restore()

    def _draw_enhanced_reflections(self, painter: QPainter, center: QPointF, radius: float,
                                  look: QPointF, wobble: QPointF) -> None:
        p1_offset = QPointF(
            -radius * 0.35 + look.x() * radius * 0.1,
            -radius * 0.35 + look.y() * radius * 0.1
        )
        p1_center = center + p1_offset

        painter.setBrush(self.palette.highlight_primary)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(p1_center, radius * 0.22, radius * 0.18)

        p2_offset = QPointF(
            look.x() * radius * 0.2 + wobble.x() * radius * 0.5,
            look.y() * radius * 0.2 + wobble.y() * radius * 0.5
        )
        p2_center = center + p2_offset

        painter.setBrush(self.palette.highlight_secondary)
        painter.drawEllipse(p2_center, radius * 0.08, radius * 0.08)

        for i in range(3):
            angle = random.random() * math.pi * 2
            dist = random.uniform(radius * 0.1, radius * 0.6)
            micro_center = center + QPointF(math.cos(angle) * dist, math.sin(angle) * dist)
            size = random.uniform(radius * 0.02, radius * 0.04)
            opacity = random.uniform(0.1, 0.3)

            painter.setBrush(QColor(255, 255, 255, int(255 * opacity)))
            painter.drawEllipse(micro_center, size, size)

    def _draw_corneal_effects(self, painter: QPainter, center: QPointF, radius: float) -> None:
        bulge_grad = QRadialGradient(center - QPointF(radius * 0.2, radius * 0.2), radius)
        bulge_grad.setColorAt(0.0, QColor(255, 255, 255, 40))
        bulge_grad.setColorAt(0.5, QColor(255, 255, 255, 15))
        bulge_grad.setColorAt(1.0, Qt.GlobalColor.transparent)

        painter.setBrush(bulge_grad)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(center, radius, radius)

        moisture_angle = math.atan2(self._cornea_wobble.y(), self._cornea_wobble.x())
        for i in range(5):
            angle = moisture_angle + i * math.pi * 0.4
            dist = radius * (0.7 + i * 0.05)
            highlight_pos = center + QPointF(math.cos(angle) * dist, math.sin(angle) * dist)

            highlight_grad = QRadialGradient(highlight_pos, radius * 0.05)
            highlight_grad.setColorAt(0.0, QColor(255, 255, 255, 150))
            highlight_grad.setColorAt(1.0, Qt.GlobalColor.transparent)

            painter.setBrush(highlight_grad)
            painter.drawEllipse(highlight_pos, radius * 0.05, radius * 0.05)

    def _draw_age_effects(self, painter: QPainter, center: QPointF, radius: float) -> None:
        painter.save()

        if self._arcus_opacity > 0:
            arcus_path = QPainterPath()
            arcus_path.addEllipse(center, radius * 1.05, radius * 1.05)
            inner_path = QPainterPath()
            inner_path.addEllipse(center, radius * 0.9, radius * 0.9)
            arcus_path = arcus_path.subtracted(inner_path)

            painter.setBrush(QColor(255, 255, 255, int(180 * self._arcus_opacity)))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawPath(arcus_path)

        if self._cataract_opacity > 0:
            cataract_grad = QRadialGradient(center, radius * 0.8)
            cataract_grad.setColorAt(0.0, Qt.GlobalColor.transparent)
            cataract_grad.setColorAt(0.7, QColor(255, 255, 240, int(60 * self._cataract_opacity)))
            cataract_grad.setColorAt(1.0, QColor(255, 255, 230, int(30 * self._cataract_opacity)))

            painter.setBrush(cataract_grad)
            painter.drawEllipse(center, radius, radius)

        painter.restore()

    def _draw_tear_film(self, painter: QPainter, rect: QRectF) -> None:
        meniscus_height = rect.height() * 0.08
        meniscus_rect = QRectF(
            rect.left(),
            rect.bottom() - meniscus_height,
            rect.width(),
            meniscus_height
        )

        meniscus_grad = QLinearGradient(meniscus_rect.topLeft(), meniscus_rect.bottomLeft())
        meniscus_grad.setColorAt(0.0, QColor(255, 255, 255, 0))
        meniscus_grad.setColorAt(0.3, QColor(255, 255, 255, 120))
        meniscus_grad.setColorAt(0.7, QColor(200, 220, 255, 80))
        meniscus_grad.setColorAt(1.0, QColor(255, 255, 255, 0))

        painter.fillRect(meniscus_rect, meniscus_grad)

        film_grad = QRadialGradient(rect.center(), rect.width() * 0.5)
        film_grad.setColorAt(0.0, Qt.GlobalColor.transparent)
        film_grad.setColorAt(0.8, Qt.GlobalColor.transparent)
        film_grad.setColorAt(1.0, QColor(255, 255, 255, 30))

        painter.setBrush(film_grad)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRect(rect)

    def _draw_enhanced_eyelids(self, painter: QPainter, rect: QRectF,
                              eye_path: QPainterPath, opening: float) -> None:
        cy, h = rect.center().y(), rect.height()

        upper_offset = h * 0.35 * opening + (self._upper_lid_tension * h * 0.15)
        upper_y = cy - upper_offset

        lower_offset = h * 0.35 * (1.0 + (1.0 - opening) * 0.4) - (self._lower_lid_tension * h * 0.15)
        lower_y = cy + lower_offset

        painter.save()
        painter.setClipPath(eye_path)

        skin_grad = QLinearGradient(QPointF(0, upper_y - h * 0.5), QPointF(0, upper_y))
        skin_grad.setColorAt(0.0, self.palette.eyelid_skin.darker(110))
        skin_grad.setColorAt(1.0, self.palette.eyelid_skin)

        painter.fillRect(QRectF(rect.left(), rect.top() - h, rect.width(),
                               upper_y - rect.top() + h), skin_grad)

        lower_skin_grad = QLinearGradient(QPointF(0, lower_y), QPointF(0, lower_y + h * 0.5))
        lower_skin_grad.setColorAt(0.0, self.palette.eyelid_skin)
        lower_skin_grad.setColorAt(1.0, self.palette.eyelid_skin.darker(120))

        painter.fillRect(QRectF(rect.left(), lower_y, rect.width(),
                               rect.bottom() - lower_y + h), lower_skin_grad)

        painter.setPen(QPen(QColor(255, 180, 160, 180), 2.0 + self._blink * 1.5))
        painter.drawLine(QPointF(rect.left() + rect.width() * 0.1, upper_y),
                        QPointF(rect.right() - rect.width() * 0.1, upper_y))

        if opening > 0.3:
            lash_shadow = QLinearGradient(QPointF(0, upper_y), QPointF(0, upper_y + h * 0.08))
            lash_shadow.setColorAt(0.0, QColor(0, 0, 0, 100))
            lash_shadow.setColorAt(1.0, Qt.GlobalColor.transparent)

            painter.fillRect(QRectF(rect.left(), upper_y, rect.width(), h * 0.1), lash_shadow)

        if self._brow_raise > 0:
            crease_y = upper_y - h * 0.15
            crease_grad = QLinearGradient(QPointF(0, crease_y), QPointF(0, crease_y + h * 0.05))
            crease_grad.setColorAt(0.0, QColor(0, 0, 0, 60))
            crease_grad.setColorAt(1.0, Qt.GlobalColor.transparent)

            painter.fillRect(QRectF(rect.left(), crease_y, rect.width(), h * 0.06), crease_grad)

        painter.restore()

    def _get_emotion_tint(self) -> QColor:
        tints = {
            EyeEmotion.ANGRY: QColor(255, 100, 100),
            EyeEmotion.SAD: QColor(150, 150, 255),
            EyeEmotion.HAPPY: QColor(255, 255, 150),
            EyeEmotion.SURPRISED: QColor(255, 200, 150),
            EyeEmotion.TIRED: QColor(150, 150, 150),
            EyeEmotion.SUSPICIOUS: QColor(200, 200, 100),
        }
        return tints.get(self._current_emotion, QColor(255, 255, 255))

    # -------------------------------------------------------------------------
    # Texture Generation
    # -------------------------------------------------------------------------
    def _generate_textures(self) -> None:
        self._generate_enhanced_iris_texture()
        self._generate_vein_texture()

    def _generate_enhanced_iris_texture(self) -> None:
        size = 512
        img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(0)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        center = QPointF(size // 2, size // 2)
        max_radius = size // 2 - 10

        for i in range(600):
            angle = (i / 600) * 2 * math.pi + random.uniform(-0.03, 0.03)
            width = random.uniform(0.8, 1.5)
            length = random.uniform(0.7, 0.95)

            p.setPen(QPen(self.palette.iris_light, width))

            start_radius = max_radius * 0.15
            end_radius = max_radius * length

            start_pt = center + QPointF(math.cos(angle) * start_radius,
                                       math.sin(angle) * start_radius)
            end_pt = center + QPointF(math.cos(angle) * end_radius,
                                     math.sin(angle) * end_radius)

            p.drawLine(start_pt, end_pt)

        for _ in range(25):
            angle = random.random() * 2 * math.pi
            dist = random.uniform(max_radius * 0.3, max_radius * 0.8)
            pt = center + QPointF(math.cos(angle) * dist, math.sin(angle) * dist)
            sz = random.uniform(5, 20)

            crypt_grad = QRadialGradient(pt, sz)
            crypt_grad.setColorAt(0.0, self.palette.iris_crypt)
            crypt_grad.setColorAt(1.0, Qt.GlobalColor.transparent)

            p.setBrush(crypt_grad)
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(pt, sz, sz)

        p.end()
        self._iris_texture = img

    def _generate_vein_texture(self) -> None:
        if self._vein_texture is None:
            size = 512
            img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
            img.fill(0)
            p = QPainter(img)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)

            for _ in range(15):
                path = QPainterPath()
                start = QPointF(random.uniform(0, size), random.uniform(0, size))
                path.moveTo(start)
                curr = start
                for _ in range(10):
                    curr += QPointF(random.uniform(-30, 30), random.uniform(-30, 30))
                    path.lineTo(curr)
                p.setPen(QPen(self.palette.sclera_vein, random.uniform(1, 3)))
                p.drawPath(path)
            p.end()
            self._vein_texture = img

    # -------------------------------------------------------------------------
    # Cleanup
    # -------------------------------------------------------------------------
    def cleanup(self) -> None:
        """Stop all timers and disconnect signals."""
        self._tick.stop()
        self._saccade_timer.stop()
        self._blink_timer.stop()
        self._dilation_timer.stop()
        self._micro_expression_timer.stop()
        self._mood_timer.stop()
        self._control_menu.deleteLater()

    def __del__(self) -> None:
        self.cleanup()


all = [
'EyeWidget',
'EyeEmotion',
'PupilShape',
'EyeState',
'EyePalette',
'EyeConfig',
'EyeControlMenu',
]