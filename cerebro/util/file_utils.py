"""
File utility functions for CEREBRO.
"""

import os
import hashlib
from pathlib import Path
from typing import List, Optional, Generator, Tuple


def calculate_file_hash(file_path: Path, hash_algorithm: str = "sha256", chunk_size: int = 8192) -> str:
    """
    Calculate hash of a file.
    
    Args:
        file_path: Path to the file
        hash_algorithm: Hash algorithm to use (md5, sha1, sha256, etc.)
        chunk_size: Size of chunks to read at a time
        
    Returns:
        Hex string of the file hash
    """
    hash_obj = hashlib.new(hash_algorithm)
    
    with open(file_path, 'rb') as f:
        while chunk := f.read(chunk_size):
            hash_obj.update(chunk)
    
    return hash_obj.hexdigest()


def get_file_size(file_path: Path) -> int:
    """
    Get file size in bytes.
    
    Args:
        file_path: Path to the file
        
    Returns:
        File size in bytes
    """
    return file_path.stat().st_size


def is_hidden_file(file_path: Path) -> bool:
    """
    Check if a file is hidden.
    
    Args:
        file_path: Path to the file
        
    Returns:
        True if file is hidden, False otherwise
    """
    # Unix-like systems
    if file_path.name.startswith('.'):
        return True
    
    # Windows
    if os.name == 'nt':
        try:
            import win32api
            import win32con
            attribute = win32api.GetFileAttributes(str(file_path))
            return attribute & (win32con.FILE_ATTRIBUTE_HIDDEN | win32con.FILE_ATTRIBUTE_SYSTEM)
        except (ImportError, AttributeError):
            pass
    
    return False


def find_files_by_pattern(root_dir: Path, pattern: str, recursive: bool = True) -> Generator[Path, None, None]:
    """
    Find files matching a pattern.
    
    Args:
        root_dir: Directory to search in
        pattern: Glob pattern to match
        recursive: Whether to search recursively
        
    Yields:
        Paths to matching files
    """
    if recursive:
        for file_path in root_dir.rglob(pattern):
            if file_path.is_file():
                yield file_path
    else:
        for file_path in root_dir.glob(pattern):
            if file_path.is_file():
                yield file_path


def ensure_directory_exists(dir_path: Path) -> None:
    """
    Ensure a directory exists, creating it if necessary.
    
    Args:
        dir_path: Path to the directory
    """
    dir_path.mkdir(parents=True, exist_ok=True)