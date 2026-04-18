"""
UI-layer design tokens for the CEREBRO v2 overhaul pages.

Single source of truth for colours, fonts, and layout constants shared
across the new Phase-5/6 pages (welcome, scan, results, review, history,
diagnostics).  Import individual names rather than ``import *``.
"""

# ---------------------------------------------------------------------------
# Backgrounds
# ---------------------------------------------------------------------------

NAVY        = "#0B1929"   # main dark page background (title bar, WelcomePage)
NAVY_MID    = "#1E3A5F"  # header / toolbar bars (BreadcrumbBar, section headers)
NAVY_LIGHT  = "#2E558E"  # action bars, secondary headers
PANEL_BG    = "#F0F0F0"  # light page-container background (AppShell container)
CARD_BG     = "#152535"  # dark card / alternate row stripe

# ---------------------------------------------------------------------------
# Text
# ---------------------------------------------------------------------------

TEXT_PRIMARY   = "#FFFFFF"
TEXT_SECONDARY = "#B0C4D8"
TEXT_MUTED     = "#7090A8"
TEXT_DISABLED  = "#4A6070"

# ---------------------------------------------------------------------------
# Semantic colours
# ---------------------------------------------------------------------------

RED    = "#E74C3C"   # danger, delete
GREEN  = "#27AE60"   # success, safe
BLUE   = "#2980B9"   # info, link
YELLOW = "#F39C12"   # warning

# ---------------------------------------------------------------------------
# Borders / separators
# ---------------------------------------------------------------------------

BORDER = "#2A4060"   # 1-px separator lines between sections

# ---------------------------------------------------------------------------
# Typography  —  tuples suitable for tk/ctk ``font=`` parameter
# ---------------------------------------------------------------------------

FONT_TITLE  = ("Segoe UI", 16, "bold")
FONT_HEADER = ("Segoe UI", 13, "bold")
FONT_BODY   = ("Segoe UI", 12)
FONT_SMALL  = ("Segoe UI", 11)
FONT_MONO   = ("Consolas", 11)

# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

SECTION_HEADER_H = 36   # px — dark header bar above each section
ROW_H            = 26   # px — default treeview row height
PAD_X            = 16   # px — standard horizontal padding
PAD_Y            = 10   # px — standard vertical padding
