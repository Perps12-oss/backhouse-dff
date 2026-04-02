# cerebro/ui/theme_bridge_v1.py
"""
V1 Theme Bridge — connects ThemeEngineV3 to the PySide6 UI.

Translates the 80-slot semantic token system into the formats the v1 UI needs:
  - 10-key legacy palette dict (for backward compat with current_colors())
  - Full QSS stylesheet string (for setStyleSheet on QApplication)
  - QPalette (for Qt widget color roles)

This bridge does NOT replace ThemeEngine. It wraps and extends it:
  - ThemeEngineV3 resolves the 80 semantic slots from JSON themes
  - This bridge translates those resolved slots into v1-compatible formats
  - The existing ThemeEngine._apply_to_app() still applies the QSS
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

# Legacy key → new semantic slot mapping.
# Every old token("bg") call maps to token("base.background"), etc.
LEGACY_KEY_MAP: Dict[str, str] = {
    # Direct palette mappings (from ThemeSpec.palette keys)
    "bg":                  "base.background",
    "background":          "base.background",
    "panel":               "panel.background",
    "panel2":              "base.backgroundSecondary",
    "card_bg":             "base.backgroundElevated",
    "text":                "base.foreground",
    "text_primary":        "base.foreground",
    "muted":               "base.foregroundSecondary",
    "text_secondary":      "base.foregroundSecondary",
    "accent":              "base.accent",
    "accent2":             "base.accentHover",
    "line":                "base.border",
    "border":              "base.border",
    "danger":              "feedback.danger",
    "ok":                  "feedback.success",
    "warning":             "feedback.warning",
    "info":                "feedback.info",
    # Computed/special values from get_colors()
    "hover_bg":            "base.backgroundTertiary",
    "glass_bg":            "base.background",
}


def resolve_legacy_key(engine: Any, key: str, fallback: str = "#7aa2ff") -> str:
    """Resolve an old-style palette key through the v3 engine.

    First checks the LEGACY_KEY_MAP for a semantic slot mapping.
    If not found, tries the key directly as a v3 slot name.
    """
    semantic = LEGACY_KEY_MAP.get(key)
    if semantic:
        return engine.get_color(semantic, fallback)
    # Maybe it's already a semantic key (e.g. "base.background")
    return engine.get_color(key, fallback)


def build_legacy_colors(engine: Any) -> Dict[str, str]:
    """Build the legacy 17-key color dict that current_colors() returns.

    This is what _tokens._colors() currently returns. By producing the same
    keys from ThemeEngineV3, every existing token() call keeps working.
    """
    g = engine.get_color
    theme_type = engine.get_theme_metadata(engine.active_theme_name).get("type", "dark")

    colors: Dict[str, str] = {
        # Direct mappings
        "background":          g("base.background"),
        "bg":                  g("base.background"),
        "card_bg":             g("base.backgroundElevated"),
        "panel":               g("panel.background"),
        "panel2":              g("base.backgroundSecondary"),
        "border":              g("base.border"),
        "line":                g("base.border"),
        "text_primary":        g("base.foreground"),
        "text":                g("base.foreground"),
        "text_secondary":      g("base.foregroundSecondary"),
        "muted":               g("base.foregroundSecondary"),
        "accent":              g("base.accent"),
        "accent2":             g("base.accentHover"),
        "danger":              g("feedback.danger"),
        "ok":                  g("feedback.success"),
        "warning":             g("feedback.warning"),
        "info":                g("feedback.info"),
        # Computed
        "hover_bg":            g("base.backgroundTertiary"),
        "glass_bg":            g("base.background"),
        "is_dark":             "true" if theme_type == "dark" else "false",
    }

    return colors


def build_theme_spec_palette(engine: Any) -> Dict[str, str]:
    """Build the 10-key palette dict that ThemeSpec expects.

    This is used to construct a ThemeSpec for the existing ThemeEngine.
    """
    g = engine.get_color

    return {
        "bg":      g("base.background"),
        "panel":   g("panel.background"),
        "panel2":  g("base.backgroundSecondary"),
        "text":    g("base.foreground"),
        "muted":   g("base.foregroundSecondary"),
        "accent":  g("base.accent"),
        "accent2": g("base.accentHover"),
        "line":    g("base.border"),
        "danger":  g("feedback.danger"),
        "ok":      g("feedback.success"),
    }


def generate_v3_qss(engine: Any) -> str:
    """Generate a comprehensive QSS stylesheet from all 80 resolved slots.

    This replaces the old _base_qss(theme) with per-zone semantic control.
    The existing _base_qss() used only 10 palette keys; this uses all 80.
    """
    g = engine.get_color
    meta = engine.get_theme_metadata(engine.active_theme_name)
    is_dark = meta.get("type", "dark") == "dark"
    text_on_accent = "#0a0b0f" if is_dark else "#ffffff"

    return f"""
    * {{
        font-family: "Segoe UI", "Microsoft YaHei", sans-serif;
        color: {g("base.foreground")};
        outline: none;
    }}

    QMainWindow {{
        background: {g("base.background")};
    }}

    QWidget {{
        background: transparent;
    }}

    /* ──── Tooltips ──── */
    QToolTip {{
        background: {g("dialog.background")};
        color: {g("dialog.foreground")};
        border: 1px solid {g("dialog.border")};
        padding: 8px;
        border-radius: 8px;
        font-size: 12px;
    }}

    /* ──── Glass morphism panels (legacy compat) ──── */
    .glass-panel {{
        background: {g("panel.background")};
        border: 1px solid {g("panel.border")};
        border-radius: 16px;
        padding: 16px;
    }}

    .glass-card {{
        background: {g("base.backgroundElevated")};
        border: 1px solid {g("base.border")};
        border-radius: 12px;
        padding: 12px;
    }}

    /* ──── Inputs ──── */
    QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
        background: {g("input.background")};
        border: 1px solid {g("input.border")};
        border-radius: 10px;
        padding: 8px 12px;
        color: {g("input.foreground")};
        selection-background-color: {g("base.accent")};
        selection-color: {text_on_accent};
    }}

    QLineEdit:hover, QTextEdit:hover, QPlainTextEdit:hover, QComboBox:hover {{
        border: 1px solid {g("base.accent")};
        background: {g("base.backgroundTertiary")};
    }}

    QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus {{
        border: 1px solid {g("input.borderFocus")};
        background: {g("input.background")};
    }}

    QComboBox::drop-down {{
        border: none;
        width: 24px;
    }}

    QComboBox::down-arrow {{
        image: none;
        border-left: 5px solid transparent;
        border-right: 5px solid transparent;
        border-top: 6px solid {g("base.foregroundSecondary")};
    }}

    QComboBox::down-arrow:on {{
        border-top: none;
        border-bottom: 6px solid {g("base.accent")};
    }}

    QComboBox QAbstractItemView {{
        background: {g("input.background")};
        border: 1px solid {g("input.border")};
        border-radius: 8px;
        selection-background-color: {g("base.accent")};
        padding: 4px;
    }}

    /* ──── Buttons ──── */
    QPushButton {{
        background: {g("button.secondary")};
        border: 1px solid {g("button.secondaryBorder")};
        border-radius: 12px;
        padding: 10px 16px;
        font-weight: 500;
        color: {g("button.secondaryForeground")};
    }}

    QPushButton:hover {{
        border: 1px solid {g("base.accent")};
        background: {g("button.secondaryHover")};
    }}

    QPushButton:pressed {{
        background: {g("base.backgroundSecondary")};
        border: 1px solid {g("base.accentHover")};
    }}

    QPushButton:disabled {{
        color: {g("base.foregroundMuted")};
        border-color: {g("base.border")};
        background: {g("base.backgroundSecondary")};
    }}

    QPushButton.accent {{
        background: {g("button.primary")};
        color: {g("button.primaryForeground")};
        border: none;
    }}

    QPushButton.accent:hover {{
        background: {g("button.primaryHover")};
        border: none;
    }}

    QPushButton.danger {{
        background: {g("button.danger")};
        color: {g("button.dangerForeground")};
        border: none;
    }}

    QPushButton.success {{
        background: {g("feedback.success")};
        color: #0a0b0f;
        border: none;
    }}

    /* ──── Scrollbars ──── */
    QScrollBar:vertical {{
        background: transparent;
        width: 12px;
        margin: 2px;
        border-radius: 6px;
    }}

    QScrollBar::handle:vertical {{
        background: {g("base.border")};
        border-radius: 6px;
        min-height: 24px;
        margin: 2px;
    }}

    QScrollBar::handle:vertical:hover {{
        background: {g("base.accent")};
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
        background: {g("base.border")};
        border-radius: 6px;
        min-width: 24px;
        margin: 2px;
    }}

    QScrollBar::handle:horizontal:hover {{
        background: {g("base.accent")};
    }}

    /* ──── Tables ──── */
    QTableView {{
        background: {g("results.background")};
        alternate-background-color: {g("results.rowOdd")};
        gridline-color: {g("base.border")};
        border: 1px solid {g("base.border")};
        border-radius: 12px;
        selection-background-color: {g("results.rowSelected")};
        selection-color: {g("results.foreground")};
    }}

    QTableView::item {{
        padding: 8px;
        border-bottom: 1px solid {g("base.border")};
    }}

    QTableView::item:selected {{
        background: {g("results.rowSelected")};
    }}

    QHeaderView::section {{
        background: {g("results.headerBackground")};
        border: none;
        border-bottom: 2px solid {g("base.border")};
        border-right: 1px solid {g("base.border")};
        padding: 10px;
        font-weight: 600;
        color: {g("results.headerForeground")};
    }}

    QHeaderView::section:last {{
        border-right: none;
    }}

    /* ──── Tree views ──── */
    QTreeView {{
        background: {g("results.background")};
        alternate-background-color: {g("results.rowOdd")};
        border: 1px solid {g("base.border")};
        border-radius: 12px;
        selection-background-color: {g("results.rowSelected")};
        selection-color: {g("results.foreground")};
        color: {g("results.foreground")};
    }}

    QTreeView::item {{
        padding: 6px 8px;
        border-bottom: 1px solid {g("base.border")};
    }}

    QTreeView::item:hover {{
        background: {g("results.rowHover")};
    }}

    QTreeView::item:selected {{
        background: {g("results.rowSelected")};
    }}

    /* ──── Lists ──── */
    QListView {{
        background: {g("base.backgroundSecondary")};
        border: 1px solid {g("base.border")};
        border-radius: 12px;
        outline: none;
    }}

    QListView::item {{
        padding: 8px 12px;
        border-radius: 8px;
        margin: 2px 4px;
    }}

    QListView::item:selected {{
        background: {g("base.accent")};
        color: {text_on_accent};
    }}

    QListView::item:hover {{
        background: {g("base.backgroundTertiary")};
    }}

    /* ──── Progress bars ──── */
    QProgressBar {{
        border: 1px solid {g("base.border")};
        border-radius: 8px;
        text-align: center;
        background: {g("status.progressTrack")};
        height: 12px;
        color: {g("base.foreground")};
    }}

    QProgressBar::chunk {{
        background: {g("status.progressBar")};
        border-radius: 6px;
    }}

    /* ──── Sliders ──── */
    QSlider::groove:horizontal {{
        height: 6px;
        background: {g("input.sliderTrack")};
        border-radius: 3px;
    }}

    QSlider::handle:horizontal {{
        background: {g("base.accent")};
        width: 18px;
        height: 18px;
        margin: -6px 0;
        border-radius: 9px;
        border: 2px solid {g("base.backgroundSecondary")};
    }}

    QSlider::handle:horizontal:hover {{
        background: {g("base.accentHover")};
        border: 2px solid {g("base.accent")};
    }}

    QSlider::sub-page:horizontal {{
        background: {g("base.accent")};
        border-radius: 3px;
    }}

    /* ──── Tabs ──── */
    QTabWidget::pane {{
        border: 1px solid {g("tabs.border")};
        border-radius: 12px;
        background: {g("tabs.background")};
        top: -1px;
    }}

    QTabBar::tab {{
        background: {g("tabs.background")};
        border: 1px solid {g("tabs.border")};
        border-bottom: none;
        border-top-left-radius: 8px;
        border-top-right-radius: 8px;
        padding: 10px 20px;
        margin-right: 2px;
        color: {g("tabs.foreground")};
    }}

    QTabBar::tab:selected {{
        background: {g("tabs.activeBackground")};
        color: {g("tabs.activeForeground")};
        border-bottom: 2px solid {g("base.accent")};
    }}

    QTabBar::tab:hover {{
        background: {g("tabs.hoverBackground")};
    }}

    /* ──── Group boxes ──── */
    QGroupBox {{
        background: {g("base.backgroundSecondary")};
        border: 1px solid {g("base.border")};
        border-radius: 12px;
        margin-top: 12px;
        padding-top: 12px;
        font-weight: 600;
    }}

    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 12px;
        padding: 0 8px;
        color: {g("base.accent")};
    }}

    /* ──── Checkboxes and Radio buttons ──── */
    QCheckBox, QRadioButton {{
        spacing: 8px;
    }}

    QCheckBox::indicator, QRadioButton::indicator {{
        width: 18px;
        height: 18px;
        border-radius: 4px;
        border: 2px solid {g("base.border")};
        background: {g("base.backgroundSecondary")};
    }}

    QRadioButton::indicator {{
        border-radius: 9px;
    }}

    QCheckBox::indicator:checked {{
        background: {g("results.checkboxActive")};
        border-color: {g("results.checkboxActive")};
        image: url(data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIxMiIgaGVpZ2h0PSIxMiIgdmlld0JveD0iMCAwIDI0IDI0IiBmaWxsPSJub25lIiBzdHJva2U9IiMwYTBiMGYiIHN0cm9rZS13aWR0aD0iMyIgc3Ryb2tlLWxpbmVjYXA9InJvdW5kIiBzdHJva2UtbGluZWpvaW49InJvdW5kIj48cG9seWxpbmUgcG9pbnRzPSIyMCA2IDkgMTcgNCAxMiI+PC9wb2x5bGluZT48L3N2Zz4=);
    }}

    QRadioButton::indicator:checked {{
        background: {g("results.checkboxActive")};
        border-color: {g("results.checkboxActive")};
    }}

    /* ──── Menus ──── */
    QMenu {{
        background: {g("base.backgroundSecondary")};
        border: 1px solid {g("base.border")};
        border-radius: 8px;
        padding: 6px;
    }}

    QMenu::item {{
        padding: 8px 24px;
        border-radius: 6px;
        color: {g("base.foreground")};
    }}

    QMenu::item:selected {{
        background: {g("base.accent")};
        color: {text_on_accent};
    }}

    QMenu::separator {{
        height: 1px;
        background: {g("base.border")};
        margin: 6px 12px;
    }}

    /* ──── Utility classes ──── */
    .accent {{ color: {g("base.accent")}; }}
    .accent2 {{ color: {g("base.accentHover")}; }}
    .danger {{ color: {g("feedback.danger")}; }}
    .ok {{ color: {g("feedback.success")}; }}
    .muted {{ color: {g("base.foregroundSecondary")}; }}
    .text-secondary {{ color: {g("base.foregroundSecondary")}; }}

    /* ──── Animations ──── */
    .fade-in {{
        animation: fadeIn 300ms ease-in;
    }}

    @keyframes fadeIn {{
        from {{ opacity: 0; }}
        to {{ opacity: 1; }}
    }}
    """


def apply_v3_theme_to_qapp(engine: Any) -> bool:
    """Apply the ThemeEngineV3 theme to the running QApplication.

    Generates QSS from all 80 resolved slots and applies it.
    Also creates a QPalette from the resolved colors.

    Returns True if successful, False if no QApplication exists.
    """
    try:
        from PySide6.QtWidgets import QApplication
        from PySide6.QtGui import QPalette, QColor

        app = QApplication.instance()
        if not app:
            return False

        # Generate QSS from 80 slots
        qss = generate_v3_qss(engine)
        app.setStyleSheet(qss)

        # Create QPalette from resolved slots
        palette = QPalette()
        meta = engine.get_theme_metadata(engine.active_theme_name)
        is_dark = meta.get("type", "dark") == "dark"
        g = engine.get_color

        palette.setColor(QPalette.Window, QColor(g("base.background")))
        palette.setColor(QPalette.Base, QColor(g("base.backgroundSecondary")))
        palette.setColor(QPalette.AlternateBase, QColor(g("base.background")))
        palette.setColor(QPalette.Text, QColor(g("base.foreground")))
        palette.setColor(QPalette.WindowText, QColor(g("base.foreground")))
        palette.setColor(QPalette.Button, QColor(g("base.backgroundSecondary")))
        palette.setColor(QPalette.ButtonText, QColor(g("base.foreground")))
        palette.setColor(QPalette.PlaceholderText, QColor(g("base.foregroundMuted")))
        palette.setColor(QPalette.Highlight, QColor(g("base.accent")))
        text_on_accent = "#0a0b0f" if is_dark else "#ffffff"
        palette.setColor(QPalette.HighlightedText, QColor(text_on_accent))
        palette.setColor(QPalette.ToolTipBase, QColor(g("dialog.background")))
        palette.setColor(QPalette.ToolTipText, QColor(g("dialog.foreground")))
        palette.setColor(QPalette.BrightText, QColor(g("feedback.danger")))

        # Disabled states
        palette.setColor(QPalette.Disabled, QPalette.Text,
                         QColor(g("base.foregroundMuted")))
        palette.setColor(QPalette.Disabled, QPalette.ButtonText,
                         QColor(g("base.foregroundMuted")))
        palette.setColor(QPalette.Disabled, QPalette.WindowText,
                         QColor(g("base.foregroundMuted")))

        app.setPalette(palette)

        # Force style refresh
        app.setStyle(app.style())
        return True

    except Exception:
        return False


def get_theme_card_colors(engine: Any) -> List[str]:
    """Get 4 representative colors for a ThemeCard swatch preview.

    Returns: [background, panel, accent, foreground]
    """
    g = engine.get_color
    return [
        g("base.background"),
        g("panel.background"),
        g("base.accent"),
        g("base.foreground"),
    ]


__all__ = [
    "LEGACY_KEY_MAP",
    "resolve_legacy_key",
    "build_legacy_colors",
    "build_theme_spec_palette",
    "generate_v3_qss",
    "apply_v3_theme_to_qapp",
    "get_theme_card_colors",
]
