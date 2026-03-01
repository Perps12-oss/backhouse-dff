# cerebro/ui/theme_engine.py
"""
CEREBRO Theme Engine v2.0
Enhanced with glassmorphism, dynamic gradients, and full backward compatibility.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from PySide6.QtCore import QObject, Signal, QPropertyAnimation, QEasingCurve, Property
from PySide6.QtGui import QColor, QPalette, QLinearGradient, QGradient
from PySide6.QtWidgets import QApplication


# =============================================================================
# Data Classes
# =============================================================================

@dataclass(frozen=True, slots=True)
class ThemeSpec:
    """Immutable theme specification."""
    key: str
    name: str
    tagline: str
    palette: Dict[str, str]  # hex colors
    qss: str                 # optional QSS string
    is_dark: bool = True
    glass_morphism: bool = True
    category: str = "Studio"
    tags: tuple = ()  # frozen-safe immutable sequence of tag strings
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "key": self.key,
            "name": self.name,
            "tagline": self.tagline,
            "palette": self.palette,
            "qss": self.qss,
            "is_dark": self.is_dark,
            "glass_morphism": self.glass_morphism,
            "category": self.category,
            "tags": list(self.tags),
        }


@dataclass(frozen=True, slots=True)
class GradientSpec:
    """Gradient specification for dynamic themes."""
    name: str
    colors: List[str]  # List of hex colors
    angle: float = 135.0  # Gradient angle in degrees


# =============================================================================
# Utility Functions
# =============================================================================

def _here() -> Path:
    """Get the directory of this file."""
    return Path(__file__).resolve().parent


def _themes_dir() -> Path:
    """Get the themes directory."""
    return _here() / "themes"


def _safe_hex(s: str, fallback: str) -> str:
    """Validate and normalize hex color."""
    s = (s or "").strip()
    if not s:
        return fallback
    if s.startswith("#"):
        # Validate hex length
        if len(s) in (4, 7, 9):
            return s.lower()
    # Try to parse as rgb/rgba
    rgb_match = re.match(r'rgba?\((\d+),\s*(\d+),\s*(\d+)', s)
    if rgb_match:
        r, g, b = map(int, rgb_match.groups())
        return f"#{r:02x}{g:02x}{b:02x}"
    return fallback


def _hex_to_rgb(hex_color: str) -> Tuple[int, int, int]:
    """Convert hex color to RGB tuple."""
    hex_color = hex_color.lstrip('#')
    if len(hex_color) == 3:
        hex_color = ''.join(c * 2 for c in hex_color)
    return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))


def _rgb_to_hex(r: int, g: int, b: int) -> str:
    """Convert RGB to hex color."""
    return f"#{r:02x}{g:02x}{b:02x}"


def _interpolate_color(color1: str, color2: str, factor: float) -> str:
    """Interpolate between two hex colors."""
    r1, g1, b1 = _hex_to_rgb(color1)
    r2, g2, b2 = _hex_to_rgb(color2)
    r = int(r1 + (r2 - r1) * factor)
    g = int(g1 + (g2 - g1) * factor)
    b = int(b1 + (b2 - b1) * factor)
    return _rgb_to_hex(r, g, b)


def _adjust_brightness(hex_color: str, factor: float) -> str:
    """Adjust brightness of a hex color."""
    r, g, b = _hex_to_rgb(hex_color)
    r = max(0, min(255, int(r * factor)))
    g = max(0, min(255, int(g * factor)))
    b = max(0, min(255, int(b * factor)))
    return _rgb_to_hex(r, g, b)


def _generate_glass_gradient(bg: str, panel: str, is_dark: bool) -> str:
    """Generate glass morphism gradient."""
    bg_rgb = _hex_to_rgb(bg)
    panel_rgb = _hex_to_rgb(panel)
    
    if is_dark:
        # Dark mode: subtle transparency
        return f"qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {bg}, stop:1 {panel})"
    else:
        # Light mode: frosted glass effect
        return f"qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 rgba({bg_rgb[0]}, {bg_rgb[1]}, {bg_rgb[2]}, 240), stop:1 rgba({panel_rgb[0]}, {panel_rgb[1]}, {panel_rgb[2]}, 200))"


def _generate_neon_glow(accent: str, intensity: float = 0.3) -> str:
    """Generate neon glow effect color."""
    rgb = _hex_to_rgb(accent)
    glow = f"rgba({rgb[0]}, {rgb[1]}, {rgb[2]}, {intensity})"
    return glow


# =============================================================================
# Palette Generation
# =============================================================================

def _mk_palette(theme: ThemeSpec) -> QPalette:
    """Create QPalette from theme specification."""
    p = QPalette()
    bg = QColor(theme.palette.get("bg", "#0f1115"))
    panel = QColor(theme.palette.get("panel", "#151922"))
    text = QColor(theme.palette.get("text", "#e7ecf2"))
    muted = QColor(theme.palette.get("muted", "#aab3c0"))
    accent = QColor(theme.palette.get("accent", "#7aa2ff"))
    accent2 = QColor(theme.palette.get("accent2", "#a78bfa"))
    danger = QColor(theme.palette.get("danger", "#ff5c7c"))
    ok = QColor(theme.palette.get("ok", "#4ade80"))
    line = QColor(theme.palette.get("line", "#262c3a"))

    # Base colors
    p.setColor(QPalette.Window, bg)
    p.setColor(QPalette.Base, panel)
    p.setColor(QPalette.AlternateBase, bg)
    p.setColor(QPalette.Text, text)
    p.setColor(QPalette.WindowText, text)
    p.setColor(QPalette.Button, panel)
    p.setColor(QPalette.ButtonText, text)
    p.setColor(QPalette.PlaceholderText, muted)
    p.setColor(QPalette.Highlight, accent)
    p.setColor(QPalette.HighlightedText, QColor("#0a0b0f") if theme.is_dark else QColor("#ffffff"))
    p.setColor(QPalette.ToolTipBase, panel)
    p.setColor(QPalette.ToolTipText, text)
    p.setColor(QPalette.BrightText, danger)
    
    # Disabled states
    p.setColor(QPalette.Disabled, QPalette.Text, muted)
    p.setColor(QPalette.Disabled, QPalette.ButtonText, muted)
    p.setColor(QPalette.Disabled, QPalette.WindowText, muted)
    
    return p


# =============================================================================
# QSS Generation
# =============================================================================

def _base_qss(theme: ThemeSpec) -> str:
    """Generate base QSS with optional glassmorphism."""
    bg = _safe_hex(theme.palette.get("bg"), "#0f1115")
    panel = _safe_hex(theme.palette.get("panel"), "#151922")
    panel2 = _safe_hex(theme.palette.get("panel2"), "#0c0f14")
    text = _safe_hex(theme.palette.get("text"), "#e7ecf2")
    muted = _safe_hex(theme.palette.get("muted"), "#aab3c0")
    accent = _safe_hex(theme.palette.get("accent"), "#7aa2ff")
    accent2 = _safe_hex(theme.palette.get("accent2"), "#a78bfa")
    line = _safe_hex(theme.palette.get("line"), "#252b39")
    danger = _safe_hex(theme.palette.get("danger"), "#ff5c7c")
    ok = _safe_hex(theme.palette.get("ok"), "#4ade80")
    
    # Generate glass effect if enabled
    glass_bg = _generate_glass_gradient(bg, panel, theme.is_dark)
    neon_glow = _generate_neon_glow(accent, 0.4)
    
    base_styles = f"""
    * {{
        font-family: "Segoe UI", "Microsoft YaHei", sans-serif;
        color: {text};
        outline: none;
    }}

    QMainWindow {{
        background: {bg};
    }}

    QWidget {{
        color: {text};
    }}

    QStackedWidget, QWidget#pageStack {{
        background: {bg};
        color: {text};
    }}

    QFrame {{
        color: {text};
    }}

    QLabel {{
        background: transparent;
        color: {text};
    }}

    QToolTip {{
        background: {panel};
        color: {text};
        border: 1px solid {line};
        padding: 8px;
        border-radius: 8px;
        font-size: 12px;
    }}

    /* Glass morphism panels */
    .glass-panel {{
        background: {glass_bg};
        border: 1px solid {line};
        border-radius: 16px;
        padding: 16px;
    }}
    
    .glass-card {{
        background: rgba({_hex_to_rgb(panel)[0]}, {_hex_to_rgb(panel)[1]}, {_hex_to_rgb(panel)[2]}, 180);
        border: 1px solid {line};
        border-radius: 12px;
        padding: 12px;
    }}

    /* Input fields with glass effect */
    QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
        background: {panel};
        border: 1px solid {line};
        border-radius: 10px;
        padding: 8px 12px;
        selection-background-color: {accent};
        selection-color: {'#0a0b0f' if theme.is_dark else '#ffffff'};
    }}
    
    QLineEdit:hover, QTextEdit:hover, QPlainTextEdit:hover, QComboBox:hover {{
        border: 1px solid {_interpolate_color(line, accent, 0.5)};
        background: {_adjust_brightness(panel, 1.1 if theme.is_dark else 0.95)};
    }}
    
    QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus {{
        border: 1px solid {accent};
        background: {_adjust_brightness(panel, 1.15 if theme.is_dark else 0.9)};
    }}

    QComboBox::drop-down {{
        border: none;
        width: 24px;
    }}
    
    QComboBox::down-arrow {{
        image: none;
        border-left: 5px solid transparent;
        border-right: 5px solid transparent;
        border-top: 6px solid {muted};
    }}
    
    QComboBox::down-arrow:on {{
        border-top: none;
        border-bottom: 6px solid {accent};
    }}

    QComboBox QAbstractItemView {{
        background: {panel};
        border: 1px solid {line};
        border-radius: 8px;
        selection-background-color: {accent};
        padding: 4px;
    }}

    /* Buttons with neon glow on hover */
    QPushButton {{
        background: {panel};
        border: 1px solid {line};
        border-radius: 12px;
        padding: 10px 16px;
        font-weight: 500;
    }}
    
    QPushButton:hover {{
        border: 1px solid {accent};
        background: {_adjust_brightness(panel, 1.2 if theme.is_dark else 0.9)};
    }}
    
    QPushButton:pressed {{
        background: {panel2};
        border: 1px solid {accent2};
    }}
    
    QPushButton:disabled {{
        color: {muted};
        border-color: {line};
        background: {panel2};
    }}
    
    QPushButton.accent {{
        background: {accent};
        color: {'#0a0b0f' if theme.is_dark else '#ffffff'};
        border: none;
    }}
    
    QPushButton.accent:hover {{
        background: {_adjust_brightness(accent, 1.1)};
        border: 1px solid {neon_glow};
    }}
    
    QPushButton.danger {{
        background: {danger};
        color: #ffffff;
        border: none;
    }}
    
    QPushButton.success {{
        background: {ok};
        color: #0a0b0f;
        border: none;
    }}

    /* Scrollbars with accent color */
    QScrollBar:vertical {{
        background: transparent;
        width: 12px;
        margin: 2px;
        border-radius: 6px;
    }}
    
    QScrollBar::handle:vertical {{
        background: {line};
        border-radius: 6px;
        min-height: 24px;
        margin: 2px;
    }}
    
    QScrollBar::handle:vertical:hover {{
        background: {accent};
    }}
    
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0px;
    }}
    
    QScrollBar:horizontal {{
        background: transparent;
        height: 12px;
        margin: 2px;
        border-radius: 6px;
    }}
    
    QScrollBar::handle:horizontal {{
        background: {line};
        border-radius: 6px;
        min-width: 24px;
        margin: 2px;
    }}
    
    QScrollBar::handle:horizontal:hover {{
        background: {accent};
    }}

    /* Tables with modern styling */
    QTableView {{
        background: {panel};
        alternate-background-color: {panel2};
        gridline-color: {line};
        border: 1px solid {line};
        border-radius: 12px;
        selection-background-color: {accent};
        selection-color: {'#0a0b0f' if theme.is_dark else '#ffffff'};
    }}
    
    QTableView::item {{
        padding: 8px;
        border-bottom: 1px solid {line};
    }}
    
    QTableView::item:selected {{
        background: {accent};
    }}
    
    QHeaderView::section {{
        background: {panel2};
        border: none;
        border-bottom: 2px solid {line};
        border-right: 1px solid {line};
        padding: 10px;
        font-weight: 600;
        color: {text};
    }}
    
    QHeaderView::section:last {{
        border-right: none;
    }}

    /* Lists */
    QListView {{
        background: {panel};
        border: 1px solid {line};
        border-radius: 12px;
        outline: none;
    }}
    
    QListView::item {{
        padding: 8px 12px;
        border-radius: 8px;
        margin: 2px 4px;
    }}
    
    QListView::item:selected {{
        background: {accent};
        color: {'#0a0b0f' if theme.is_dark else '#ffffff'};
    }}
    
    QListView::item:hover {{
        background: {_interpolate_color(panel, accent, 0.1)};
    }}

    /* Progress bars */
    QProgressBar {{
        border: 1px solid {line};
        border-radius: 8px;
        text-align: center;
        background: {panel2};
        height: 12px;
    }}
    
    QProgressBar::chunk {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {accent}, stop:1 {accent2});
        border-radius: 6px;
    }}

    /* Sliders */
    QSlider::groove:horizontal {{
        height: 6px;
        background: {line};
        border-radius: 3px;
    }}
    
    QSlider::handle:horizontal {{
        background: {accent};
        width: 18px;
        height: 18px;
        margin: -6px 0;
        border-radius: 9px;
        border: 2px solid {panel};
    }}
    
    QSlider::handle:horizontal:hover {{
        background: {accent2};
        border: 2px solid {accent};
    }}
    
    QSlider::sub-page:horizontal {{
        background: {accent};
        border-radius: 3px;
    }}

    /* Tabs */
    QTabWidget::pane {{
        border: 1px solid {line};
        border-radius: 12px;
        background: {panel};
        top: -1px;
    }}
    
    QTabBar::tab {{
        background: {panel2};
        border: 1px solid {line};
        border-bottom: none;
        border-top-left-radius: 8px;
        border-top-right-radius: 8px;
        padding: 10px 20px;
        margin-right: 2px;
    }}
    
    QTabBar::tab:selected {{
        background: {panel};
        border-bottom: 2px solid {accent};
    }}
    
    QTabBar::tab:hover {{
        background: {_adjust_brightness(panel2, 1.1 if theme.is_dark else 0.95)};
    }}

    /* Group boxes */
    QGroupBox {{
        background: {panel};
        border: 1px solid {line};
        border-radius: 12px;
        margin-top: 12px;
        padding-top: 12px;
        font-weight: 600;
        color: {text};
    }}
    
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 12px;
        padding: 0 8px;
        color: {accent};
    }}

    /* Splitter */
    QSplitter::handle {{
        background: {line};
        width: 4px;
        height: 4px;
    }}
    QSplitter::handle:hover {{
        background: {accent};
    }}

    /* Checkboxes and Radio buttons */
    QCheckBox, QRadioButton {{
        spacing: 8px;
    }}
    
    QCheckBox::indicator, QRadioButton::indicator {{
        width: 18px;
        height: 18px;
        border-radius: 4px;
        border: 2px solid {line};
        background: {panel2};
    }}
    
    QRadioButton::indicator {{
        border-radius: 9px;
    }}
    
    QCheckBox::indicator:checked {{
        background: {accent};
        border-color: {accent};
        image: url(data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIxMiIgaGVpZ2h0PSIxMiIgdmlld0JveD0iMCAwIDI0IDI0IiBmaWxsPSJub25lIiBzdHJva2U9IiMwYTBiMGYiIHN0cm9rZS13aWR0aD0iMyIgc3Ryb2tlLWxpbmVjYXA9InJvdW5kIiBzdHJva2UtbGluZWpvaW49InJvdW5kIj48cG9seWxpbmUgcG9pbnRzPSIyMCA2IDkgMTcgNCAxMiI+PC9wb2x5bGluZT48L3N2Zz4=);
    }}
    
    QRadioButton::indicator:checked {{
        background: {accent};
        border-color: {accent};
    }}

    /* Menu styling */
    QMenu {{
        background: {panel};
        border: 1px solid {line};
        border-radius: 8px;
        padding: 6px;
    }}
    
    QMenu::item {{
        padding: 8px 24px;
        border-radius: 6px;
    }}
    
    QMenu::item:selected {{
        background: {accent};
        color: {'#0a0b0f' if theme.is_dark else '#ffffff'};
    }}
    
    QMenu::separator {{
        height: 1px;
        background: {line};
        margin: 6px 12px;
    }}

    /* Utility classes */
    .accent {{ color: {accent}; }}
    .accent2 {{ color: {accent2}; }}
    .danger {{ color: {danger}; }}
    .ok {{ color: {ok}; }}
    .muted {{ color: {muted}; }}
    .text-secondary {{ color: {muted}; }}
    
    /* Animations */
    .fade-in {{
        animation: fadeIn 300ms ease-in;
    }}
    
    @keyframes fadeIn {{
        from {{ opacity: 0; }}
        to {{ opacity: 1; }}
    }}
    """
    
    return base_styles


# =============================================================================
# Built-in Themes
# =============================================================================

def _builtin_themes() -> Dict[str, ThemeSpec]:
    """Generate all built-in themes with curated palettes."""

    def t(
        key: str, name: str, tagline: str,
        bg: str, panel: str, panel2: str, line: str,
        accent: str, accent2: str,
        is_dark: bool,
        category: str = "Studio",
        tags: tuple = (),
        text: str = "", muted: str = "",
    ) -> ThemeSpec:
        pal = {
            "bg": bg,
            "panel": panel,
            "panel2": panel2,
            "text": text or ("#e4e9f1" if is_dark else "#101828"),
            "muted": muted or ("#8b95a8" if is_dark else "#526280"),
            "accent": accent,
            "accent2": accent2,
            "line": line,
            "danger": "#ff5c7c",
            "ok": "#4ade80",
        }
        return ThemeSpec(
            key=key, name=name, tagline=tagline,
            palette=pal, qss="", is_dark=is_dark, glass_morphism=True,
            category=category, tags=tags,
        )

    themes = {
        # ── Studio ────────────────────────────────────────────────
        "gemini": t(
            "gemini", "Gemini", "The default Cerebro experience",
            bg="#0f1115", panel="#161b24", panel2="#0b0e13", line="#232a38",
            accent="#00c4b4", accent2="#5eead4",
            is_dark=True, category="Studio", tags=("Dark", "Studio"),
        ),
        "gemini_light": t(
            "gemini_light", "Gemini Light", "Clean, bright, production-ready",
            bg="#f1f5f4", panel="#ffffff", panel2="#e8edec", line="#c8d5d2",
            accent="#00a99d", accent2="#5eead4",
            is_dark=False, category="Studio", tags=("Light", "Studio"),
        ),
        "dark": t(
            "dark", "Midnight", "Late-night clarity",
            bg="#0f1115", panel="#161b24", panel2="#0b0e13", line="#232a38",
            accent="#7aa2ff", accent2="#a78bfa",
            is_dark=True, category="Studio", tags=("Dark", "Studio"),
        ),
        "light": t(
            "light", "Daylight", "Bright and focused",
            bg="#f5f7fa", panel="#ffffff", panel2="#eaf0f6", line="#cdd5e0",
            accent="#2563eb", accent2="#7c3aed",
            is_dark=False, category="Studio", tags=("Light", "Studio"),
        ),
        "cobalt_suit": t(
            "cobalt_suit", "Cobalt", "Refined corporate edge",
            bg="#0c1022", panel="#111832", panel2="#090d1a", line="#1e2845",
            accent="#3b82f6", accent2="#a78bfa",
            is_dark=True, category="Studio", tags=("Dark", "Studio", "Cool"),
        ),
        "graphite_mint": t(
            "graphite_mint", "Graphite Mint", "Business casual elegance",
            bg="#0f1115", panel="#171c24", panel2="#0b0e13", line="#232a38",
            accent="#2dd4bf", accent2="#99f6e4",
            is_dark=True, category="Studio", tags=("Dark", "Studio"),
        ),
        "royal_ink": t(
            "royal_ink", "Royal Ink", "Indigo meets electric cyan",
            bg="#0d1018", panel="#14192c", panel2="#0a0d14", line="#1e2540",
            accent="#818cf8", accent2="#22d3ee",
            is_dark=True, category="Studio", tags=("Dark", "Studio"),
        ),

        # ── Neon ──────────────────────────────────────────────────
        "neon_void": t(
            "neon_void", "Neon Void", "Pure glow on black",
            bg="#08080e", panel="#0e1018", panel2="#060608", line="#181c2a",
            accent="#22d3ee", accent2="#a78bfa",
            is_dark=True, category="Neon", tags=("Dark", "Neon"),
        ),
        "laser_lilac": t(
            "laser_lilac", "Laser Lilac", "Violet beams, soft landing",
            bg="#0c0b12", panel="#141220", panel2="#0a0910", line="#1e1a32",
            accent="#c084fc", accent2="#60a5fa",
            is_dark=True, category="Neon", tags=("Dark", "Neon"),
        ),
        "sakura_overdrive": t(
            "sakura_overdrive", "Sakura Drive", "Pink neon, purple echoes",
            bg="#10090e", panel="#1a1018", panel2="#0c080a", line="#2a1828",
            accent="#fb7185", accent2="#c084fc",
            is_dark=True, category="Neon", tags=("Dark", "Neon"),
        ),
        "lime_lab": t(
            "lime_lab", "Lime Lab", "High-energy phosphor green",
            bg="#0a100c", panel="#101a12", panel2="#080c08", line="#1a2a18",
            accent="#a3e635", accent2="#22c55e",
            is_dark=True, category="Neon", tags=("Dark", "Neon", "Nature"),
        ),

        # ── Warm ──────────────────────────────────────────────────
        "coal_cinnamon": t(
            "coal_cinnamon", "Coal & Cinnamon", "Dark warmth, amber glow",
            bg="#111012", panel="#1a181c", panel2="#0c0b0d", line="#2a262e",
            accent="#fb923c", accent2="#f472b6",
            is_dark=True, category="Warm", tags=("Dark", "Warm"),
        ),
        "amber_archive": t(
            "amber_archive", "Amber Archive", "Golden tones, warm focus",
            bg="#12100c", panel="#1c1810", panel2="#0d0b08", line="#2a2418",
            accent="#fbbf24", accent2="#fb923c",
            is_dark=True, category="Warm", tags=("Dark", "Warm"),
        ),
        "blood_moon": t(
            "blood_moon", "Blood Moon", "Dramatic red-orange dusk",
            bg="#110a0c", panel="#1c1014", panel2="#0c0808", line="#2c1820",
            accent="#fb7185", accent2="#f97316",
            is_dark=True, category="Warm", tags=("Dark", "Warm"),
        ),
        "hacker_sunrise": t(
            "hacker_sunrise", "Hacker Sunrise", "Orange dawn meets cyan sky",
            bg="#0d0e0c", panel="#161a12", panel2="#0a0c08", line="#222818",
            accent="#f97316", accent2="#22d3ee",
            is_dark=True, category="Warm", tags=("Dark", "Warm"),
        ),
        "desert_ui": t(
            "desert_ui", "Desert UI", "Sand-gold with sky-blue accents",
            bg="#13110c", panel="#1e1a12", panel2="#0e0c08", line="#2a2418",
            accent="#fbbf24", accent2="#60a5fa",
            is_dark=True, category="Warm", tags=("Dark", "Warm"),
        ),
        "noir_peach": t(
            "noir_peach", "Noir Peach", "Rose softness on dark canvas",
            bg="#100e12", panel="#1a1820", panel2="#0c0a0e", line="#26222c",
            accent="#fb7185", accent2="#fbbf24",
            is_dark=True, category="Warm", tags=("Dark", "Warm"),
        ),

        # ── Cool ──────────────────────────────────────────────────
        "arctic_byte": t(
            "arctic_byte", "Arctic Byte", "Frost-blue precision",
            bg="#0c1018", panel="#111a26", panel2="#080c12", line="#1a2438",
            accent="#60a5fa", accent2="#22d3ee",
            is_dark=True, category="Cool", tags=("Dark", "Cool"),
        ),
        "deep_ocean": t(
            "deep_ocean", "Deep Ocean", "Calm navy, sea-green highlights",
            bg="#081018", panel="#0e1a28", panel2="#060c12", line="#162438",
            accent="#38bdf8", accent2="#34d399",
            is_dark=True, category="Cool", tags=("Dark", "Cool"),
        ),
        "violet_vault": t(
            "violet_vault", "Violet Vault", "Deep plum with rose sparks",
            bg="#0e0a14", panel="#161028", panel2="#0a0810", line="#201838",
            accent="#a78bfa", accent2="#fb7185",
            is_dark=True, category="Cool", tags=("Dark", "Cool"),
        ),

        # ── Nature ────────────────────────────────────────────────
        "emerald_ritual": t(
            "emerald_ritual", "Emerald Ritual", "Lush green, cyan shimmer",
            bg="#0c1210", panel="#101c18", panel2="#080e0c", line="#182a22",
            accent="#34d399", accent2="#22d3ee",
            is_dark=True, category="Nature", tags=("Dark", "Nature"),
        ),
        "forest_law": t(
            "forest_law", "Forest Law", "Deep evergreen, sky accent",
            bg="#081210", panel="#0e1c14", panel2="#060e0a", line="#142a1c",
            accent="#22c55e", accent2="#38bdf8",
            is_dark=True, category="Nature", tags=("Dark", "Nature"),
        ),
        "mint_terminal": t(
            "mint_terminal", "Mint Terminal", "Retro-fresh CRT vibes",
            bg="#0c1210", panel="#101c16", panel2="#080e0c", line="#182a20",
            accent="#4ade80", accent2="#a7f3d0",
            is_dark=True, category="Nature", tags=("Dark", "Nature"),
        ),

        # ── Light ─────────────────────────────────────────────────
        "paperwork": t(
            "paperwork", "Paperwork", "Clean daylight with blue ink",
            bg="#f5f3f0", panel="#ffffff", panel2="#ebe7e2", line="#d2ccc4",
            accent="#0ea5e9", accent2="#7c3aed",
            is_dark=False, category="Studio", tags=("Light", "Studio"),
        ),
        "ice_cream": t(
            "ice_cream", "Ice Cream", "Soft pastels, sweet contrast",
            bg="#f2f6ff", panel="#ffffff", panel2="#e6ecf8", line="#c8d2e4",
            accent="#60a5fa", accent2="#fb7185",
            is_dark=False, category="Studio", tags=("Light", "Studio"),
        ),
    }
    return themes


# =============================================================================
# JSON Loading
# =============================================================================

def _load_theme_json(path: Path) -> Optional[ThemeSpec]:
    """Load theme from JSON file with validation."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        
        # Validate required fields
        key = str(data.get("key") or path.stem).strip()
        name = str(data.get("name") or key).strip()
        tagline = str(data.get("tagline") or "").strip()
        pal = dict(data.get("palette") or {})
        is_dark = bool(data.get("is_dark", True))
        glass = bool(data.get("glass_morphism", True))
        qss = str(data.get("qss") or "")
        
        # Normalize palette
        pal_norm = {}
        required_keys = ("bg", "panel", "panel2", "text", "muted", 
                        "accent", "accent2", "line", "danger", "ok")
        for k in required_keys:
            if k in pal:
                pal_norm[k] = _safe_hex(str(pal[k]), "#0f1115" if k == "bg" else "#7aa2ff")
        
        category = str(data.get("category") or "Studio").strip()
        raw_tags = data.get("tags") or []
        tags = tuple(str(t) for t in raw_tags) if isinstance(raw_tags, list) else ()

        return ThemeSpec(
            key=key, name=name, tagline=tagline, 
            palette=pal_norm, qss=qss, is_dark=is_dark, glass_morphism=glass,
            category=category, tags=tags,
        )
    except Exception as e:
        print(f"[ThemeEngine] Failed to load theme from {path}: {e}")
        return None


