"""
Status Bar Widget

Bottom status bar with live scan metrics.
Shows: Scanned, Duplicates, Groups, Reclaimable, Elapsed, Progress bar.
"""

from __future__ import annotations

import logging
import tkinter as tk
from tkinter import ttk
from typing import Optional, Callable

try:
    import customtkinter as ctk
    CTkFrame = ctk.CTkFrame
    CTkLabel = ctk.CTkLabel
    CTkProgressBar = ctk.CTkProgressBar
except ImportError:
    # Fallback to standard tkinter
    CTkFrame = tk.Frame
    CTkLabel = tk.Label
    CTkProgressBar = ttk.Progressbar

from cerebro.v2.core.design_tokens import Spacing, Dimensions, Typography
from cerebro.v2.core.theme_bridge_v2 import theme_color, subscribe_to_theme
from cerebro.utils.formatting import format_bytes


class StatusBarMetrics:
    """Metrics displayed in the status bar."""

    def __init__(
        self,
        files_scanned: int = 0,
        duplicates_found: int = 0,
        groups_found: int = 0,
        bytes_reclaimable: int = 0,
        elapsed_seconds: float = 0.0,
        eta_seconds: Optional[float] = None,
        is_scanning: bool = False,
        progress_percent: float = 0.0
    ):
        self.files_scanned = files_scanned
        self.duplicates_found = duplicates_found
        self.groups_found = groups_found
        self.bytes_reclaimable = bytes_reclaimable
        self.elapsed_seconds = elapsed_seconds
        self.eta_seconds = eta_seconds
        self.is_scanning = is_scanning
        self.progress_percent = progress_percent

    def clone(self) -> "StatusBarMetrics":
        """Create a copy of this metrics."""
        return StatusBarMetrics(
            files_scanned=self.files_scanned,
            duplicates_found=self.duplicates_found,
            groups_found=self.groups_found,
            bytes_reclaimable=self.bytes_reclaimable,
            elapsed_seconds=self.elapsed_seconds,
            eta_seconds=self.eta_seconds,
            is_scanning=self.is_scanning,
            progress_percent=self.progress_percent
        )


