# cerebro/core/preview.py
"""
File preview functionality.
"""

from pathlib import Path
from typing import Optional
import subprocess
import os
import platform

class PreviewManager:
    """Manages file previews."""
    
    def preview_file(self, path: Path) -> bool:
        """Preview a file using system default application."""
        try:
            if not path.exists():
                return False
            
            if platform.system() == "Darwin":  # macOS
                subprocess.run(["open", str(path)], check=False)
            elif platform.system() == "Windows":
                os.startfile(str(path))
            else:  # Linux
                subprocess.run(["xdg-open", str(path)], check=False)
            return True
            
        except Exception as e:
            print(f"[Preview] Failed to preview {path}: {e}")
            return False