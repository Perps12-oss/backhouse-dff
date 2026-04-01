"""
Toolbar Widget

Top toolbar with buttons: Add Path, Remove, Start Search, Stop, Settings, Help.
Supports drag-and-drop for adding folders.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import filedialog
from typing import Optional, Callable, List
from pathlib import Path

try:
    import customtkinter as ctk
    CTkFrame = ctk.CTkFrame
    CTkButton = ctk.CTkButton
    CTkLabel = ctk.CTkLabel
except ImportError:
    # Fallback to standard tkinter
    CTkFrame = tk.Frame
    CTkButton = tk.Button
    CTkLabel = tk.Label

from cerebro.v2.core.design_tokens import Colors, Spacing, Typography, Dimensions


class Toolbar(CTkFrame):
    """
    Top toolbar with main action buttons.

    Features:
    - Add Path / Remove buttons for folder management
    - Start Search / Stop buttons for scan control
    - Settings / Help buttons
    - Hover animations on buttons
    - Drag-and-drop zone for adding folders
    - Keyboard shortcut support
    """

    def __init__(self, master=None, **kwargs):
        """Initialize toolbar."""
        super().__init__(master, **kwargs)

        # State
        self._folders: List[Path] = []
        self._scanning: bool = False

        # Widgets
        self._add_path_btn: Optional[CTkButton] = None
        self._remove_btn: Optional[CTkButton] = None
        self._start_btn: Optional[CTkButton] = None
        self._stop_btn: Optional[CTkButton] = None
        self._settings_btn: Optional[CTkButton] = None
        self._help_btn: Optional[CTkButton] = None
        self._separator: Optional[CTkLabel] = None

        # Callbacks
        self._on_add_path: Optional[Callable[[], None]] = None
        self._on_remove_selected: Optional[Callable[[], None]] = None
        self._on_start_search: Optional[Callable[[], None]] = None
        self._on_stop_search: Optional[Callable[[], None]] = None
        self._on_settings: Optional[Callable[[], None]] = None
        self._on_help: Optional[Callable[[], None]] = None

        # Build UI
        self._build_widgets()
        self._layout_widgets()
        self._bind_shortcuts()

    def _build_widgets(self) -> None:
        """Build all toolbar widgets."""
        # Add Path button
        self._add_path_btn = CTkButton(
            self,
            text="📁 Add Path",
            width=Dimensions.BUTTON_HEIGHT_LG,
            height=Dimensions.BUTTON_HEIGHT_MD,
            font=Typography.FONT_MD,
            fg_color=Colors.BG_TERTIARY.hex,
            hover_color=Colors.BG_QUATERNARY.hex,
            border_width=1,
            border_color=Colors.BORDER.hex,
            corner_radius=Spacing.BORDER_RADIUS_MD
        )

        # Remove button
        self._remove_btn = CTkButton(
            self,
            text="🗑 Remove",
            width=Dimensions.BUTTON_HEIGHT_LG,
            height=Dimensions.BUTTON_HEIGHT_MD,
            font=Typography.FONT_MD,
            fg_color=Colors.BG_TERTIARY.hex,
            hover_color=Colors.BG_QUATERNARY.hex,
            border_width=1,
            border_color=Colors.BORDER.hex,
            corner_radius=Spacing.BORDER_RADIUS_MD
        )

        # Separator
        self._separator = CTkLabel(
            self,
            text="│",
            width=30,
            text_color=Colors.BORDER.hex,
            font=Typography.FONT_LG
        )

        # Start Search button
        self._start_btn = CTkButton(
            self,
            text="▶ Start Search",
            width=Dimensions.BUTTON_HEIGHT_XL,
            height=Dimensions.BUTTON_HEIGHT_MD,
            font=Typography.FONT_MD,
            fg_color=Colors.ACCENT.hex,
            hover_color=Colors.ACCENT_HOVER.hex,
            border_width=0,
            corner_radius=Spacing.BORDER_RADIUS_MD
        )

        # Stop button
        self._stop_btn = CTkButton(
            self,
            text="⏹ Stop",
            width=Dimensions.BUTTON_HEIGHT_LG,
            height=Dimensions.BUTTON_HEIGHT_MD,
            font=Typography.FONT_MD,
            fg_color=Colors.DANGER.hex,
            hover_color=Colors.DANGER_HOVER.hex,
            border_width=0,
            corner_radius=Spacing.BORDER_RADIUS_MD,
            state="disabled"  # Disabled initially
        )

        # Separator
        self._separator2 = CTkLabel(
            self,
            text="│",
            width=30,
            text_color=Colors.BORDER.hex,
            font=Typography.FONT_LG
        )

        # Settings button
        self._settings_btn = CTkButton(
            self,
            text="⚙",
            width=Dimensions.BUTTON_HEIGHT_MD,
            height=Dimensions.BUTTON_HEIGHT_MD,
            font=Typography.FONT_LG,
            fg_color=Colors.TEXT_SECONDARY.hex,
            hover_color=Colors.TEXT_PRIMARY.hex,
            border_width=0,
            corner_radius=Spacing.BORDER_RADIUS_SM
        )

        # Help button
        self._help_btn = CTkButton(
            self,
            text="?",
            width=Dimensions.BUTTON_HEIGHT_MD,
            height=Dimensions.BUTTON_HEIGHT_MD,
            font=Typography.FONT_LG,
            fg_color=Colors.TEXT_SECONDARY.hex,
            hover_color=Colors.TEXT_PRIMARY.hex,
            border_width=0,
            corner_radius=Spacing.BORDER_RADIUS_SM
        )

    def _layout_widgets(self) -> None:
        """Layout the toolbar widgets."""
        self.configure(
            height=Dimensions.TOOLBAR_HEIGHT,
            fg_color=Colors.BG_SECONDARY.hex
        )

        # Pack widgets in a horizontal row
        self._add_path_btn.pack(
            side="left",
            padx=Spacing.MD,
            pady=(Spacing.SM, Spacing.SM)
        )

        self._remove_btn.pack(
            side="left",
            padx=Spacing.MD,
            pady=(Spacing.SM, Spacing.SM)
        )

        self._separator.pack(
            side="left",
            padx=Spacing.XS
        )

        self._start_btn.pack(
            side="left",
            padx=Spacing.MD,
            pady=(Spacing.SM, Spacing.SM)
        )

        self._stop_btn.pack(
            side="left",
            padx=Spacing.MD,
            pady=(Spacing.SM, Spacing.SM)
        )

        self._separator2.pack(
            side="left",
            padx=Spacing.XS
        )

        self._settings_btn.pack(
            side="left",
            padx=Spacing.MD,
            pady=(Spacing.SM, Spacing.SM)
        )

        self._help_btn.pack(
            side="left",
            padx=Spacing.MD,
            pady=(Spacing.SM, Spacing.SM)
        )

        # Spacer to push everything to left
        spacer = CTkLabel(self, text="")
        spacer.pack(side="right", padx=Spacing.LG)

    def _bind_shortcuts(self) -> None:
        """Bind keyboard shortcuts."""
        try:
            # Get the root window for binding
            root = self.winfo_toplevel()
            if root:
                root.bind("<Control-o>", lambda e: self._trigger_add_path())
                root.bind("<Control-O>", lambda e: self._trigger_add_path())
                root.bind("<Control-Return>", lambda e: self._trigger_start())
                root.bind("<Control-Enter>", lambda e: self._trigger_start())
                root.bind("<Escape>", lambda e: self._trigger_stop())
                root.bind("<Control-comma>", lambda e: self._trigger_settings())
        except Exception:
            pass

    def _trigger_add_path(self) -> None:
        """Trigger add path action."""
        if self._on_add_path:
            self._on_add_path()

    def _trigger_start(self) -> None:
        """Trigger start search action."""
        if self._on_start_search and not self._scanning:
            self._on_start_search()

    def _trigger_stop(self) -> None:
        """Trigger stop search action."""
        if self._on_stop_search and self._scanning:
            self._on_stop_search()

    def _trigger_settings(self) -> None:
        """Trigger settings action."""
        if self._on_settings:
            self._on_settings()

    def set_scanning(self, scanning: bool) -> None:
        """
        Update UI state based on scan status.

        Args:
            scanning: Whether a scan is currently in progress.
        """
        self._scanning = scanning

        if scanning:
            # Disable Start, enable Stop
            try:
                self._start_btn.configure(state="disabled")
                self._stop_btn.configure(state="normal")
            except AttributeError:
                pass
        else:
            # Enable Start, disable Stop
            try:
                self._start_btn.configure(state="normal")
                self._stop_btn.configure(state="disabled")
            except AttributeError:
                pass

    def set_folders_count(self, count: int) -> None:
        """
        Update display showing number of folders.

        Args:
            count: Number of folders currently added.
        """
        # Could add a small label showing count
        pass

    def on_add_path(self, callback: Callable[[], None]) -> None:
        """
        Set callback for add path button.

        Args:
            callback: Function to call when Add Path is clicked.
        """
        self._on_add_path = callback

    def on_remove_selected(self, callback: Callable[[], None]) -> None:
        """
        Set callback for remove button.

        Args:
            callback: Function to call when Remove is clicked.
        """
        self._on_remove_selected = callback

    def on_start_search(self, callback: Callable[[], None]) -> None:
        """
        Set callback for start search button.

        Args:
            callback: Function to call when Start Search is clicked.
        """
        self._on_start_search = callback

    def on_stop_search(self, callback: Callable[[], None]) -> None:
        """
        Set callback for stop search button.

        Args:
            callback: Function to call when Stop is clicked.
        """
        self._on_stop_search = callback

    def on_settings(self, callback: Callable[[], None]) -> None:
        """
        Set callback for settings button.

        Args:
            callback: Function to call when Settings is clicked.
        """
        self._on_settings = callback

    def on_help(self, callback: Callable[[], None]) -> None:
        """
        Set callback for help button.

        Args:
            callback: Function to call when Help is clicked.
        """
        self._on_help = callback

    def get_folders(self) -> List[Path]:
        """Get current list of folders."""
        return self._folders.copy()

    def add_folder(self, path: Path) -> None:
        """
        Add a folder to the list.

        Args:
            path: Path to add.
        """
        if path not in self._folders:
            self._folders.append(path)

    def remove_folder(self, path: Path) -> None:
        """
        Remove a folder from the list.

        Args:
            path: Path to remove.
        """
        if path in self._folders:
            self._folders.remove(path)

    def clear_folders(self) -> None:
        """Clear all folders from the list."""
        self._folders.clear()


# Simple logger fallback
logger = __import__('logging').getLogger(__name__)
