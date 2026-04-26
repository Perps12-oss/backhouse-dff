# cerebro/core/utils.py
"""
Utility functions for the CEREBRO core modules.
"""

import os
import stat
import hashlib
import platform
from pathlib import Path
from typing import List, Optional, Dict, Any, Set

# --- Constants ---
DEFAULT_SKIP_DIRS: Set[str] = {
    "$Recycle.Bin", "System Volume Information", "Recovery", "Windows",
    "Program Files", "Program Files (x86)", "ProgramData", "AppData",
    ".git", ".svn", ".hg", "__pycache__", "node_modules", ".vscode", ".idea"
}
DEFAULT_SKIP_EXTENSIONS: Set[str] = {
    ".tmp", ".temp", ".bak", ".swp", ".log", ".dmp", ".part", ".crdownload"
}
# Common system file/directory names
SYSTEM_NAMES: Set[str] = {
    "kernel32.dll", "user32.dll", "ntdll.dll", "shell32.dll", # Windows
    "kernel", "libc.so", "ld-linux.so", # Linux
    "ds_store", ".ds_store", # macOS
}

# --- Formatting & Metadata Functions ---

def format_size(size_bytes: int) -> str:
    """Format a size in bytes to a human-readable string."""
    if size_bytes == 0:
        return "0 B"
    size_names = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    while size_bytes >= 1024 and i < len(size_names) - 1:
        size_bytes /= 1024.0
        i += 1
    return f"{size_bytes:.2f} {size_names[i]}"

def get_file_metadata(file_path: Path) -> Dict[str, Any]:
    """Get basic metadata for a file."""
    try:
        stat_result = file_path.stat()
        return {
            "path": str(file_path),
            "size": stat_result.st_size,
            "mtime": stat_result.st_mtime,
            "is_dir": file_path.is_dir(),
            "is_file": file_path.is_file(),
            "is_hidden": is_hidden(file_path),
            "is_system": is_system_file(file_path),
        }
    except OSError:
        return None

# --- Hashing & Caching ---

def calculate_file_hash(file_path: Path, algorithm: str = "sha256") -> str:
    """Calculate the hash of a file."""
    hash_func = hashlib.new(algorithm)
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_func.update(chunk)
    return hash_func.hexdigest()

class HashCache:
    """A simple cache for file hashes to avoid re-computing them."""
    
    def __init__(self):
        self._cache: Dict[Path, str] = {}
        self._mtime_cache: Dict[Path, float] = {}

    def get_hash(self, file_path: Path, hash_bytes: int = 1024 * 1024) -> Optional[str]:
        """Get the hash for a file, using the cache if possible."""
        try:
            current_mtime = file_path.stat().st_mtime
        except OSError:
            return None

        if (file_path in self._cache and 
            file_path in self._mtime_cache and 
            self._mtime_cache[file_path] == current_mtime):
            return self._cache[file_path]

        try:
            with open(file_path, 'rb') as f:
                chunk = f.read(hash_bytes)
                file_hash = hashlib.sha256(chunk).hexdigest()
            
            self._cache[file_path] = file_hash
            self._mtime_cache[file_path] = current_mtime
            return file_hash
        except (OSError, IOError):
            return None
            
    def clear(self):
        """Clear the cache."""
        self._cache.clear()
        self._mtime_cache.clear()

# --- File & Directory Skipping Logic ---

def is_hidden(file_path: Path) -> bool:
    """Check if a file or directory is hidden."""
    if file_path.name.startswith('.'):
        return True
    if os.name == 'nt':
        try:
            attribute = file_path.stat().st_file_attributes
            return attribute & (stat.FILE_ATTRIBUTE_HIDDEN | stat.FILE_ATTRIBUTE_SYSTEM)
        except (AttributeError, ImportError):
            pass
    return False

def is_system_file(file_path: Path) -> bool:
    """
    Determine if a file or directory is a critical system file.
    This is a heuristic and may not be 100% accurate.
    """
    # Check against a list of known system file/directory names
    if file_path.name.lower() in SYSTEM_NAMES:
        return True
        
    # On Windows, check the file attributes
    if os.name == 'nt':
        try:
            attribute = file_path.stat().st_file_attributes
            return bool(attribute & stat.FILE_ATTRIBUTE_SYSTEM)
        except (AttributeError, ImportError):
            pass
            
    # On Unix-like systems, check if it's in a system directory like /etc, /bin, /sbin, /usr
    if platform.system() != "Windows":
        try:
            parts = file_path.resolve().parts
            if len(parts) > 1 and parts[1] in {"bin", "sbin", "etc", "lib", "usr", "var", "opt"}:
                return True
        except (OSError, RuntimeError):
            pass # Can happen with broken symlinks
            
    return False

def should_skip_directory(
    dir_path: Path, 
    include_hidden: bool = False, 
    include_system: bool = False,
    custom_skip_patterns: Optional[List[str]] = None
) -> bool:
    """Determine if a directory should be skipped during a scan."""
    skip_patterns = set(DEFAULT_SKIP_DIRS)
    if custom_skip_patterns:
        skip_patterns.update(custom_skip_patterns)
        
    if dir_path.name in skip_patterns:
        return True
    if not include_hidden and is_hidden(dir_path):
        return True
    if not include_system and is_system_file(dir_path):
        return True
    if not os.access(dir_path, os.R_OK):
        return True
    return False

def should_skip_file(
    file_path: Path,
    min_size_bytes: int = 0,
    include_hidden: bool = False,
    include_system: bool = False,
    custom_skip_extensions: Optional[List[str]] = None
) -> bool:
    """Determine if a file should be skipped during a scan."""
    try:
        if file_path.stat().st_size < min_size_bytes:
            return True
    except OSError:
        return True # Can't access file, so skip it
        
    if not include_hidden and is_hidden(file_path):
        return True
    if not include_system and is_system_file(file_path):
        return True
        
    skip_extensions = set(DEFAULT_SKIP_EXTENSIONS)
    if custom_skip_extensions:
        normalized_exts = {ext if ext.startswith('.') else f'.{ext}' for ext in custom_skip_extensions}
        skip_extensions.update(normalized_exts)
        
    if file_path.suffix.lower() in skip_extensions:
        return True
        
    return False