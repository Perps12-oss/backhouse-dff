"""
Main Window

Root CTk() window with complete Ashisoft-style single-window layout.
Handles window lifecycle, panel organization, and keyboard shortcuts.
"""

from __future__ import annotations

import tkinter as tk
from typing import Optional, Callable, List
from pathlib import Path

try:
    import customtkinter as ctk
    CTk = ctk.CTk
    CTkFrame = ctk.CTkFrame
    CTkLabel = ctk.CTkLabel
    # CTkPanedWindow doesn't exist in customtkinter, use tkinter.PanedWindow
    CTkPanedWindow = tk.PanedWindow
except ImportError:
    CTk = tk.Tk
    CTkFrame = tk.Frame
    CTkLabel = tk.Label
    CTkPanedWindow = tk.PanedWindow

from cerebro.v2.core.design_tokens import (
    Colors, Spacing, Typography, Dimensions
)
from cerebro.v2.ui.toolbar import Toolbar
from cerebro.v2.ui.mode_tabs import ModeTabs
from cerebro.v2.ui.status_bar import StatusBar
from cerebro.v2.ui.selection_bar import SelectionBar
from cerebro.v2.ui.settings_dialog import SettingsDialog, Settings
from cerebro.v2.ui.folder_panel import FolderPanel
from cerebro.v2.ui.results_panel import ResultsPanel
from cerebro.v2.ui.preview_panel import PreviewPanel


