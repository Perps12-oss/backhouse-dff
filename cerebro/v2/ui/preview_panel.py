"""
Preview Panel Widget

Bottom panel with side-by-side comparison viewer.
Uses two synchronized ZoomCanvas widgets with metadata labels.
"""

from __future__ import annotations

import tkinter as tk
from typing import Optional, Callable, Dict, Any
from pathlib import Path

try:
    import customtkinter as ctk
    CTkFrame = ctk.CTkFrame
    CTkLabel = ctk.CTkLabel
    CTkButton = ctk.CTkButton
    CTkSwitch = ctk.CTkSwitch
except ImportError:
    CTkFrame = tk.Frame
    CTkLabel = tk.Label
    CTkButton = tk.Button
    CTkSwitch = tk.Checkbutton

from cerebro.v2.core.design_tokens import (
    Colors, Spacing, Typography, Dimensions
)
from cerebro.v2.ui.widgets.zoom_canvas import ZoomCanvas


class PreviewSidePanel(CTkFrame):
    """
    One side of the preview panel with canvas and metadata.

    Features:
    - ZoomCanvas for image display
    - Metadata labels (resolution, size, format, date, path)
    - Keep This button (marks file as keeper)
    """

    def __init__(self, master=None, title: str = "", **kwargs):
        super().__init__(master, **kwargs)
        self._title = title

        # State
        self._current_file: Optional[Dict[str, Any]] = None

        # Widgets
        self._canvas: Optional[ZoomCanvas] = None
        self._keep_btn: Optional[CTkButton] = None
        self._metadata_labels: Dict[str, CTkLabel] = {}

        # Callbacks
        self._on_keep_clicked: Optional[Callable[[], None]] = None

        # Build UI
        self._build_ui()

    def _build_ui(self) -> None:
        """Build preview side panel UI."""
        self.configure(
            fg_color=Colors.BG_TERTIARY.hex
        )

        # Title label
        if self._title:
            CTkLabel(
                self,
                text=self._title,
                font=Typography.FONT_SM,
                text_color=Colors.TEXT_SECONDARY.hex
            ).pack(anchor="w", padx=Spacing.SM, pady=(Spacing.SM, 0))

        # Canvas frame
        canvas_frame = CTkFrame(self)
        canvas_frame.pack(fill="both", expand=True, padx=Spacing.XS)

        # ZoomCanvas
        self._canvas = ZoomCanvas(
            canvas_frame,
            bg_color=Colors.BG_SECONDARY.hex
        )
        self._canvas.pack(fill="both", expand=True)

        # Metadata frame
        metadata_frame = CTkFrame(
            self,
            height=80,
            fg_color=Colors.BG_QUATERNARY.hex
        )
        metadata_frame.pack(fill="x", padx=Spacing.XS, pady=Spacing.SM)

        # Metadata labels grid
        self._build_metadata_labels(metadata_frame)

        # Keep This button
        self._keep_btn = CTkButton(
            self,
            text="📌 Keep This",
            height=28,
            font=Typography.FONT_SM,
            fg_color=Colors.SUCCESS.hex,
            hover_color=Colors.SUCCESS_HOVER.hex,
            corner_radius=Spacing.BORDER_RADIUS_SM
        )
        self._keep_btn.pack(fill="x", padx=Spacing.SM, pady=(0, Spacing.SM))
        self._keep_btn.configure(command=self._on_keep_clicked)

        # Initially disabled
        self._keep_btn.configure(state="disabled")

    def _build_metadata_labels(self, parent: CTkFrame) -> None:
        """Build metadata labels grid."""
        # Resolution label
        self._metadata_labels["resolution"] = CTkLabel(
            parent,
            text="-- x -- px",
            font=Typography.FONT_SM,
            text_color=Colors.TEXT_SECONDARY.hex
        )
        self._metadata_labels["resolution"].grid(
            row=0, column=0, padx=Spacing.SM, pady=Spacing.XS, sticky="w"
        )

        # Size label
        self._metadata_labels["size"] = CTkLabel(
            parent,
            text="0 B",
            font=Typography.FONT_SM,
            text_color=Colors.TEXT_SECONDARY.hex
        )
        self._metadata_labels["size"].grid(
            row=0, column=1, padx=Spacing.SM, pady=Spacing.XS, sticky="w"
        )

        # Format label
        self._metadata_labels["format"] = CTkLabel(
            parent,
            text="--",
            font=Typography.FONT_XS,
            text_color=Colors.TEXT_MUTED.hex,
            width=40
        )
        self._metadata_labels["format"].grid(
            row=0, column=2, padx=Spacing.SM, pady=Spacing.XS, sticky="w"
        )

        # Date label
        self._metadata_labels["date"] = CTkLabel(
            parent,
            text="----/--/--",
            font=Typography.FONT_XS,
            text_color=Colors.TEXT_MUTED.hex
        )
        self._metadata_labels["date"].grid(
            row=1, column=0, columnspan=2,
            padx=Spacing.SM, pady=Spacing.XS, sticky="w"
        )

        # Path label (truncated)
        self._metadata_labels["path"] = CTkLabel(
            parent,
            text="",
            font=Typography.FONT_XS,
            text_color=Colors.TEXT_MUTED.hex,
            anchor="w"
        )
        self._metadata_labels["path"].grid(
            row=1, column=2,
            padx=Spacing.SM, pady=Spacing.XS, sticky="w"
        )

    def load_file(self, file_data: Dict[str, Any]) -> None:
        """
        Load a file into preview.

        Args:
            file_data: Dictionary with file info (path, size, modified, etc.).
        """
        self._current_file = file_data
        path_str = file_data.get("path", "")
        path = Path(path_str) if path_str else None

        if not path or not path.exists():
            self._clear_display()
            return

        # Load image into canvas
        self._canvas.load_image(path, fit=True)

        # Update metadata
        self._update_metadata(file_data, path)

        # Enable keep button
        self._keep_btn.configure(state="normal")

    def _clear_display(self) -> None:
        """Clear the preview display."""
        self._current_file = None

        # Clear canvas
        # TODO: Add clear method to ZoomCanvas or just reset
        self._canvas.reset_view()

        # Reset metadata labels
        self._metadata_labels["resolution"].configure(text="-- x -- px")
        self._metadata_labels["size"].configure(text="0 B")
        self._metadata_labels["format"].configure(text="--")
        self._metadata_labels["date"].configure(text="----/--/--")
        self._metadata_labels["path"].configure(text="")

        # Disable keep button
        self._keep_btn.configure(state="disabled")

    def _update_metadata(self, file_data: Dict[str, Any], path: Path) -> None:
        """Update metadata labels from file data."""
        # Resolution (if available)
        width = file_data.get("width")
        height = file_data.get("height")
        if width and height:
            self._metadata_labels["resolution"].configure(
                text=f"{width} × {height} px"
            )
        else:
            self._metadata_labels["resolution"].configure(text="-- x -- px")

        # Size
        size = file_data.get("size", 0)
        self._metadata_labels["size"].configure(text=self._format_bytes(size))

        # Format (extension)
        ext = path.suffix.upper().lstrip('.')
        self._metadata_labels["format"].configure(text=ext if ext else "--")

        # Modified date
        modified = file_data.get("modified", 0)
        if modified:
            self._metadata_labels["date"].configure(
                text=self._format_date(modified)
            )
        else:
            self._metadata_labels["date"].configure(text="----/--/--")

        # Path (truncated)
        path_str = str(path)
        if len(path_str) > 50:
            path_str = "..." + path_str[-47:]
        self._metadata_labels["path"].configure(text=path_str)

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

    def _format_date(self, timestamp: float) -> str:
        """Format timestamp to readable date."""
        if not timestamp:
            return "----/--/--"

        from datetime import datetime
        dt = datetime.fromtimestamp(timestamp)
        return dt.strftime("%Y-%m-%d")

    def _on_keep_clicked(self) -> None:
        """Handle Keep This button click."""
        if self._on_keep_clicked and self._current_file:
            self._on_keep_clicked()

    def get_canvas(self) -> ZoomCanvas:
        """Get the ZoomCanvas widget."""
        return self._canvas

    def on_keep_clicked(self, callback: Callable[[], None]) -> None:
        """Set callback for Keep This button."""
        self._on_keep_clicked = callback


