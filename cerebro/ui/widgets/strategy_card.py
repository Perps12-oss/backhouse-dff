# cerebro/ui/widgets/strategy_card.py
"""
Strategy Card Widget - Displays strategy information with glass morphism styling
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
    QFrame, QProgressBar, QGraphicsDropShadowEffect
)
from PySide6.QtCore import Qt, Signal, QPropertyAnimation, QEasingCurve, QSize
from PySide6.QtGui import QFont, QColor, QLinearGradient, QPainter, QBrush, QPen

from cerebro.ui.widgets.glass_panel import GlassPanel


class StrategyCard(GlassPanel):
    """
    Interactive card displaying a smart strategy with visual indicators
    """
    
    clicked = Signal(object)  # Emits the strategy enum/value
    apply_requested = Signal(object)
    
    def __init__(self, strategy, parent=None):
        super().__init__(parent)
        self.strategy = strategy
        self._is_selected = False
        self._is_hovered = False
        self._setup_ui()
        self._apply_styles()
    
    def _setup_ui(self):
        """Initialize the card UI"""
        self.setFixedSize(200, 140)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)
        
        # Icon and name header
        header = QHBoxLayout()
        
        self.icon_label = QLabel(self.strategy.icon)
        self.icon_label.setStyleSheet("font-size: 28px;")
        header.addWidget(self.icon_label)
        
        header.addStretch()
        
        # Selection indicator
        self.selection_indicator = QLabel("✓")
        self.selection_indicator.setStyleSheet("""
            QLabel {
                color: #22c55e;
                font-size: 16px;
                font-weight: bold;
                padding: 2px 6px;
                background: rgba(34, 197, 94, 0.2);
                border-radius: 12px;
            }
        """)
        self.selection_indicator.setVisible(False)
        header.addWidget(self.selection_indicator)
        
        layout.addLayout(header)
        
        # Strategy name
        self.name_label = QLabel(self.strategy.display_name)
        name_font = QFont()
        name_font.setPointSize(14)
        name_font.setBold(True)
        self.name_label.setFont(name_font)
        self.name_label.setStyleSheet("color: #f1f5f9;")
        layout.addWidget(self.name_label)
        
        # Description
        self.desc_label = QLabel(self.strategy.description)
        self.desc_label.setWordWrap(True)
        self.desc_label.setStyleSheet("""
            QLabel {
                color: #94a3b8;
                font-size: 11px;
                line-height: 1.4;
            }
        """)
        layout.addWidget(self.desc_label)
        
        layout.addStretch()
        
        # Confidence/Usage bar (optional)
        self.confidence_bar = QProgressBar()
        self.confidence_bar.setRange(0, 100)
        self.confidence_bar.setValue(0)
        self.confidence_bar.setTextVisible(False)
        self.confidence_bar.setFixedHeight(4)
        self.confidence_bar.setStyleSheet("""
            QProgressBar {
                background: rgba(255, 255, 255, 0.1);
                border-radius: 2px;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #3b82f6, stop:1 #8b5cf6);
                border-radius: 2px;
            }
        """)
        self.confidence_bar.setVisible(False)
        layout.addWidget(self.confidence_bar)
    
    def _apply_styles(self):
        """Apply glass morphism styles"""
        self.setStyleSheet("""
            StrategyCard {
                background: rgba(30, 41, 59, 0.6);
                border: 2px solid rgba(255, 255, 255, 0.1);
                border-radius: 12px;
            }
            StrategyCard:hover {
                background: rgba(30, 41, 59, 0.8);
                border-color: rgba(59, 130, 246, 0.5);
            }
            StrategyCard[selected="true"] {
                background: rgba(59, 130, 246, 0.15);
                border-color: #3b82f6;
            }
        """)
        
        # Add shadow effect
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(20)
        shadow.setColor(QColor(0, 0, 0, 80))
        shadow.setOffset(0, 4)
        self.setGraphicsEffect(shadow)
    
    def set_selected(self, selected: bool):
        """Update selection state"""
        self._is_selected = selected
        self.selection_indicator.setVisible(selected)
        self.setProperty("selected", selected)
        self.style().unpolish(self)
        self.style().polish(self)
        
        # Animate confidence bar if selected
        if selected:
            self.confidence_bar.setVisible(True)
            self._animate_confidence()
    
    def _animate_confidence(self):
        """Animate confidence bar"""
        self.anim = QPropertyAnimation(self.confidence_bar, b"value")
        self.anim.setDuration(800)
        self.anim.setStartValue(0)
        self.anim.setEndValue(85)  # Example confidence value
        self.anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.anim.start()
    
    def set_confidence(self, value: int):
        """Set confidence value (0-100)"""
        self.confidence_bar.setValue(value)
        self.confidence_bar.setVisible(True)
        
        # Color based on confidence
        if value > 70:
            color = "#22c55e"
        elif value > 40:
            color = "#f59e0b"
        else:
            color = "#ef4444"
        
        self.confidence_bar.setStyleSheet(f"""
            QProgressBar {{
                background: rgba(255, 255, 255, 0.1);
                border-radius: 2px;
            }}
            QProgressBar::chunk {{
                background: {color};
                border-radius: 2px;
            }}
        """)
    
    def mousePressEvent(self, event):
        """Handle click"""
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.strategy)
        super().mousePressEvent(event)
    
    def enterEvent(self, event):
        """Hover enter"""
        self._is_hovered = True
        super().enterEvent(event)
    
    def leaveEvent(self, event):
        """Hover leave"""
        self._is_hovered = False
        super().leaveEvent(event)