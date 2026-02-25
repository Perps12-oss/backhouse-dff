# cerebro/ui/pages/start_page.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Dict, Any, List

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QFrame, QLabel

from cerebro.ui.components.modern._tokens import token as theme_token
from cerebro.ui.pages.base_station import BaseStation
from cerebro.ui.widgets.eye_widget import EyeWidget, EyeEmotion, PupilShape
from cerebro.services.logger import get_logger


# -----------------------------------------------------------------------------
# Backward-compat: StartScanConfig used by old imports/wiring.
# -----------------------------------------------------------------------------
@dataclass(slots=True)
class StartScanConfig:
    root: str = ""
    fast_mode: bool = False
    include_hidden: bool = False
    follow_symlinks: bool = False
    min_size_bytes: int = 1024
    allowed_extensions: Optional[List[str]] = None
    exclude_dirs: Optional[List[str]] = None
    max_workers: int = 0
    cache_path: Optional[str] = None
    scan_name: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "root": self.root,
            "fast_mode": bool(self.fast_mode),
            "include_hidden": bool(self.include_hidden),
            "follow_symlinks": bool(self.follow_symlinks),
            "min_size_bytes": int(self.min_size_bytes),
            "allowed_extensions": list(self.allowed_extensions) if self.allowed_extensions else None,
            "exclude_dirs": list(self.exclude_dirs) if self.exclude_dirs else None,
            "max_workers": int(self.max_workers),
            "cache_path": self.cache_path,
            "scan_name": self.scan_name,
            "mode": "fast" if self.fast_mode else "standard",
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "StartScanConfig":
        return cls(
            root=str(d.get("root") or d.get("scan_root") or d.get("path") or ""),
            fast_mode=bool(d.get("fast_mode", False) or (str(d.get("mode", "")).lower() == "fast")),
            include_hidden=bool(d.get("include_hidden", False)),
            follow_symlinks=bool(d.get("follow_symlinks", False)),
            min_size_bytes=int(d.get("min_size_bytes", 1024)),
            allowed_extensions=list(d.get("allowed_extensions") or []) or None,
            exclude_dirs=list(d.get("exclude_dirs") or []) or None,
            max_workers=int(d.get("max_workers", 0)),
            cache_path=d.get("cache_path"),
            scan_name=d.get("scan_name"),
        )


def _pick_emotion(*names: str) -> Any:
    for n in names:
        if hasattr(EyeEmotion, n):
            return getattr(EyeEmotion, n)
    for n in ("FOCUSED", "NEUTRAL", "IDLE", "DEFAULT"):
        if hasattr(EyeEmotion, n):
            return getattr(EyeEmotion, n)
    return None


def _safe_pupil(name: str) -> Any:
    if hasattr(PupilShape, name):
        return getattr(PupilShape, name)
    for n in ("ROUND", "CIRCLE", "DEFAULT"):
        if hasattr(PupilShape, n):
            return getattr(PupilShape, n)
    return None


@dataclass(frozen=True, slots=True)
class EyePreset:
    name: str
    emotion: Any
    pupil: Any
    dilation: float
    blink: float
    hero: bool


