# cerebro/ui/pages/base_station.py
from __future__ import annotations

from typing import Any, Dict, Optional
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget

from cerebro.ui.theme_engine import current_colors, ThemeEngine


class BaseStation(QWidget):
   """
   Base class for all Station Pages with automatic theme support.
   
   Features:
   - Automatic theme application on enter/creation
   - Theme change propagation
   - Color accessor utilities
   """

   # Lifecycle signals
   became_unsafe = Signal()
   became_safe = Signal()
   theme_applied = Signal(dict)  # Emitted when theme is applied with colors dict

   def __init__(self, parent: Optional[QWidget] = None, theme_engine: Optional[ThemeEngine] = None) -> None:
       super().__init__(parent)
       self._is_active: bool = False
       self._theme_engine = theme_engine
       self._theme_colors: Dict[str, str] = {}
       
       # Apply initial theme
       self._apply_theme()

   def _apply_theme(self) -> None:
       """Apply current theme to this station."""
       self._theme_colors = current_colors()
       
       # Set base background
       bg = self._theme_colors.get('bg', '#0f1115')
       text = self._theme_colors.get('text', '#e7ecf2')
       
       self.setStyleSheet(f"""
           BaseStation {{
               background-color: {bg};
               color: {text};
           }}
       """)
       
       # Notify subclasses
       self.on_theme_applied(self._theme_colors)
       self.theme_applied.emit(self._theme_colors)
   
   def on_theme_applied(self, colors: Dict[str, str]) -> None:
       """
       Override this to apply custom theme logic.
       Called automatically when theme changes.
       """
       pass
   
   def refresh_theme(self) -> None:
       """Force theme refresh."""
       self._apply_theme()
   
   def get_color(self, key: str, fallback: str = "#7aa2ff") -> str:
       """Get theme color by key."""
       return self._theme_colors.get(key, fallback) if self._theme_colors else fallback
   
   def get_colors(self) -> Dict[str, str]:
       """Get all theme colors."""
       return self._theme_colors.copy()

   # ----------------------------
   # Lifecycle (override in pages)
   # ----------------------------

   def on_enter(self) -> None:
       """Called when station becomes current."""
       self._is_active = True
       # Refresh theme when entering (in case it changed while away)
       self.refresh_theme()

   def on_exit(self) -> None:
       """Called when station loses focus."""
       self._is_active = False

   def cleanup(self) -> None:
       """Stop timers/workers, release resources."""
       pass

   def reset(self) -> None:
       """Clear internal state, stop workers, disconnect temporary signals. Page appears as if freshly loaded."""
       pass

   def reset_for_new_scan(self) -> None:
       """Clear scan-specific data, reset progress, hide stale results. Called when a new scan starts."""
       pass

   # ----------------------------
   # Navigation safety
   # ----------------------------

   def are_you_safe_to_leave(self) -> bool:
       """
       Return False to block navigation (e.g. scan running).
       MainWindow will prompt the user and can call emergency_stop/cleanup.
       """
       return True

   def notify_unsafe(self) -> None:
       self.became_unsafe.emit()

   def notify_safe(self) -> None:
       self.became_safe.emit()

   # ----------------------------
   # Diagnostics (optional)
   # ----------------------------

   def is_active(self) -> bool:
       return self._is_active

   def get_statistics(self) -> Dict[str, Any]:
       return {
           "station_type": self.__class__.__name__,
           "is_active": self._is_active,
           "is_safe": self.are_you_safe_to_leave(),
       }