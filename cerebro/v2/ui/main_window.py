"""
Main Window

Root CTk() window with complete Ashisoft-style single-window layout.
Handles window lifecycle, panel organization, and keyboard shortcuts.
"""

from __future__ import annotations

import logging
import os
import tkinter as tk
import time
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

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
from cerebro.v2.ui.toolbar import Toolbar, TopActionToolbar
from cerebro.v2.ui.mode_tabs import ModeTabs, ModeNavPanel
from cerebro.v2.ui.status_bar import StatusBar, StatusBarMetrics
from cerebro.v2.ui.settings_dialog import SettingsDialog, Settings, get_settings_path
from cerebro.v2.ui.folder_panel import FolderPanel
from cerebro.v2.ui.results_panel import ResultsPanel
from cerebro.v2.ui.preview_panel import PreviewPanel
from cerebro.v2.ui.main_window_controllers import (
    HistoryRecorder,
    PreviewCoordinator,
    ScanController,
)
from cerebro.v2.ui.widgets.thumbnail_grid import ThumbnailGrid
from cerebro.v2.ui.feedback import CTkMessageInterface, FeedbackPanel, confirm_yes_no, show_text_panel
from cerebro.v2.core.deletion_history_db import log_deletion_event
from cerebro.engines.orchestrator import ScanOrchestrator
from cerebro.engines.base_engine import (
    ScanProgress, ScanState, DuplicateGroup, DuplicateFile
)
from cerebro.services.logger import get_logger
from cerebro.utils.formatting import format_bytes

logger = get_logger(__name__)  # wraps logging.getLogger(__name__)