class PreviewPanel(CTkFrame):
    """
    Bottom panel with side-by-side comparison viewer.

    Features:
    - Two synchronized ZoomCanvas widgets
    - Metadata display for each image
    - Keep This buttons for each side
    - Sync zoom/pan between canvases
    - Collapsible
    - Diff toggle (visual difference overlay)
    """

    def __init__(self, master=None, **kwargs):
        super().__init__(master, **kwargs)

        # State
        self._file_a: Optional[Dict[str, Any]] = None
        self._file_b: Optional[Dict[str, Any]] = None
        self._comparison_mode: bool = False
        self._diff_enabled: bool = False
        self._collapsed: bool = False

        # Widgets
        self._header_frame: Optional[CTkFrame] = None
        self._collapse_btn: Optional[CTkButton] = None
        self._diff_switch: Optional[CTkSwitch] = None
        self._sync_btn: Optional[CTkButton] = None
        self._side_a_panel: Optional[PreviewSidePanel] = None
        self._side_b_panel: Optional[PreviewSidePanel] = None
        self._content_frame: Optional[CTkFrame] = None
        self._empty_label: Optional[CTkLabel] = None

        # Callbacks
        self._on_keep_a: Optional[Callable[[], None]] = None
        self._on_keep_b: Optional[Callable[[], None]] = None

        # Build UI
        self._build_ui()

    def _build_ui(self) -> None:
        """Build preview panel UI."""
        self.configure(
            fg_color=Colors.BG_SECONDARY.hex
        )

        # Header frame
        self._build_header()

        # Content frame (holds side panels)
        self._content_frame = CTkFrame(self)
        self._content_frame.pack(fill="both", expand=True, padx=Spacing.XS, pady=Spacing.SM)

        # Side-by-side panels
        self._build_side_panels()

        # Empty state label
        self._empty_label = CTkLabel(
            self._content_frame,
            text="Select a file to preview\nSelect two files for comparison",
            font=Typography.FONT_MD,
            text_color=Colors.TEXT_MUTED.hex
        )
        self._empty_label.pack(expand=True)

        # Initially hide side panels
        self._side_a_panel.pack_forget()
        self._side_b_panel.pack_forget()

    def _build_header(self) -> None:
        """Build panel header with collapse toggle and options."""
        self._header_frame = CTkFrame(
            self,
            height=32,
            fg_color=Colors.BG_TERTIARY.hex
        )
        self._header_frame.pack(fill="x")

        # Title
        CTkLabel(
            self._header_frame,
            text="Preview",
            font=Typography.FONT_MD,
            text_color=Colors.TEXT_PRIMARY.hex
        ).pack(side="left", padx=Spacing.MD)

        # Spacer
        spacer = CTkLabel(self._header_frame, text="")
        spacer.pack(side="left", expand=True)

        # Diff toggle switch
        self._diff_switch = CTkSwitch(
            self._header_frame,
            text="Diff Overlay",
            font=Typography.FONT_SM,
            onvalue=True,
            offvalue=False
        )
        self._diff_switch.pack(side="right", padx=Spacing.SM)
        # TODO: Configure command for diff switch

        # Sync button
        self._sync_btn = CTkButton(
            self._header_frame,
            text="🔗 Sync",
            width=60,
            height=28,
            font=Typography.FONT_SM,
            fg_color=Colors.BG_QUATERNARY.hex,
            hover_color=Colors.BG_PRIMARY.hex,
            corner_radius=Spacing.BORDER_RADIUS_SM
        )
        self._sync_btn.pack(side="right", padx=Spacing.SM)
        self._sync_btn.configure(command=self._toggle_sync)

        # Collapse button
        self._collapse_btn = CTkButton(
            self._header_frame,
            text="▼",
            width=32,
            height=28,
            font=Typography.FONT_MD,
            fg_color=Colors.TEXT_SECONDARY.hex,
            hover_color=Colors.TEXT_PRIMARY.hex,
            corner_radius=0
        )
        self._collapse_btn.pack(side="right", padx=Spacing.SM)
        self._collapse_btn.configure(command=self._toggle_collapse)

    def _build_side_panels(self) -> None:
        """Build side-by-side preview panels."""
        # Side A panel
        self._side_a_panel = PreviewSidePanel(
            self._content_frame,
            title="Image A"
        )
        self._side_a_panel.pack(side="left", fill="both", expand=True, padx=Spacing.XS)
        self._side_a_panel.on_keep_clicked(self._on_keep_a_clicked)

        # Side B panel
        self._side_b_panel = PreviewSidePanel(
            self._content_frame,
            title="Image B"
        )
        self._side_b_panel.pack(side="left", fill="both", expand=True, padx=Spacing.XS)
        self._side_b_panel.on_keep_clicked(self._on_keep_b_clicked)

        # Sync canvases
        self._side_a_panel.get_canvas().sync_with(self._side_b_panel.get_canvas())

    def _toggle_collapse(self) -> None:
        """Toggle panel collapse state."""
        self._collapsed = not self._collapsed

        if self._collapsed:
            # Collapse: hide content, show only header
            self._content_frame.pack_forget()
            self._collapse_btn.configure(text="▶")
        else:
            # Expand: show content
            self._content_frame.pack(fill="both", expand=True, padx=Spacing.XS, pady=Spacing.SM)
            self._collapse_btn.configure(text="▼")

            # Show/hide panels based on state
            self._update_content_visibility()

    def _toggle_sync(self) -> None:
        """Toggle canvas synchronization."""
        canvas_a = self._side_a_panel.get_canvas()
        canvas_b = self._side_b_panel.get_canvas()

        # Toggle sync
        if canvas_a._sync_partner:
            # Unsync
            canvas_a._sync_partner = None
            canvas_b._sync_partner = None
            self._sync_btn.configure(text="🔗 Sync")
        else:
            # Sync
            canvas_a.sync_with(canvas_b)
            self._sync_btn.configure(text="🔗 Synced")

    def _update_content_visibility(self) -> None:
        """Update visibility of side panels based on state."""
        if self._file_a or self._file_b:
            # Show panels
            if self._empty_label.winfo_ismapped():
                self._empty_label.pack_forget()
            if not self._side_a_panel.winfo_ismapped():
                self._side_a_panel.pack(side="left", fill="both", expand=True, padx=Spacing.XS)
                self._side_b_panel.pack(side="left", fill="both", expand=True, padx=Spacing.XS)
        else:
            # Show empty label
            if self._side_a_panel.winfo_ismapped():
                self._side_a_panel.pack_forget()
                self._side_b_panel.pack_forget()
            if not self._empty_label.winfo_ismapped():
                self._empty_label.pack(expand=True)

    # ===================
    # PUBLIC API
    # ===================

    def load_file_a(self, file_data: Dict[str, Any]) -> None:
        """
        Load a file into panel A.

        Args:
            file_data: Dictionary with file info.
        """
        self._file_a = file_data
        self._comparison_mode = bool(self._file_b)

        if file_data:
            self._side_a_panel.load_file(file_data)
        else:
            self._side_a_panel._clear_display()

        self._update_content_visibility()

    def load_file_b(self, file_data: Dict[str, Any]) -> None:
        """
        Load a file into panel B.

        Args:
            file_data: Dictionary with file info.
        """
        self._file_b = file_data
        self._comparison_mode = bool(self._file_a)

        if file_data:
            self._side_b_panel.load_file(file_data)
        else:
            self._side_b_panel._clear_display()

        self._update_content_visibility()

    def load_single(self, file_data: Dict[str, Any]) -> None:
        """
        Load a single file (clears side B).

        Args:
            file_data: Dictionary with file info.
        """
        self._file_a = file_data
        self._file_b = None
        self._comparison_mode = False

        self._side_a_panel.load_file(file_data)
        self._side_b_panel._clear_display()

        self._update_content_visibility()

    def load_comparison(self, file_a: Dict[str, Any], file_b: Dict[str, Any]) -> None:
        """
        Load two files for side-by-side comparison.

        Args:
            file_a: First file to display.
            file_b: Second file to display.
        """
        self._file_a = file_a
        self._file_b = file_b
        self._comparison_mode = True

        self._side_a_panel.load_file(file_a)
        self._side_b_panel.load_file(file_b)

        self._update_content_visibility()

    def clear(self) -> None:
        """Clear all preview panels."""
        self._file_a = None
        self._file_b = None
        self._comparison_mode = False

        self._side_a_panel._clear_display()
        self._side_b_panel._clear_display()

        self._update_content_visibility()

    def reset_views(self) -> None:
        """Reset both canvas views to fit-to-window."""
        self._side_a_panel.get_canvas().reset_view()
        self._side_b_panel.get_canvas().reset_view()

    def zoom_in(self) -> None:
        """Zoom in on both canvases."""
        self._side_a_panel.get_canvas().zoom_in()
        # Sync will automatically update B

    def zoom_out(self) -> None:
        """Zoom out on both canvases."""
        self._side_a_panel.get_canvas().zoom_out()

    def get_file_a(self) -> Optional[Dict[str, Any]]:
        """Get file A data."""
        return self._file_a

    def get_file_b(self) -> Optional[Dict[str, Any]]:
        """Get file B data."""
        return self._file_b

    def is_comparison_mode(self) -> bool:
        """Check if showing comparison (two files)."""
        return self._comparison_mode

    def toggle_diff_overlay(self, enabled: bool) -> None:
        """
        Toggle diff overlay mode.

        Args:
            enabled: Whether to show diff overlay.
        """
        self._diff_enabled = enabled
        # TODO: Implement diff overlay visualization

    def set_collapsed(self, collapsed: bool) -> None:
        """
        Set collapsed state.

        Args:
            collapsed: Whether panel should be collapsed.
        """
        if self._collapsed != collapsed:
            self._toggle_collapse()

    def is_collapsed(self) -> bool:
        """Check if panel is collapsed."""
        return self._collapsed

    def on_keep_a(self, callback: Callable[[], None]) -> None:
        """Set callback for Keep A button."""
        self._on_keep_a = callback

    def on_keep_b(self, callback: Callable[[], None]) -> None:
        """Set callback for Keep B button."""
        self._on_keep_b = callback

    def _on_keep_a_clicked(self) -> None:
        """Handle Keep A button click."""
        if self._on_keep_a:
            self._on_keep_a()

    def _on_keep_b_clicked(self) -> None:
        """Handle Keep B button click."""
        if self._on_keep_b:
            self._on_keep_b()


# Simple logger fallback
logger = __import__('logging').getLogger(__name__)