class StatusBar(CTkFrame):
    """
    Status bar with live metrics during scans.

    Features:
    - File count, duplicate count, group count
    - Space reclaimable (human-readable)
    - Elapsed time
    - Progress bar (subtle, invisible when not scanning)
    - Updates via polling (every 200ms recommended)
    """

    def __init__(self, master=None, **kwargs):
        """Initialize status bar."""
        super().__init__(master, **kwargs)

        # Metrics
        self._metrics = StatusBarMetrics()

        # Widgets
        self._scanned_label: Optional[CTkLabel] = None
        self._duplicates_label: Optional[CTkLabel] = None
        self._groups_label: Optional[CTkLabel] = None
        self._reclaimable_label: Optional[CTkLabel] = None
        self._elapsed_label: Optional[CTkLabel] = None
        self._eta_label: Optional[CTkLabel] = None
        self._progress_bar: Optional[CTkProgressBar] = None

        # Polling
        self._polling: bool = False
        self._poll_interval: int = 200  # milliseconds

        # Theme subscription
        subscribe_to_theme(self, self._apply_theme)

        # Build UI
        self._build_widgets()
        self._layout_widgets()

    def _build_widgets(self) -> None:
        """Build all status bar widgets."""
        # Scanned label
        self._scanned_label = CTkLabel(
            self,
            text="Scanned: 0",
            font=Typography.FONT_SM,
            text_color=theme_color("status.foreground")
        )

        # Duplicates label
        self._duplicates_label = CTkLabel(
            self,
            text="Duplicates: 0",
            font=Typography.FONT_SM,
            text_color=theme_color("status.foreground")
        )

        # Groups label
        self._groups_label = CTkLabel(
            self,
            text="Groups: 0",
            font=Typography.FONT_SM,
            text_color=theme_color("status.foreground")
        )

        # Reclaimable label
        self._reclaimable_label = CTkLabel(
            self,
            text="Reclaimable: 0 B",
            font=Typography.FONT_SM,
            text_color=theme_color("feedback.success")
        )

        # Elapsed label
        self._elapsed_label = CTkLabel(
            self,
            text="Elapsed: 00:00:00",
            font=Typography.FONT_MONO,
            text_color=theme_color("status.foreground")
        )

        self._eta_label = CTkLabel(
            self,
            text="ETA: —",
            font=Typography.FONT_MONO,
            text_color=theme_color("status.foreground")
        )

        # Progress bar (subtle, thin)
        self._progress_bar = CTkProgressBar(
            self,
            orientation="horizontal",
            width=200,
            height=6,
            progress_color=theme_color("status.accent"),
            fg_color=theme_color("status.background")
        )
        # Hide initially
        self._progress_bar.set(0)
        if hasattr(self._progress_bar, "pack_forget"):
            self._progress_bar.pack_forget()
        elif hasattr(self._progress_bar, "place_forget"):
            self._progress_bar.place_forget()

    def _layout_widgets(self) -> None:
        """Layout the status bar widgets."""
        # Configure grid weights
        self.columnconfigure(0, weight=0)  # Scanned
        self.columnconfigure(1, weight=0)  # Duplicates
        self.columnconfigure(2, weight=0)  # Groups
        self.columnconfigure(3, weight=1)  # Spacer
        self.columnconfigure(4, weight=0)  # Reclaimable
        self.columnconfigure(5, weight=0)  # Spacer
        self.columnconfigure(6, weight=0)  # Elapsed
        self.columnconfigure(7, weight=0)  # ETA
        self.columnconfigure(8, weight=0)  # Progress bar

        # Row settings
        self.rowconfigure(0, weight=1)

        # Add widgets to grid
        self._scanned_label.grid(
            row=0, column=0,
            padx=Spacing.MD, pady=(0, 0),
            sticky="w"
        )

        self._duplicates_label.grid(
            row=0, column=1,
            padx=Spacing.MD, pady=(0, 0),
            sticky="w"
        )

        self._groups_label.grid(
            row=0, column=2,
            padx=Spacing.MD, pady=(0, 0),
            sticky="w"
        )

        self._reclaimable_label.grid(
            row=0, column=4,
            padx=Spacing.MD, pady=(0, 0),
            sticky="w"
        )

        self._elapsed_label.grid(
            row=0, column=6,
            padx=Spacing.MD, pady=(0, 0),
            sticky="w"
        )
        self._eta_label.grid(
            row=0, column=7,
            padx=Spacing.MD, pady=(0, 0),
            sticky="w"
        )

    def update_metrics(self, metrics: StatusBarMetrics) -> None:
        """
        Update all displayed metrics.

        Args:
            metrics: New metrics to display.
        """
        self._metrics = metrics.clone()
        self._refresh_labels()

        # Update progress bar visibility
        if metrics.is_scanning:
            self._show_progress_bar()
            self._progress_bar.set(metrics.progress_percent)
        else:
            self._hide_progress_bar()

    def _refresh_labels(self) -> None:
        """Refresh all label text based on current metrics."""
        self._scanned_label.configure(
            text=f"Scanned: {self._metrics.files_scanned:,}"
        )

        self._duplicates_label.configure(
            text=f"Duplicates: {self._metrics.duplicates_found:,}"
        )

        self._groups_label.configure(
            text=f"Groups: {self._metrics.groups_found:,}"
        )

        # Format reclaimable space
        reclaimable = format_bytes(self._metrics.bytes_reclaimable, decimals=1)
        self._reclaimable_label.configure(
            text=f"Reclaimable: {reclaimable}",
            text_color=theme_color("feedback.success")
        )

        # Format elapsed time
        elapsed = self._format_time(self._metrics.elapsed_seconds)
        self._elapsed_label.configure(text=f"Elapsed: {elapsed}")

        # Format ETA
        eta = "—" if self._metrics.eta_seconds is None else self._format_time(self._metrics.eta_seconds)
        self._eta_label.configure(text=f"ETA: {eta}")

    def _show_progress_bar(self) -> None:
        """Show progress bar in grid."""
        if hasattr(self._progress_bar, "grid_info"):
            info = self._progress_bar.grid_info()
            if not info:
                self._progress_bar.grid(
                    row=0, column=8,
                    padx=Spacing.LG, pady=(0, 0),
                    sticky="e"
                )

    def _hide_progress_bar(self) -> None:
        """Hide progress bar from grid."""
        if hasattr(self._progress_bar, "grid_forget"):
            self._progress_bar.grid_forget()
        elif hasattr(self._progress_bar, "place_forget"):
            self._progress_bar.place_forget()

    def set_scanning(self, scanning: bool) -> None:
        """
        Set scanning state (controls progress bar visibility).

        Args:
            scanning: Whether a scan is currently in progress.
        """
        self._metrics.is_scanning = scanning
        if scanning:
            self._show_progress_bar()
        else:
            self._hide_progress_bar()

    def update_scanned(self, count: int) -> None:
        """Update files scanned count."""
        self._metrics.files_scanned = count
        self._refresh_labels()

    def update_duplicates(self, count: int) -> None:
        """Update duplicates found count."""
        self._metrics.duplicates_found = count
        self._refresh_labels()

    def update_groups(self, count: int) -> None:
        """Update groups found count."""
        self._metrics.groups_found = count
        self._refresh_labels()

    def update_reclaimable(self, bytes_count: int) -> None:
        """Update reclaimable bytes."""
        self._metrics.bytes_reclaimable = bytes_count
        self._refresh_labels()

    def update_elapsed(self, seconds: float) -> None:
        """Update elapsed time."""
        self._metrics.elapsed_seconds = seconds
        self._refresh_labels()

    def update_eta(self, seconds: Optional[float]) -> None:
        """Update ETA (None clears ETA)."""
        self._metrics.eta_seconds = seconds
        self._refresh_labels()

    def update_progress(self, percent: float) -> None:
        """Update progress bar percentage."""
        self._metrics.progress_percent = percent
        self._progress_bar.set(percent)

    def increment_elapsed(self, delta: float = 0.1) -> None:
        """Add to elapsed time (for manual polling)."""
        self._metrics.elapsed_seconds += delta
        self._refresh_labels()

    def start_polling(self, callback: Callable[[], None],
                     interval: int = 200) -> None:
        """
        Start periodic polling for elapsed time updates.

        Args:
            callback: Function to call on each poll tick.
            interval: Polling interval in milliseconds (default 200).
        """
        if self._polling:
            return

        self._polling = True
        self._poll_interval = interval

        def poll():
            if not self._polling:
                return
            callback()
            self.after(interval, poll)

        self.after(interval, poll)

    def stop_polling(self) -> None:
        """Stop periodic polling."""
        self._polling = False

    def reset(self) -> None:
        """Reset all metrics to zero."""
        self.update_metrics(StatusBarMetrics())
        self.update_progress(0)

    def get_metrics(self) -> StatusBarMetrics:
        """Get current metrics."""
        return self._metrics.clone()

    def _apply_theme(self) -> None:
        """Re-apply theme colors to all widgets."""
        fg = theme_color("status.foreground")
        success = theme_color("feedback.success")
        accent = theme_color("status.accent")
        bg = theme_color("status.background")

        self._scanned_label.configure(text_color=fg)
        self._duplicates_label.configure(text_color=fg)
        self._groups_label.configure(text_color=fg)
        self._reclaimable_label.configure(text_color=success)
        self._elapsed_label.configure(text_color=fg)
        self._eta_label.configure(text_color=fg)

        self._progress_bar.configure(
            progress_color=accent,
            fg_color=bg,
        )

    def _format_time(self, seconds: float) -> str:
        """
        Format seconds to HH:MM:SS string.

        Args:
            seconds: Number of seconds.

        Returns:
            Formatted time string.
        """
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)

        return f"{hours:02d}:{minutes:02d}:{secs:02d}"


# Simple logger fallback
logger = __import__('logging').getLogger(__name__)