def _save_theme_json(path: Path, theme: ThemeSpec) -> bool:
    """Save theme to JSON file."""
    try:
        path.write_text(json.dumps(theme.to_dict(), indent=2), encoding="utf-8")
        return True
    except Exception as e:
        print(f"[ThemeEngine] Failed to save theme to {path}: {e}")
        return False


# =============================================================================
# Main Theme Engine
# =============================================================================

class ThemeEngine(QObject):
    """
    Enhanced theme engine with glassmorphism support and dynamic gradients.
    """
    theme_previewed = Signal(str)
    theme_applied = Signal(str)
    theme_loaded = Signal(str)  # New: emitted when theme is loaded from disk
    
    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._themes: Dict[str, ThemeSpec] = {}
        self._current: str = "gemini"
        self._preview: Optional[str] = None
        self._animation_enabled: bool = True
        
        self.ensure_themes_seeded()
        self.reload()

    # -------------------------------------------------------------------------
    # Theme Management
    # -------------------------------------------------------------------------
    
    def ensure_themes_seeded(self) -> None:
        """Ensure themes directory exists."""
        try:
            _themes_dir().mkdir(parents=True, exist_ok=True)
        except Exception as e:
            print(f"[ThemeEngine] Failed to create themes dir: {e}")

    def reload(self) -> None:
        """Reload all themes from built-in and disk."""
        themes: Dict[str, ThemeSpec] = dict(_builtin_themes())
        tdir = _themes_dir()
        
        # Load custom themes from disk
        try:
            if tdir.exists():
                for p in tdir.glob("*.json"):
                    spec = _load_theme_json(p)
                    if spec and spec.key:
                        themes[spec.key] = spec
                        self.theme_loaded.emit(spec.key)
        except Exception as e:
            print(f"[ThemeEngine] Error loading custom themes: {e}")

        self._themes = themes
        
        # Restore saved theme or default to Gemini
        restored = self._load_theme_from_config()
        if restored and restored in self._themes:
            self._current = restored
        else:
            if self._current not in self._themes:
                self._current = "gemini"

        self._apply_to_app(self._themes[self._current])

    def list_themes(self) -> List[ThemeSpec]:
        """Get list of all available themes."""
        return list(self._themes.values())
    
    def list_theme_keys(self) -> List[str]:
        """Get list of theme keys."""
        return list(self._themes.keys())

    def get_theme(self, key: str) -> Optional[ThemeSpec]:
        """Get theme by key."""
        return self._themes.get(key)

    @property
    def current_theme_key(self) -> str:
        """Get current theme key."""
        return self._current
    
    @property
    def current_theme(self) -> Optional[ThemeSpec]:
        """Get current theme spec."""
        return self._themes.get(self._current)

    def has_theme(self, key: str) -> bool:
        """Check if theme exists."""
        return key in self._themes

    # -------------------------------------------------------------------------
    # Theme Application
    # -------------------------------------------------------------------------
    
    def preview_theme(self, key: str) -> bool:
        """Preview a theme without saving."""
        if key not in self._themes:
            return False
        self._preview = key
        self._apply_to_app(self._themes[key])
        self.theme_previewed.emit(key)
        return True

    def apply_theme(self, key: str) -> bool:
        """Apply and save a theme."""
        if key not in self._themes:
            return False
        self._current = key
        self._preview = None
        self._apply_to_app(self._themes[key])
        self._save_theme_to_config(key)
        self.theme_applied.emit(key)
        return True

    def cancel_preview(self) -> None:
        """Cancel preview and revert to current theme."""
        self._preview = None
        if self._current in self._themes:
            self._apply_to_app(self._themes[self._current])

    def _apply_to_app(self, theme: ThemeSpec) -> None:
        """Apply theme to QApplication."""
        app = QApplication.instance()
        if not app:
            return
        
        # Apply palette
        app.setPalette(_mk_palette(theme))
        
        # Generate and apply QSS
        qss = _base_qss(theme)
        if theme.qss:
            qss = qss + "\n" + theme.qss
        
        app.setStyleSheet(qss)
        
        # Force style refresh
        app.setStyle(app.style())

    # -------------------------------------------------------------------------
    # Color Utilities (Backward Compatibility)
    # -------------------------------------------------------------------------
    
    def get_colors(self) -> Dict[str, str]:
        """
        Get current theme colors for backward compatibility.
        Maps theme palette to expected color keys.
        """
        theme = self.get_theme(self._current)
        if not theme:
            # Return default dark theme colors
            return self._default_colors()
        
        palette = theme.palette
        return {
            # Direct mappings
            "background": palette.get("bg", "#0f1115"),
            "bg": palette.get("bg", "#0f1115"),
            "card_bg": palette.get("panel", "#151922"),
            "panel": palette.get("panel", "#151922"),
            "panel2": palette.get("panel2", "#0b0e13"),
            "border": palette.get("line", "rgba(120,140,180,0.2)"),
            "line": palette.get("line", "#262c3a"),
            "text_primary": palette.get("text", "#e7ecf2"),
            "text": palette.get("text", "#e7ecf2"),
            "text_secondary": palette.get("muted", "#aab3c0"),
            "muted": palette.get("muted", "#aab3c0"),
            "accent": palette.get("accent", "#7aa2ff"),
            "accent2": palette.get("accent2", "#a78bfa"),
            "danger": palette.get("danger", "#ff5c7c"),
            "ok": palette.get("ok", "#4ade80"),
            # Computed values
            "hover_bg": f"rgba({_hex_to_rgb(palette.get('accent', '#7aa2ff'))[0]}, "
                       f"{_hex_to_rgb(palette.get('accent', '#7aa2ff'))[1]}, "
                       f"{_hex_to_rgb(palette.get('accent', '#7aa2ff'))[2]}, 0.15)",
            "glass_bg": _generate_glass_gradient(
                palette.get("bg", "#0f1115"),
                palette.get("panel", "#151922"),
                theme.is_dark
            ),
            "is_dark": str(theme.is_dark).lower(),
        }
    
    def _default_colors(self) -> Dict[str, str]:
        """Return default dark theme colors."""
        return {
            "background": "#0f1115",
            "bg": "#0f1115",
            "card_bg": "#151922",
            "panel": "#151922",
            "panel2": "#0b0e13",
            "border": "rgba(120,140,180,0.2)",
            "line": "#262c3a",
            "text_primary": "#e7ecf2",
            "text": "#e7ecf2",
            "text_secondary": "#aab3c0",
            "muted": "#aab3c0",
            "accent": "#7aa2ff",
            "accent2": "#a78bfa",
            "danger": "#ff5c7c",
            "ok": "#4ade80",
            "hover_bg": "rgba(122, 162, 255, 0.15)",
            "glass_bg": "rgba(15, 17, 21, 0.95)",
            "is_dark": "true",
        }

    def get_color(self, key: str, fallback: str = "#7aa2ff") -> str:
        """Get specific color by key."""
        colors = self.get_colors()
        return colors.get(key, fallback)

    def interpolate_theme(self, theme1_key: str, theme2_key: str, factor: float) -> ThemeSpec:
        """
        Create an interpolated theme between two themes.
        factor: 0.0 = theme1, 1.0 = theme2
        """
        t1 = self._themes.get(theme1_key)
        t2 = self._themes.get(theme2_key)
        
        if not t1 or not t2:
            raise ValueError("Theme not found")
        
        new_palette = {}
        for k in t1.palette:
            c1 = t1.palette.get(k, "#0f1115")
            c2 = t2.palette.get(k, "#0f1115")
            new_palette[k] = _interpolate_color(c1, c2, factor)
        
        return ThemeSpec(
            key=f"interpolated_{theme1_key}_{theme2_key}",
            name=f"Blend: {t1.name} + {t2.name}",
            tagline="Dynamic blend",
            palette=new_palette,
            qss="",
            is_dark=t1.is_dark if factor < 0.5 else t2.is_dark
        )

    # -------------------------------------------------------------------------
    # Dynamic Theme Generation
    # -------------------------------------------------------------------------
    
    def generate_gradient_theme(self, name: str, colors: List[str], 
                               is_dark: bool = True) -> ThemeSpec:
        """Generate a theme from a list of gradient colors."""
        if len(colors) < 2:
            raise ValueError("Need at least 2 colors for gradient theme")
        
        bg = colors[0]
        panel = _interpolate_color(colors[0], colors[1], 0.3)
        accent = colors[-1]
        accent2 = colors[-2] if len(colors) > 2 else _adjust_brightness(accent, 1.2)
        
        # Generate text colors based on brightness
        bg_lum = sum(_hex_to_rgb(bg)) / 3
        text = "#e7ecf2" if bg_lum < 128 else "#0d1320"
        muted = "#aab3c0" if bg_lum < 128 else "#455067"
        
        palette = {
            "bg": bg,
            "panel": panel,
            "panel2": _interpolate_color(bg, panel, 0.5),
            "text": text,
            "muted": muted,
            "accent": accent,
            "accent2": accent2,
            "line": _interpolate_color(bg, text, 0.2),
            "danger": "#ff5c7c",
            "ok": "#4ade80",
        }
        
        return ThemeSpec(
            key=f"gradient_{name.lower().replace(' ', '_')}",
            name=name,
            tagline=f"Dynamic gradient theme with {len(colors)} colors",
            palette=palette,
            qss="",
            is_dark=is_dark
        )

    def save_custom_theme(self, theme: ThemeSpec) -> bool:
        """Save a custom theme to disk."""
        path = _themes_dir() / f"{theme.key}.json"
        return _save_theme_json(path, theme)

    def delete_custom_theme(self, key: str) -> bool:
        """Delete a custom theme from disk."""
        if key in _builtin_themes():
            return False  # Can't delete built-in
        
        path = _themes_dir() / f"{key}.json"
        try:
            if path.exists():
                path.unlink()
                self.reload()
                return True
        except Exception as e:
            print(f"[ThemeEngine] Failed to delete theme {key}: {e}")
        return False

    # -------------------------------------------------------------------------
    # Configuration Persistence
    # -------------------------------------------------------------------------
    
    def _load_theme_from_config(self) -> Optional[str]:
        """Load saved theme from config."""
        try:
            from cerebro.services.config import load_config
            cfg = load_config()
            ui = getattr(cfg, "ui", None)
            if ui is None:
                return None
            theme = getattr(ui, "theme", None)
            if isinstance(theme, str) and theme:
                return theme
        except Exception:
            pass
        return None

    def _save_theme_to_config(self, key: str) -> None:
        """Save theme to config."""
        try:
            from cerebro.services.config import load_config, save_config
            cfg = load_config()
            ui = getattr(cfg, "ui", None)
            if ui is not None and hasattr(ui, "theme"):
                ui.theme = str(key)
                save_config(cfg)
        except Exception:
            pass


