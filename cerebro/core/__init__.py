"""
cerebro.core package

IMPORTANT:
- Keep this module lightweight.
- Do NOT import heavy modules (pipeline, scanners, UI) at import-time.
Reason: multiprocessing on Windows re-imports packages in child processes.
"""

from __future__ import annotations
from typing import Any

__all__ = [
    "CerebroPipeline",
]

def __getattr__(name: str) -> Any:
    # Lazy exports to preserve older "from cerebro.core import CerebroPipeline"
    if name == "CerebroPipeline":
        from .pipeline import CerebroPipeline  # local import to avoid side effects
        return CerebroPipeline
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
