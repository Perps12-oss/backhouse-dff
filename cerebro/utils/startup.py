# cerebro/utils/startup.py
"""
Startup utilities for CEREBRO application.

This module provides reusable utilities for application startup,
including dependency checking, environment validation, and more.
"""
from __future__ import annotations

import sys
import platform
from typing import List, Tuple, Optional
from pathlib import Path


class DependencyChecker:
    """Check and validate application dependencies."""
    
    @staticmethod
    def check_python_version(minimum: Tuple[int, int] = (3, 8)) -> Tuple[bool, Optional[str]]:
        """
        Check if Python version meets minimum requirement.
        
        Args:
            minimum: Minimum version tuple (major, minor)
            
        Returns:
            (success, error_message)
        """
        current = sys.version_info[:2]
        if current < minimum:
            error = (
                f"Python {minimum[0]}.{minimum[1]}+ required, "
                f"but {current[0]}.{current[1]} found.\n"
                f"Please upgrade Python."
            )
            return False, error
        return True, None
    
    @staticmethod
    def check_pyside6() -> Tuple[bool, Optional[str]]:
        """
        Check if PySide6 is available.
        
        Returns:
            (success, error_message)
        """
        try:
            import PySide6
            from PySide6.QtCore import __version__
            return True, None
        except ImportError:
            error = (
                "PySide6 is not installed.\n\n"
                "Install with:\n"
                "  pip install PySide6\n\n"
                "Or install all dependencies:\n"
                "  pip install -r requirements.txt"
            )
            return False, error
    
    @staticmethod
    def check_pillow() -> Tuple[bool, Optional[str]]:
        """
        Check if Pillow is available.
        
        Returns:
            (success, error_message)
        """
        try:
            import PIL
            return True, None
        except ImportError:
            error = (
                "Pillow is not installed (required for image processing).\n\n"
                "Install with:\n"
                "  pip install Pillow"
            )
            return False, error
    
    @staticmethod
    def check_all(include_optional: bool = False) -> Tuple[bool, List[str]]:
        """
        Check all required dependencies.
        
        Args:
            include_optional: Also check optional dependencies
            
        Returns:
            (all_ok, list_of_errors)
        """
        errors = []
        
        # Check Python version
        ok, err = DependencyChecker.check_python_version()
        if not ok:
            errors.append(err)
        
        # Check PySide6
        ok, err = DependencyChecker.check_pyside6()
        if not ok:
            errors.append(err)
        
        # Check Pillow
        ok, err = DependencyChecker.check_pillow()
        if not ok:
            errors.append(err)
        
        return len(errors) == 0, errors


class EnvironmentValidator:
    """Validate runtime environment."""
    
    @staticmethod
    def get_platform_info() -> dict:
        """
        Get platform information.
        
        Returns:
            Dictionary with platform details
        """
        return {
            'system': platform.system(),
            'release': platform.release(),
            'version': platform.version(),
            'machine': platform.machine(),
            'processor': platform.processor(),
            'python_version': sys.version,
            'python_implementation': platform.python_implementation(),
        }
    
    @staticmethod
    def validate_platform() -> Tuple[bool, Optional[str]]:
        """
        Validate that platform is supported.
        
        Returns:
            (is_valid, error_message)
        """
        system = platform.system()
        supported = ['Windows', 'Linux', 'Darwin']  # Darwin = macOS
        
        if system not in supported:
            return False, f"Unsupported platform: {system}"
        
        return True, None
    
    @staticmethod
    def check_display_available() -> bool:
        """
        Check if display/GUI is available.
        
        Returns:
            True if display is available
        """
        if platform.system() == 'Linux':
            import os
            return 'DISPLAY' in os.environ
        
        # Windows and macOS always have display
        return True
    
    @staticmethod
    def check_write_permissions(directory: Path) -> bool:
        """
        Check if we have write permissions in directory.
        
        Args:
            directory: Directory to check
            
        Returns:
            True if writable
        """
        try:
            directory.mkdir(parents=True, exist_ok=True)
            test_file = directory / ".write_test"
            test_file.write_text("test")
            test_file.unlink()
            return True
        except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
            return False
    
    @staticmethod
    def validate_all() -> Tuple[bool, List[str]]:
        """
        Run all environment validations.
        
        Returns:
            (all_ok, list_of_warnings)
        """
        warnings = []
        
        # Check platform
        ok, err = EnvironmentValidator.validate_platform()
        if not ok:
            warnings.append(err)
        
        # Check display
        if not EnvironmentValidator.check_display_available():
            warnings.append("No display detected - GUI may not work")
        
        return len(warnings) == 0, warnings


class StartupTimer:
    """Track startup performance."""
    
    def __init__(self):
        import time
        self.start_time = time.time()
        self.steps: List[Tuple[str, float]] = []
    
    def mark(self, step_name: str) -> float:
        """
        Mark a step completion.
        
        Args:
            step_name: Name of the completed step
            
        Returns:
            Elapsed time since start
        """
        import time
        elapsed = time.time() - self.start_time
        self.steps.append((step_name, elapsed))
        return elapsed
    
    def get_total_time(self) -> float:
        """Get total elapsed time."""
        import time
        return time.time() - self.start_time
    
    def get_summary(self) -> dict:
        """
        Get startup summary.
        
        Returns:
            Dictionary with timing information
        """
        return {
            'total_time': self.get_total_time(),
            'steps': self.steps,
            'num_steps': len(self.steps),
        }


def create_directories(base_dir: Path) -> bool:
    """
    Create required application directories.
    
    Args:
        base_dir: Base application directory
        
    Returns:
        True if successful
    """
    directories = [
        base_dir,
        base_dir / "cache",
        base_dir / "logs",
        base_dir / "backups",
        base_dir / "themes",
        base_dir / "history",
    ]
    
    try:
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)
        return True
    except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
        return False


def get_application_info() -> dict:
    """
    Get comprehensive application information.
    
    Returns:
        Dictionary with app info
    """
    return {
        'platform': EnvironmentValidator.get_platform_info(),
        'python_path': sys.executable,
        'sys_path': sys.path,
    }
