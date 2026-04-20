"""
Cerebro v2 Scan Engines

Pluggable scan engine architecture for duplicate detection.
"""

from cerebro.engines.base_engine import (
    BaseEngine,
    ScanState,
    ScanProgress,
    DuplicateGroup,
    DuplicateFile,
    EngineOption
)
from cerebro.engines.orchestrator import ScanOrchestrator
from cerebro.engines.hash_cache import HashCache

__all__ = [
    'BaseEngine',
    'ScanState',
    'ScanProgress',
    'DuplicateGroup',
    'DuplicateFile',
    'EngineOption',
    'ScanOrchestrator',
    'HashCache',
]