class MainWindow(CTk, CTkMessageInterface):
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
        self._view_mode: str = "list"
        self._thumbnail_grid_dirty: bool = True
        self._last_layout_width: int = 0
        self._app_settings: Settings = Settings.load(get_settings_path())

        # Scan state
        self._scan_start_time: float = 0.0
        self._eta_smoothed: float = 0.0
        self._polling_enabled: bool = False
        self._selected_file_ids: List[str] = []  # For preview panel
        self._preview_focus_id: str = ""  # Row/card focused for metadata when nothing checked

        # Scan results (core.DuplicateGroup format)
        self._scan_results: List[DuplicateGroup] = []

        # Create orchestrator
        self._orchestrator = ScanOrchestrator()
        self._orchestrator.set_mode("files")
        self._history_recorder = HistoryRecorder(self)
        self._preview_coordinator = PreviewCoordinator(self)
        self._scan_controller = ScanController(self, self._history_recorder)

        # Initialize components
        self._setup_window()
        self._setup_theme()
        self._build_ui()
        self._bind_shortcuts()
        self._bind_window_events()
        subscribe_to_theme(self, self._apply_theme)
        self._apply_loaded_settings()

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
        self._build_preview_panel()
        self._build_status_bar()

        # Post-build setup
        self.after(100, self._restore_window_state)  # restore after layout settles
        self.after(200, self._setup_drag_drop)        # DnD after window is mapped
        self.after(260, lambda: self._apply_master_detail_proportions(force=True))

    def _build_toolbar(self) -> None:
        """Build and install toolbar."""
        self._toolbar = TopActionToolbar(
            self._content_container,
            height=Dimensions.TOOLBAR_HEIGHT
        )
        self._toolbar.pack(fill="x", padx=Spacing.MD, pady=(Spacing.MD, 0))

        # Wire callbacks
        self._toolbar.on_add_path(self._on_add_path)
        self._toolbar.on_back(self._on_back_to_start)
        self._toolbar.on_remove_selected(self._on_remove_path)
        self._toolbar.on_start_search(self._on_start_search)
        self._toolbar.on_stop_search(self._on_stop_search)
        self._toolbar.on_auto_mark(self._on_auto_mark)
        self._toolbar.on_delete_selected(self._on_delete_selected)
        self._toolbar.on_move_to(self._on_move_to)
        self._toolbar.on_settings(self._on_settings)
        self._toolbar.on_help(self._on_help)
        self._toolbar.on_view_mode_changed(self._on_view_mode_changed)

    def _build_mode_tabs(self) -> None:
        """Build and install mode tabs."""
        self._mode_tabs = ModeNavPanel(
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
                orient=tk.HORIZONTAL
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
        self._thumbnail_grid = ThumbnailGrid(self._center_panel_frame)
        self._thumbnail_grid.set_mode(self._current_scan_mode)

        # Wire folder panel callbacks
        self._folder_panel.on_folders_changed(self._on_folders_changed)
        self._folder_panel.on_protected_changed(self._on_protected_changed)
        self._folder_panel.on_options_changed(self._on_options_changed)
        self._folder_panel.on_collapse_toggled(self._on_folder_panel_collapse)

        # Wire results panel callbacks
        self._results_panel.on_selection_changed(self._on_selection_changed)
        self._results_panel.on_request_add_folder(self._on_add_path)
        self._results_panel.on_request_start_search(self._on_start_search)
        self._results_panel.on_request_auto_mark(self._on_auto_mark_default)
        self._results_panel.attach_thumbnail_grid(self._thumbnail_grid)
        self._results_panel.set_results_view_mode("list")
        self._results_panel.on_file_row_focus(self._on_tree_preview_focus)
        self._thumbnail_grid.on_selection_changed(self._on_thumbnail_grid_selection_changed)
        self._thumbnail_grid.on_focus_changed(self._on_thumbnail_grid_focus)
        self._thumbnail_grid.on_request_add_folder(self._on_add_path)
        self._thumbnail_grid.on_request_start_search(self._on_start_search)

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
        # Space = toggle checkbox on focused treeview row
        self.bind("<space>", self._on_space_toggle)

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
            candidate = Path(path)
            folders = self._folder_panel.get_scan_folders()
            if candidate not in folders:
                self._folder_panel.set_scan_folders(folders + [candidate])
                self._toolbar.add_folder(candidate)

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
            logger.info("Removed folder from scan list")
        else:
            logger.debug("Remove folder requested with empty folder list")

    def _on_back_to_start(self) -> None:
        """Return from review state to the getting-started landing view."""
        if self._scanning:
            self._status_bar.flash_message("Stop scan before returning to start.")
            return

        self._scan_results.clear()
        self._selected_file_ids = []
        self._preview_focus_id = ""

        try:
            self._results_panel.hide_scan_complete()
        except (AttributeError, tk.TclError):
            pass
        self._results_panel.clear()

        try:
            self._thumbnail_grid.clear()
        except (AttributeError, tk.TclError):
            pass
        self._thumbnail_grid_dirty = True

        if self._view_mode != "list":
            self._toolbar.set_view_mode("list", fire_callback=False)
            self._on_view_mode_changed("list")
        else:
            self._toolbar.set_has_selection(False)

        try:
            self._preview_panel.clear()
            self._preview_panel.set_layout_mode("compact")
        except (AttributeError, tk.TclError) as exc:
            logger.debug("Preview reset on back-to-start skipped: %s", exc)

        self._status_bar.flash_message("Back to start.")

    def _on_start_search(self) -> None:
        """Handle start search button."""
        self._scan_controller.start_search()

    def _on_stop_search(self) -> None:
        """Handle stop search button."""
        self._scan_controller.stop_search()

    def _on_settings(self) -> None:
        """Handle settings button."""
        updated = SettingsDialog.show_dialog(parent=self, settings=self._app_settings)
        if updated:
            self._app_settings = updated
            self._apply_loaded_settings()
            self._status_bar.flash_message("Settings saved.")

    def _on_help(self) -> None:
        """Handle help button — show a small popup menu."""
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="Keyboard Shortcuts…", command=self._show_keyboard_help)
        menu.add_command(label="Scan History…",        command=self._show_scan_history)
        menu.add_command(label="Deletion History…",    command=self._show_deletion_history)
        try:
            btn = self._toolbar._help_btn
            x = btn.winfo_rootx()
            y = btn.winfo_rooty() + btn.winfo_height()
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def _show_keyboard_help(self) -> None:
        show_text_panel(self, "Keyboard Shortcuts", (
            "Ctrl+O          Add folder\n"
            "Ctrl+Enter      Start scan\n"
            "Escape          Stop scan / close dialog\n"
            "Delete          Delete selected\n"
            "Space           Toggle checkbox\n"
            "Ctrl+A          Select all\n"
            "Ctrl+D          Deselect all\n"
            "Ctrl+I          Invert selection\n"
            "F5              Refresh\n"
            "Ctrl+P          Toggle preview panel\n"
            "1–6             Switch scan mode\n"
        ))

    def _show_scan_history(self) -> None:
        from cerebro.v2.ui.scan_history_dialog import ScanHistoryDialog
        ScanHistoryDialog.show(parent=self)

    def _show_deletion_history(self) -> None:
        from cerebro.v2.ui.deletion_history_dialog import DeletionHistoryDialog
        DeletionHistoryDialog.show(parent=self)

    def _on_folder_panel_collapse(self, collapsed: bool) -> None:
        """Resize paned window sash when left panel collapses/expands."""
        self._apply_master_detail_proportions(force=True)

    def _on_folders_changed(self, folders: List[Path]) -> None:
        """Handle folder list changes."""
        logger.debug("Folders changed: %d folder(s)", len(folders))

    def _on_protected_changed(self, folders: List[Path]) -> None:
        """Handle protected folder list changes."""
        logger.debug("Protected folders changed: %d folder(s)", len(folders))

    def _on_options_changed(self, mode: str, options: dict) -> None:
        """Handle scan options changes."""
        logger.debug("Options changed for mode %s: %s", mode, options)

    # ===================
    # SCAN INTEGRATION
    # ===================

    def _on_scan_progress(self, progress: ScanProgress) -> None:
        """
        Handle progress updates from scan engine (called from background thread).

        Args:
            progress: ScanProgress object with current scan state.
        """
        # Marshal all UI updates onto the main thread
        self.after(0, lambda p=progress: self._handle_progress_on_main(p))

    def _handle_progress_on_main(self, progress: ScanProgress) -> None:
        """Process a progress update on the main thread."""
        self._update_status_bar(progress)

        if progress.state == ScanState.SCANNING:
            elapsed = (
                time.time() - self._scan_start_time
                if self._scan_start_time > 0
                else 0.0
            )
            self._results_panel.update_scan_progress(
                stage=progress.stage,
                files_scanned=progress.files_scanned,
                files_total=progress.files_total,
                elapsed_seconds=elapsed,
            )

        if progress.state in (ScanState.COMPLETED, ScanState.CANCELLED, ScanState.ERROR):
            self._on_scan_finished(progress.state)

    def _update_status_bar(self, progress: ScanProgress) -> None:
        """
        Update status bar with scan progress.

        Args:
            progress: ScanProgress object.
        """
        elapsed = time.time() - self._scan_start_time if self._scan_start_time > 0 else 0.0
        eta = self._compute_eta(
            files_scanned=progress.files_scanned,
            files_total=progress.files_total,
            elapsed=elapsed,
        )

        metrics = StatusBarMetrics(
            files_scanned=progress.files_scanned,
            duplicates_found=progress.duplicates_found,
            groups_found=progress.groups_found,
            bytes_reclaimable=progress.bytes_reclaimable,
            elapsed_seconds=elapsed,
            eta_seconds=eta,
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

            # Keep the in-panel progress view in sync with get_progress(). Engines may
            # throttle cross-thread callbacks (e.g. photos mode every N files) while
            # files_scanned is updated every iteration for polling.
            if progress.state == ScanState.SCANNING:
                elapsed = (
                    time.time() - self._scan_start_time
                    if self._scan_start_time > 0
                    else 0.0
                )
                self._results_panel.update_scan_progress(
                    stage=progress.stage,
                    files_scanned=progress.files_scanned,
                    files_total=progress.files_total,
                    elapsed_seconds=elapsed,
                )

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
        self._scan_controller.finish_scan(final_state)

    def _compute_eta(self, files_scanned: int, files_total: int, elapsed: float) -> Optional[float]:
        """Estimate scan ETA using files/sec with lightweight smoothing."""
        if files_total <= 0 or files_scanned <= 0 or elapsed <= 0:
            return None
        if files_scanned >= files_total:
            return 0.0

        # Avoid noisy ETA during scan warmup.
        if files_scanned < 100 and elapsed < 2.0:
            return None

        rate = files_scanned / elapsed
        if rate <= 0:
            return None

        remaining = max(0, files_total - files_scanned)
        raw_eta = remaining / rate
        if raw_eta <= 0:
            return 0.0

        if self._eta_smoothed <= 0:
            self._eta_smoothed = raw_eta
        else:
            self._eta_smoothed = (0.7 * self._eta_smoothed) + (0.3 * raw_eta)
        return self._eta_smoothed

    def _load_results_to_panel(self) -> None:
        """Load scan results into both views (list + thumbnail grid)."""
        # Pass core DuplicateGroup objects directly — results_panel uses DuplicateFile attributes.
        # For large_files mode, provide total scanned bytes so the panel can show % of disk.
        from cerebro.v2.ui.mode_tabs import ScanMode
        self._thumbnail_grid.set_mode(self._current_scan_mode)
        if self._current_scan_mode == ScanMode.LARGE_FILES:
            total_bytes = sum(
                f.size for g in self._scan_results for f in g.files
            )
            self._results_panel._total_scan_bytes = total_bytes
        self._results_panel.load_results(self._scan_results)
        # Building thousands of thumbnail cards can block UI.
        # Only hydrate grid eagerly when grid view is active; otherwise defer.
        self._thumbnail_grid_dirty = True
        if self._view_mode == "grid":
            self.after(0, self._hydrate_thumbnail_grid_if_needed)

    # ===================
    # PREVIEW INTEGRATION
    # ===================

    def _on_view_mode_changed(self, mode: str) -> None:
        """Swap center content between list table and thumbnail grid."""
        if mode not in ("list", "grid") or mode == self._view_mode:
            return
        self._view_mode = mode
        try:
            self._results_panel.set_results_view_mode(mode)
        except (tk.TclError, AttributeError) as exc:
            logger.debug("set_results_view_mode skipped: %s", exc)
        try:
            self._results_panel.pack_forget()
            self._thumbnail_grid.pack_forget()
        except (tk.TclError, AttributeError) as exc:
            logger.debug("Failed to hide previous view widgets: %s", exc)
        if mode == "grid":
            self._thumbnail_grid.pack(fill="both", expand=True)
            self.after(0, self._hydrate_thumbnail_grid_if_needed)
            try:
                self._preview_panel.set_layout_mode("ashisoft")
            except (tk.TclError, AttributeError) as exc:
                logger.debug("Failed to switch preview to ashisoft layout: %s", exc)
        else:
            self._results_panel.pack(fill="both", expand=True)
            try:
                self._preview_panel.set_layout_mode("compact")
            except (tk.TclError, AttributeError) as exc:
                logger.debug("Failed to switch preview to compact layout: %s", exc)
        self._apply_master_detail_proportions(force=True)

    def _hydrate_thumbnail_grid_if_needed(self) -> None:
        """Lazily load scan results into thumbnail grid when required."""
        if not self._thumbnail_grid_dirty:
            return
        try:
            self._thumbnail_grid.load_results(self._scan_results)
            self._thumbnail_grid.apply_check_state(
                set(self._results_panel._treeview.get_checked()), notify=False
            )
            self._thumbnail_grid_dirty = False
        except (RuntimeError, tk.TclError, AttributeError) as exc:
            logger.warning("Thumbnail grid hydration failed: %s", exc)

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
            self._results_panel._sync_thumbnail_checks_from_tree()
            self._on_selection_changed(self._results_panel._get_checked_item_ids())

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
            self._results_panel._sync_thumbnail_checks_from_tree()
            self._on_selection_changed(self._results_panel._get_checked_item_ids())

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
        """Handle mode tab change — full page-swap: clear results, update UI, reconfigure engine."""
        if self._scanning:
            return  # don't switch mid-scan
        self._current_scan_mode = new_mode

        # Clear stale results from previous mode
        self._scan_results.clear()
        if hasattr(self, '_results_panel') and self._results_panel:
            self._results_panel.clear()
        if hasattr(self, '_thumbnail_grid') and self._thumbnail_grid:
            try:
                self._thumbnail_grid.set_mode(new_mode)
                self._thumbnail_grid.clear()
            except (tk.TclError, RuntimeError, AttributeError) as exc:
                logger.debug("Failed clearing thumbnail grid on mode switch: %s", exc)
        self._thumbnail_grid_dirty = True
        self._preview_focus_id = ""
        try:
            self._preview_panel.clear()
        except (tk.TclError, AttributeError) as exc:
            logger.debug("Preview clear on mode change skipped: %s", exc)

        # Update left panel scan options for this mode
        if hasattr(self, '_folder_panel') and self._folder_panel:
            self._folder_panel.set_scan_mode(new_mode)

        # Update results treeview columns for this mode
        if hasattr(self, '_results_panel') and self._results_panel:
            self._results_panel.set_mode(new_mode)

        # Switch orchestrator to the new engine (if available for this mode)
        try:
            self._orchestrator.set_mode(new_mode)
        except ValueError:
            pass  # engine not available yet (e.g. videos without FFmpeg)

        # Show FFmpeg missing warning when switching to Videos mode
        from cerebro.v2.ui.mode_tabs import ScanMode
        if new_mode == ScanMode.VIDEOS:
            try:
                from cerebro.engines.video_dedup_engine import VideoDedupEngine
                engine = self._orchestrator._engines.get("videos")
                ffmpeg_missing = isinstance(engine, VideoDedupEngine) and not engine._ffmpeg
            except (ImportError, AttributeError) as exc:
                logger.debug("FFmpeg capability probe failed: %s", exc)
                ffmpeg_missing = False
            self._results_panel.show_ffmpeg_warning(ffmpeg_missing)
        else:
            if hasattr(self._results_panel, "_ffmpeg_banner"):
                self._results_panel.show_ffmpeg_warning(False)
        self._apply_master_detail_proportions(force=True)

    def _on_auto_mark_default(self) -> None:
        """Apply saved default auto-mark rule (banner / settings)."""
        rule = self._app_settings.auto_mark_selection_rule()
        self._on_auto_mark(rule)

    def _on_auto_mark(self, rule: str) -> None:
        """Handle Auto Mark dropdown selection from toolbar."""
        self._results_panel.apply_selection_rule(rule)
        count = self._results_panel.get_selected_count()
        self._toolbar.set_has_selection(count > 0)

    def _on_move_to(self) -> None:
        """Handle Move To toolbar button — ask for destination, move checked files."""
        from tkinter import filedialog
        def _fd_path(fd: Any) -> str:
            if isinstance(fd, dict):
                return str(fd.get("path", ""))
            return str(getattr(fd, "path", ""))

        selected_files = self._results_panel.get_selected_files()
        if not selected_files:
            self.show_info("Move Selected", "No files selected to move.")
            return
        dest = filedialog.askdirectory(title="Move files to…")
        if not dest:
            return
        import shutil
        dest_path = Path(dest)
        moved, errors = 0, []
        for f in selected_files:
            src = Path(_fd_path(f))
            if src.exists():
                try:
                    shutil.move(str(src), str(dest_path / src.name))
                    moved += 1
                except (OSError, shutil.Error) as exc:
                    errors.append(str(exc))
        msg = f"Moved {moved} file(s) to {dest_path}"
        if errors:
            msg += f"\n{len(errors)} error(s) — check console."
            for e in errors:
                logger.warning("Move error: %s", e)
        self.show_info("Move Complete", msg)
        # Refresh results
        self._on_refresh()

    def _on_apply_rule(self, rule: str) -> None:
        """Handle apply selection rule."""
        self._results_panel.apply_selection_rule(rule)

    def _on_select_all(self) -> None:
        """Handle select all action."""
        self._results_panel._treeview.check_all()
        self._results_panel._sync_thumbnail_checks_from_tree()

    def _on_deselect_all(self) -> None:
        """Handle deselect all action."""
        self._results_panel._treeview.uncheck_all()
        self._results_panel._sync_thumbnail_checks_from_tree()

    def _on_invert_selection(self) -> None:
        """Handle invert selection action."""
        self._results_panel._treeview.invert_checks()
        self._results_panel._sync_thumbnail_checks_from_tree()

    def _on_delete_selected(self) -> None:
        """Handle delete selected action."""
        def _fd_path(fd: Any) -> str:
            if isinstance(fd, dict):
                return str(fd.get("path", ""))
            return str(getattr(fd, "path", ""))

        def _fd_size(fd: Any) -> int:
            if isinstance(fd, dict):
                return int(fd.get("size", 0))
            return int(getattr(fd, "size", 0))

        selected_files = self._results_panel.get_selected_files()
        if not selected_files:
            self.show_info(
                "Delete Selected",
                "No files selected for deletion."
            )
            return

        reclaimable_space = self._results_panel.get_reclaimable_space()
        reclaimable_str = format_bytes(reclaimable_space, decimals=1)

        confirm = True
        if self._app_settings.general.get("confirm_before_delete", True):
            confirm = self.confirm_action(
                "Send to Recycle Bin",
                f"Send {len(selected_files)} files to the Recycle Bin?\n\n"
                f"Space freed: {reclaimable_str}\n\n"
                f"You can restore them from the Recycle Bin if needed."
            )

        if confirm:
            try:
                from send2trash import send2trash
            except ImportError:
                self.show_error(
                    "Dependency Missing",
                    "send2trash package is required.\n\n"
                    "Install with: pip install send2trash"
                )
                return

            self._toolbar.set_has_selection(False)
            self._status_bar.flash_message("Deleting selected files...")

            def _delete_worker() -> None:
                success_count = 0
                failed_files: List[tuple[str, str]] = []
                deleted_paths: List[str] = []
                deleted_entries: List[Any] = []

                for file_data in selected_files:
                    file_path = Path(_fd_path(file_data))
                    try:
                        send2trash(str(file_path))
                        success_count += 1
                        deleted_paths.append(str(file_path))
                        deleted_entries.append(file_data)
                        log_deletion_event(str(file_path), _fd_size(file_data), self.get_scan_mode())
                    except OSError as e:
                        failed_files.append((str(file_path), str(e)))

                self.after(
                    0,
                    lambda: self._finalize_delete_selected(
                        selected_files=selected_files,
                        deleted_entries=deleted_entries,
                        deleted_paths=deleted_paths,
                        failed_files=failed_files,
                        success_count=success_count,
                        reclaimable_str=reclaimable_str,
                    ),
                )

            threading.Thread(target=_delete_worker, daemon=True, name="delete-selected").start()

    def _finalize_delete_selected(
        self,
        *,
        selected_files: List[Any],
        deleted_entries: List[Any],
        deleted_paths: List[str],
        failed_files: List[tuple[str, str]],
        success_count: int,
        reclaimable_str: str,
    ) -> None:
        """Apply UI updates after background recycle-bin operation finishes."""
        if failed_files:
            failed_list = "\n".join(f"{f}: {e}" for f, e in failed_files[:5])
            more = f"\n... and {len(failed_files) - 5} more" if len(failed_files) > 5 else ""
            FeedbackPanel(
                self,
                "Delete Partially Failed",
                f"Deleted {success_count}/{len(selected_files)} files.\n\n"
                f"Failed:\n{failed_list}{more}",
                type="warning",
            )
        elif success_count > 0:
            _UndoToast(self, success_count, reclaimable_str, deleted_paths)

        if deleted_entries:
            self._remove_deleted_files(deleted_entries)

        # Deletion refresh already renders remaining rows unchecked.
        self._toolbar.set_has_selection(False)
        new_reclaimable = self._results_panel.get_reclaimable_space()
        self._status_bar.update_reclaimable(new_reclaimable)
        if success_count > 0:
            self._status_bar.flash_message(f"Deleted {success_count} file(s).")
        elif failed_files:
            self._status_bar.flash_message("No files were deleted (some failed).")

    def _remove_deleted_files(self, deleted_files: List[Dict[str, Any]]) -> None:
        """
        Remove deleted files from results and keep list/grid views in sync.

        Args:
            deleted_files: List of file data dictionaries for deleted files.
        """
        def _fd_path(fd: Any) -> str:
            if isinstance(fd, dict):
                return str(fd.get("path", ""))
            return str(getattr(fd, "path", ""))

        deleted_paths = [p for p in (_fd_path(f) for f in deleted_files) if p]
        if not deleted_paths:
            return

        # Incremental in-place tree update is much cheaper than a full rebuild.
        self._results_panel.remove_paths(deleted_paths)
        # Keep top-level snapshot aligned with the panel's in-memory groups.
        self._scan_results = list(self._results_panel._groups)

        # Ensure thumbnail grid reflects deletions too (prevents stale cards).
        self._thumbnail_grid_dirty = True
        if self._view_mode == "grid":
            self.after(0, self._hydrate_thumbnail_grid_if_needed)

    def _on_selection_changed(self, checked_items: List[str]) -> None:
        """Handle selection changes from results panel."""
        self._preview_coordinator.on_selection_changed(checked_items)

    def _on_tree_preview_focus(self, item_id: str) -> None:
        """List view: a file row was activated for preview/metadata."""
        self._preview_focus_id = item_id
        self._preview_coordinator.update_preview_panel(
            self._results_panel._get_checked_item_ids()
        )

    def _on_thumbnail_grid_focus(self, item_id: str) -> None:
        """Grid view: user clicked a card for preview (checkbox is separate)."""
        self._preview_focus_id = item_id
        self._preview_coordinator.update_preview_panel(
            self._results_panel._get_checked_item_ids()
        )

    def _on_thumbnail_grid_selection_changed(self, checked_items: List[str]) -> None:
        """Grid checkboxes changed — mirror onto treeview, then toolbar + preview."""
        self._results_panel.sync_tree_checks_from_grid_state(checked_items)
        self._preview_coordinator.on_selection_changed(checked_items)

    def _update_preview_panel(self, checked_items: List[str]) -> None:
        """
        Update preview panel based on selected files.

        Args:
            checked_items: List of checked item IDs.
        """
        self._preview_coordinator.update_preview_panel(checked_items)

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
        logger.info("Refresh / re-scan requested")
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
        if event.widget is not self:
            return
        width = int(getattr(event, "width", 0) or 0)
        if width <= 0:
            return
        # Re-apply split ratios only on meaningful width changes.
        if abs(width - self._last_layout_width) < 120:
            return
        self._last_layout_width = width
        self.after(0, self._apply_master_detail_proportions)

    def _target_left_panel_width(self) -> int:
        if not hasattr(self, "_folder_panel") or not hasattr(self, "_horizontal_paned"):
            return Dimensions.LEFT_PANEL_DEFAULT_WIDTH
        try:
            if self._folder_panel.is_collapsed():
                return self._folder_panel.COLLAPSED_WIDTH
        except (AttributeError, tk.TclError):
            return Dimensions.LEFT_PANEL_DEFAULT_WIDTH

        total_w = int(self._horizontal_paned.winfo_width() or 0)
        if total_w <= 0:
            total_w = int(self.winfo_width() or 0)
        if total_w <= 0:
            return Dimensions.LEFT_PANEL_DEFAULT_WIDTH

        ratio_target = int(total_w * 0.24)
        ratio_target = max(Dimensions.LEFT_PANEL_MIN_WIDTH, ratio_target)
        ratio_target = min(Dimensions.LEFT_PANEL_MAX_WIDTH, ratio_target)

        # Keep detail pane readable in both list and grid review modes.
        min_center = 560 if self._view_mode == "grid" else 460
        max_left = max(Dimensions.LEFT_PANEL_MIN_WIDTH, total_w - min_center)
        return max(Dimensions.LEFT_PANEL_MIN_WIDTH, min(ratio_target, max_left))

    def _apply_master_detail_proportions(self, *, force: bool = False) -> None:
        """Maintain an Ashisoft-like master/detail split."""
        try:
            target = self._target_left_panel_width()
            current = int(self._horizontal_paned.sash_coord(0)[0])
            if force or abs(current - target) >= 8:
                self._horizontal_paned.sash_place(0, target, 0)
        except (tk.TclError, AttributeError, RuntimeError, ValueError) as exc:
            logger.debug("Master/detail split update skipped: %s", exc)

    def _on_space_toggle(self, event) -> None:
        """Space bar: toggle the checkbox on the currently focused treeview row."""
        try:
            tv = self._results_panel._treeview
            focused = tv.focus()
            if focused and focused not in tv._group_rows:
                tv.toggle_check(focused)
        except (AttributeError, tk.TclError, KeyError) as exc:
            logger.debug("Space toggle ignored due to UI state: %s", exc)

    # ------------------------------------------------------------------
    # Drag-and-drop support (tkinterdnd2 optional)
    # ------------------------------------------------------------------

    def _setup_drag_drop(self) -> None:
        """Register this window as a folder drop target (tkinterdnd2 optional)."""
        try:
            # tkinterdnd2 patches Tk/CTk with DnD support
            self.drop_target_register("DND_Files")
            self.dnd_bind("<<Drop>>", self._on_dnd_drop)
        except (AttributeError, tk.TclError, RuntimeError) as exc:
            logger.debug("Drag-and-drop setup unavailable: %s", exc)

    def _on_dnd_drop(self, event) -> None:
        """Handle files/folders dropped onto the window."""
        raw = event.data
        # tkinterdnd2 delivers paths space-separated or {braced}
        import re
        paths = re.findall(r'\{([^}]+)\}|(\S+)', raw)
        for braced, plain in paths:
            p = Path(braced or plain)
            if p.is_dir():
                self._on_add_path_explicit(p)

    def _on_add_path_explicit(self, path: Path) -> None:
        """Add a specific folder path (used by drag-drop and getting-started)."""
        try:
            self._folder_panel.set_scan_folders(
                list(dict.fromkeys(self._folder_panel.get_scan_folders() + [path]))
            )
        except (AttributeError, tk.TclError) as exc:
            logger.warning("Failed to add dropped folder '%s': %s", path, exc)

    # ------------------------------------------------------------------
    # Window state persistence
    # ------------------------------------------------------------------

    _STATE_FILE = Path.home() / ".cerebro" / "window_state.json"

    def _save_window_state(self) -> None:
        """Persist window geometry and last-used folders."""
        import json
        state = {
            "geometry": self.geometry(),
            "folders": [str(f) for f in self._folder_panel.get_scan_folders()],
            "mode": self._current_scan_mode,
        }
        try:
            self._STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            self._STATE_FILE.write_text(json.dumps(state, indent=2))
        except (OSError, ValueError, TypeError) as exc:
            logger.warning("Failed to persist window state: %s", exc)

    def _restore_window_state(self) -> None:
        """Restore last window geometry and folders if state file exists."""
        import json
        try:
            if not self._STATE_FILE.exists():
                return
            state = json.loads(self._STATE_FILE.read_text())
            geo = state.get("geometry")
            if geo:
                self.geometry(geo)
            folders = [Path(f) for f in state.get("folders", []) if Path(f).is_dir()]
            if folders:
                self._folder_panel.set_scan_folders(folders)
            mode = state.get("mode")
            if mode:
                try:
                    self._mode_tabs.set_mode(mode)
                    self._current_scan_mode = mode
                    self._thumbnail_grid.set_mode(mode)
                except (ValueError, tk.TclError, AttributeError) as exc:
                    logger.debug("Saved mode restore skipped: %s", exc)
            self.after(0, lambda: self._apply_master_detail_proportions(force=True))
        except (OSError, ValueError, TypeError, tk.TclError) as exc:
            logger.warning("Failed to restore window state: %s", exc)

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
        """Handle window close — save state then quit."""
        self._save_window_state()
        if self._scanning:
            self._orchestrator.cancel()
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


# =============================================================================
# Undo Toast — non-blocking notification after send2trash
# =============================================================================

class _UndoToast:
    """
    Floating toast that appears at the bottom-right of the parent window
    after files are moved to the Recycle Bin.

    Dismisses automatically after TIMEOUT_S seconds or when the user
    clicks Undo (which attempts OS-level restore from Trash).
    """

    TIMEOUT_S = 30
    BG = "#1e2430"
    FG = "#e0e0e0"
    ACCENT = "#4fc3f7"

    def __init__(self, parent: tk.Wm, count: int, size_str: str,
                 deleted_paths: List[str]) -> None:
        self._parent = parent
        self._deleted = deleted_paths
        self._after_id = None

        self._win = tk.Toplevel(parent)
        self._win.overrideredirect(True)
        self._win.attributes("-topmost", True)
        try:
            self._win.attributes("-alpha", 0.95)
        except tk.TclError as exc:
            logger.debug("Toast transparency unsupported: %s", exc)

        # Content
        frame = tk.Frame(self._win, bg=self.BG, padx=14, pady=10)
        frame.pack(fill="both")

        tk.Label(
            frame,
            text=f"🗑  {count} file{'s' if count != 1 else ''} moved to Recycle Bin  ({size_str})",
            bg=self.BG, fg=self.FG,
            font=("", 10),
        ).pack(side="left", padx=(0, 16))

        tk.Button(
            frame, text="Undo", bg=self.ACCENT, fg="#000",
            relief="flat", padx=8, pady=2, font=("", 10, "bold"),
            cursor="hand2",
            command=self._undo,
        ).pack(side="left")

        tk.Button(
            frame, text="✕", bg=self.BG, fg=self.FG,
            relief="flat", padx=6, font=("", 10),
            cursor="hand2",
            command=self._dismiss,
        ).pack(side="left", padx=(8, 0))

        # Position: bottom-right of parent
        self._win.update_idletasks()
        px = parent.winfo_rootx() + parent.winfo_width()  - self._win.winfo_width() - 24
        py = parent.winfo_rooty() + parent.winfo_height() - self._win.winfo_height() - 40
        self._win.geometry(f"+{px}+{py}")

        # Auto-dismiss
        self._after_id = parent.after(self.TIMEOUT_S * 1000, self._dismiss)

    def _dismiss(self) -> None:
        try:
            if self._after_id:
                self._parent.after_cancel(self._after_id)
            self._win.destroy()
        except (tk.TclError, ValueError, AttributeError) as exc:
            logger.debug("Undo toast dismiss cleanup skipped: %s", exc)

    def _undo(self) -> None:
        """Attempt to restore trashed files from the platform Recycle Bin."""
        import sys, subprocess
        restored = 0
        if sys.platform == "win32":
            # On Windows, open the Recycle Bin so the user can restore manually
            try:
                subprocess.Popen(["explorer.exe", "shell:RecycleBinFolder"])
                restored = -1  # sentinel = opened folder, not auto-restored
            except (OSError, subprocess.SubprocessError) as exc:
                logger.warning("Failed to open Recycle Bin on Windows: %s", exc)
        elif sys.platform == "darwin":
            try:
                subprocess.Popen(["open", os.path.expanduser("~/.Trash")])
                restored = -1
            except (OSError, subprocess.SubprocessError) as exc:
                logger.warning("Failed to open Trash on macOS: %s", exc)
        else:
            # Linux/XDG: try trash-restore or open file manager
            try:
                trash_dir = Path.home() / ".local" / "share" / "Trash" / "files"
                subprocess.Popen(["xdg-open", str(trash_dir)])
                restored = -1
            except (OSError, subprocess.SubprocessError) as exc:
                logger.warning("Failed to open Trash folder on Linux: %s", exc)

        if restored == -1:
            show_text_panel(
                self._parent,
                "Undo",
                "The Recycle Bin has been opened.\n"
                "Select the files and choose 'Restore' to recover them.",
            )
        self._dismiss()


# --- CTkMessageInterface implementation ---
def _mw_show_error(self, title: str, message: str) -> None:
    FeedbackPanel(self, title=title, message=message, type="error")


def _mw_show_info(self, title: str, message: str) -> None:
    FeedbackPanel(self, title=title, message=message, type="info")


def _mw_confirm_action(self, title: str, message: str) -> bool:
    return confirm_yes_no(self, title=title, message=message)


MainWindow.show_error = _mw_show_error
MainWindow.show_info = _mw_show_info
MainWindow.confirm_action = _mw_confirm_action


def _apply_loaded_settings(self: MainWindow) -> None:
    """Apply persisted settings to mode/options and startup UI state."""
    try:
        mode = str(self._app_settings.general.get("default_mode", "files"))
        self._mode_tabs.set_mode(mode)
        self._current_scan_mode = mode
        self._folder_panel.set_scan_mode(mode)
        self._results_panel.set_mode(mode)
        self._orchestrator.set_mode(mode)
    except (ValueError, AttributeError, tk.TclError, RuntimeError) as exc:
        logger.warning("Failed applying persisted mode settings: %s", exc)
    try:
        self._folder_panel.set_photo_phash_dhash_defaults(
            int(self._app_settings.photo_mode.get("phash_threshold", 8)),
            int(self._app_settings.photo_mode.get("dhash_threshold", 10)),
        )
        self._folder_panel.set_scan_mode(self._current_scan_mode)
    except (ValueError, AttributeError, tk.TclError, TypeError) as exc:
        logger.warning("Failed applying photo hash defaults: %s", exc)


MainWindow._apply_loaded_settings = _apply_loaded_settings


