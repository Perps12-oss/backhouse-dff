"""
Zoom Canvas Widget

Reusable CTkCanvas subclass with image zoom/pan capabilities.
Supports mouse-wheel zoom, click-drag pan, and synchronized viewing.
"""

from __future__ import annotations

import math
import tkinter as tk
from tkinter import ttk
from typing import Optional, Tuple, Callable
from pathlib import Path

try:
    import customtkinter as ctk
    CTkCanvas = ctk.CTkCanvas
except ImportError:
    CTkCanvas = tk.Canvas

try:
    from PIL import Image, ImageTk
    HAS_PIL = True
except ImportError:
    HAS_PIL = False
    Image = None

from cerebro.v2.core.design_tokens import Colors, Spacing, Dimensions


class ViewState:
    """Represents the current view state of an image."""

    def __init__(self):
        self.zoom_level: float = 1.0
        self.pan_x: float = 0.0
        self.pan_y: float = 0.0

    def clone(self) -> "ViewState":
        """Create a copy of this state."""
        return ViewState()

    def __repr__(self) -> str:
        return f"ViewState(zoom={self.zoom_level:.2f}, pan=({self.pan_x:.1f}, {self.pan_y:.1f}))"


class ZoomCanvas(CTkCanvas):
    """
    Canvas widget with zoom and pan support for image viewing.

    Features:
    - Mouse-wheel zoom (centered on cursor)
    - Click-drag pan
    - Synchronized zoom/pan with other canvas instances
    - Fit-to-window capability
    """

    MIN_ZOOM = 0.1
    MAX_ZOOM = 50.0
    ZOOM_STEP = 1.1
    ZOOM_ACCELERATOR = 2.0

    def __init__(self, master=None, **kwargs):
        """Initialize zoom canvas."""
        super().__init__(master, **kwargs)

        # Image data
        self._image_path: Optional[Path] = None
        self._original_image: Optional[Image.Image] = None
        self._display_image: Optional[ImageTk.PhotoImage] = None
        self._image_width: int = 0
        self._image_height: int = 0

        # View state
        self._view_state = ViewState()
        self._sync_partner: Optional[ZoomCanvas] = None

        # Pan state
        self._drag_start_x: Optional[float] = None
        self._drag_start_y: Optional[float] = None
        self._drag_start_pan_x: float = 0.0
        self._drag_start_pan_y: float = 0.0
        self._dragging: bool = False

        # Callbacks
        self._on_zoom_changed: Optional[Callable] = None
        self._on_pan_changed: Optional[Callable] = None
        self._on_image_loaded: Optional[Callable] = None

        # Bind events
        self._bind_events()

    def _bind_events(self) -> None:
        """Bind mouse and keyboard events."""
        self.bind("<MouseWheel>", self._on_mouse_wheel)
        self.bind("<Button-1>", self._on_mouse_down)
        self.bind("<B1-Motion>", self._on_mouse_drag)
        self.bind("<ButtonRelease-1>", self._on_mouse_up)
        self.bind("<ButtonPress-2>", self._on_right_click)

        # Keyboard bindings
        self.bind("<Key-0>", lambda e: self.zoom_in())
        self.bind("<Key-minus>", lambda e: self.zoom_out())
        self.bind("<Key-equal>", lambda e: self.zoom_in())
        self.bind("<Key-Left>", lambda e: self._pan(20, 0))
        self.bind("<Key-Right>", lambda e: self._pan(-20, 0))
        self.bind("<Key-Up>", lambda e: self._pan(0, 20))
        self.bind("<Key-Down>", lambda e: self._pan(0, -20))

    def load_image(self, path: Path, fit: bool = True) -> bool:
        """
        Load an image into the canvas.

        Args:
            path: Path to the image file.
            fit: If True, fit image to canvas size on load.

        Returns:
            True if image loaded successfully, False otherwise.
        """
        if not HAS_PIL:
            logger.warning("PIL not available, cannot load images")
            return False

        try:
            # Load image
            self._image_path = path
            self._original_image = Image.open(path)

            # Store dimensions
            self._image_width, self._image_height = self._original_image.size

            # Reset view state
            self._view_state = ViewState()
            if fit:
                self.fit_to_window()

            # Render image
            self._render_image()

            # Notify callback
            if self._on_image_loaded:
                self._on_image_loaded(self._image_path, self._image_width, self._image_height)

            return True

        except Exception as e:
            logger.error(f"Failed to load image {path}: {e}")
            return False

    def _render_image(self) -> None:
        """Render the image at current zoom and pan position."""
        if not self._original_image:
            return

        try:
            # Calculate visible dimensions
            zoom = self._view_state.zoom_level
            display_width = int(self._image_width * zoom)
            display_height = int(self._image_height * zoom)

            # Resize image for display
            if zoom != 1.0:
                # Use nearest for sharp edges when zoomed in
                resample = Image.Resampling.NEAREST if zoom > 1.0 else Image.Resampling.LANCZOS
                resized = self._original_image.resize(
                    (display_width, display_height),
                    resample
                )
            else:
                resized = self._original_image

            # Create PhotoImage
            self._display_image = ImageTk.PhotoImage(resized)

            # Calculate canvas center
            canvas_width = self.winfo_width()
            canvas_height = self.winfo_height()
            center_x = canvas_width / 2
            center_y = canvas_height / 2

            # Calculate position (centered + pan offset)
            pos_x = center_x - (display_width / 2) + self._view_state.pan_x
            pos_y = center_y - (display_height / 2) + self._view_state.pan_y

            # Clear and draw
            self.delete("all")
            self.create_image(
                self._display_image,
                pos_x,
                pos_y,
                anchor="nw",
                tags="image"
            )

        except Exception as e:
            logger.error(f"Failed to render image: {e}")

    def fit_to_window(self) -> None:
        """Fit image to canvas size."""
        if not self._original_image:
            return

        canvas_width = self.winfo_width()
        canvas_height = self.winfo_height()

        if self._image_width == 0 or self._image_height == 0:
            return

        # Calculate zoom to fit
        zoom_x = canvas_width / self._image_width
        zoom_y = canvas_height / self._image_height
        self._view_state.zoom_level = min(zoom_x, zoom_y)

        # Center the image
        self._view_state.pan_x = 0
        self._view_state.pan_y = 0

        self._render_image()
        self._notify_zoom_changed()

    def zoom_in(self, factor: Optional[float] = None) -> None:
        """Zoom in."""
        if not self._original_image:
            return

        old_zoom = self._view_state.zoom_level
        new_zoom = old_zoom * (factor or self.ZOOM_STEP)

        self._view_state.zoom_level = min(new_zoom, self.MAX_ZOOM)
        self._render_image()
        self._notify_zoom_changed()

        # Sync with partner
        if self._sync_partner:
            self._sync_partner.zoom_to(old_zoom, self._view_state.zoom_level)

    def zoom_out(self, factor: Optional[float] = None) -> None:
        """Zoom out."""
        if not self._original_image:
            return

        old_zoom = self._view_state.zoom_level
        new_zoom = old_zoom / (factor or self.ZOOM_STEP)

        self._view_state.zoom_level = max(new_zoom, self.MIN_ZOOM)
        self._render_image()
        self._notify_zoom_changed()

        # Sync with partner
        if self._sync_partner:
            self._sync_partner.zoom_to(old_zoom, self._view_state.zoom_level)

    def zoom_to(self, old_zoom: float, new_zoom: float) -> None:
        """
        Zoom to specific level (for sync from partner).

        Args:
            old_zoom: Previous zoom level (for calculating zoom factor).
            new_zoom: New zoom level to set.
        """
        if not self._original_image:
            return

        self._view_state.zoom_level = max(min(new_zoom, self.MAX_ZOOM), self.MIN_ZOOM)
        self._render_image()
        self._notify_zoom_changed()

    def _pan(self, dx: float, dy: float) -> None:
        """Pan the view."""
        if not self._original_image:
            return

        self._view_state.pan_x += dx
        self._view_state.pan_y += dy
        self._render_image()
        self._notify_pan_changed()

        # Sync with partner
        if self._sync_partner:
            self._sync_partner.set_pan(self._view_state.pan_x, self._view_state.pan_y)

    def set_pan(self, x: float, y: float) -> None:
        """Set pan position (for sync from partner)."""
        if not self._original_image:
            return

        self._view_state.pan_x = x
        self._view_state.pan_y = y
        self._render_image()
        self._notify_pan_changed()

    def reset_view(self) -> None:
        """Reset view to default (fit to window)."""
        self._view_state = ViewState()
        self.fit_to_window()

    def sync_with(self, other_canvas: "ZoomCanvas") -> None:
        """
        Synchronize zoom and pan with another canvas.

        When one canvas is zoomed/panned, the other matches.
        """
        self._sync_partner = other_canvas
        other_canvas._sync_partner = self

    def get_view_state(self) -> ViewState:
        """Get current view state."""
        return self._view_state.clone()

    def set_view_state(self, state: ViewState) -> None:
        """Set view state (for restoring saved state)."""
        if not self._original_image:
            return

        self._view_state = state.clone()
        self._render_image()
        self._notify_zoom_changed()
        self._notify_pan_changed()

    def get_image_info(self) -> dict:
        """Get information about loaded image."""
        return {
            "path": str(self._image_path) if self._image_path else None,
            "width": self._image_width,
            "height": self._image_height,
            "zoom": self._view_state.zoom_level,
        }

    # ===================
    # EVENT HANDLERS
    # ===================

    def _on_mouse_wheel(self, event) -> None:
        """Handle mouse wheel for zooming."""
        if not self._original_image:
            return

        # Get mouse position relative to canvas
        canvas_x = self.canvasx(event.x)
        canvas_y = self.canvasy(event.y)

        # Calculate zoom factor based on wheel direction
        # Windows: event.delta, Linux: event.num
        delta = getattr(event, "delta", 0)
        if delta == 0:
            delta = -event.num  # Linux

        if delta > 0:
            # Zoom out
            factor = 1.0 / self.ZOOM_ACCELERATOR
        else:
            # Zoom in
            factor = self.ZOOM_ACCELERATOR

        old_zoom = self._view_state.zoom_level
        new_zoom = old_zoom * factor
        self._view_state.zoom_level = max(min(new_zoom, self.MAX_ZOOM), self.MIN_ZOOM)

        # Adjust pan to keep mouse over same image point
        # Calculate image position under mouse before zoom
        image_x = canvas_x - (self._image_width / 2) * old_zoom - self._view_state.pan_x
        image_y = canvas_y - (self._image_height / 2) * old_zoom - self._view_state.pan_y

        # Recalculate pan to keep image_x, image_y under mouse after zoom
        self._view_state.pan_x = canvas_x - (self._image_width / 2) * new_zoom - image_x
        self._view_state.pan_y = canvas_y - (self._image_height / 2) * new_zoom - image_y

        self._render_image()
        self._notify_zoom_changed()

        # Sync with partner
        if self._sync_partner:
            self._sync_partner.zoom_to(old_zoom, self._view_state.zoom_level)

    def _on_mouse_down(self, event) -> None:
        """Handle mouse button press for panning."""
        self._dragging = True
        self._drag_start_x = event.x
        self._drag_start_y = event.y
        self._drag_start_pan_x = self._view_state.pan_x
        self._drag_start_pan_y = self._view_state.pan_y

    def _on_mouse_drag(self, event) -> None:
        """Handle mouse drag for panning."""
        if not self._dragging:
            return

        dx = event.x - self._drag_start_x
        dy = event.y - self._drag_start_y

        self._view_state.pan_x = self._drag_start_pan_x + dx
        self._view_state.pan_y = self._drag_start_pan_y + dy

        self._render_image()
        self._notify_pan_changed()

        # Sync with partner
        if self._sync_partner:
            self._sync_partner.set_pan(self._view_state.pan_x, self._view_state.pan_y)

    def _on_mouse_up(self, event) -> None:
        """Handle mouse button release."""
        self._dragging = False

    def _on_right_click(self, event) -> None:
        """Handle right-click (reset zoom)."""
        self.reset_view()

    def _notify_zoom_changed(self) -> None:
        """Notify callbacks that zoom changed."""
        if self._on_zoom_changed:
            self._on_zoom_changed(self._view_state.zoom_level)

    def _notify_pan_changed(self) -> None:
        """Notify callbacks that pan changed."""
        if self._on_pan_changed:
            self._on_pan_changed(self._view_state.pan_x, self._view_state.pan_y)

    def on_zoom_changed(self, callback: Callable[[float], None]) -> None:
        """Set callback for zoom changes."""
        self._on_zoom_changed = callback

    def on_pan_changed(self, callback: Callable[[float, float], None]) -> None:
        """Set callback for pan changes."""
        self._on_pan_changed = callback

    def on_image_loaded(self, callback: Callable[[Path, int, int], None]) -> None:
        """Set callback for image loaded."""
        self._on_image_loaded = callback


# Simple logger fallback
logger = __import__('logging').getLogger(__name__)
