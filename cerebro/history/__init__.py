"""
cerebro.history package

IMPORTANT:
- Keep this module lightweight.
- Do NOT import UI pages (HistoryPage) here.
Reason: core/pipeline may import history.store; importing UI causes circular imports,
especially under multiprocessing on Windows.
"""

from __future__ import annotations
from typing import Any

__all__ = [
    "HistoryStore",
]

def __getattr__(name: str) -> Any:
    if name == "HistoryStore":
        from .store import HistoryStore  # lazy import
        return HistoryStore
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
