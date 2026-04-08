# cerebro/ui/pages/station_navigator.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Any, List, Tuple
import math

from PySide6.QtCore import Qt, Signal, QPropertyAnimation, QEasingCurve, QSize, QPointF, QRectF
from PySide6.QtGui import QFont, QPainter, QPen, QBrush, QColor, QLinearGradient, QRadialGradient, QPainterPath
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QFrame, 
)

from cerebro.ui.state_bus import get_state_bus
from cerebro.ui.theme_engine import get_theme_manager, current_colors


@dataclass(frozen=True, slots=True)
class StationConfig:
    id: str
    name: str
    icon: str
    hint: str = ""
    lockable: bool = False


class SpineButton(QPushButton):
    """Custom button with intelligent painting for rings, badges, and lock states."""
    
    def __init__(
        self,
        station_id: str,
        icon: str,
        text: str,
        collapsed: bool = False,
        parent: Optional[QWidget] = None
    ):
        super().__init__(parent)
        self.station_id = station_id
        self._icon = icon
        self._text = text
        self._collapsed = collapsed
        
        # Intelligence data
        self._progress: Optional[float] = None  # 0.0 to 1.0
        self._badge_count: Optional[int] = None
        self._is_locked: bool = False
        self._lock_reason: str = ""
        self._is_pulsing: bool = False
        self._is_current: bool = False
        self._is_hovered: bool = False
        self._pulse_phase: float = 0.0
        
        # Animation timer for pulsing
        from PySide6.QtCore import QTimer
        self._pulse_timer = QTimer(self)
        self._pulse_timer.timeout.connect(self._update_pulse)
        self._pulse_timer.start(50)  # 20 FPS
        
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(40 if not collapsed else 36)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        
        self._apply_text()
        self.setMouseTracking(True)
    
    def set_collapsed(self, collapsed: bool) -> None:
        self._collapsed = bool(collapsed)
        self.setMinimumHeight(36 if collapsed else 40)
        self._apply_text()
        self.update()
    
    def set_intelligence(
        self,
        progress: Optional[float] = None,
        badge_count: Optional[int] = None,
        is_locked: bool = False,
        lock_reason: str = "",
        is_current: bool = False,
        is_pulsing: bool = False
    ) -> None:
        """Update intelligence visualization parameters."""
        changed = False
        
        if progress != self._progress:
            self._progress = progress
            changed = True
        
        if badge_count != self._badge_count:
            self._badge_count = badge_count
            changed = True
        
        if is_locked != self._is_locked:
            self._is_locked = is_locked
            changed = True
        
        if lock_reason != self._lock_reason:
            self._lock_reason = lock_reason
            changed = True
        
        if is_current != self._is_current:
            self._is_current = is_current
            changed = True
        
        if is_pulsing != self._is_pulsing:
            self._is_pulsing = is_pulsing
            if is_pulsing and not self._pulse_timer.isActive():
                self._pulse_timer.start(50)
            elif not is_pulsing:
                self._pulse_phase = 0.0
            changed = True
        
        if changed:
            self.update()
    
    def enterEvent(self, event):
        self._is_hovered = True
        self.update()
        super().enterEvent(event)
    
    def leaveEvent(self, event):
        self._is_hovered = False
        self.update()
        super().leaveEvent(event)
    
    def _update_pulse(self) -> None:
        if self._is_pulsing:
            self._pulse_phase = (self._pulse_phase + 0.1) % (2 * math.pi)
            self.update()
    
    def _apply_text(self) -> None:
        if self._collapsed:
            self.setText(f"{self._icon}")
        else:
            self.setText(f"{self._icon}  {self._text}")
    
    def paintEvent(self, event):
        """Custom paint with rings, badges, and lock states."""
        # First, paint default button
        super().paintEvent(event)
        
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        rect = self.rect()
        padding = 8
        
        if self._collapsed:
            # Collapsed mode - centered icon with surrounding visualizations
            center_x = rect.width() // 2
            center_y = rect.height() // 2
            radius = min(rect.width(), rect.height()) // 2 - 4
            
            # Draw progress ring (if any)
            if self._progress is not None and 0 <= self._progress <= 1:
                self._draw_progress_ring(painter, center_x, center_y, radius)
            
            # Draw badge (collapsed: small dot in corner)
            if self._badge_count is not None and self._badge_count > 0:
                self._draw_badge_collapsed(painter, rect)
            
            # Draw lock icon (collapsed: small lock in opposite corner)
            if self._is_locked:
                self._draw_lock_collapsed(painter, rect)
            
            # Draw pulsing glow
            if self._is_pulsing:
                self._draw_pulse_glow(painter, center_x, center_y, radius)
        else:
            # Expanded mode - visualizations on the right side
            right_margin = 12
            center_y = rect.height() // 2
            ring_radius = 14
            
            # Draw progress ring (right aligned)
            if self._progress is not None and 0 <= self._progress <= 1:
                ring_x = rect.width() - right_margin - ring_radius
                self._draw_progress_ring(painter, ring_x, center_y, ring_radius)
                right_margin += ring_radius * 2 + 4
            
            # Draw badge (right aligned after progress)
            if self._badge_count is not None and self._badge_count > 0:
                badge_x = rect.width() - right_margin - 16
                self._draw_badge_expanded(painter, badge_x, center_y)
                right_margin += 32
            
            # Draw lock icon (if locked)
            if self._is_locked:
                lock_x = rect.width() - right_margin - 12
                self._draw_lock_expanded(painter, lock_x, center_y)
            
            # Draw current station indicator (left side bar)
            if self._is_current:
                self._draw_current_indicator(painter, rect)
            
            # Draw pulsing glow
            if self._is_pulsing:
                self._draw_pulse_glow(painter, rect.width() - 40, center_y, 16)
    
    def _draw_progress_ring(self, painter: QPainter, cx: int, cy: int, radius: int):
        """Draw a progress ring around the given center."""
        colors = current_colors()
        ring_width = 3
        
        # Background ring
        painter.setPen(QPen(QColor(colors.get('muted', '#4A5568')), ring_width))
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(QPointF(cx, cy), radius, radius)
        
        # Progress arc
        if self._progress and self._progress > 0:
            # Color based on progress
            if self._progress < 0.3:
                progress_color = QColor(colors.get('warning', '#F6AD55'))
            elif self._progress < 0.7:
                progress_color = QColor(colors.get('info', '#63B3ED'))
            else:
                progress_color = QColor(colors.get('success', '#68D391'))
            
            pen = QPen(progress_color, ring_width)
            pen.setCapStyle(Qt.RoundCap)
            painter.setPen(pen)
            
            # Draw progress arc
            span_angle = int(self._progress * 360 * 16)
            painter.drawArc(
                cx - radius, cy - radius,
                radius * 2, radius * 2,
                90 * 16,  # Start at top
                -span_angle  # Clockwise
            )
    
    def _draw_badge_collapsed(self, painter: QPainter, rect: QRectF):
        """Draw badge in collapsed mode (small red dot)."""
        dot_size = 8
        dot_x = rect.width() - 6
        dot_y = 6
        
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(QColor('#F56565')))  # Red
        
        # Add glow effect
        painter.setOpacity(0.9)
        painter.drawEllipse(dot_x - dot_size//2, dot_y - dot_size//2, dot_size, dot_size)
        painter.setOpacity(1.0)
    
    def _draw_badge_expanded(self, painter: QPainter, x: int, y: int):
        """Draw badge in expanded mode (count with background)."""
        if self._badge_count is None or self._badge_count <= 0:
            return
        
        badge_text = str(self._badge_count) if self._badge_count < 100 else "99+"
        
        # Calculate text size
        font = painter.font()
        font.setPointSize(9)
        painter.setFont(font)
        text_rect = painter.boundingRect(0, 0, 100, 100, Qt.AlignCenter, badge_text)
        
        # Badge background
        badge_width = max(20, text_rect.width() + 10)
        badge_height = 20
        badge_rect = QRectF(
            x - badge_width//2,
            y - badge_height//2,
            badge_width,
            badge_height
        )
        
        # Rounded background
        painter.setPen(Qt.NoPen)
        gradient = QLinearGradient(badge_rect.topLeft(), badge_rect.bottomRight())
        gradient.setColorAt(0, QColor('#F56565'))
        gradient.setColorAt(1, QColor('#C53030'))
        painter.setBrush(QBrush(gradient))
        painter.drawRoundedRect(badge_rect, badge_height//2, badge_height//2)
        
        # Badge text
        painter.setPen(QPen(QColor('#FFFFFF')))
        painter.drawText(badge_rect, Qt.AlignCenter, badge_text)
    
    def _draw_lock_collapsed(self, painter: QPainter, rect: QRectF):
        """Draw lock icon in collapsed mode (small lock in corner)."""
        lock_size = 10
        lock_x = 6
        lock_y = rect.height() - 12
        
        painter.setPen(QPen(QColor('#A0AEC0'), 1))
        painter.setBrush(QBrush(QColor('#718096')))
        
        # Draw simple lock symbol
        painter.drawRect(lock_x, lock_y, lock_size, lock_size*0.7)
        painter.drawArc(lock_x - 2, lock_y - 3, lock_size + 4, 6, 0, 180 * 16)
    
    def _draw_lock_expanded(self, painter: QPainter, x: int, y: int):
        """Draw lock icon in expanded mode."""
        lock_size = 14
        
        painter.setPen(QPen(QColor('#A0AEC0'), 1.5))
        painter.setBrush(QBrush(QColor('#718096')))
        
        # Draw lock body
        painter.drawRect(x - lock_size//2, y - lock_size//3, lock_size, lock_size*0.7)
        # Draw lock arc
        painter.drawArc(x - lock_size//2 - 2, y - lock_size//3 - 4, lock_size + 4, 8, 0, 180 * 16)
        
        # Add lock text hint on hover
        if self._is_hovered and self._lock_reason:
            self._draw_lock_tooltip(painter, x, y)
    
    def _draw_lock_tooltip(self, painter: QPainter, x: int, y: int):
        """Draw lock reason tooltip."""
        font = painter.font()
        font.setPointSize(8)
        painter.setFont(font)
        
        text = self._lock_reason[:20] + "..." if len(self._lock_reason) > 20 else self._lock_reason
        text_rect = painter.boundingRect(0, 0, 200, 100, Qt.AlignCenter, text)
        
        tooltip_rect = QRectF(
            x - text_rect.width()//2 - 6,
            y - 35,
            text_rect.width() + 12,
            text_rect.height() + 8
        )
        
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(QColor(30, 30, 40, 220)))
        painter.drawRoundedRect(tooltip_rect, 4, 4)
        
        painter.setPen(QPen(QColor('#E2E8F0')))
        painter.drawText(tooltip_rect, Qt.AlignCenter, text)
    
    def _draw_current_indicator(self, painter: QPainter, rect: QRectF):
        """Draw current station indicator (left accent bar)."""
        indicator_width = 4
        indicator_margin = 4
        
        painter.setPen(Qt.NoPen)
        gradient = QLinearGradient(
            rect.left(), rect.top(),
            rect.left(), rect.bottom()
        )
        gradient.setColorAt(0, QColor('#4299E1'))
        gradient.setColorAt(0.5, QColor('#667EEA'))
        gradient.setColorAt(1, QColor('#4299E1'))
        painter.setBrush(QBrush(gradient))
        
        painter.drawRect(
            rect.left() + indicator_margin,
            rect.top() + indicator_margin,
            indicator_width,
            rect.height() - 2 * indicator_margin
        )
    
    def _draw_pulse_glow(self, painter: QPainter, cx: int, cy: int, base_radius: int):
        """Draw pulsing glow effect."""
        pulse_radius = base_radius + 4 + math.sin(self._pulse_phase) * 3
        
        painter.setPen(Qt.NoPen)
        gradient = QRadialGradient(cx, cy, pulse_radius)
        gradient.setColorAt(0, QColor(66, 153, 225, 100))
        gradient.setColorAt(1, QColor(66, 153, 225, 0))
        painter.setBrush(QBrush(gradient))
        
        painter.drawEllipse(QPointF(cx, cy), pulse_radius, pulse_radius)


class StationNavigator(QWidget):
    """
    Intelligent Spine Navigator with visual intelligence:
    - Progress rings for scanning
    - Badge counts for review/history
    - Lock states for guided mode
    - Pulsing animations for active operations
    """
    station_requested = Signal(str)
    station_changed = Signal(str)
    mode_changed = Signal(str)
    
    STATIONS: List[StationConfig] = [
        StationConfig("mission", "Mission", "👁️", "Start", False),
        StationConfig("scan", "Scan", "🔎", "Scan", True),
        StationConfig("review", "Review", "🧾", "Review", True),
        StationConfig("history", "History", "🕰️", "History", True),
        StationConfig("themes", "Themes", "🎨", "Themes", False),
        StationConfig("settings", "Settings", "⚙️", "Settings", False),
        StationConfig("audit", "Audit", "🧪", "Audit", False),
        StationConfig("hub", "Hub", "🧰", "Extras", False),
    ]
    
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("StationNavigator")
        self._bus = get_state_bus()
        self._theme = get_theme_manager()
        
        self._collapsed = False
        self._current_station: str = "mission"
        self._current_mode: str = "guided"
        self._suppress_emit = False
        
        # Intelligence state storage
        self._station_intelligence: Dict[str, Dict[str, Any]] = {
            st.id: {
                "progress": None,
                "badge_count": None,
                "is_locked": False,
                "lock_reason": "",
                "is_pulsing": False,
            }
            for st in self.STATIONS
        }
        
        # Animation for collapse/expand
        self._anim = QPropertyAnimation(self, b"minimumWidth", self)
        self._anim.setDuration(180)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        
        self._build_ui()
        self._wire_bus()
        self._apply_theme()
        
        self.set_collapsed(False)
        self.set_current_station("mission")
        
        # Set up guided mode locks
        self._apply_guided_mode_locks()
    
    def _build_ui(self) -> None:
        self.setMinimumWidth(200)
        self.setMaximumWidth(260)
        
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)
        
        # Brand header
        brand = QHBoxLayout()
        brand.setContentsMargins(0, 0, 0, 0)
        
        self._brand_label = QLabel("CEREBRO")
        self._brand_label.setFont(QFont("Segoe UI", 11, QFont.Black))
        
        self._collapse_btn = QPushButton("⟷")
        self._collapse_btn.setFixedSize(QSize(28, 28))
        self._collapse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._collapse_btn.clicked.connect(self.toggle_collapsed)
        
        brand.addWidget(self._brand_label, 1)
        brand.addWidget(self._collapse_btn, 0, Qt.AlignRight)
        
        root.addLayout(brand)
        
        # Separator
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        root.addWidget(line)
        
        # Station buttons
        self._btns: Dict[str, SpineButton] = {}
        for st in self.STATIONS:
            btn = SpineButton(st.id, st.icon, st.name, collapsed=False)
            btn.setObjectName(f"nav_{st.id}")
            btn.clicked.connect(lambda checked=False, sid=st.id: self._on_station_clicked(sid))
            self._btns[st.id] = btn
            root.addWidget(btn)
        
        root.addStretch(1)
        
        # Mode selector
        self._mode_btn = QPushButton("🧠  Mode: Guided")
        self._mode_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._mode_btn.setMinimumHeight(32)
        self._mode_btn.clicked.connect(self._toggle_mode)
        root.addWidget(self._mode_btn)
        
        self._apply_theme()
    
    def _apply_theme(self):
        """Apply theme colors to the navigator."""
        colors = current_colors()
        
        self.setStyleSheet(f"""
            #StationNavigator {{
                background: {colors.get('panel', '#151922')};
                border-right: 1px solid {colors.get('border', 'rgba(120,140,180,0.18)')};
            }}
            QPushButton {{
                text-align: left;
                padding: 8px 10px;
                border-radius: 8px;
                border: 1px solid {colors.get('border', 'rgba(120,140,180,0.18)')};
                background: {colors.get('card', 'rgba(20, 26, 38, 0.35)')};
                color: {colors.get('text', '#e7ecf2')};
                font-size: 12px;
                font-weight: 500;
            }}
            QPushButton:hover {{
                border-color: {colors.get('primary', 'rgba(130,170,255,0.45)')};
                background: {colors.get('card_hover', 'rgba(20, 26, 38, 0.55)')};
            }}
            QPushButton[active="true"] {{
                border-color: {colors.get('primary', 'rgba(130,170,255,0.70)')};
                background: {colors.get('active', 'rgba(55, 90, 170, 0.22)')};
            }}
            QPushButton:disabled {{
                color: {colors.get('muted', '#4A5568')};
                background: {colors.get('card', 'rgba(20, 26, 38, 0.20)')};
            }}
            QLabel {{
                color: {colors.get('text', '#e7ecf2')};
            }}
            QFrame {{
                border: 1px solid {colors.get('border', 'rgba(120,140,180,0.20)')};
            }}
        """)
        
        self._brand_label.setStyleSheet(f"color: {colors.get('text', 'rgba(235,242,255,0.95)')};")
    
    def _wire_bus(self) -> None:
        """Connect to StateBus signals for intelligence updates."""
        self._bus.station_status_updated.connect(self._on_station_status)
        self._bus.scan_progress.connect(self._on_scan_progress)
        self._bus.scan_completed.connect(self._on_scan_completed)
        self._bus.scan_started.connect(self._on_scan_started)
        self._bus.theme_changed.connect(self._on_theme_changed)
    
    def _on_theme_changed(self, theme_key: str):
        """Handle theme changes."""
        self._apply_theme()
        for btn in self._btns.values():
            btn.update()
    
    def _on_station_status(self, status) -> None:
        """Update station intelligence from bus."""
        sid = getattr(status, "station_id", None)
        if not sid or sid not in self._btns:
            return
        
        # Update intelligence state
        self._station_intelligence[sid].update({
            "badge_count": getattr(status, "badge_count", None),
            "progress": getattr(status, "progress", None),
            "is_locked": getattr(status, "is_locked", False),
            "lock_reason": getattr(status, "lock_reason", ""),
            "is_pulsing": getattr(status, "is_pulsing", False),
        })
        
        # Apply to button
        self._btns[sid].set_intelligence(
            progress=self._station_intelligence[sid]["progress"],
            badge_count=self._station_intelligence[sid]["badge_count"],
            is_locked=self._station_intelligence[sid]["is_locked"],
            lock_reason=self._station_intelligence[sid]["lock_reason"],
            is_current=(sid == self._current_station),
            is_pulsing=self._station_intelligence[sid]["is_pulsing"]
        )
    
    def _on_scan_progress(self, progress_data) -> None:
        """Handle scan progress updates."""
        progress = getattr(progress_data, "progress", 0.0)
        
        # Update scan station intelligence
        self._station_intelligence["scan"].update({
            "progress": progress,
            "is_pulsing": progress < 1.0 and progress > 0.0,
        })
        
        # Apply to scan button
        self._btns["scan"].set_intelligence(
            progress=progress,
            badge_count=self._station_intelligence["scan"]["badge_count"],
            is_locked=self._station_intelligence["scan"]["is_locked"],
            lock_reason=self._station_intelligence["scan"]["lock_reason"],
            is_current=("scan" == self._current_station),
            is_pulsing=self._station_intelligence["scan"]["is_pulsing"]
        )
    
    def _on_scan_started(self, scan_id: str) -> None:
        """Handle scan started - reset review badge."""
        self._station_intelligence["review"]["badge_count"] = None
        self._btns["review"].set_intelligence(
            progress=self._station_intelligence["review"]["progress"],
            badge_count=None,
            is_locked=self._station_intelligence["review"]["is_locked"],
            lock_reason=self._station_intelligence["review"]["lock_reason"],
            is_current=("review" == self._current_station),
            is_pulsing=False
        )
    
    def _on_scan_completed(self, result: dict) -> None:
        """Handle scan completed - update review badge with duplicate count."""
        duplicate_count = result.get("duplicate_count", 0)
        group_count = result.get("group_count", 0)
        
        # Show badge if there are duplicates
        badge = duplicate_count if duplicate_count > 0 else None
        
        self._station_intelligence["review"].update({
            "badge_count": badge,
            "is_pulsing": duplicate_count > 0,
        })
        
        self._btns["review"].set_intelligence(
            progress=self._station_intelligence["review"]["progress"],
            badge_count=badge,
            is_locked=self._station_intelligence["review"]["is_locked"],
            lock_reason=self._station_intelligence["review"]["lock_reason"],
            is_current=("review" == self._current_station),
            is_pulsing=(duplicate_count > 0)
        )
    
    def _apply_guided_mode_locks(self):
        """Apply locks based on current mode."""
        # Navigation gating is disabled; guided mode no longer locks stations.
        if self._current_mode == "guided":
            for st in self.STATIONS:
                if st.lockable:
                    self._station_intelligence[st.id].update({
                        "is_locked": False,
                        "lock_reason": "",
                    })
        
        # Update all buttons
        for sid, btn in self._btns.items():
            btn.set_intelligence(
                progress=self._station_intelligence[sid]["progress"],
                badge_count=self._station_intelligence[sid]["badge_count"],
                is_locked=self._station_intelligence[sid]["is_locked"],
                lock_reason=self._station_intelligence[sid]["lock_reason"],
                is_current=(sid == self._current_station),
                is_pulsing=self._station_intelligence[sid]["is_pulsing"]
            )
    
    def _on_station_clicked(self, station_id: str) -> None:
        """Handle station button click."""
        if self._suppress_emit:
            return

        self.set_current_station(station_id)
        self.station_requested.emit(station_id)
    
    def set_current_station(self, station_id: str) -> None:
        """Programmatically set current station (doesn't emit request)."""
        if station_id not in self._btns:
            return
        
        old_station = self._current_station
        self._current_station = station_id
        
        # Update old station
        if old_station in self._btns:
            self._btns[old_station].set_intelligence(
                progress=self._station_intelligence[old_station]["progress"],
                badge_count=self._station_intelligence[old_station]["badge_count"],
                is_locked=self._station_intelligence[old_station]["is_locked"],
                lock_reason=self._station_intelligence[old_station]["lock_reason"],
                is_current=False,
                is_pulsing=self._station_intelligence[old_station]["is_pulsing"]
            )
        
        # Update new station
        self._btns[station_id].set_intelligence(
            progress=self._station_intelligence[station_id]["progress"],
            badge_count=self._station_intelligence[station_id]["badge_count"],
            is_locked=self._station_intelligence[station_id]["is_locked"],
            lock_reason=self._station_intelligence[station_id]["lock_reason"],
            is_current=True,
            is_pulsing=self._station_intelligence[station_id]["is_pulsing"]
        )
        
        self.station_changed.emit(station_id)
    
    def toggle_collapsed(self) -> None:
        self.set_collapsed(not self._collapsed)
    
    def set_collapsed(self, collapsed: bool) -> None:
        self._collapsed = bool(collapsed)
        
        target = 64 if self._collapsed else 200
        self._anim.stop()
        self._anim.setStartValue(self.minimumWidth())
        self._anim.setEndValue(target)
        self._anim.start()
        
        self.setMaximumWidth(target)
        self.setMinimumWidth(target)
        
        self._brand_label.setVisible(not self._collapsed)
        
        for btn in self._btns.values():
            btn.set_collapsed(self._collapsed)
        
        self._mode_btn.setText("🧠" if self._collapsed else f"🧠  Mode: {self._current_mode.capitalize()}")
    
    def _toggle_mode(self) -> None:
        """Toggle between guided and expert modes."""
        self._current_mode = "expert" if self._current_mode == "guided" else "guided"
        self._mode_btn.setText("🧠" if self._collapsed else f"🧠  Mode: {self._current_mode.capitalize()}")
        
        # Apply mode-specific locks
        self._apply_guided_mode_locks()
        
        # Notify system
        self.mode_changed.emit(self._current_mode)
        self._bus.mode_changed.emit(self._current_mode)
    
    def refresh_theme(self) -> None:
        """Called when theme changes externally."""
        self._apply_theme()
        self.update()

    def reset(self) -> None:
        """Clear internal state; no workers. Navigation registry only."""
        pass

    def reset_for_new_scan(self) -> None:
        """No scan-specific state."""
        pass