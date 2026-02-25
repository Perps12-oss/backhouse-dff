# cerebro/ui/__init__.py
"""
CEREBRO UI Package
"""

# Import the new theme system components instead of the old ones
from .theme_engine import ThemeManager, ThemeMixin

# Keep the existing imports for other components
from .main_window import MainWindow


__all__ = [
    'ThemeManager',
    'ThemeMixin',
    'MainWindow',
    'create_main_window',
]