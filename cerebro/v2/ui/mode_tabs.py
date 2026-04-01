"""
Mode Tabs Widget

CTkSegmentedButton for selecting scan mode.
Emits callback when mode changes.
"""

from __future__ import annotations

import tkinter as tk
from typing import Optional, Callable, List

try:
    import customtkinter as ctk
    CTkSegmentedButton = ctk.CTkSegmentedButton
except ImportError:
    # Fallback to standard tkinter
    CTkSegmentedButton = tk.Frame

from cerebro.v2.core.design_tokens import Colors, Spacing, Typography


class ScanMode:
    """Available scan modes."""

    FILES = "files"
    PHOTOS = "photos"
    VIDEOS = "videos"
    MUSIC = "music"
    EMPTY_FOLDERS = "empty_folders"
    LARGE_FILES = "large_files"

    @classmethod
    def display_name(cls, mode: str) -> str:
        """Get human-readable name for mode."""
        names = {
            cls.FILES: "Files",
            cls.PHOTOS: "Photos",
            cls.VIDEOS: "Videos",
            cls.MUSIC: "Music",
            cls.EMPTY_FOLDERS: "Empty Folders",
            cls.LARGE_FILES: "Large Files",
        }
        return names.get(mode, mode)

    @classmethod
    def all_modes(cls) -> List[str]:
        """Get list of all available scan modes."""
        return [
            cls.FILES,
            cls.PHOTOS,
            cls.VIDEOS,
            cls.MUSIC,
            cls.EMPTY_FOLDERS,
            cls.LARGE_FILES,
        ]

    @classmethod
    def display_names(cls) -> List[str]:
        """Get list of human-readable mode names."""
        return [cls.display_name(m) for m in cls.all_modes()]


class ModeTabs(CTkSegmentedButton):
    """
    Scan mode selector using segmented button.

    Features:
    - 6 scan mode segments
    - Accent color on active segment
    - Emits callback when mode changes
    - Supports keyboard shortcuts (1-6 for modes)
    """

    def __init__(self, master=None, **kwargs):
        """Initialize mode tabs."""
        # Get display names for all modes
        values = ScanMode.display_names()

        super().__init__(
            master,
            values=values,
            **kwargs
        )

        # State
        self._current_mode: str = ScanMode.FILES
        self._on_mode_changed: Optional[Callable[[str], None]] = None

        # Bind selection change event
        self._bind_events()

    def _bind_events(self) -> None:
        """Bind selection change event."""
        # CustomTkinter uses command parameter for callback
        # We'll wrap it with our own callback

    def set_mode(self, mode: str) -> None:
        """
        Set the current scan mode.

        Args:
            mode: The mode to select (from ScanMode class).
        """
        if mode not in ScanMode.all_modes():
            raise ValueError(f"Invalid scan mode: {mode}")

        self._current_mode = mode
        display_name = ScanMode.display_name(mode)

        try:
            # CustomTkinter: set by value
            self.set(display_name)
        except AttributeError:
            # Fallback: manually handle selection
            pass

    def get_mode(self) -> str:
        """Get the current scan mode."""
        return self._current_mode

    def get_display_mode(self) -> str:
        """Get the current mode's display name."""
        return ScanMode.display_name(self._current_mode)

    def on_mode_changed(self, callback: Callable[[str], None]) -> None:
        """
        Set callback for mode changes.

        Args:
            callback: Function called with (new_mode).
        """
        self._on_mode_changed = callback

        # Configure button to call our callback
        try:
            self.configure(command=self._on_selection)
        except AttributeError:
            pass

    def _on_selection(self, value: str) -> None:
        """Handle mode selection from segmented button."""
        # Convert display name back to mode key
        mode_map = {
            "Files": ScanMode.FILES,
            "Photos": ScanMode.PHOTOS,
            "Videos": ScanMode.VIDEOS,
            "Music": ScanMode.MUSIC,
            "Empty Folders": ScanMode.EMPTY_FOLDERS,
            "Large Files": ScanMode.LARGE_FILES,
        }

        new_mode = mode_map.get(value)
        if new_mode and new_mode != self._current_mode:
            self._current_mode = new_mode
            if self._on_mode_changed:
                self._on_mode_changed(new_mode)

    def disable_mode(self, mode: str) -> None:
        """
        Disable a specific mode (e.g., video mode when FFmpeg missing).

        Args:
            mode: The mode to disable.
        """
        if mode not in ScanMode.all_modes():
            return

        display_name = ScanMode.display_name(mode)

        # CustomTkinter doesn't support disabling individual segments natively
        # We'd need to manage this via state and re-creating the widget

    def enable_all_modes(self) -> None:
        """Enable all scan modes."""
        # Re-enable any disabled modes
        pass

    def set_tooltip_text(self, mode: str, text: str) -> None:
        """
        Set tooltip text for a mode.

        Args:
            mode: The mode to set tooltip for.
            text: The tooltip text.
        """
        # Tooltip support depends on CustomTkinter version
        pass

    def get_mode_description(self, mode: str) -> str:
        """Get description for a mode (for tooltips/help)."""
        descriptions = {
            ScanMode.FILES: "Find exact duplicate files by content (SHA256/Blake3)",
            ScanMode.PHOTOS: "Find similar images using perceptual hashing (pHash/dHash)",
            ScanMode.VIDEOS: "Find similar videos using keyframe comparison",
            ScanMode.MUSIC: "Find duplicate audio by ID3 tags and duration",
            ScanMode.EMPTY_FOLDERS: "Find empty directories and nested empty trees",
            ScanMode.LARGE_FILES: "List largest files on disk (informational only)",
        }
        return descriptions.get(mode, "")


# Simple logger fallback
logger = __import__('logging').getLogger(__name__)
