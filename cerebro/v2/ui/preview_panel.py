"""
Preview Panel Widget

Collapsible bottom panel for file preview.

Behaviour:
- Collapsed by default (32 px header strip only).
- Auto-expands when a file is selected from the results panel.
- Context-sensitive: shows image for image files; metadata-only for others.
- Side-by-side comparison when two files are loaded.
- No "Keep A / Keep B" buttons (selection is handled via checkboxes in results).
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

from cerebro.v2.core.design_tokens import Spacing, Typography, Dimensions
from cerebro.v2.core.theme_bridge_v2 import theme_color, subscribe_to_theme
from cerebro.v2.ui.widgets.zoom_canvas import ZoomCanvas
from cerebro.v2.ui.widgets.metadata_table import MetadataTable
from cerebro.utils.formatting import format_bytes

# Image extensions that should show the canvas
_IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".tif",
    ".webp", ".heic", ".heif", ".cr2", ".cr3", ".nef",
    ".arw", ".dng", ".orf", ".rw2", ".pef", ".raf", ".sr2",
}

_DEFAULT_HEIGHT = 220  # px when expanded


def _format_bytes(n: int) -> str:
    return format_bytes(n, decimals=1)


def _format_date(ts: float) -> str:
    if not ts:
        return "—"
    from datetime import datetime
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# Side panel (one half of the comparison)
# ---------------------------------------------------------------------------

class _SidePanel(CTkFrame):
    """
    Single-side preview: optional image canvas + compact metadata row.
    No Keep button.
    """

    def __init__(self, master=None, title: str = "A", **kwargs):
        super().__init__(master, **kwargs)
        self._title = title
        self._current_file: Optional[Dict[str, Any]] = None

        subscribe_to_theme(self, self._apply_theme)
        self._build()

    def _build(self) -> None:
        self.configure(fg_color=theme_color("base.backgroundTertiary"))

        # Title bar
        title_bar = CTkFrame(self, height=24,
                             fg_color=theme_color("base.backgroundElevated"))
        title_bar.pack(fill="x")
        self._title_lbl = CTkLabel(
            title_bar, text=self._title,
            font=Typography.FONT_XS,
            text_color=theme_color("base.foregroundSecondary"))
        self._title_lbl.pack(side="left", padx=Spacing.SM)

        # Canvas (hidden for non-image files)
        self._canvas = ZoomCanvas(self, bg_color=theme_color("preview.background"))
        self._canvas.pack(fill="both", expand=True, padx=Spacing.XS, pady=Spacing.XS)

        # Placeholder for non-image files
        self._no_preview = CTkLabel(
            self, text="No preview",
            font=Typography.FONT_SM,
            text_color=theme_color("base.foregroundMuted"))
        # (not packed initially)

        # Metadata bar — single compact line
        meta_bar = CTkFrame(self, height=28,
                            fg_color=theme_color("base.backgroundElevated"))
        meta_bar.pack(fill="x")

        self._meta_lbl = CTkLabel(
            meta_bar, text="—",
            font=Typography.FONT_XS,
            text_color=theme_color("base.foregroundSecondary"),
            anchor="w")
        self._meta_lbl.pack(side="left", padx=Spacing.SM, fill="x", expand=True)

        self._ext_badge = CTkLabel(
            meta_bar, text="",
            font=Typography.FONT_XS,
            text_color=theme_color("base.foregroundMuted"),
            width=40)
        self._ext_badge.pack(side="right", padx=Spacing.SM)

    def _apply_theme(self) -> None:
        try:
            self.configure(fg_color=theme_color("base.backgroundTertiary"))
            self._meta_lbl.configure(text_color=theme_color("base.foregroundSecondary"))
            self._ext_badge.configure(text_color=theme_color("base.foregroundMuted"))
        except Exception:
            pass

    def _fd_get(self, file_data: Any, key: str, default: Any = None) -> Any:
        if isinstance(file_data, dict):
            return file_data.get(key, default)
        value = getattr(file_data, key, default)
        if value is not None:
            return value
        meta = getattr(file_data, "metadata", None)
        if isinstance(meta, dict):
            return meta.get(key, default)
        return default

    def load(self, file_data: Any) -> None:
        self._current_file = file_data
        path_str = str(self._fd_get(file_data, "path", "") or "")
        path = Path(path_str) if path_str else None

        is_image = (path and path.suffix.lower() in _IMAGE_EXTENSIONS
                    and path.exists())

        if is_image:
            self._no_preview.pack_forget()
            self._canvas.pack(fill="both", expand=True,
                              padx=Spacing.XS, pady=Spacing.XS)
            self._canvas.load_image(path, fit=True)
        else:
            self._canvas.pack_forget()
            self._no_preview.pack(expand=True)

        # Compact metadata: "1280 × 720 px  ·  3.2 MB  ·  2024-05-01"
        parts = []
        w, h = self._fd_get(file_data, "width"), self._fd_get(file_data, "height")
        if w and h:
            parts.append(f"{w} × {h} px")
        size = self._fd_get(file_data, "size", 0)
        if size:
            parts.append(_format_bytes(size))
        modified = self._fd_get(file_data, "modified", 0)
        if modified:
            parts.append(_format_date(modified))
        self._meta_lbl.configure(text="  ·  ".join(parts) if parts else "—")

        ext = path.suffix.upper().lstrip(".") if path else ""
        self._ext_badge.configure(text=ext)

        # Update title to show filename
        name = path.name if path else "File"
        if len(name) > 34:
            name = name[:31] + "..."
        self._title_lbl.configure(text=name)

    def clear(self) -> None:
        self._current_file = None
        self._canvas.reset_view()
        self._canvas.pack(fill="both", expand=True,
                          padx=Spacing.XS, pady=Spacing.XS)
        self._no_preview.pack_forget()
        self._meta_lbl.configure(text="—")
        self._ext_badge.configure(text="")
        self._title_lbl.configure(text=self._title)

    def get_canvas(self) -> ZoomCanvas:
        return self._canvas


# ---------------------------------------------------------------------------
# PreviewPanel — public widget
# ---------------------------------------------------------------------------

class PreviewPanel(CTkFrame):
    """
    Collapsible preview panel.

    Collapsed by default (header strip only, 32 px).
    Auto-expands to _DEFAULT_HEIGHT when load_single() or load_comparison()
    is called with non-None data.
    """

    def __init__(self, master=None, **kwargs):
        super().__init__(master, **kwargs)

        self._collapsed: bool = True
        self._file_a: Optional[Any] = None
        self._file_b: Optional[Any] = None
        self._sync_enabled: bool = True
        self._layout_mode: str = "compact"
        self._metadata_table: Optional[MetadataTable] = None

        subscribe_to_theme(self, self._apply_theme)
        self._build()

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _build(self) -> None:
        self.configure(fg_color=theme_color("preview.background"))

        # ── Header (always visible) ────────────────────────────────
        self._header = CTkFrame(
            self, height=32,
            fg_color=theme_color("base.backgroundTertiary"))
        self._header.pack(fill="x")
        self._header.pack_propagate(False)

        self._expand_btn = CTkButton(
            self._header, text="▶  Preview",
            width=100, height=28,
            font=Typography.FONT_SM,
            fg_color="transparent",
            hover_color=theme_color("base.backgroundElevated"),
            text_color=theme_color("base.foregroundSecondary"),
            border_width=0, corner_radius=0,
            anchor="w",
        )
        self._expand_btn.pack(side="left", padx=Spacing.XS)
        self._expand_btn.configure(command=self._toggle)

        # Diff switch (right side of header)
        self._diff_switch = CTkSwitch(
            self._header, text="Diff",
            font=Typography.FONT_XS,
            width=60,
            onvalue=True, offvalue=False,
            command=self._on_diff_toggled,
        )
        self._diff_switch.pack(side="right", padx=Spacing.SM)

        # Sync button
        self._sync_btn = CTkButton(
            self._header, text="🔗", width=36, height=24,
            font=Typography.FONT_SM,
            fg_color=theme_color("base.backgroundElevated"),
            hover_color=theme_color("base.background"),
            corner_radius=Spacing.BORDER_RADIUS_SM,
        )
        self._sync_btn.pack(side="right", padx=(0, Spacing.XS))
        self._sync_btn.configure(command=self._toggle_sync)

        # ── Content (hidden when collapsed) ────────────────────────
        self._content = CTkFrame(
            self, fg_color=theme_color("preview.background"))
        # Not packed — starts collapsed

        self._side_a = _SidePanel(self._content, title="A")
        self._side_b = _SidePanel(self._content, title="B")

        # Sync canvases by default
        self._side_a.get_canvas().sync_with(self._side_b.get_canvas())

        # Both sides hidden until data loaded
        self._side_a.pack_forget()
        self._side_b.pack_forget()

        # Empty hint inside content
        self._hint = CTkLabel(
            self._content,
            text="Select a file in the results to preview it here.",
            font=Typography.FONT_SM,
            text_color=theme_color("base.foregroundMuted"))
        self._hint.pack(expand=True)

        # Ashisoft alternate content (always-visible style)
        self._ashisoft_content = CTkFrame(self, fg_color=theme_color("preview.background"))
        self._ashisoft_canvas = ZoomCanvas(self._ashisoft_content, bg_color=theme_color("preview.background"))
        self._ashisoft_canvas.pack(fill="both", expand=True, padx=Spacing.XS, pady=(Spacing.XS, Spacing.XS))
        self._ashisoft_no_preview = CTkLabel(
            self._ashisoft_content,
            text="Select a file in the results to preview it here.",
            font=Typography.FONT_SM,
            text_color=theme_color("base.foregroundMuted"),
        )
        self._metadata_table = MetadataTable(self._ashisoft_content)
        self._metadata_table.pack(fill="x", side="bottom", padx=Spacing.XS, pady=(0, Spacing.XS))

    # ------------------------------------------------------------------
    # Collapse / expand
    # ------------------------------------------------------------------

    def _toggle(self) -> None:
        self.set_collapsed(not self._collapsed)

    def set_collapsed(self, collapsed: bool) -> None:
        if self._collapsed == collapsed:
            return
        self._collapsed = collapsed
        if collapsed:
            self._content.pack_forget()
            self._expand_btn.configure(text="▶  Preview")
        else:
            self._content.pack(fill="both", expand=True)
            self._expand_btn.configure(text="▼  Preview")

    def is_collapsed(self) -> bool:
        return self._collapsed

    def _auto_expand(self) -> None:
        """Expand if currently collapsed (called when data arrives)."""
        if self._collapsed:
            self.set_collapsed(False)

    # ------------------------------------------------------------------
    # Sync / diff
    # ------------------------------------------------------------------

    def _toggle_sync(self) -> None:
        ca = self._side_a.get_canvas()
        cb = self._side_b.get_canvas()
        if self._sync_enabled:
            ca._sync_partner = None
            cb._sync_partner = None
            self._sync_enabled = False
            self._sync_btn.configure(fg_color=theme_color("base.backgroundTertiary"))
        else:
            ca.sync_with(cb)
            self._sync_enabled = True
            self._sync_btn.configure(fg_color=theme_color("base.backgroundElevated"))

    def _on_diff_toggled(self) -> None:
        pass  # TODO: pixel-diff overlay in a future task

    # ------------------------------------------------------------------
    # Content visibility helpers
    # ------------------------------------------------------------------

    def _update_layout(self) -> None:
        """Show correct side panels based on loaded data."""
        has_a = self._file_a is not None
        has_b = self._file_b is not None

        self._hint.pack_forget()
        self._side_a.pack_forget()
        self._side_b.pack_forget()

        if not has_a and not has_b:
            self._hint.pack(expand=True)
            return

        if has_a and has_b:
            self._side_a.pack(side="left", fill="both", expand=True,
                              padx=(Spacing.XS, 0), pady=Spacing.XS)
            self._side_b.pack(side="left", fill="both", expand=True,
                              padx=(0, Spacing.XS), pady=Spacing.XS)
        else:
            # Single file — only side A, full width
            self._side_a.pack(fill="both", expand=True,
                              padx=Spacing.XS, pady=Spacing.XS)

    # ------------------------------------------------------------------
    # Theme
    # ------------------------------------------------------------------

    def _apply_theme(self) -> None:
        try:
            self.configure(fg_color=theme_color("preview.background"))
            self._header.configure(fg_color=theme_color("base.backgroundTertiary"))
            self._content.configure(fg_color=theme_color("preview.background"))
            self._hint.configure(text_color=theme_color("base.foregroundMuted"))
            self._expand_btn.configure(
                hover_color=theme_color("base.backgroundElevated"),
                text_color=theme_color("base.foregroundSecondary"))
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def _update_ashisoft_view(self) -> None:
        if self._metadata_table is None:
            return
        target = self._file_a or self._file_b
        if not target:
            try:
                self._ashisoft_canvas.pack_forget()
                self._ashisoft_no_preview.pack(expand=True)
            except Exception:
                pass
            self._metadata_table.clear()
            return
        if isinstance(target, dict):
            path_str = str(target.get("path", "") or "")
        else:
            path_str = str(getattr(target, "path", "") or "")
        path = Path(path_str) if path_str else None
        is_image = (path and path.suffix.lower() in _IMAGE_EXTENSIONS and path.exists())
        try:
            if is_image:
                self._ashisoft_no_preview.pack_forget()
                self._ashisoft_canvas.pack(fill="both", expand=True, padx=Spacing.XS, pady=(Spacing.XS, Spacing.XS), before=self._metadata_table)
                self._ashisoft_canvas.load_image(path, fit=True)
            else:
                self._ashisoft_canvas.pack_forget()
                self._ashisoft_no_preview.pack(expand=True, before=self._metadata_table)
        except Exception:
            pass
        self._metadata_table.load(path)

    def set_layout_mode(self, mode: str) -> None:
        if mode not in ("compact", "ashisoft") or mode == self._layout_mode:
            return
        self._layout_mode = mode
        try:
            self._content.pack_forget()
            self._ashisoft_content.pack_forget()
        except Exception:
            pass
        if mode == "ashisoft":
            try:
                self._header.pack_forget()
            except Exception:
                pass
            self._ashisoft_content.pack(fill="both", expand=True)
            self._collapsed = False
            self._update_ashisoft_view()
        else:
            try:
                self._header.pack(fill="x", before=self._ashisoft_content)
            except Exception:
                try:
                    self._header.pack(fill="x")
                except Exception:
                    pass
            if not self._collapsed:
                self._content.pack(fill="both", expand=True)

    def get_layout_mode(self) -> str:
        return self._layout_mode

    def load_single(self, file_data: Optional[Any]) -> None:
        """Load one file (clears side B). Pass None to clear."""
        self._file_a = file_data
        self._file_b = None

        if file_data:
            self._side_a.load(file_data)
            self._side_b.clear()
            self._auto_expand()
        else:
            self._side_a.clear()
            self._side_b.clear()

        self._update_layout()
        self._update_ashisoft_view()

    def load_comparison(
        self,
        file_a: Optional[Any],
        file_b: Optional[Any],
    ) -> None:
        """Load two files for side-by-side comparison."""
        self._file_a = file_a
        self._file_b = file_b

        if file_a:
            self._side_a.load(file_a)
        else:
            self._side_a.clear()

        if file_b:
            self._side_b.load(file_b)
        else:
            self._side_b.clear()

        if file_a or file_b:
            self._auto_expand()

        self._update_layout()
        self._update_ashisoft_view()

    def load_file_a(self, file_data: Optional[Any]) -> None:
        self._file_a = file_data
        if file_data:
            self._side_a.load(file_data)
            self._auto_expand()
        else:
            self._side_a.clear()
        self._update_layout()
        self._update_ashisoft_view()

    def load_file_b(self, file_data: Optional[Any]) -> None:
        self._file_b = file_data
        if file_data:
            self._side_b.load(file_data)
            self._auto_expand()
        else:
            self._side_b.clear()
        self._update_layout()
        self._update_ashisoft_view()

    def clear(self) -> None:
        """Clear all previews."""
        self._file_a = None
        self._file_b = None
        self._side_a.clear()
        self._side_b.clear()
        self._update_layout()
        self._update_ashisoft_view()

    def get_file_a(self) -> Optional[Dict[str, Any]]:
        return self._file_a

    def get_file_b(self) -> Optional[Dict[str, Any]]:
        return self._file_b

    def is_comparison_mode(self) -> bool:
        return self._file_a is not None and self._file_b is not None

    # Stub kept for API compatibility — no-ops since buttons removed
    def on_keep_a(self, callback: Callable[[], None]) -> None:
        pass

    def on_keep_b(self, callback: Callable[[], None]) -> None:
        pass


logger = __import__('logging').getLogger(__name__)
