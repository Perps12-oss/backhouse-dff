"""
Validation utility functions for CEREBRO.
"""

import os
from pathlib import Path
from typing import List, Optional, Tuple


def validate_directory_path(path: str) -> Tuple[bool, Optional[str]]:
    """
    Validate that a path is a directory and exists.
    
    Args:
        path: Path to validate
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    try:
        dir_path = Path(path)
        if not dir_path.exists():
            return False, "Directory does not exist"
        if not dir_path.is_dir():
            return False, "Path is not a directory"
        return True, None
    except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError) as e:
        return False, f"Error validating path: {str(e)}"


def validate_file_path(path: str) -> Tuple[bool, Optional[str]]:
    """
    Validate that a path is a file and exists.
    
    Args:
        path: Path to validate
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    try:
        file_path = Path(path)
        if not file_path.exists():
            return False, "File does not exist"
        if not file_path.is_file():
            return False, "Path is not a file"
        return True, None
    except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError) as e:
        return False, f"Error validating path: {str(e)}"


def validate_file_size(file_path: Path, min_size: int = 0, max_size: Optional[int] = None) -> Tuple[bool, Optional[str]]:
    """
    Validate that a file meets size requirements.
    
    Args:
        file_path: Path to the file
        min_size: Minimum size in bytes
        max_size: Maximum size in bytes (None for no limit)
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    try:
        size = file_path.stat().st_size
        if size < min_size:
            return False, f"File is too small (minimum: {min_size} bytes)"
        if max_size is not None and size > max_size:
            return False, f"File is too large (maximum: {max_size} bytes)"
        return True, None
    except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError) as e:
        return False, f"Error checking file size: {str(e)}"


def validate_file_extensions(file_paths: List[Path], allowed_extensions: List[str]) -> Tuple[bool, List[str]]:
    """
    Validate that files have allowed extensions.
    
    Args:
        file_paths: List of file paths to validate
        allowed_extensions: List of allowed extensions (including the dot, e.g., '.txt')
        
    Returns:
        Tuple of (all_valid, list_of_invalid_files)
    """
    invalid_files = []
    for file_path in file_paths:
        if file_path.suffix.lower() not in [ext.lower() for ext in allowed_extensions]:
            invalid_files.append(str(file_path))
    
    return len(invalid_files) == 0, invalid_files


def sanitize_filename(filename: str) -> str:
    """
    Sanitize a filename by removing or replacing invalid characters.
    
    Args:
        filename: Original filename
        
    Returns:
        Sanitized filename
    """
    # Define invalid characters for different OS
    if os.name == 'nt':  # Windows
        invalid_chars = '<>:"/\\|?*'
    else:  # Unix-like
        invalid_chars = '/'
    
    # Replace invalid characters with underscores
    for char in invalid_chars:
        filename = filename.replace(char, '_')
    
    # Remove control characters
    filename = ''.join(c for c in filename if ord(c) >= 32)
    
    # Ensure filename is not empty
    if not filename:
        filename = "unnamed_file"
    
    return filename