class EyeControlPanel(QFrame):
    """Retractable panel for eye presets and toggles. Theme tokens only."""
    def __init__(self, eye: EyeWidget, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._eye = eye
        self.setObjectName("EyeControlPanel")
        self.setVisible(False)
        panel = theme_token("panel")
        line = theme_token("line")
        text = theme_token("text")
        accent = theme_token("accent")
        self.setStyleSheet(f"""
            #EyeControlPanel {{
                background: {panel};
                border: 1px solid {line};
                border-radius: 14px;
            }}
            QPushButton {{
                text-align: left;
                padding: 8px 10px;
                border-radius: 10px;
                border: 1px solid {line};
                background: transparent;
                color: {text};
            }}
            QPushButton:hover {{ border-color: {accent}; }}
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        self._presets = [
            EyePreset("Calm Keeper", _pick_emotion("CALM", "NEUTRAL", "IDLE"), _safe_pupil("ROUND"), 0.55, 0.35, False),
            EyePreset("Scanner Focus", _pick_emotion("FOCUSED", "LOCKED"), _safe_pupil("ROUND"), 0.65, 0.25, True),
            EyePreset("Curious", _pick_emotion("CURIOUS", "ALERT"), _safe_pupil("ROUND"), 0.60, 0.30, False),
            EyePreset("Regret Guardian", _pick_emotion("SAD", "ANGRY", "FEAR"), _safe_pupil("SLIT"), 0.50, 0.40, False),
        ]
        for p in self._presets:
            btn = QPushButton(p.name)
            btn.clicked.connect(lambda checked=False, preset=p: self._apply_preset(preset))
            layout.addWidget(btn)
        self._toggle_follow = QPushButton("Toggle: Follow Cursor")
        self._toggle_follow.clicked.connect(self._toggle_focus)
        layout.addWidget(self._toggle_follow)
        self._toggle_blink = QPushButton("Toggle: Blink")
        self._toggle_blink.clicked.connect(self._toggle_blinking)
        layout.addWidget(self._toggle_blink)

    def _apply_preset(self, p: EyePreset) -> None:
        if p.emotion is not None and hasattr(self._eye, "set_emotion"):
            self._eye.set_emotion(p.emotion)
        if p.pupil is not None and hasattr(self._eye, "set_pupil_shape"):
            self._eye.set_pupil_shape(p.pupil)
        if hasattr(self._eye, "set_dilation"):
            self._eye.set_dilation(p.dilation)
        if hasattr(self._eye, "set_blink"):
            self._eye.set_blink(p.blink)
        if hasattr(self._eye, "set_hero_mode"):
            self._eye.set_hero_mode(p.hero)

    def _toggle_focus(self) -> None:
        state = bool(self.property("follow") or False)
        self.setProperty("follow", not state)
        if hasattr(self._eye, "set_focus"):
            self._eye.set_focus(not state)

    def _toggle_blinking(self) -> None:
        state = bool(self.property("blink") or True)
        self.setProperty("blink", not state)
        if hasattr(self._eye, "set_blink"):
            self._eye.set_blink(0.35 if not state else 0.0)


class StartPage(BaseStation):
    station_id = "mission"
    station_title = "Mission"
    navigate_requested = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._log = get_logger("ui.StartPage")
        self._build_ui()

    def _build_ui(self) -> None:
        self.setObjectName("StartPage")
        bg = theme_token("bg")
        text = theme_token("text")
        muted = theme_token("muted")
        accent = theme_token("accent")
        line = theme_token("line")
        panel = theme_token("panel")
        self.setStyleSheet(f"""
            StartPage {{ background: {bg}; }}
        """)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        center = QWidget(self)
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(32, 32, 32, 32)
        center_layout.setSpacing(20)
        center_layout.addStretch(1)

        # Title and tagline
        title = QLabel("CEREBRO")
        title.setObjectName("StartPageTitle")
        title.setStyleSheet(f"font-size: 28px; font-weight: 800; letter-spacing: 0.08em; color: {text};")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        center_layout.addWidget(title)
        tagline = QLabel("One eye on your duplicates.")
        tagline.setObjectName("StartPageTagline")
        tagline.setStyleSheet(f"font-size: 15px; color: {muted};")
        tagline.setAlignment(Qt.AlignmentFlag.AlignCenter)
        center_layout.addWidget(tagline)
        center_layout.addSpacing(8)

        # Hero container: eye in a spotlight frame
        hero_frame = QFrame()
        hero_frame.setObjectName("EyeHeroFrame")
        hero_frame.setStyleSheet(f"""
            #EyeHeroFrame {{
                background: {panel};
                border: 1px solid {line};
                border-radius: 24px;
                padding: 24px;
            }}
            #EyeHeroFrame:hover {{ border-color: {accent}; }}
        """)
        hero_layout = QVBoxLayout(hero_frame)
        hero_layout.setContentsMargins(24, 24, 24, 24)
        hero_layout.setSpacing(0)

        self.eye = EyeWidget()
        self.eye.setMinimumHeight(400)
        self.eye.setMaximumHeight(520)
        emo = _pick_emotion("FOCUSED", "NEUTRAL", "IDLE")
        if emo is not None and hasattr(self.eye, "set_emotion"):
            self.eye.set_emotion(emo)
        if hasattr(self.eye, "set_focus"):
            self.eye.set_focus(True)
        if hasattr(self.eye, "set_hero_mode"):
            self.eye.set_hero_mode(True)

        eye_row = QHBoxLayout()
        eye_row.addStretch(1)
        eye_row.addWidget(self.eye, 0)
        eye_row.addStretch(1)
        hero_layout.addLayout(eye_row)
        center_layout.addWidget(hero_frame, 0, Qt.AlignmentFlag.AlignCenter)
        center_layout.addStretch(1)

        # Nav: Scan = primary CTA, others secondary
        nav = QHBoxLayout()
        nav.setSpacing(12)
        scan_btn = QPushButton("🔎  Start Scan")
        scan_btn.setObjectName("StartPagePrimaryCTA")
        scan_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        scan_btn.setMinimumHeight(48)
        scan_btn.setMinimumWidth(160)
        scan_btn.setStyleSheet(f"""
            QPushButton#StartPagePrimaryCTA {{
                background: {accent};
                color: white;
                border: none;
                border-radius: 14px;
                font-size: 16px;
                font-weight: 700;
                padding: 12px 24px;
            }}
            QPushButton#StartPagePrimaryCTA:hover {{ opacity: 0.95; }}
            QPushButton#StartPagePrimaryCTA:pressed {{ padding: 14px 22px 10px 26px; }}
        """)
        scan_btn.clicked.connect(lambda: self.navigate_requested.emit("scan"))
        nav.addStretch(1)
        nav.addWidget(scan_btn, 0)
        nav.addStretch(1)
        center_layout.addLayout(nav)

        def mk_secondary(label: str, sid: str) -> QPushButton:
            b = QPushButton(label)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setMinimumHeight(40)
            b.setStyleSheet(f"""
                QPushButton {{
                    background: transparent;
                    border: 1px solid {line};
                    border-radius: 12px;
                    padding: 8px 16px;
                    color: {text};
                }}
                QPushButton:hover {{ border-color: {accent}; color: {accent}; }}
            """)
            b.clicked.connect(lambda: self.navigate_requested.emit(sid))
            return b

        secondary_row = QHBoxLayout()
        secondary_row.setSpacing(10)
        secondary_row.addStretch(1)
        secondary_row.addWidget(mk_secondary("🎨 Themes", "themes"))
        secondary_row.addWidget(mk_secondary("🕰️ History", "history"))
        secondary_row.addWidget(mk_secondary("⚙️ Settings", "settings"))
        secondary_row.addWidget(mk_secondary("🧰 Hub", "hub"))
        secondary_row.addStretch(1)
        center_layout.addLayout(secondary_row)
        center_layout.addStretch(1)
        root.addWidget(center, 1)

        # Use the eye widget's built-in control menu instead of separate panel
        self._eye_toggle = QPushButton("👁️")
        self._eye_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self._eye_toggle.setFixedSize(44, 44)
        self._eye_toggle.setStyleSheet(f"""
            QPushButton {{
                background: {panel};
                border: 1px solid {line};
                border-radius: 22px;
                color: {text};
            }}
            QPushButton:hover {{ border-color: {accent}; }}
        """)
        self._eye_toggle.clicked.connect(self._toggle_eye_controls)
        self._eye_toggle.setParent(self)
        
        # Hide the eye widget's gear button since we have our own toggle
        if hasattr(self.eye, '_menu_btn'):
            self.eye._menu_btn.setVisible(False)
        
        self._place_overlays()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._place_overlays()

    def _place_overlays(self) -> None:
        margin = 18
        self._eye_toggle.move(self.width() - self._eye_toggle.width() - margin, margin)

    def _toggle_eye_controls(self) -> None:
        """Toggle the eye widget's control menu."""
        if hasattr(self.eye, '_control_menu'):
            if self.eye._control_menu.isVisible():
                self.eye._control_menu.hide()
            else:
                # Position the control menu next to the toggle button
                btn_global = self._eye_toggle.mapToGlobal(self._eye_toggle.rect().bottomLeft())
                self.eye._control_menu.move(
                    btn_global.x() - self.eye._control_menu.width() + self._eye_toggle.width(),
                    btn_global.y() + 10
                )
                self.eye._control_menu.show()

    def reset(self) -> None:
        pass

    def reset_for_new_scan(self) -> None:
        pass
