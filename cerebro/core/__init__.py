# path: cerebro/core/__init__.py
"""
Core components for duplicate detection and file management.
"""

# Core pipeline
from .pipeline import (
    CerebroPipeline,
    create_default_pipeline,
    PipelineResult,
    PipelineEvent,
    PipelineStats,
)

# Session management
from .session import (
    SessionManager,
    create_session_manager,
    ScanState,
)

# Core models
from .models import (
    PipelineRequest,
    PipelineMode,
    DeletionPolicy,
    FileMetadata,
    DuplicateGroup,
    DuplicateItem,
    FileType,
    ScanProgress,
    ComparisonStats,
)

# Functional components
from .discovery import FileDiscovery
from .grouping import SizeGrouping
from .hashing import FileHashing
from .clustering import HashClustering
from .decision import DecisionEngine
from .deletion import DeletionEngine
# cerebro/core/__init__.py - ADD THIS:
from .preview import PreviewManager

# Scanners
from .scanners import (
    AdvancedScanner,
    SimpleScanner,
    ScannerBridge,
    create_scanner_bridge,
)

# Visual components
from .visual_hashing import (
    VisualHashSettings,
    compute_visual_hash,
    is_image_path,
    hamming_distance,
)

from .visual_similarity import VisualSimilarityClustering

__all__ = [
    # Pipeline
    'CerebroPipeline',
    'create_default_pipeline',
    'PipelineResult',
    'PipelineEvent',
    'PipelineStats',
    
    # Session
    'SessionManager',
    'create_session_manager',
    'ScanState',
    
    # Models
    'PipelineRequest',
    'PipelineMode',
    'DeletionPolicy',
    'FileMetadata',
    'DuplicateGroup',
    'DuplicateItem',
    'FileType',
    'ScanProgress',
    'ComparisonStats',
    
    # Components
    'FileDiscovery',
    'SizeGrouping',
    'FileHashing',
    'HashClustering',
    'DecisionEngine',
    'DeletionEngine',
    
    # Scanners
    'AdvancedScanner',
    'SimpleScanner',
    'ScannerBridge',
    'create_scanner_bridge',
    
    # Visual
    'VisualHashSettings',
    'compute_visual_hash',
    'is_image_path',
    'hamming_distance',
    'VisualSimilarityClustering',
]