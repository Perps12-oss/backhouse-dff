"""
Main Window

Root CTk() window with complete Ashisoft-style single-window layout.
Handles window lifecycle, panel organization, and keyboard shortcuts.
"""

from __future__ import annotations

import tkinter as tk
from typing import Optional, Callable, List, Dict, Any
from pathlib import Path
import time

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
    Spacing, Typography, Dimensions
)
from cerebro.v2.core.theme_bridge_v2 import theme_color, subscribe_to_theme, set_ctk_appearance_mode
from cerebro.v2.ui.toolbar import Toolbar
from cerebro.v2.ui.mode_tabs import ModeTabs
from cerebro.v2.ui.status_bar import StatusBar, StatusBarMetrics
from cerebro.v2.ui.selection_bar import SelectionBar
from cerebro.v2.ui.settings_dialog import SettingsDialog, Settings
from cerebro.v2.ui.folder_panel import FolderPanel
from cerebro.v2.ui.results_panel import ResultsPanel, DuplicateGroup as ResultsDuplicateGroup
from cerebro.v2.ui.preview_panel import PreviewPanel
from cerebro.engines.orchestrator import ScanOrchestrator
from cerebro.engines.base_engine import (
    ScanProgress, ScanState, DuplicateGroup, DuplicateFile
)


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

        # Scan state
        self._scan_start_time: float = 0.0
        self._polling_enabled: bool = False
        self._selected_file_ids: List[str] = []  # For preview panel

        # Scan results (core.DuplicateGroup format)
        self._scan_results: List[DuplicateGroup] = []

        # Create orchestrator
        self._orchestrator = ScanOrchestrator()
        self._orchestrator.set_mode("files")

        # Initialize components
        self._setup_window()
        self._setup_theme()
        self._build_ui()
        self._bind_shortcuts()
        self._bind_window_events()
        subscribe_to_theme(self, self._apply_theme)

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
            ctk.set_default_color_theme("blue")
        except (NameError, AttributeError):
            pass
        set_ctk_appearance_mode()

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
        self._main_frame = CTkFrame(
            self,
            fg_color=theme_color("base.background")
        )
        self._main_frame.pack(fill="both", expand=True)

        # Vertical layout container
        self._content_container = CTkFrame(self._main_frame)
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
            fg_color=theme_color("panel.background"),
            width=Dimensions.LEFT_PANEL_DEFAULT_WIDTH
        )

        self._center_panel_frame = CTkFrame(
            self._horizontal_paned,
            fg_color=theme_color("panel.background")
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
        self._folder_panel.on_collapse_toggled(self._on_folder_panel_collapse)

        # Wire results panel callbacks
        self._results_panel.on_selection_changed(self._on_selection_changed)
        self._results_panel.on_request_add_folder(self._on_add_path)
        self._results_panel.on_request_start_search(self._on_start_search)

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
            fg_color=theme_color("panel.background")
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
            from tkinter import messagebox
            messagebox.showwarning("No Folders", "Please add at least one folder to scan.")
            return

        # Clear previous results
        self._scan_results.clear()
        self._results_panel.clear()
        self._status_bar.reset()

        # Reset state
        self._scan_start_time = time.time()
        self._scanning = True
        self._toolbar.set_scanning(True)
        self._status_bar.set_scanning(True)

        # Get scan parameters
        scan_mode = self.get_scan_mode()
        protected_folders = self._folder_panel.get_protected_folders()
        scan_options = self._folder_panel.get_options()

        print(f"Starting scan in {scan_mode} mode...")
        print(f"Folders: {[str(f) for f in folders]}")
        print(f"Protected: {[str(f) for f in protected_folders]}")
        print(f"Options: {scan_options}")

        # Collapse left panel so results get full width
        self._folder_panel.set_collapsed(True)

        # Set mode and start scan
        self._orchestrator.set_mode(scan_mode)

        try:
            self._orchestrator.start_scan(
                folders=folders,
                protected=protected_folders,
                options=scan_options,
                progress_callback=self._on_scan_progress
            )
            # Start polling for progress updates
            self._start_progress_polling()
        except RuntimeError as e:
            print(f"Failed to start scan: {e}")
            self._on_scan_finished()

    def _on_stop_search(self) -> None:
        """Handle stop search button."""
        print("Stopping search...")
        self._orchestrator.cancel()
        # Stop will be detected via progress callback
        # Don't reset state yet - wait for scan to fully stop

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

    def _on_folder_panel_collapse(self, collapsed: bool) -> None:
        """Resize paned window sash when left panel collapses/expands."""
        try:
            if collapsed:
                self._horizontal_paned.sash_place(
                    0, self._folder_panel.COLLAPSED_WIDTH, 0)
            else:
                self._horizontal_paned.sash_place(
                    0, Dimensions.LEFT_PANEL_DEFAULT_WIDTH, 0)
        except Exception:
            pass  # PanedWindow variant may not support sash_place

    def _on_folders_changed(self, folders: List[Path]) -> None:
        """Handle folder list changes."""
        print(f"Folders changed: {len(folders)} folders")

    def _on_protected_changed(self, folders: List[Path]) -> None:
        """Handle protected folder list changes."""
        print(f"Protected folders changed: {len(folders)} folders")

    def _on_options_changed(self, mode: str, options: dict) -> None:
        """Handle scan options changes."""
        print(f"Options changed for mode {mode}: {options}")

    # ===================
    # SCAN INTEGRATION
    # ===================

    def _on_scan_progress(self, progress: ScanProgress) -> None:
        """
        Handle progress updates from scan engine.

        Args:
            progress: ScanProgress object with current scan state.
        """
        # Update status bar with scan metrics
        self._update_status_bar(progress)

        # Check if scan finished
        if progress.state in (ScanState.COMPLETED, ScanState.CANCELLED, ScanState.ERROR):
            self._on_scan_finished(progress.state)

    def _update_status_bar(self, progress: ScanProgress) -> None:
        """
        Update status bar with scan progress.

        Args:
            progress: ScanProgress object.
        """
        elapsed = time.time() - self._scan_start_time if self._scan_start_time > 0 else 0.0

        metrics = StatusBarMetrics(
            files_scanned=progress.files_scanned,
            duplicates_found=progress.duplicates_found,
            groups_found=progress.groups_found,
            bytes_reclaimable=progress.bytes_reclaimable,
            elapsed_seconds=elapsed,
            is_scanning=(progress.state == ScanState.SCANNING),
            progress_percent=min(100.0, elapsed * 5) if progress.files_total > 0 else 0.0
        )

        self._status_bar.update_metrics(metrics)

        # Show current file if available
        if progress.current_file and progress.state == ScanState.SCANNING:
            self._status_bar.after(0, lambda: self._status_bar._elapsed_label.configure(
                text=f"Scanning: {Path(progress.current_file).name[:40]}..."
            ))

    def _start_progress_polling(self) -> None:
        """Start periodic polling for scan progress updates."""
        if self._polling_enabled:
            return

        self._polling_enabled = True

        def poll():
            if not self._polling_enabled or not self._scanning:
                return

            # Get current progress from orchestrator
            progress = self._orchestrator.get_progress()
            self._update_status_bar(progress)

            # Continue polling
            self.after(200, poll)

        self.after(200, poll)

    def _stop_progress_polling(self) -> None:
        """Stop periodic polling for scan progress updates."""
        self._polling_enabled = False

    def _on_scan_finished(self, final_state: ScanState = ScanState.COMPLETED) -> None:
        """
        Handle scan completion.

        Args:
            final_state: The final state of the scan (completed/cancelled/error).
        """
        # Stop polling
        self._stop_progress_polling()

        # Update UI state
        self._scanning = False
        self._toolbar.set_scanning(False)
        self._status_bar.set_scanning(False)

        # Re-expand left panel so user can adjust folders before next scan
        self._folder_panel.set_collapsed(False)

        # Get results from orchestrator
        self._scan_results = self._orchestrator.get_results()
        print(f"Scan finished with state: {final_state}")
        print(f"Found {len(self._scan_results)} duplicate groups")

        # Load results into panel
        if self._scan_results:
            self._load_results_to_panel()

        # Show completion message
        from tkinter import messagebox
        if final_state == ScanState.COMPLETED:
            total_files = sum(len(g.files) for g in self._scan_results)
            reclaimable = sum(g.reclaimable for g in self._scan_results)
            reclaimable_str = self._format_bytes(reclaimable)
            messagebox.showinfo(
                "Scan Complete",
                f"Found {len(self._scan_results)} duplicate groups\n"
                f"Total files: {total_files}\n"
                f"Space reclaimable: {reclaimable_str}"
            )
        elif final_state == ScanState.CANCELLED:
            messagebox.showinfo("Scan Cancelled", "Scan was cancelled by user.")
        elif final_state == ScanState.ERROR:
            messagebox.showerror("Scan Error", "An error occurred during scanning.")

    def _load_results_to_panel(self) -> None:
        """Load scan results into the results panel."""
        # Transform core.DuplicateGroup to results panel format
        results_groups = self._transform_results(self._scan_results)
        self._results_panel.load_results(results_groups)

    def _transform_results(self, core_groups: List[DuplicateGroup]) -> List[ResultsDuplicateGroup]:
        """
        Transform core.DuplicateGroup to results panel format.

        Args:
            core_groups: List of core.DuplicateGroup objects from engine.

        Returns:
            List of results panel DuplicateGroup objects.
        """
        results_groups = []

        for core_group in core_groups:
            # Transform files
            files_list = []
            for file_obj in core_group.files:
                files_list.append({
                    "path": str(file_obj.path),
                    "size": file_obj.size,
                    "modified": file_obj.modified,
                    "similarity": file_obj.similarity,
                    "checked": False,  # Will be marked by selection rule
                    "extension": file_obj.extension or Path(file_obj.path).suffix.lower()
                })

            # Create results panel group
            total_size = sum(f["size"] for f in files_list)
            reclaimable = total_size - max(f["size"] for f in files_list) if files_list else 0

            results_group = ResultsDuplicateGroup(
                group_id=core_group.group_id,
                files=files_list,
                total_size=total_size,
                reclaimable=reclaimable
            )
            results_groups.append(results_group)

        return results_groups

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

    # ===================
    # PREVIEW INTEGRATION
    # ===================

    def _on_keep_a(self) -> None:
        """Handle keep file A button in preview."""
        if not self._selected_file_ids or len(self._selected_file_ids) < 1:
            return

        # Get the first selected file
        file_data = self._get_file_data_by_id(self._selected_file_ids[0])
        if file_data:
            # Mark this file as the keeper (unchecked)
            item_id = self._selected_file_ids[0]
            self._results_panel._treeview.set_check(item_id, False)
            # Check all other files in the same group
            self._mark_others_in_group_checked(item_id, True)
            # Update selection count
            self._on_selection_changed(self._results_panel._treeview.get_checked())

    def _on_keep_b(self) -> None:
        """Handle keep file B button in preview."""
        if not self._selected_file_ids or len(self._selected_file_ids) < 2:
            return

        # Get the second selected file
        file_data = self._get_file_data_by_id(self._selected_file_ids[1])
        if file_data:
            # Mark this file as the keeper (unchecked)
            item_id = self._selected_file_ids[1]
            self._results_panel._treeview.set_check(item_id, False)
            # Check all other files in the same group
            self._mark_others_in_group_checked(item_id, True)
            # Update selection count
            self._on_selection_changed(self._results_panel._treeview.get_checked())

    def _get_file_data_by_id(self, item_id: str) -> Optional[Dict[str, Any]]:
        """
        Get file data from results panel by item ID.

        Args:
            item_id: The item ID in format "group_idx_file_idx".

        Returns:
            File data dict or None.
        """
        # Parse item_id: group_index_file_index
        parts = item_id.split("_")
        if len(parts) != 2:
            return None

        group_id = int(parts[0])
        file_index = int(parts[1])

        # Find in filtered groups
        for group in self._results_panel._filtered_groups:
            if group.group_id == group_id and file_index < len(group.files):
                return group.files[file_index]
        return None

    def _mark_others_in_group_checked(self, exclude_item_id: str, checked: bool) -> None:
        """
        Mark all other files in the same group as checked/unchecked.

        Args:
            exclude_item_id: Item ID to exclude.
            checked: Whether to mark as checked or unchecked.
        """
        # Parse item_id to get group
        parts = exclude_item_id.split("_")
        if len(parts) != 2:
            return

        group_id = int(parts[0])

        # Find all other items in the same group
        for group in self._results_panel._filtered_groups:
            if group.group_id == group_id:
                for i in range(len(group.files)):
                    other_id = f"{group_id}_{i}"
                    if other_id != exclude_item_id:
                        self._results_panel._treeview.set_check(other_id, checked)
                break

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
            # Actually delete files using send2trash
            success_count = 0
            failed_files = []

            try:
                from send2trash import send2trash
            except ImportError:
                from tkinter import messagebox
                messagebox.showerror(
                    "Dependency Missing",
                    "send2trash package is required.\n\n"
                    "Install with: pip install send2trash"
                )
                return

            # Delete each selected file
            for file_data in selected_files:
                file_path = Path(file_data.get("path", ""))
                try:
                    send2trash(str(file_path))
                    success_count += 1
                except Exception as e:
                    failed_files.append((str(file_path), str(e)))

            # Show result
            from tkinter import messagebox
            if failed_files:
                failed_list = "\n".join(f"{f}: {e}" for f, e in failed_files[:5])
                more = f"\n... and {len(failed_files) - 5} more" if len(failed_files) > 5 else ""
                messagebox.showwarning(
                    "Delete Partially Failed",
                    f"Deleted {success_count}/{len(selected_files)} files.\n\n"
                    f"Failed:\n{failed_list}{more}"
                )
            else:
                messagebox.showinfo(
                    "Delete Complete",
                    f"Successfully deleted {success_count} files.\n\n"
                    f"Reclaimed: {reclaimable_str}"
                )

            # Remove deleted files from results
            self._remove_deleted_files(selected_files)

            # Clear selection
            self._on_deselect_all()

            # Update status bar reclaimable
            new_reclaimable = self._results_panel.get_reclaimable_space()
            self._status_bar.update_reclaimable(new_reclaimable)

    def _remove_deleted_files(self, deleted_files: List[Dict[str, Any]]) -> None:
        """
        Remove deleted files from the results panel.

        Args:
            deleted_files: List of file data dictionaries for deleted files.
        """
        deleted_paths = {f.get("path", "") for f in deleted_files}

        # Remove deleted files from filtered groups
        groups_to_update = []
        for group in self._results_panel._filtered_groups:
            # Filter out deleted files
            remaining_files = [
                f for f in group.files
                if f.get("path", "") not in deleted_paths
            ]

            if remaining_files:
                # Update group with remaining files
                new_total_size = sum(f.get("size", 0) for f in remaining_files)
                new_reclaimable = new_total_size - max(f.get("size", 0) for f in remaining_files) if remaining_files else 0

                group.files = remaining_files
                group.total_size = new_total_size
                group.reclaimable = new_reclaimable
                groups_to_update.append(group)
            # If group is now empty, it will be removed by _refresh_treeview

        # Update filtered groups
        self._results_panel._filtered_groups = [
            g for g in self._results_panel._filtered_groups if g.files
        ]

        # Refresh treeview
        self._results_panel._refresh_treeview()
        self._results_panel._update_status()

    def _on_selection_changed(self, checked_items: List[str]) -> None:
        """Handle selection changes from results panel."""
        # Update selection bar counter
        self._selection_bar.set_selected_count(len(checked_items))
        # Enable/disable delete button based on selection
        self._selection_bar.set_delete_enabled(len(checked_items) > 0)

        # Update preview panel
        self._update_preview_panel(checked_items)

    def _update_preview_panel(self, checked_items: List[str]) -> None:
        """
        Update preview panel based on selected files.

        Args:
            checked_items: List of checked item IDs.
        """
        # Store selected file IDs for keep buttons
        self._selected_file_ids = checked_items[:2]  # Max 2 for comparison

        # Get file data for preview
        files_data = []
        for item_id in checked_items[:2]:  # Only show first 2 selected
            file_data = self._get_file_data_by_id(item_id)
            if file_data:
                files_data.append(file_data)

        # Update preview panel based on selection
        if not files_data:
            self._preview_panel.clear()
        elif len(files_data) == 1:
            # Single file preview
            self._preview_panel.load_single(files_data[0])
        elif len(files_data) >= 2:
            # Side-by-side comparison
            self._preview_panel.load_comparison(files_data[0], files_data[1])
        else:
            self._preview_panel.clear()

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

    def _apply_theme(self) -> None:
        """Apply current theme colors to all themed widgets."""
        try:
            self._main_frame.configure(fg_color=theme_color("base.background"))
            self._left_panel_frame.configure(fg_color=theme_color("panel.background"))
            self._center_panel_frame.configure(fg_color=theme_color("panel.background"))
            self._preview_frame.configure(fg_color=theme_color("panel.background"))
        except (tk.TclError, AttributeError):
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
