# cerebro/ui/controllers/__init__.py
"""
UI Controllers package.

Controllers are the "brains" between workers/engine and UI pages:
- Workers emit raw facts.
- Controllers aggregate/normalize and emit UI-ready signals.
- Pages/widgets should bind to controllers, not directly to workers.
"""

from .live_scan_controller import LiveScanController

__all__ = ["LiveScanController"]