# =============================================================================
# Backward Compatibility: ThemeManager + ThemeMixin
# =============================================================================

class ThemeManager(ThemeEngine):
    """
    Backward-compatible ThemeManager that extends ThemeEngine.
    Maintains all legacy functionality while adding new features.
    """
    theme_changed = Signal(str)  # Legacy signal name

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        # Connect new signal to legacy signal
        self.theme_applied.connect(self.theme_changed.emit)

    def set_theme(self, key: str) -> bool:
        """Legacy method to set theme."""
        return self.apply_theme(key)
    
    def get_current_theme(self) -> Optional[ThemeSpec]:
        """Legacy method to get current theme."""
        return self.current_theme
    
    def get_theme_names(self) -> List[str]:
        """Legacy method to get theme names."""
        return [t.name for t in self.list_themes()]


class ThemeMixin:
    """
    Compatibility mixin for widgets.
    Provides hooks for theme change notifications.
    """
    def __init__(self):
        self._theme_engine: Optional[ThemeEngine] = None
    
    def set_theme_engine(self, engine: ThemeEngine) -> None:
        """Set theme engine reference."""
        self._theme_engine = engine
        if engine:
            engine.theme_applied.connect(self._on_theme_changed)
    
    def _on_theme_changed(self, theme_key: str) -> None:
        """Override this method to handle theme changes."""
        self.apply_theme()
    
    def apply_theme(self) -> None:
        """
        Apply current theme to widget.
        Override in subclasses for custom styling.
        """
        pass
    
    def get_theme_colors(self) -> Dict[str, str]:
        """Get current theme colors."""
        if self._theme_engine:
            return self._theme_engine.get_colors()
        return {}


# =============================================================================
# Singleton Pattern
# =============================================================================

_THEME_SINGLETON: Optional[ThemeManager] = None


def get_theme_manager() -> ThemeManager:
    """Get or create the global theme manager singleton."""
    global _THEME_SINGLETON
    if _THEME_SINGLETON is None:
        _THEME_SINGLETON = ThemeManager()
    return _THEME_SINGLETON


def reset_theme_manager() -> None:
    """Reset the singleton (useful for testing)."""
    global _THEME_SINGLETON
    _THEME_SINGLETON = None


# =============================================================================
# Quick Access Functions
# =============================================================================

def current_colors() -> Dict[str, str]:
    """Quick access to current theme colors."""
    return get_theme_manager().get_colors()


def apply_theme(key: str) -> bool:
    """Quick apply theme by key."""
    return get_theme_manager().apply_theme(key)


# Export all public symbols
__all__ = [
    'ThemeEngine', 'ThemeManager', 'ThemeMixin', 'ThemeSpec', 'GradientSpec',
    'get_theme_manager', 'reset_theme_manager', 'current_colors', 'apply_theme',
    '_interpolate_color', '_adjust_brightness', '_hex_to_rgb', '_rgb_to_hex'
]
