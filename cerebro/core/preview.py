# cerebro/core/preview.py
"""
File preview functionality.
"""

import logging
import os
import platform
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

_SAFE_PREVIEW_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff", ".heic", ".svg",
    ".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v",
    ".mp3", ".flac", ".wav", ".aac", ".ogg", ".m4a",
    ".pdf", ".txt", ".md", ".docx", ".xlsx", ".pptx", ".csv",
}


class PreviewManager:
    """Manages file previews."""

    def preview_file(self, path: Path) -> bool:
        """Preview a file using system default application."""
        try:
            path = Path(path)
            if not path.exists():
                return False

            if path.suffix.lower() not in _SAFE_PREVIEW_EXTENSIONS:
                logger.warning("Preview blocked for unsafe extension: %s", path.suffix)
                return False

            if platform.system() == "Darwin":
                subprocess.run(["open", str(path)], check=False, shell=False)
            elif platform.system() == "Windows":
                os.startfile(str(path))
            else:
                subprocess.run(["xdg-open", str(path)], check=False, shell=False)
            return True

        except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError) as e:
            logger.info("Preview failed for %s: %s", path, e)
            return False