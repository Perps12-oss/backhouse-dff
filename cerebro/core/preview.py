import logging
# cerebro/core/preview.py
"""
File preview functionality.
"""

from pathlib import Path
from typing import Optional
import subprocess
import os
import platform
logger = logging.getLogger(__name__)

class PreviewManager:
    """Manages file previews."""
    
    def preview_file(self, path: Path) -> bool:
        """Preview a file using system default application."""
        try:
            path = Path(path)
            if not path.exists():
                return False
            
            if platform.system() == "Darwin":  # macOS
                subprocess.run(["open", str(path)], check=False, shell=False)
            elif platform.system() == "Windows":
                os.startfile(str(path))
            else:  # Linux
                subprocess.run(["xdg-open", str(path)], check=False, shell=False)
            return True
            
        except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError) as e:
            logger.info(f"[Preview] Failed to preview {path}: {e}")
            return False