# path: CEREBRO/__init__.py
"""
CEREBRO - Intelligent Duplicate File Finder
Version: 5.0.0

Main package entry point.
"""

__version__ = "5.0.0"
__author__ = "CEREBRO Labs"
__license__ = "Proprietary"

from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
LOG_DIR = ROOT_DIR / "logs"
CONFIG_DIR = ROOT_DIR / "config"

# Ensure directories exist
LOG_DIR.mkdir(exist_ok=True)

# Export version info
__all__ = ['__version__', '__author__', 'ROOT_DIR', 'LOG_DIR']