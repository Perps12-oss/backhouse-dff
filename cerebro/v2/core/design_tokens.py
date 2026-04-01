"""
Design Tokens

Single source of truth for the Cerebro v2 design system.
Contains all colors, typography, spacing, and visual constants.
"""

from dataclasses import dataclass
from typing import NamedTuple


class Color(NamedTuple):
    """RGBA color representation."""
    red: int
    green: int
    blue: int
    alpha: int = 255

    @property
    def hex(self) -> str:
        """Return CSS hex color string."""
        return f"#{self.red:02x}{self.green:02x}{self.blue:02x}"

    @classmethod
    def from_hex(cls, hex_str: str) -> "Color":
        """Create Color from hex string."""
        hex_str = hex_str.lstrip('#')
        if len(hex_str) == 6:
            r = int(hex_str[0:2], 16)
            g = int(hex_str[2:4], 16)
            b = int(hex_str[4:6], 16)
            return cls(r, g, b)
        elif len(hex_str) == 8:
            r = int(hex_str[0:2], 16)
            g = int(hex_str[2:4], 16)
            b = int(hex_str[4:6], 16)
            a = int(hex_str[6:8], 16)
            return cls(r, g, b, a)
        raise ValueError(f"Invalid hex color: {hex_str}")


class Colors:
    """Color palette for dark navy + cyan theme."""

    # Primary backgrounds
    BG_PRIMARY = Color.from_hex("#0A0E14")      # Main window background
    BG_SECONDARY = Color.from_hex("#0D1117")    # Panel backgrounds
    BG_TERTIARY = Color.from_hex("#161B22")    # Card/row backgrounds
    BG_QUATERNARY = Color.from_hex("#1C2333")  # Group headers

    # Accents
    ACCENT = Color.from_hex("#22D3EE")          # Primary accent (cyan)
    ACCENT_HOVER = Color.from_hex("#06B6D4")    # Button hover
    ACCENT_DIM = Color.from_hex("#164E63")      # Disabled/inactive accent

    # Text
    TEXT_PRIMARY = Color.from_hex("#E6EDF3")     # Primary text
    TEXT_SECONDARY = Color.from_hex("#8B949E")  # Secondary/muted text
    TEXT_MUTED = Color.from_hex("#6E7681")       # Very muted text
    TEXT_DISABLED = Color.from_hex("#484F58")    # Disabled text

    # Borders and dividers
    BORDER = Color.from_hex("#30363D")          # Panel borders
    BORDER_LIGHT = Color.from_hex("#3B434D")     # Highlighted borders
    BORDER_DIM = Color.from_hex("#21262D")       # Subtle borders

    # Semantic colors
    DANGER = Color.from_hex("#F85149")         # Delete buttons, errors
    DANGER_HOVER = Color.from_hex("#DA3633")   # Danger hover
    SUCCESS = Color.from_hex("#3FB950")         # Scan complete, saved space
    SUCCESS_HOVER = Color.from_hex("#2EA043")   # Success hover
    WARNING = Color.from_hex("#D29922")         # Warnings, protected folders
    WARNING_HOVER = Color.from_hex("#9A6700")   # Warning hover
    INFO = Color.from_hex("#58A6FF")            # Information

    # CustomTkinter compatible string values
    CTK_BG_PRIMARY = "#0A0E14"
    CTK_BG_SECONDARY = "#0D1117"
    CTK_BG_TERTIARY = "#161B22"
    CTK_ACCENT = "#22D3EE"
    CTK_ACCENT_HOVER = "#06B6D4"
    CTK_TEXT_PRIMARY = "#E6EDF3"
    CTK_TEXT_SECONDARY = "#8B949E"
    CTK_DANGER = "#F85149"
    CTK_SUCCESS = "#3FB950"
    CTK_WARNING = "#D29922"


class Spacing:
    """Spacing constants (in pixels)."""

    XXXS = 2
    XXS = 4
    XS = 8
    SM = 12
    MD = 16
    LG = 24
    XL = 32
    XXL = 48
    XXXL = 64

    # Component-specific
    PADDING_XS = XS
    PADDING_SM = SM
    PADDING_MD = MD
    PADDING_LG = LG

    GAP_XS = XS
    GAP_SM = SM
    GAP_MD = MD
    GAP_LG = LG

    BORDER_RADIUS_XS = 2
    BORDER_RADIUS_SM = 4
    BORDER_RADIUS_MD = 8
    BORDER_RADIUS_LG = 12