class MainWindow(CTk):
    """
    Main application window with complete single-window layout.

    Layout structure:
    ┌─────────────────────────────────────────────────────────────┐
    │  TOOLBAR                                                   │
    ├─────────────────────────────────────────────────────────────┤
    │  MODE TABS                                                  │
    ├──────────────┬──────────────────────────────────────────────┤
    │  LEFT PANEL  │  CENTER PANEL — Results                     │
    │              │                                              │
    │  ┌─────────┐ │  ┌────────────────────────────────────┐   │
    │  │ Folders │ │  │ CheckTreeview with groups         │   │
    │  │ List   │ │  │                                │   │
    │  └─────────┘ │  └────────────────────────────────────┘   │
    ├──────────────┴──────────────────────────────────────────────┤
    │  SELECTION ASSISTANT                                      │
    ├─────────────────────────────────────────────────────────────┤
    │  PREVIEW PANEL (collapsible)                               │
    ├─────────────────────────────────────────────────────────────┤
    │  STATUS BAR                                                │
    └─────────────────────────────────────────────────────────────┘
    """

    def __init__(self):
        """Initialize main window."""
        super().__init__()

        # Window state
        self._current_scan_mode: str = "files"
        self._scanning: bool = False
        self._preview_collapsed: bool = False

        # Initialize components
        self._setup_window()
        self._setup_theme()
        self._build_ui()
        self._bind_shortcuts()
        self._bind_window_events()

    def _setup_window(self) -> None:
        """Configure window properties."""
        self.title("Cerebro v2 — Ashisoft Edition")
        self.geometry(
            f"{Dimensions.WINDOW_DEFAULT_WIDTH}x{Dimensions.WINDOW_DEFAULT_HEIGHT}"
        )
        self.minsize(
            Dimensions.WINDOW_MIN_WIDTH,
            Dimensions.WINDOW_MIN_HEIGHT
        )

        # Center window on screen
        self.center_window()

    def _setup_theme(self) -> None:
        """Configure CustomTkinter theme."""
        try:
            ctk.set_appearance_mode("dark")
            ctk.set_default_color_theme("blue")
        except (NameError, AttributeError):
            pass

    def center_window(self) -> None:
        """Center the window on the primary display."""
        self.update_idletasks()
        width = self.winfo_width()
        height = self.winfo_height()
        x = (self.winfo_screenwidth() // 2) - (width // 2)
        y = (self.winfo_screenheight() // 2) - (height // 2)
        self.geometry(f"{width}x{height}+{x}+{y}")

    def _build_ui(self) -> None:
        """Build the complete UI layout."""
        # Configure main frame
        main_frame = CTkFrame(
            self,
            fg_color=Colors.BG_PRIMARY.hex
        )
        main_frame.pack(fill="both", expand=True)

        # Vertical layout container
        self._content_container = CTkFrame(main_frame)
        self._content_container.pack(fill="both", expand=True)

        # Build components top-to-bottom
        self._build_toolbar()
        self._build_mode_tabs()
        self._build_horizontal_paned()
        self._build_selection_bar()
        self._build_preview_panel()
        self._build_status_bar()

    def _build_toolbar(self) -> None:
        """Build and install toolbar."""
        self._toolbar = Toolbar(
            self._content_container,
            height=Dimensions.TOOLBAR_HEIGHT
        )
        self._toolbar.pack(fill="x", padx=Spacing.MD, pady=(Spacing.MD, 0))

        # Wire callbacks
        self._toolbar.on_add_path(self._on_add_path)
        self._toolbar.on_remove_selected(self._on_remove_path)
        self._toolbar.on_start_search(self._on_start_search)
        self._toolbar.on_stop_search(self._on_stop_search)
        self._toolbar.on_settings(self._on_settings)
        self._toolbar.on_help(self._on_help)

    def _build_mode_tabs(self) -> None:
        """Build and install mode tabs."""
        self._mode_tabs = ModeTabs(
            self._content_container,
            height=Dimensions.MODE_TABS_HEIGHT
        )
        self._mode_tabs.pack(fill="x", padx=Spacing.MD, pady=Spacing.SM)

        # Wire callback
        self._mode_tabs.on_mode_changed(self._on_mode_changed)

    def _build_horizontal_paned(self) -> None:
        """Build the horizontal paned window for main content area."""
        try:
            self._horizontal_paned = CTkPanedWindow(
                self._content_container,
                orientation="horizontal"
            )
        except TypeError:
            # Fallback to standard PanedWindow
            self._horizontal_paned = tk.PanedWindow(
                self._content_container,
                orient=tk.HORIZONTAL,
                sashwidth=6,
                sashrelief="flat"
            )

        self._horizontal_paned.pack(
            fill="both",
            expand=True,
            padx=Spacing.MD,
            pady=Spacing.SM
        )

        # Create frames for actual panels
        self._left_panel_frame = CTkFrame(
            self._horizontal_paned,
            fg_color=Colors.BG_SECONDARY.hex,
            width=Dimensions.LEFT_PANEL_DEFAULT_WIDTH
        )

        self._center_panel_frame = CTkFrame(
            self._horizontal_paned,
            fg_color=Colors.BG_SECONDARY.hex
        )

        # Add frames to paned window
        try:
            self._horizontal_paned.add(
                self._left_panel_frame,
                minsize=Dimensions.LEFT_PANEL_MIN_WIDTH,
                width=Dimensions.LEFT_PANEL_DEFAULT_WIDTH
            )
            self._horizontal_paned.add(
                self._center_panel_frame,
                stretch="always"
            )
        except (AttributeError, TypeError):
            # Fallback for standard PanedWindow
            self._horizontal_paned.add(self._left_panel_frame)
            self._horizontal_paned.add(self._center_panel_frame)

        # Create and pack actual panels
        self._folder_panel = FolderPanel(self._left_panel_frame)
        self._folder_panel.pack(fill="both", expand=True)

        self._results_panel = ResultsPanel(self._center_panel_frame)
        self._results_panel.pack(fill="both", expand=True)

        # Wire folder panel callbacks
        self._folder_panel.on_folders_changed(self._on_folders_changed)
        self._folder_panel.on_protected_changed(self._on_protected_changed)
        self._folder_panel.on_options_changed(self._on_options_changed)

        # Wire results panel callbacks
        self._results_panel.on_selection_changed(self._on_selection_changed)

    def _build_selection_bar(self) -> None:
        """Build and install selection bar."""
        self._selection_bar = SelectionBar(
            self._content_container,
            height=Dimensions.BUTTON_HEIGHT_LG
        )
        self._selection_bar.pack(fill="x", padx=Spacing.MD, pady=Spacing.SM)

        # Wire callbacks
        self._selection_bar.on_apply_rule(self._on_apply_rule)
        self._selection_bar.on_select_all(self._on_select_all)
        self._selection_bar.on_deselect_all(self._on_deselect_all)
        self._selection_bar.on_invert(self._on_invert_selection)
        self._selection_bar.on_delete_selected(self._on_delete_selected)

    def _build_preview_panel(self) -> None:
        """Build and install collapsible preview panel."""
        self._preview_frame = CTkFrame(
            self._content_container,
            height=Dimensions.PREVIEW_PANEL_DEFAULT_HEIGHT,
            fg_color=Colors.BG_SECONDARY.hex
        )
        self._preview_frame.pack(fill="x", padx=Spacing.MD, pady=Spacing.SM)

        # Create and pack actual preview panel
        self._preview_panel = PreviewPanel(self._preview_frame)
        self._preview_panel.pack(fill="both", expand=True)

        # Wire preview panel callbacks
        self._preview_panel.on_keep_a(self._on_keep_a)
        self._preview_panel.on_keep_b(self._on_keep_b)

    def _build_status_bar(self) -> None:
        """Build and install status bar."""
        self._status_bar = StatusBar(
            self._content_container,
            height=Dimensions.STATUS_BAR_HEIGHT
        )
        self._status_bar.pack(fill="x", padx=Spacing.MD, pady=(0, Spacing.MD))

    def _bind_shortcuts(self) -> None:
        """Bind global keyboard shortcuts."""
        self.bind("<Control-a>", lambda e: self._on_select_all())
        self.bind("<Control-A>", lambda e: self._on_select_all())
        self.bind("<Control-d>", lambda e: self._on_deselect_all())
        self.bind("<Control-D>", lambda e: self._on_deselect_all())
        self.bind("<Control-i>", lambda e: self._on_invert_selection())
        self.bind("<Control-I>", lambda e: self._on_invert_selection())
        self.bind("<F5>", lambda e: self._on_refresh())
        self.bind("<Control-p>", lambda e: self._toggle_preview_panel())
        self.bind("<Control-P>", lambda e: self._toggle_preview_panel())
        self.bind("<Escape>", lambda e: self._on_escape())

        # Mode shortcuts (1-6)
        self.bind("<Key-1>", lambda e: self._set_mode(1))
        self.bind("<Key-2>", lambda e: self._set_mode(2))
        self.bind("<Key-3>", lambda e: self._set_mode(3))
        self.bind("<Key-4>", lambda e: self._set_mode(4))
        self.bind("<Key-5>", lambda e: self._set_mode(5))
        self.bind("<Key-6>", lambda e: self._set_mode(6))

    def _bind_window_events(self) -> None:
        """Bind window lifecycle events."""
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind("<Configure>", self._on_configure)

    # ===================
    # EVENT HANDLERS
    # ===================

    def _on_add_path(self) -> None:
        """Handle add path button."""
        from tkinter import filedialog
        path = filedialog.askdirectory(title="Select folder to scan")
        if path:
            self._folder_panel.get_scan_folders().append(Path(path))
            self._toolbar.add_folder(Path(path))
            print(f"Added folder: {path}")

    def _on_remove_path(self) -> None:
        """Handle remove path button."""
        # Remove the most recently added folder
        folders = self._folder_panel.get_scan_folders()
        if folders:
            path_to_remove = folders[-1]
            # Remove from toolbar
            if path_to_remove in self._toolbar.get_folders():
                self._toolbar.remove_folder(path_to_remove)
            # Remove from folder panel
            updated_folders = folders[:-1]
            self._folder_panel.set_scan_folders(updated_folders)
            print(f"Removed folder: {path_to_remove}")
        else:
            print("No folders to remove")

    def _on_start_search(self) -> None:
        """Handle start search button."""
        folders = self._folder_panel.get_scan_folders()
        if not folders:
            print("No folders selected for scanning")
            return

        print("Starting search...")
        self._scanning = True
        self._toolbar.set_scanning(True)
        self._status_bar.set_scanning(True)
        # TODO: Trigger scan with engine orchestrator when implemented
        # Scan mode: self.get_scan_mode()
        # Folders: folders
        # Options: self._folder_panel.get_options()

    def _on_stop_search(self) -> None:
        """Handle stop search button."""
        print("Stopping search...")
        self._scanning = False
        self._toolbar.set_scanning(False)
        self._status_bar.set_scanning(False)
        # TODO: Cancel scan with engine orchestrator when implemented

    def _on_settings(self) -> None:
        """Handle settings button."""
        # Create and show settings dialog as a modal
        SettingsDialog.show_dialog(parent=self, settings=None)

    def _on_help(self) -> None:
        """Handle help button."""
        # Create a simple help dialog
        from tkinter import messagebox
        help_text = """Cerebro v2 — Help

Keyboard Shortcuts:
Ctrl+O — Add folder
Ctrl+Enter — Start scan
Escape — Stop scan
Ctrl+A — Select all
Ctrl+D — Deselect all
Ctrl+I — Invert selection
F5 — Refresh
Ctrl+P — Toggle preview panel
1-6 — Switch scan mode

Scan Modes:
1. Files — Duplicate files by hash
2. Photos — Similar images
3. Videos — Duplicate videos
4. Music — Duplicate music files
5. Empty Folders — Find empty dirs
6. Large Files — Find large files

For more information, visit:
github.com/Perps12-oss/dedup"""
        messagebox.showinfo("Help", help_text)

    def _on_folders_changed(self, folders: List[Path]) -> None:
        """Handle folder list changes."""
        print(f"Folders changed: {len(folders)} folders")

    def _on_protected_changed(self, folders: List[Path]) -> None:
        """Handle protected folder list changes."""
        print(f"Protected folders changed: {len(folders)} folders")

    def _on_options_changed(self, mode: str, options: dict) -> None:
        """Handle scan options changes."""
        print(f"Options changed for mode {mode}: {options}")

    def _on_keep_a(self) -> None:
        """Handle keep file A button in preview."""
        print("Keep A clicked")
        # TODO: Mark file A as keeper in results

    def _on_keep_b(self) -> None:
        """Handle keep file B button in preview."""
        print("Keep B clicked")
        # TODO: Mark file B as keeper in results

    def _on_mode_changed(self, new_mode: str) -> None:
        """Handle mode tab change."""
        self._current_scan_mode = new_mode
        print(f"Mode changed to: {new_mode}")

        # Update folder panel options
        if hasattr(self, '_folder_panel') and self._folder_panel:
            self._folder_panel.set_scan_mode(new_mode)

        # Update results panel columns
        if hasattr(self, '_results_panel') and self._results_panel:
            self._results_panel.set_mode(new_mode)

    def _on_apply_rule(self, rule: str) -> None:
        """Handle apply selection rule."""
        self._results_panel.apply_selection_rule(rule)
        # Update selection bar counter
        self._selection_bar.set_selected_count(self._results_panel.get_selected_count())

    def _on_select_all(self) -> None:
        """Handle select all action."""
        # Use treeview's check_all method
        self._results_panel._treeview.check_all()
        # Update selection bar counter
        self._selection_bar.set_selected_count(self._results_panel.get_total_count())

    def _on_deselect_all(self) -> None:
        """Handle deselect all action."""
        # Use treeview's uncheck_all method
        self._results_panel._treeview.uncheck_all()
        # Update selection bar counter
        self._selection_bar.set_selected_count(0)

    def _on_invert_selection(self) -> None:
        """Handle invert selection action."""
        # Use treeview's invert_checks method
        self._results_panel._treeview.invert_checks()
        # Update selection bar counter
        selected_count = self._results_panel._treeview.get_checked_count()
        self._selection_bar.set_selected_count(selected_count)

    def _on_delete_selected(self) -> None:
        """Handle delete selected action."""
        from tkinter import messagebox

        selected_files = self._results_panel.get_selected_files()
        if not selected_files:
            messagebox.showinfo(
                "Delete Selected",
                "No files selected for deletion."
            )
            return

        reclaimable_space = self._results_panel.get_reclaimable_space()
        reclaimable_str = self._format_bytes(reclaimable_space)

        confirm = messagebox.askyesno(
            "Confirm Delete",
            f"Are you sure you want to delete {len(selected_files)} files?\n\n"
            f"Reclaimable space: {reclaimable_str}\n\n"
            f"This action cannot be undone."
        )

        if confirm:
            # TODO: Actually delete files
            print(f"Deleting {len(selected_files)} files...")
            messagebox.showinfo(
                "Delete",
                f"Deleted {len(selected_files)} files."
            )
            # Clear selection
            self._on_deselect_all()

    def _on_selection_changed(self, checked_items: List[str]) -> None:
        """Handle selection changes from results panel."""
        # Update selection bar counter
        self._selection_bar.set_selected_count(len(checked_items))
        # Enable/disable delete button based on selection
        self._selection_bar.set_delete_enabled(len(checked_items) > 0)

    def _format_bytes(self, bytes_count: int) -> str:
        """Format bytes to human-readable string."""
        if bytes_count == 0:
            return "0 B"

        units = ["B", "KB", "MB", "GB", "TB"]
        unit_index = 0
        size = float(bytes_count)

        while size >= 1024 and unit_index < len(units) - 1:
            size /= 1024
            unit_index += 1

        if unit_index == 0:
            return f"{int(size)} {units[unit_index]}"
        else:
            return f"{size:.1f} {units[unit_index]}"

    def _set_mode(self, mode_num: int) -> None:
        """Set scan mode via keyboard shortcut (1-6)."""
        from cerebro.v2.ui.mode_tabs import ScanMode
        modes = ScanMode.all_modes()
        if 1 <= mode_num <= len(modes):
            self._mode_tabs.set_mode(modes[mode_num - 1])

    def _toggle_preview_panel(self) -> None:
        """Toggle preview panel visibility."""
        if hasattr(self, '_preview_panel') and self._preview_panel:
            self._preview_panel.set_collapsed(not self._preview_panel.is_collapsed())
            self._preview_collapsed = self._preview_panel.is_collapsed()
        else:
            # Fallback to frame-level toggle if panel not available
            if self._preview_collapsed:
                self._preview_frame.pack(fill="x", padx=Spacing.MD, pady=Spacing.SM)
            else:
                self._preview_frame.pack_forget()
            self._preview_collapsed = not self._preview_collapsed

    def _on_refresh(self) -> None:
        """Handle F5 refresh."""
        print("Refresh / re-scan")
        # TODO: Re-scan current folders

    def _on_escape(self) -> None:
        """Handle Escape key."""
        if self._scanning:
            self._on_stop_search()
        else:
            # TODO: Close dialogs, cancel active operations
            pass

    def _on_configure(self, event) -> None:
        """Handle window resize."""
        # Can be used for responsive layout adjustments
        pass

    def _on_close(self) -> None:
        """Handle window close event."""
        print("Closing application...")
        # TODO: Save window state, clean up resources
        self.quit()

    # ===================
    # PUBLIC API
    # ===================

    def run(self) -> None:
        """Run the main application loop."""
        self.mainloop()

    def get_scan_mode(self) -> str:
        """Get current scan mode."""
        return self._current_scan_mode

    def get_toolbar(self) -> Toolbar:
        """Get toolbar widget reference."""
        return self._toolbar

    def get_mode_tabs(self) -> ModeTabs:
        """Get mode tabs widget reference."""
        return self._mode_tabs

    def get_status_bar(self) -> StatusBar:
        """Get status bar widget reference."""
        return self._status_bar

    def get_selection_bar(self) -> SelectionBar:
        """Get selection bar widget reference."""
        return self._selection_bar

    def get_folder_panel(self) -> FolderPanel:
        """Get folder panel widget reference."""
        return self._folder_panel

    def get_results_panel(self) -> ResultsPanel:
        """Get results panel widget reference."""
        return self._results_panel

    def get_preview_panel(self) -> PreviewPanel:
        """Get preview panel widget reference."""
        return self._preview_panel

    def get_left_panel_frame(self) -> CTkFrame:
        """Get left panel frame (for folder panel)."""
        return self._left_panel_frame

    def get_center_panel_frame(self) -> CTkFrame:
        """Get center panel frame (for results panel)."""
        return self._center_panel_frame

    def get_preview_frame(self) -> CTkFrame:
        """Get preview frame (for preview panel)."""
        return self._preview_frame


def run_app() -> None:
    """Entry point for running Cerebro v2."""
    app = MainWindow()
    app.run()


if __name__ == "__main__":
    run_app()


# Simple logger fallback
logger = __import__('logging').getLogger(__name__)
