# path: cerebro/core/scanners/__init__.py
"""
scanners/__init__.py — Scanner Integration Bridge

Provides unified scanner interface that works with both:
1. AdvancedScanner (full featured)
2. SimpleScanner (lightweight)
3. Quantum scanning strategies
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Union, Any

from cerebro.core.models import FileMetadata
from .advanced_scanner import AdvancedScanner, ScanConfig, QuantumKind
from .simple_scanner import SimpleScanner


class ScannerBridge:
    """
    Unified scanner interface.
    
    Automatically selects appropriate scanner based on:
    - Request complexity
    - Performance requirements
    - Feature requirements
    """
    
    def __init__(self):
        self.advanced_scanner = AdvancedScanner()
        self.simple_scanner = SimpleScanner()
        
    def scan_directory(
        self,
        directory: Path,
        options: Dict[str, Any],
        *,
        use_simple: bool = False,
        cancel_event: Any = None,
    ) -> List[FileMetadata]:
        """
        Scan directory with automatic scanner selection.
        
        Args:
            directory: Directory to scan
            options: Scanner options
            use_simple: Force simple scanner
            cancel_event: Cancellation event
            
        Returns:
            List of file metadata
        """
        if use_simple:
            return self.simple_scanner.scan_directory(
                directory, options, cancel_event=cancel_event
            )
        
        # Auto-select based on options
        if self._should_use_simple(options):
            return self.simple_scanner.scan_directory(
                directory, options, cancel_event=cancel_event
            )
        
        # Use advanced scanner
        config = self._options_to_config(options)
        scanner = AdvancedScanner(config=config)
        
        # Convert to FileMetadata list
        results = []
        for meta in scanner.scan([directory]):
            results.append(meta)
        
        return results
    
    def create_for_request(
        self,
        request: Any,
        *,
        kind: Optional[Union[str, QuantumKind]] = None,
    ) -> AdvancedScanner:
        """Create quantum-aware scanner for pipeline request."""
        return AdvancedScanner.create_for_request(request, kind=kind)
    
    # =================================================================
    # PRIVATE METHODS
    # =================================================================
    
    def _should_use_simple(self, options: Dict[str, Any]) -> bool:
        """Determine if simple scanner should be used."""
        # Use simple scanner for quick scans
        mode = options.get('mode', '').lower()
        if mode in ('quick', 'simple', 'fast'):
            return True
        
        # Use simple scanner for basic operations
        complex_options = {
            'calculate_full_hash',
            'sample_content',
            'use_mmap_for_large_files',
            'adaptive_throttling',
        }
        
        for opt in complex_options:
            if options.get(opt):
                return False  # Need advanced scanner
        
        return True
    
    def _options_to_config(self, options: Dict[str, Any]) -> ScanConfig:
        """Convert options dict to ScanConfig."""
        config = ScanConfig()
        
        # Map common options
        option_map = {
            'min_file_size': 'min_file_size',
            'max_file_size': 'max_file_size',
            'follow_symlinks': 'follow_symlinks',
            'scan_hidden': 'scan_hidden',
            'max_depth': 'max_depth',
            'max_workers': 'max_workers',
            'calculate_quick_hash': 'calculate_quick_hash',
            'calculate_full_hash': 'calculate_full_hash',
            'hash_algorithm': 'hash_algorithm',
        }
        
        for opt_key, config_key in option_map.items():
            if opt_key in options:
                setattr(config, config_key, options[opt_key])
        
        return config


# =====================================================================
# FACTORY FUNCTIONS
# =====================================================================

def create_scanner_bridge() -> ScannerBridge:
    """Create scanner bridge."""
    return ScannerBridge()


def create_quantum_scanner(
    request: Any,
    kind: Optional[Union[str, QuantumKind]] = None,
) -> AdvancedScanner:
    """Create quantum-aware scanner."""
    return AdvancedScanner.create_for_request(request, kind=kind)


__all__ = [
    'ScannerBridge',
    'create_scanner_bridge',
    'create_quantum_scanner',
    'AdvancedScanner',
    'SimpleScanner',
    'ScanConfig',
    'QuantumKind',
]