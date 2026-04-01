"""
Cerebro v2 Core Module

Foundational utilities and design system.
"""

from cerebro.v2.core.design_tokens import (
    Colors,
    Color,
    Spacing,
    Typography,
    Dimensions,
    Duration,
    ZIndex,
    Shadows,
    Tokens
)
from cerebro.v2.core.performance import (
    PoolManager,
    get_pool_manager,
    run_parallel,
    timing,
    PerformanceMonitor,
    shutdown_all
)

__all__ = [
    # Design tokens
    'Colors',
    'Color',
    'Spacing',
    'Typography',
    'Dimensions',
    'Duration',
    'ZIndex',
    'Shadows',
    'Tokens',
    # Performance
    'PoolManager',
    'get_pool_manager',
    'run_parallel',
    'timing',
    'PerformanceMonitor',
    'shutdown_all',
]