class Typography:
    """Typography constants."""

    # Font families
    FONT_FAMILY_DEFAULT = "Segoe UI"
    FONT_FAMILY_MONO = "Consolas"
    FONT_FAMILY_ICONS = "Segoe UI Symbol"

    # Font sizes
    FONT_SIZE_XS = 11
    FONT_SIZE_SM = 12
    FONT_SIZE_MD = 13
    FONT_SIZE_LG = 16
    FONT_SIZE_XL = 20
    FONT_SIZE_XXL = 24
    FONT_SIZE_XXXL = 32

    # Font weights (CustomTkinter uses: "normal", "bold")
    WEIGHT_NORMAL = "normal"
    WEIGHT_BOLD = "bold"

    # CustomTkinter font tuples
    FONT_XS = (FONT_FAMILY_DEFAULT, FONT_SIZE_XS)
    FONT_SM = (FONT_FAMILY_DEFAULT, FONT_SIZE_SM)
    FONT_MD = (FONT_FAMILY_DEFAULT, FONT_SIZE_MD)
    FONT_LG = (FONT_FAMILY_DEFAULT, FONT_SIZE_LG)
    FONT_XL = (FONT_FAMILY_DEFAULT, FONT_SIZE_XL, WEIGHT_BOLD)
    FONT_XXL = (FONT_FAMILY_DEFAULT, FONT_SIZE_XXL, WEIGHT_BOLD)
    FONT_MONO = (FONT_FAMILY_MONO, FONT_SIZE_SM)

    # Icon font
    FONT_ICONS = (FONT_FAMILY_ICONS, 16)


class Dimensions:
    """Widget and layout dimensions (in pixels)."""

    # Window
    WINDOW_MIN_WIDTH = 1024
    WINDOW_MIN_HEIGHT = 700
    WINDOW_DEFAULT_WIDTH = 1280
    WINDOW_DEFAULT_HEIGHT = 800

    # Toolbar
    TOOLBAR_HEIGHT = 48

    # Mode tabs
    MODE_TABS_HEIGHT = 40

    # Panels
    LEFT_PANEL_MIN_WIDTH = 200
    LEFT_PANEL_DEFAULT_WIDTH = 250
    LEFT_PANEL_MAX_WIDTH = 400

    # Preview panel
    PREVIEW_PANEL_MIN_HEIGHT = 150
    PREVIEW_PANEL_DEFAULT_HEIGHT = 200
    PREVIEW_PANEL_MAX_HEIGHT = 400

    # Status bar
    STATUS_BAR_HEIGHT = 28

    # Buttons
    BUTTON_HEIGHT_SM = 28
    BUTTON_HEIGHT_MD = 36
    BUTTON_HEIGHT_LG = 44

    # Icons
    ICON_SIZE_SM = 16
    ICON_SIZE_MD = 20
    ICON_SIZE_LG = 24
    ICON_SIZE_XL = 32

    # Treeview/List items
    ROW_HEIGHT = 28
    ROW_HEIGHT_COMPACT = 24


class Duration:
    """Animation and timing durations (in milliseconds)."""

    FAST = 150
    NORMAL = 300
    SLOW = 500
    EXTRA_SLOW = 1000

    HOVER_DELAY = 100
    TOOLTIP_DELAY = 500


class ZIndex:
    """Z-index layering for stacked widgets."""
    BACKGROUND = 0
    PANEL = 10
    CONTENT = 20
    OVERLAY = 100
    DROPDOWN = 200
    MODAL = 300
    TOOLTIP = 400


class Shadows:
    """Shadow effects (offset-x, offset-y, blur, spread, color)."""

    NONE = (0, 0, 0, 0, Colors.BG_PRIMARY.hex)

    # Subtle shadow for raised elements
    SUBTLE = (0, 1, 3, 0, "#00000040")

    # Medium shadow for cards
    MEDIUM = (0, 4, 6, -1, "#00000060")

    # Heavy shadow for modals
    HEAVY = (0, 10, 15, -3, "#00000080")


# Token groups for easy import
class Tokens:
    """All design tokens in one place."""

    colors = Colors
    spacing = Spacing
    typography = Typography
    dimensions = Dimensions
    duration = Duration
    z_index = ZIndex
    shadows = Shadows


# Helper functions
def hex_to_ctk_color(hex_color: str) -> str:
    """Convert hex color to CustomTkinter color string."""
    return hex_color


def lighten_color(hex_color: str, percent: int = 10) -> str:
    """Lighten a hex color by a percentage."""
    color = Color.from_hex(hex_color)
    factor = 1 + (percent / 100)
    r = min(255, int(color.red * factor))
    g = min(255, int(color.green * factor))
    b = min(255, int(color.blue * factor))
    return Color(r, g, b, color.alpha).hex


def darken_color(hex_color: str, percent: int = 10) -> str:
    """Darken a hex color by a percentage."""
    color = Color.from_hex(hex_color)
    factor = 1 - (percent / 100)
    r = max(0, int(color.red * factor))
    g = max(0, int(color.green * factor))
    b = max(0, int(color.blue * factor))
    return Color(r, g, b, color.alpha).hex
