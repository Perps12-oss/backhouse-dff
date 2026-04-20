"""
Results Panel Widget

Center panel with grouped results display using CheckTreeview.
Features sub-filtering by file type and sortable columns.
"""

from __future__ import annotations

import logging
import time
import tkinter as tk
from typing import Optional, Callable, List, Dict, Any
from pathlib import Path

try:
    import customtkinter as ctk
    CTkFrame = ctk.CTkFrame
    CTkLabel = ctk.CTkLabel
    CTkButton = ctk.CTkButton
    CTkProgressBar = ctk.CTkProgressBar
except ImportError:
    CTkFrame = tk.Frame
    CTkLabel = tk.Label
    CTkButton = tk.Button
    CTkProgressBar = None  # type: ignore[misc, assignment]

from cerebro.v2.core.design_tokens import Spacing, Typography, Dimensions
from cerebro.v2.core.theme_bridge_v2 import theme_color, subscribe_to_theme
from cerebro.v2.ui.feedback import FeedbackPanel, show_text_panel
from cerebro.v2.ui.widgets.check_treeview import CheckTreeview
from cerebro.v2.ui.widgets.scan_in_progress_view import (
    ScanInProgressView,
    friendly_stage_label,
    _STAGE_LABELS,
)
from cerebro.engines.base_engine import DuplicateGroup, DuplicateFile, ScanState
from cerebro.services.logger import get_logger
from cerebro.utils.formatting import format_bytes

logger = get_logger(__name__)  # wraps logging.getLogger(__name__)

# Back-compat alias: tests and legacy call sites still import the leading-underscore
# name from this module. The class itself now lives in widgets.scan_in_progress_view.
_ScanInProgressView = ScanInProgressView


def _format_duration(seconds: float) -> str:
    """Format elapsed seconds for banner text (no leading zeros on hours)."""
    s = max(0, int(seconds))
    if s < 60:
        return f"{s}s"
    if s < 3600:
        m, sec = divmod(s, 60)
        return f"{m}m {sec}s"
    h, rem = divmod(s, 3600)
    m = rem // 60
    return f"{h}h {m}m"


class _ScanCompleteBanner(CTkFrame):
    """Prominent summary card after a scan finishes (persists until dismissed)."""

    def __init__(
        self,
        master,
        *,
        on_auto_mark: Callable[[], None],
        on_dismiss: Callable[[], None],
        **kwargs,
    ) -> None:
        super().__init__(master, height=92, **kwargs)
        self._on_auto_mark = on_auto_mark
        self._on_dismiss = on_dismiss
        self._auto_btn: Optional[CTkButton] = None
        self._text_label: Optional[CTkLabel] = None
        self._inner: Optional[CTkFrame] = None
        self._show_after_id: Optional[str] = None
        self._anim_after_id: Optional[str] = None
        self._anim_step: int = 0
        self._anim_targets: List[tuple] = []
        self._content_row: Optional[CTkFrame] = None
        subscribe_to_theme(self, self._apply_theme)

    @staticmethod
    def _blend_hex(start: str, end: str, t: float) -> str:
        """Blend two #RRGGBB colors for simple fade animation."""
        if not (isinstance(start, str) and isinstance(end, str)):
            return end
        if not (start.startswith("#") and end.startswith("#") and len(start) >= 7 and len(end) >= 7):
            return end
        t = max(0.0, min(1.0, float(t)))
        try:
            sr, sg, sb = int(start[1:3], 16), int(start[3:5], 16), int(start[5:7], 16)
            er, eg, eb = int(end[1:3], 16), int(end[3:5], 16), int(end[5:7], 16)
        except ValueError:
            return end
        r = int(sr + (er - sr) * t)
        g = int(sg + (eg - sg) * t)
        b = int(sb + (eb - sb) * t)
        return f"#{r:02x}{g:02x}{b:02x}"

    def _cancel_animation_jobs(self) -> None:
        if self._show_after_id:
            try:
                self.after_cancel(self._show_after_id)
            except tk.TclError:
                pass
            self._show_after_id = None
        if self._anim_after_id:
            try:
                self.after_cancel(self._anim_after_id)
            except tk.TclError:
                pass
            self._anim_after_id = None

    def schedule_show(self, delay_ms: int = 260, **kwargs) -> None:
        """Show banner after a brief delay for smoother scan-to-results transition."""
        self._cancel_animation_jobs()
        self._show_after_id = self.after(delay_ms, lambda: self.show(**kwargs))

    def _apply_theme(self) -> None:
        try:
            self.configure(fg_color=theme_color("base.backgroundElevated"))
        except (tk.TclError, AttributeError, ValueError) as exc:
            logger.debug("ScanCompleteBanner theme skipped: %s", exc)

    def _animate_in(self) -> None:
        steps = 8
        self._anim_step += 1
        t = self._anim_step / steps
        top_start = Spacing.LG
        top_end = Spacing.SM
        if self._content_row is not None:
            top = int(top_start + (top_end - top_start) * t)
            try:
                self._content_row.pack_configure(pady=(top, Spacing.SM))
            except tk.TclError:
                pass

        for widget, start_color, end_color in self._anim_targets:
            try:
                widget.configure(text_color=self._blend_hex(start_color, end_color, t))
            except (tk.TclError, AttributeError):
                pass

        if self._anim_step < steps:
            self._anim_after_id = self.after(28, self._animate_in)
        else:
            self._anim_after_id = None

    def show(
        self,
        *,
        final_state: ScanState,
        groups_found: int,
        duplicates_found: int,
        bytes_reclaimable: int,
        elapsed_seconds: float,
    ) -> None:
        self._cancel_animation_jobs()
        for w in self.winfo_children():
            w.destroy()
        self._show_after_id = None
        self._inner = CTkFrame(self, fg_color=theme_color("base.backgroundElevated"), corner_radius=10)
        self._inner.pack(fill="both", expand=True, padx=0, pady=0)

        dur = _format_duration(elapsed_seconds)
        if final_state == ScanState.COMPLETED and groups_found == 0:
            headline = "Scan complete"
            detail = f"Scan complete — No duplicates found in {dur}."
            border = theme_color("feedback.success")
        elif final_state == ScanState.COMPLETED:
            headline = "Duplicates found"
            detail = (
                f"Scan complete — {duplicates_found:,} duplicates across {groups_found:,} groups"
                f" • Potential reclaim: {format_bytes(bytes_reclaimable)} • Time: {dur}"
            )
            border = theme_color("feedback.success")
        elif final_state == ScanState.CANCELLED:
            headline = "Scan cancelled"
            detail = f"{groups_found:,} groups were found before stopping • {dur}"
            try:
                border = theme_color("feedback.warning")
            except (tk.TclError, AttributeError, ValueError):
                border = theme_color("base.foregroundSecondary")
        else:
            headline = "Scan failed"
            detail = "See logs for details."
            border = theme_color("button.danger")

        stripe = CTkFrame(self._inner, width=8, fg_color=border, corner_radius=0)
        stripe.pack(side="left", fill="y")

        row = CTkFrame(self._inner, fg_color="transparent")
        row.pack(side="left", fill="both", expand=True, padx=(Spacing.MD, Spacing.MD), pady=(Spacing.LG, Spacing.SM))
        self._content_row = row

        header = CTkFrame(row, fg_color="transparent")
        header.pack(fill="x")
        icon = "🏆" if (final_state == ScanState.COMPLETED and groups_found > 0) else ("✓" if final_state == ScanState.COMPLETED else ("⏹" if final_state == ScanState.CANCELLED else "⚠"))
        headline_label = CTkLabel(
            header,
            text=f"{icon}  {headline}",
            font=("", 19, "bold"),
            text_color=theme_color("base.foreground"),
            anchor="w",
        )
        headline_label.pack(side="left")

        dismiss = CTkButton(
            header,
            text="×",
            width=32,
            height=28,
            font=("", 16),
            fg_color=theme_color("button.secondary"),
            hover_color=theme_color("button.secondaryHover"),
            command=self._on_dismiss,
        )
        dismiss.pack(side="right")

        stats = CTkFrame(row, fg_color="transparent")
        stats.pack(fill="x", pady=(Spacing.XS, 0))

        stat_value_labels: List[CTkLabel] = []

        def _stat_chip(label: str, value: str) -> None:
            chip = CTkFrame(stats, fg_color=theme_color("base.backgroundTertiary"), corner_radius=8)
            chip.pack(side="left", padx=(0, Spacing.SM), pady=(0, Spacing.XS))
            value_label = CTkLabel(
                chip,
                text=value,
                font=("", 16, "bold"),
                text_color=theme_color("base.foreground"),
            )
            value_label.pack(anchor="w", padx=Spacing.SM, pady=(Spacing.XS, 0))
            stat_value_labels.append(value_label)
            CTkLabel(
                chip,
                text=label,
                font=Typography.FONT_XS,
                text_color=theme_color("base.foregroundSecondary"),
            ).pack(anchor="w", padx=Spacing.SM, pady=(0, Spacing.XS))

        _stat_chip("Groups", f"{groups_found:,}")
        _stat_chip("Duplicates", f"{duplicates_found:,}")
        _stat_chip("Reclaimable", format_bytes(bytes_reclaimable))
        _stat_chip("Elapsed", dur)

        actions = CTkFrame(row, fg_color="transparent")
        actions.pack(side="bottom", fill="x", pady=(Spacing.SM, 0))
        review_btn = CTkButton(
            actions,
            text="Review results",
            width=126,
            height=30,
            font=Typography.FONT_SM,
            fg_color=theme_color("button.secondary"),
            hover_color=theme_color("button.secondaryHover"),
            command=self._on_dismiss,
        )
        review_btn.pack(side="right")
        if final_state == ScanState.COMPLETED and groups_found > 0:
            self._auto_btn = CTkButton(
                actions,
                text="Auto-mark",
                width=100,
                height=30,
                font=Typography.FONT_SM,
                fg_color=theme_color("button.primary"),
                hover_color=theme_color("button.primaryHover"),
                command=self._on_auto_mark,
            )
            self._auto_btn.pack(side="right", padx=(Spacing.SM, 0))

        self._text_label = CTkLabel(
            row,
            text=detail,
            font=Typography.FONT_SM,
            text_color=theme_color("base.foregroundSecondary"),
            anchor="w",
            justify="left",
        )
        self._text_label.pack(side="top", fill="x", pady=(Spacing.XS, 0))

        # Subtle entrance: slide up + text fade from muted to target.
        muted = theme_color("base.foregroundMuted")
        self._anim_targets = [(headline_label, muted, theme_color("base.foreground"))]
        for lbl in stat_value_labels:
            self._anim_targets.append((lbl, muted, theme_color("base.foreground")))
        self._anim_targets.append((self._text_label, muted, theme_color("base.foregroundSecondary")))
        self._anim_step = 0
        self._anim_after_id = self.after(16, self._animate_in)

        if not self.winfo_ismapped():
            self.pack(fill="x", padx=Spacing.XS, pady=(Spacing.XS, 0), before=self.master._status_frame)

    def hide(self) -> None:
        self._cancel_animation_jobs()
        if self.winfo_ismapped():
            self.pack_forget()


class FilterType:
    """Available result filter types."""

    ALL = "all"
    IMAGES = "images"
    VIDEOS = "videos"
    DOCUMENTS = "documents"
    AUDIO = "audio"
    OTHER = "other"

    @classmethod
    def display_name(cls, filter_type: str) -> str:
        """Get human-readable name for filter."""
        names = {
            cls.ALL: "All",
            cls.IMAGES: "Images",
            cls.VIDEOS: "Videos",
            cls.DOCUMENTS: "Docs",
            cls.AUDIO: "Audio",
            cls.OTHER: "Other"
        }
        return names.get(filter_type, filter_type)

    @classmethod
    def all_filters(cls) -> List[str]:
        """Get list of all filters."""
        return [
            cls.ALL,
            cls.IMAGES,
            cls.VIDEOS,
            cls.DOCUMENTS,
            cls.AUDIO,
            cls.OTHER
        ]

    @classmethod
    def display_names(cls) -> List[str]:
        """Get list of human-readable filter names."""
        return [cls.display_name(f) for f in cls.all_filters()]

    @classmethod
    def extensions_for_filter(cls, filter_type: str) -> List[str]:
        """Get file extensions for a filter type."""
        extensions = {
            cls.ALL: [],
            cls.IMAGES: [
                ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".tif",
                ".webp", ".heic", ".heif", ".cr2", ".cr3", ".nef",
                ".arw", ".dng", ".orf", ".rw2", ".pef", ".raf", ".sr2"
            ],
            cls.VIDEOS: [
                ".mp4", ".avi", ".mkv", ".mov", ".wmv", ".flv", ".webm",
                ".m4v", ".mpg", ".mpeg", ".3gp"
            ],
            cls.DOCUMENTS: [
                ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
                ".txt", ".rtf", ".odt", ".ods", ".odp", ".csv"
            ],
            cls.AUDIO: [
                ".mp3", ".flac", ".ogg", ".wav", ".aac", ".m4a", ".wma",
                ".opus", ".ape", ".aiff"
            ],
            cls.OTHER: []
        }
        return extensions.get(filter_type, [])


class ResultsPanel(CTkFrame):
    """
    Center panel for displaying grouped duplicate results.

    Features:
    - Filter tabs (All | Images | Videos | Docs | Audio | Other)
    - CheckTreeview with grouped results
    - Sortable columns
    - Right-click context menu
    - Selection tracking
    - Empty state display
    """

    def __init__(self, master=None, **kwargs):
        super().__init__(master, **kwargs)
        subscribe_to_theme(self, self._apply_theme)

        # State
        self._current_filter: str = FilterType.ALL
        self._current_mode: str = "files"
        self._groups: List[DuplicateGroup] = []
        self._filtered_groups: List[DuplicateGroup] = []
        self._total_items: int = 0
        self._selected_count: int = 0
        self._total_scan_bytes: int = 0  # used for large_files % display

        # Widgets
        self._filter_bar: Optional[_FilterBar] = None
        self._treeview: Optional[CheckTreeview] = None
        self._empty_label: Optional[CTkLabel] = None
        self._status_frame: Optional[CTkFrame] = None
        self._results_count_label: Optional[CTkLabel] = None
        self._mode_view_label: Optional[CTkLabel] = None
        self._selected_count_label: Optional[CTkLabel] = None
        self._selected_size_label: Optional[CTkLabel] = None

        # Callbacks
        self._on_selection_changed: Optional[Callable[[List[str]], None]] = None
        self._on_file_selected: Optional[Callable[[Dict], None]] = None
        self._on_file_double_clicked: Optional[Callable[[Dict], None]] = None
        self._on_request_stop_search: Optional[Callable[[], None]] = None
        self._on_request_auto_mark_cb: Optional[Callable[[], None]] = None

        # Build UI
        self._build_ui()
        self._show_empty_state()

    def _build_ui(self) -> None:
        """Build results panel UI."""
        self.configure(
            fg_color=theme_color("results.background")
        )

        # Filter tab bar — hidden until load_results() is called with data
        self._filter_bar = _FilterBar(self, on_filter_changed=self._on_filter_changed)
        # NOT packed here — shown only post-scan

        # Status bar (results count)
        self._build_status_bar()

        # Treeview container
        self._tree_container = CTkFrame(self)
        self._tree_container.pack(fill="both", expand=True, padx=Spacing.XS)

        # CheckTreeview
        self._treeview = CheckTreeview(
            self._tree_container,
            columns=("name", "extension", "size", "modified", "similarity"),
            selectmode="extended",
            height=20
        )
        self._treeview.pack(fill="both", expand=True)

        # Configure columns
        self._configure_columns()

        # Bind events
        self._treeview.on_check_changed(self._on_check_changed)
        self._treeview.bind("<<TreeviewSelect>>", self._on_single_click)
        self._treeview.bind("<Double-Button-1>", self._on_double_click)
        self._treeview.bind("<Button-3>", self._on_right_click)  # Right-click

        # Getting-started / empty state view
        self._empty_view = _GettingStartedView(self)
        self._empty_view.on_add_folder(self._on_gs_add_folder)
        self._empty_view.on_start_search(self._on_gs_start_search)

        self._complete_banner = _ScanCompleteBanner(
            self,
            on_auto_mark=self._on_banner_auto_mark,
            on_dismiss=self._complete_banner_dismiss,
        )
        self._scan_view = _ScanInProgressView(self, on_cancel=self._on_scan_cancel_request)

        # Callbacks that MainWindow wires up for getting-started actions
        self._on_request_add_folder: Optional[Callable[[], None]] = None
        self._on_request_start_search: Optional[Callable[[], None]] = None

        # Thumbnail grid ↔ treeview share one logical selection; grid needs tree sync for rules.
        self._thumbnail_grid: Any = None
        self._results_view_mode: str = "list"
        self._syncing_checks: bool = False
        self._bulk_selection_in_progress: bool = False
        self._on_file_row_focus: Optional[Callable[[str], None]] = None

    def _fd_path(self, fd) -> str:
        if isinstance(fd, dict):
            return str(fd.get("path", ""))
        return str(getattr(fd, "path", ""))

    def _fd_size(self, fd) -> int:
        if isinstance(fd, dict):
            return int(fd.get("size", 0))
        return int(getattr(fd, "size", 0))

    def _apply_theme(self) -> None:
        """Reconfigure all widget colors when theme changes."""
        self.configure(fg_color=theme_color("results.background"))
        if self._status_frame:
            self._status_frame.configure(fg_color=theme_color("base.backgroundTertiary"))
        if self._results_count_label:
            self._results_count_label.configure(text_color=theme_color("results.foreground"))
        if self._mode_view_label:
            self._mode_view_label.configure(text_color=theme_color("base.foregroundSecondary"))
        for lbl in (self._selected_count_label, self._selected_size_label):
            if lbl:
                lbl.configure(text_color=theme_color("base.foregroundSecondary"))

    def _build_status_bar(self) -> None:
        """Build review summary strip (counts, mode/view, and selection stats)."""
        self._status_frame = CTkFrame(
            self,
            height=32,
            fg_color=theme_color("base.backgroundTertiary")
        )
        self._status_frame.pack(fill="x", padx=Spacing.XS, pady=(0, Spacing.XS))

        left = CTkFrame(self._status_frame, fg_color="transparent")
        left.pack(side="left", fill="x", expand=True, padx=Spacing.MD)
        self._results_count_label = CTkLabel(
            left,
            text="0 groups, 0 files",
            font=Typography.FONT_SM,
            text_color=theme_color("results.foreground")
        )
        self._results_count_label.pack(side="left")
        self._mode_view_label = CTkLabel(
            left,
            text="Files • List",
            font=Typography.FONT_XS,
            text_color=theme_color("base.foregroundSecondary"),
        )
        self._mode_view_label.pack(side="left", padx=(Spacing.SM, 0))

        right = CTkFrame(self._status_frame, fg_color="transparent")
        right.pack(side="right", padx=Spacing.MD)
        self._selected_count_label = CTkLabel(
            right,
            text="Selected: 0",
            font=Typography.FONT_XS,
            text_color=theme_color("base.foregroundSecondary"),
        )
        self._selected_count_label.pack(side="left", padx=(0, Spacing.SM))
        self._selected_size_label = CTkLabel(
            right,
            text="Marked size: 0 B",
            font=Typography.FONT_XS,
            text_color=theme_color("base.foregroundSecondary"),
        )
        self._selected_size_label.pack(side="left")

    def _configure_columns(self) -> None:
        """Configure treeview columns."""
        # Name column (wider)
        self._treeview.column("name", width=250, anchor="w")
        self._treeview.heading("name", text="Name", command=lambda: self._sort_by("name"))

        # Extension column
        self._treeview.column("extension", width=80, anchor="center")
        self._treeview.heading("extension", text="Ext", command=lambda: self._sort_by("extension"))

        # Size column
        self._treeview.column("size", width=100, anchor="e")
        self._treeview.heading("size", text="Size", command=lambda: self._sort_by("size"))

        # Modified date column
        self._treeview.column("modified", width=120, anchor="center")
        self._treeview.heading("modified", text="Modified", command=lambda: self._sort_by("modified"))

        # Similarity column
        self._treeview.column("similarity", width=80, anchor="center")
        self._treeview.heading("similarity", text="Similarity", command=lambda: self._sort_by("similarity"))

    def _configure_columns_for_mode(self, mode: str) -> None:
        """Configure columns based on scan mode."""
        from cerebro.v2.ui.mode_tabs import ScanMode

        # Define column configurations per mode
        mode_columns = {
            ScanMode.FILES: {
                "columns": ("name", "extension", "size", "modified", "similarity"),
                "headings": {
                    "name": "Name",
                    "extension": "Ext",
                    "size": "Size",
                    "modified": "Modified",
                    "similarity": "Similarity"
                }
            },
            ScanMode.PHOTOS: {
                "columns": ("name", "extension", "size", "modified", "similarity", "resolution"),
                "headings": {
                    "name": "Name",
                    "extension": "Ext",
                    "size": "Size",
                    "modified": "Modified",
                    "similarity": "Similarity",
                    "resolution": "Resolution"
                }
            },
            ScanMode.VIDEOS: {
                "columns": ("name", "extension", "size", "duration", "resolution", "similarity"),
                "headings": {
                    "name": "Name",
                    "extension": "Ext",
                    "size": "Size",
                    "duration": "Duration",
                    "resolution": "Resolution",
                    "similarity": "Similarity"
                }
            },
            ScanMode.MUSIC: {
                "columns": ("name", "artist", "album", "duration", "size", "similarity"),
                "headings": {
                    "name": "Name",
                    "artist": "Artist",
                    "album": "Album",
                    "duration": "Duration",
                    "size": "Size",
                    "similarity": "Similarity"
                }
            },
            ScanMode.EMPTY_FOLDERS: {
                "columns": ("name", "path", "depth", "size"),
                "headings": {
                    "name": "Name",
                    "path": "Path",
                    "depth": "Depth",
                    "size": "Size"
                }
            },
            ScanMode.LARGE_FILES: {
                "columns": ("name", "extension", "size", "path", "modified"),
                "headings": {
                    "name": "Name",
                    "extension": "Ext",
                    "size": "Size",
                    "path": "Path",
                    "modified": "Modified"
                }
            }
        }

        config = mode_columns.get(mode, mode_columns[ScanMode.FILES])

        # Configure column widths and headings
        self._treeview.configure(columns=config["columns"])

        # Column widths
        widths = {
            "name": 250,
            "extension": 60,
            "size": 100,
            "modified": 120,
            "similarity": 80,
            "resolution": 100,
            "duration": 80,
            "artist": 120,
            "album": 120,
            "path": 200,
            "depth": 60
        }

        # Anchors
        anchors = {
            "name": "w",
            "extension": "center",
            "size": "e",
            "modified": "center",
            "similarity": "center",
            "resolution": "center",
            "duration": "center",
            "artist": "w",
            "album": "w",
            "path": "w",
            "depth": "center"
        }

        for col in config["columns"]:
            width = widths.get(col, 100)
            anchor = anchors.get(col, "w")
            heading = config["headings"][col]

            self._treeview.column(col, width=width, anchor=anchor)
            self._treeview.heading(col, text=heading, command=lambda c=col: self._sort_by(c))

    # ===================
    # EVENT HANDLERS
    # ===================

    def _on_filter_changed(self, filter_key: str) -> None:
        """Handle filter tab change — receives a FilterType key directly."""
        if filter_key != self._current_filter:
            self._current_filter = filter_key
            self._apply_filter()

    def _on_check_changed(self, _item_id: str, _checked: bool) -> None:
        """Handle checkbox state change."""
        if self._syncing_checks or self._bulk_selection_in_progress:
            return
        # Single O(n) scan — reused for count, status bar, and callback.
        checked_ids = self._get_checked_item_ids()
        self._selected_count = len(checked_ids)

        if (
            self._results_view_mode == "grid"
            and self._thumbnail_grid is not None
            and getattr(self._thumbnail_grid, "_cards", None)
        ):
            self._sync_thumbnail_checks_from_tree()
        self._update_status(checked_ids)
        if self._on_selection_changed:
            self._on_selection_changed(checked_ids)

    def _get_file_data_for_item(self, item_id: str) -> Optional[DuplicateFile]:
        """Return the DuplicateFile for a treeview item_id, or None if it's a group row."""
        parts = item_id.split("_")
        if len(parts) != 2:
            return None
        try:
            group_id = int(parts[0])
            file_index = int(parts[1])
        except ValueError:
            return None
        group = next((g for g in self._filtered_groups if g.group_id == group_id), None)
        if group and file_index < len(group.files):
            return group.files[file_index]
        return None

    def _on_single_click(self, event) -> None:
        """Handle single click — fire file-selected callback for the clicked file row."""
        selection = self._treeview.selection()
        if not selection:
            return
        item_id = selection[0]
        file_data = self._get_file_data_for_item(item_id)
        if file_data and self._on_file_selected:
            self._on_file_selected(file_data)
        if file_data and self._on_file_row_focus:
            self._on_file_row_focus(item_id)

    def _on_double_click(self, event) -> None:
        """Handle double-click — fire file-double-clicked callback."""
        selection = self._treeview.selection()
        if not selection:
            return
        item_id = selection[0]
        file_data = self._get_file_data_for_item(item_id)
        if file_data and self._on_file_double_clicked:
            self._on_file_double_clicked(file_data)

    def _on_right_click(self, event) -> None:
        """Show context menu on right-click."""
        # Identify clicked row
        item_id = self._treeview.identify_row(event.y)
        if not item_id:
            return

        is_group = item_id in self._treeview._group_rows
        file_data = None if is_group else self._get_file_data_by_item_id(item_id)

        menu = tk.Menu(self, tearoff=0)

        if file_data:
            path = self._fd_path(file_data)
            menu.add_command(label="Open File",
                             command=lambda: self._open_file(path))
            menu.add_command(label="Open Containing Folder",
                             command=lambda: self._open_folder(path))
            menu.add_command(label="Copy Path",
                             command=lambda: self._copy_path(path))
            menu.add_separator()
            menu.add_command(label="Select Group",
                             command=lambda: self._select_group_for_item(item_id))
            menu.add_command(label="Deselect Group",
                             command=lambda: self._deselect_group_for_item(item_id))
            menu.add_separator()
            menu.add_command(label="Properties",
                             command=lambda: self._show_properties(file_data))
        elif is_group:
            menu.add_command(label="Select Group",
                             command=lambda: self._select_group_by_row(item_id))
            menu.add_command(label="Deselect Group",
                             command=lambda: self._deselect_group_by_row(item_id))

        if menu.index("end") is not None:
            try:
                menu.tk_popup(event.x_root, event.y_root)
            finally:
                menu.grab_release()

    # ------------------------------------------------------------------
    # Context menu actions
    # ------------------------------------------------------------------

    def _open_file(self, path: str) -> None:
        import sys, subprocess
        try:
            if sys.platform == "win32":
                import os; os.startfile(path)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except (OSError, tk.TclError) as exc:
            FeedbackPanel(self, "Open File", f"Could not open file:\n{exc}", type="error")

    def _open_folder(self, path: str) -> None:
        import sys, subprocess
        folder = str(Path(path).parent)
        try:
            if sys.platform == "win32":
                subprocess.Popen(["explorer", f"/select,{path}"])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", "-R", path])
            else:
                subprocess.Popen(["xdg-open", folder])
        except (OSError, tk.TclError) as exc:
            FeedbackPanel(self, "Open Folder", f"Could not open folder:\n{exc}", type="error")

    def _copy_path(self, path: str) -> None:
        try:
            self.clipboard_clear()
            self.clipboard_append(path)
        except tk.TclError as exc:
            logger.warning("Clipboard copy failed: %s", exc)

    def _select_group_for_item(self, item_id: str) -> None:
        parent = self._treeview.parent(item_id) or item_id
        self._set_group_checks(parent, True)

    def _deselect_group_for_item(self, item_id: str) -> None:
        parent = self._treeview.parent(item_id) or item_id
        self._set_group_checks(parent, False)

    def _select_group_by_row(self, group_row_id: str) -> None:
        self._set_group_checks(group_row_id, True)

    def _deselect_group_by_row(self, group_row_id: str) -> None:
        self._set_group_checks(group_row_id, False)

    def _set_group_checks(self, group_row_id: str, checked: bool) -> None:
        for child in self._treeview.get_children(group_row_id):
            self._treeview.set_check(child, checked)
        if self._on_selection_changed:
            self._on_selection_changed(self._treeview.get_checked())

    def _show_properties(self, file_data: Dict[str, Any]) -> None:
        from datetime import datetime
        path = self._fd_path(file_data)
        size = self._fd_size(file_data)
        modified = getattr(file_data, "modified", file_data.get("modified", 0))
        similarity = getattr(file_data, "similarity", file_data.get("similarity", 1.0))
        size_str = format_bytes(size, decimals=1)
        mod_str = datetime.fromtimestamp(modified).strftime("%Y-%m-%d %H:%M:%S") if modified else "—"
        sim_str = f"{int(similarity * 100)}%"
        show_text_panel(
            self,
            "File Properties",
            f"Path:       {path}\n"
            f"Size:       {size_str}\n"
            f"Modified:   {mod_str}\n"
            f"Similarity: {sim_str}",
        )

    def _get_file_data_by_item_id(self, item_id: str) -> Optional[Dict[str, Any]]:
        """Resolve an item_id like '3_1' to its file_data dict."""
        try:
            parts = item_id.split("_")
            if len(parts) == 2:
                group_id, file_idx = int(parts[0]), int(parts[1])
                group = next((g for g in self._filtered_groups if g.group_id == group_id), None)
                if group and file_idx < len(group.files):
                    fd = group.files[file_idx]
                    # Normalise to dict (file objects may be DuplicateFile dataclasses or dicts)
                    if hasattr(fd, "__dict__"):
                        d = {k: getattr(fd, k) for k in ("path", "size", "modified", "similarity")}
                        d["path"] = str(d["path"])
                        return d
                    return fd
        except (ValueError, IndexError, AttributeError, TypeError) as exc:
            logger.debug("Failed to map tree item id '%s': %s", item_id, exc)
        return None

    def _sort_by(self, column: str) -> None:
        """Sort treeview by column."""
        self._treeview.sort_by_column(column)

    # ===================
    # PUBLIC API
    # ===================

    def load_results(self, groups: List[DuplicateGroup]) -> None:
        """
        Load duplicate groups into results panel.

        Args:
            groups: List of DuplicateGroup objects to display.
        """
        self._groups = groups
        self._total_items = sum(g.file_count for g in groups)

        # Show filter bar with per-type counts (only when there are results)
        if groups:
            counts = self._compute_filter_counts(groups)
            self._filter_bar.update_counts(counts)
            if not self._filter_bar.winfo_ismapped():
                self._filter_bar.pack(
                    fill="x", padx=Spacing.XS,
                    pady=(Spacing.XS, 0),
                    before=self._status_frame,
                )

        self._apply_filter()
        self._update_status()

    def _compute_filter_counts(self, groups: List[DuplicateGroup]) -> Dict[str, int]:
        """Count files per filter type across all groups."""
        counts: Dict[str, int] = {ft: 0 for ft in FilterType.all_filters()}
        for group in groups:
            for file_data in group.files:
                ext = Path(self._fd_path(file_data)).suffix.lower()
                matched = False
                for ft in (FilterType.IMAGES, FilterType.VIDEOS,
                           FilterType.DOCUMENTS, FilterType.AUDIO):
                    if ext in FilterType.extensions_for_filter(ft):
                        counts[ft] += 1
                        counts[FilterType.ALL] += 1
                        matched = True
                        break
                if not matched:
                    counts[FilterType.OTHER] += 1
                    counts[FilterType.ALL] += 1
        return counts

    def _apply_filter(self) -> None:
        """Apply current filter to groups and refresh treeview."""
        if self._current_filter == FilterType.ALL:
            self._filtered_groups = self._groups.copy()
        else:
            # Filter groups by file type
            filter_extensions = FilterType.extensions_for_filter(self._current_filter)
            self._filtered_groups = []

            for group in self._groups:
                # Check if any file in group matches filter
                filtered_files = [
                    f for f in group.files
                    if Path(f.path).suffix.lower() in filter_extensions
                ]
                if filtered_files:
                    # Build a lightweight filtered DuplicateGroup view
                    from cerebro.engines.base_engine import DuplicateGroup as _DG
                    filtered_group = _DG(
                        group_id=group.group_id,
                        files=filtered_files,
                    )
                    self._filtered_groups.append(filtered_group)

        self._refresh_treeview()

    def _refresh_treeview(self, *, precheck_non_keepers: bool = True) -> None:
        """Refresh treeview with filtered results."""
        self._treeview.clear()

        if not self._filtered_groups:
            self._show_empty_state()
            return

        self._show_results()

        # Load groups into treeview
        for group_idx, group in enumerate(self._filtered_groups):
            # Format size for display
            size_str = format_bytes(group.total_size, decimals=1)
            reclaimable_str = format_bytes(group.reclaimable, decimals=1)

            # Create group header
            group_text = f"Group {group.group_id} — {group.file_count} files, {reclaimable_str} reclaimable"
            self._treeview.insert_group(
                "",
                f"group_{group.group_id}",
                group_text
            )

            # Add file items
            for i, file_data in enumerate(group.files):
                item_id = f"{group.group_id}_{i}"
                # Non-keepers are pre-checked (marked for deletion)
                is_keeper = (i == group.get_keeper_index()) or file_data.is_keeper
                checked = (not is_keeper) if precheck_non_keepers else False

                # Format values — mode-aware
                path = Path(file_data.path)
                meta = file_data.metadata if hasattr(file_data, "metadata") and file_data.metadata else {}
                values = self._format_row(path, file_data, meta)

                tags = []
                if is_keeper:
                    tags.append("keeper")

                self._treeview.insert_item(
                    f"group_{group.group_id}",
                    item_id,
                    checked=checked,
                    values=values,
                    tags=tuple(tags) if tags else ()
                )

            # Yield to the UI loop periodically for very large result sets.
            # Without this, Tk can be marked "Not Responding" during bulk insert.
            # Interval of 50 reduces redraw overhead vs the old value of 15.
            if group_idx % 50 == 0:
                try:
                    self.update_idletasks()
                except tk.TclError as exc:
                    logger.debug("Idle task flush skipped during tree insert: %s", exc)

    def _format_row(self, path: Path, file_data, meta: dict) -> tuple:
        """Return treeview column values for the current scan mode."""
        from cerebro.v2.ui.mode_tabs import ScanMode
        mode = self._current_mode

        def _fmt_dur(seconds: float) -> str:
            if not seconds:
                return "—"
            m, s = divmod(int(seconds), 60)
            h, m = divmod(m, 60)
            return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

        if mode == ScanMode.VIDEOS:
            return (
                path.name,
                path.suffix.lstrip(".").upper() or "—",
                format_bytes(file_data.size, decimals=1),
                _fmt_dur(meta.get("duration", 0)),
                meta.get("resolution", "—"),
                f"{int(file_data.similarity * 100)}%",
            )
        elif mode == ScanMode.MUSIC:
            return (
                path.name,
                meta.get("artist", "—") or "—",
                meta.get("album", "—") or "—",
                _fmt_dur(meta.get("duration", 0)),
                format_bytes(file_data.size, decimals=1),
                f"{int(file_data.similarity * 100)}%",
            )
        elif mode == ScanMode.EMPTY_FOLDERS:
            return (
                path.name,
                str(path.parent),
                str(meta.get("depth", "—")),
                "—",
            )
        elif mode == ScanMode.LARGE_FILES:
            total = self._total_scan_bytes or file_data.size or 1
            pct = f"{file_data.size / total * 100:.1f}%" if total else "—"
            return (
                path.name,
                path.suffix.lstrip(".").upper() or "—",
                format_bytes(file_data.size, decimals=1),
                str(path.parent),
                self._format_date(file_data.modified),
            )
        elif mode == ScanMode.PHOTOS:
            return (
                path.name,
                path.suffix.lstrip(".").upper() or "—",
                format_bytes(file_data.size, decimals=1),
                self._format_date(file_data.modified),
                f"{int(file_data.similarity * 100)}%",
                meta.get("resolution", "—"),
            )
        else:  # FILES (default)
            return (
                path.name,
                path.suffix.lstrip(".").upper() or "—",
                format_bytes(file_data.size, decimals=1),
                self._format_date(file_data.modified),
                f"{int(file_data.similarity * 100)}%",
            )

    def _show_empty_state(self) -> None:
        """Show getting-started / empty state view."""
        # Unconditionally toggle; mapped-state checks can be stale during fast
        # scan state changes and cause both views to remain visible.
        self._treeview.pack_forget()
        if self._scan_view.winfo_ismapped():
            self._scan_view.pack_forget()
        self._empty_view.pack(fill="both", expand=True)

    def _show_results(self) -> None:
        """Show results treeview, hide empty state."""
        self._empty_view.pack_forget()
        if self._scan_view.winfo_ismapped():
            self._scan_view.pack_forget()
        self._treeview.pack(fill="both", expand=True)

    def _on_gs_add_folder(self) -> None:
        if self._on_request_add_folder:
            self._on_request_add_folder()

    def _on_gs_start_search(self) -> None:
        if self._on_request_start_search:
            self._on_request_start_search()

    def _update_status(self, checked_ids: Optional[List[str]] = None) -> None:
        """Update review summary strip labels.

        Args:
            checked_ids: Pre-computed list of checked item IDs. When provided the
                         method skips the O(n) get_checked() scan entirely.
        """
        from cerebro.v2.ui.mode_tabs import ScanMode

        total_files = sum(g.file_count for g in self._filtered_groups)
        self._results_count_label.configure(
            text=f"{len(self._filtered_groups)} groups, {total_files} files"
        )
        view_label = "Grid" if self._results_view_mode == "grid" else "List"
        self._mode_view_label.configure(
            text=f"{ScanMode.display_name(self._current_mode)} • {view_label}"
        )
        if checked_ids is None:
            checked_ids = self._get_checked_item_ids()
        checked_set = set(checked_ids)
        marked_size = 0
        for g in self._filtered_groups:
            for i, fd in enumerate(g.files):
                if f"{g.group_id}_{i}" in checked_set:
                    marked_size += self._fd_size(fd)
        self._selected_count = len(checked_set)
        self._selected_count_label.configure(text=f"Selected: {self._selected_count}")
        self._selected_size_label.configure(text=f"Marked size: {format_bytes(marked_size)}")

    def _format_date(self, timestamp: float) -> str:
        """Format timestamp to readable date."""
        if not timestamp:
            return "Unknown"

        from datetime import datetime
        dt = datetime.fromtimestamp(timestamp)
        return dt.strftime("%Y-%m-%d")

    def clear(self) -> None:
        """Clear all results."""
        self._groups.clear()
        self._filtered_groups.clear()
        self._total_items = 0
        self._selected_count = 0
        self._treeview.clear()
        # Hide filter bar — only shown post-scan
        if self._filter_bar.winfo_ismapped():
            self._filter_bar.pack_forget()
        if self._scan_view.winfo_ismapped():
            self._scan_view.pack_forget()
        self._show_empty_state()
        self._update_status()

    # Compatibility helpers used by main window wiring.
    def show_welcome_screen(self) -> None:
        self.clear()

    def on_request_stop_search(self, cb: Callable[[], None]) -> None:
        self._on_request_stop_search = cb

    def on_request_auto_mark(self, cb: Callable[[], None]) -> None:
        self._on_request_auto_mark_cb = cb

    def _on_scan_cancel_request(self) -> None:
        if self._on_request_stop_search:
            self._on_request_stop_search()

    def _on_banner_auto_mark(self) -> None:
        if self._on_request_auto_mark_cb:
            self._on_request_auto_mark_cb()

    def _complete_banner_dismiss(self) -> None:
        self._complete_banner.hide()

    def show_scanning_progress(self) -> None:
        """Show live in-progress UI instead of getting-started / tree."""
        self._treeview.pack_forget()
        self._empty_view.pack_forget()
        if self._scan_view.winfo_ismapped():
            self._scan_view.pack_forget()
        self._scan_view.pack(fill="both", expand=True)
        self._scan_view.reset()

    def hide_scan_progress(self) -> None:
        """Remove in-progress view; restore tree or empty state."""
        if self._scan_view.winfo_ismapped():
            self._scan_view.pack_forget()
        if self._groups:
            self._show_results()
        else:
            self._show_empty_state()

    def update_scan_progress(
        self,
        *,
        stage: str,
        files_scanned: int,
        files_total: int,
        elapsed_seconds: float,
    ) -> None:
        if not self._scan_view.winfo_ismapped():
            return
        self._scan_view.update_progress(
            stage=stage,
            files_scanned=files_scanned,
            files_total=files_total,
            elapsed_seconds=elapsed_seconds,
        )

    def show_scan_complete(
        self,
        *,
        final_state: ScanState,
        groups_found: int,
        duplicates_found: int,
        bytes_reclaimable: int,
        elapsed_seconds: float,
    ) -> None:
        self._complete_banner.schedule_show(
            delay_ms=320,
            final_state=final_state,
            groups_found=groups_found,
            duplicates_found=duplicates_found,
            bytes_reclaimable=bytes_reclaimable,
            elapsed_seconds=elapsed_seconds,
        )

    def hide_scan_complete(self) -> None:
        self._complete_banner.hide()

    def set_live_scan_status(self, message: str) -> None:
        self._results_count_label.configure(text=message)

    def refresh_after_delete(self) -> None:
        self._refresh_treeview()
        self._update_status()

    def get_selected_items(self) -> List:
        return self.get_selected_files()

    def remove_paths(self, paths: List[str]) -> None:
        """
        Remove deleted files from in-memory groups and treeview.

        Args:
            paths: List of file path strings to remove.
        """
        path_set = set(paths)

        for group in list(self._groups):
            # Remove matching files from group
            removed_indices = [
                i for i, f in enumerate(group.files)
                if str(f.path) in path_set
            ]
            for i in sorted(removed_indices, reverse=True):
                item_id = f"{group.group_id}_{i}"
                try:
                    self._treeview.delete(item_id)
                except tk.TclError as exc:
                    logger.debug("Failed to delete tree row '%s': %s", item_id, exc)
                group.files.pop(i)

            # Recalculate group derived fields
            if group.files:
                group.total_size = sum(f.size for f in group.files)
                keeper_size = max(f.size for f in group.files)
                group.reclaimable = group.total_size - keeper_size
            else:
                # Remove empty group row and data
                group_row_id = f"group_{group.group_id}"
                try:
                    self._treeview.delete(group_row_id)
                except tk.TclError as exc:
                    logger.debug("Failed to delete group row '%s': %s", group_row_id, exc)
                self._groups.remove(group)

        self._filtered_groups = list(self._groups)
        self._total_items = sum(g.file_count for g in self._groups)
        self._selected_count = max(0, self._selected_count - len(paths))
        self._update_status()

        if not self._groups:
            self._show_empty_state()

    def uncheck_path(self, path: str) -> None:
        """Uncheck the file row matching path (mark as keeper / keep)."""
        for group in self._filtered_groups:
            for i, f in enumerate(group.files):
                if str(f.path) == path:
                    item_id = f"{group.group_id}_{i}"
                    self._treeview.set_check(item_id, False)
                    return

    def attach_thumbnail_grid(self, grid: Any) -> None:
        """Wire the thumbnail grid so selection rules and delete apply in grid view."""
        self._thumbnail_grid = grid

    def set_results_view_mode(self, mode: str) -> None:
        """Whether the user is viewing list (tree) or grid thumbnails."""
        self._results_view_mode = mode if mode in ("list", "grid") else "list"
        self._update_status()

    def on_file_row_focus(self, callback: Callable[[str], None]) -> None:
        """Callback when a list row is activated for preview (separate from checkbox)."""
        self._on_file_row_focus = callback

    def _get_checked_item_ids(self) -> List[str]:
        if (
            self._results_view_mode == "grid"
            and self._thumbnail_grid is not None
            and getattr(self._thumbnail_grid, "_cards", None)
        ):
            return self._thumbnail_grid.get_checked()
        return self._treeview.get_checked()

    def _sync_thumbnail_checks_from_tree(self) -> None:
        """Mirror treeview checks onto thumbnail cards when the grid is built."""
        if self._thumbnail_grid is None:
            return
        cards = getattr(self._thumbnail_grid, "_cards", None)
        if not cards:
            return
        self._thumbnail_grid.apply_check_state(
            set(self._treeview.get_checked()), notify=False
        )

    def sync_tree_checks_from_grid_state(self, checked: List[str]) -> None:
        """After the user toggles grid checkboxes, update the hidden treeview."""
        self._syncing_checks = True
        try:
            checked_set = set(checked)
            for g in self._filtered_groups:
                for i in range(len(g.files)):
                    iid = f"{g.group_id}_{i}"
                    want = iid in checked_set
                    cur = self._treeview._item_states.get(iid, False)
                    if cur != want:
                        self._treeview.set_check(iid, want, notify=False)
            self._selected_count = len(checked)
        finally:
            self._syncing_checks = False
        self._update_status(list(checked_set))

    def get_selected_files(self) -> List[Dict[str, Any]]:
        """
        Get list of selected (checked) files.

        Returns:
            List of file data dictionaries for checked items.
        """
        checked_ids = self._get_checked_item_ids()
        # O(1) group lookup — avoids O(n×groups) linear scan for large result sets
        group_map = {g.group_id: g for g in self._filtered_groups}
        files = []

        for item_id in checked_ids:
            parts = item_id.split("_")
            if len(parts) == 2:
                try:
                    group_id = int(parts[0])
                    file_index = int(parts[1])
                except ValueError:
                    continue
                group = group_map.get(group_id)
                if group and file_index < len(group.files):
                    files.append(group.files[file_index])

        return files

    def get_reclaimable_space(self) -> int:
        """
        Calculate total reclaimable space from selected files.

        Returns:
            Total bytes reclaimable.
        """
        files = self.get_selected_files()
        return sum(f.size for f in files)

    def get_selected_count(self) -> int:
        """Get count of selected files."""
        return self._selected_count

    def get_total_count(self) -> int:
        """Get total count of all files."""
        return self._total_items

    def apply_selection_rule(self, rule: str) -> None:
        """
        Apply a selection rule to all results.

        Args:
            rule: Selection rule identifier.
        """
        self._bulk_selection_in_progress = True
        try:
            # Clear current selection
            self._treeview.uncheck_all(notify=False)
            self._selected_count = 0

            if rule == "select_all":
                self._treeview.check_all(notify=False)

            elif rule == "select_except_largest":
                # Keep largest in each group, select others
                for group in self._filtered_groups:
                    keeper_idx = group.get_keeper_index()
                    for i, _file_data in enumerate(group.files):
                        if i != keeper_idx:
                            item_id = f"{group.group_id}_{i}"
                            self._treeview.set_check(item_id, True, notify=False, update_display=False)

            elif rule == "select_except_smallest":
                # Keep smallest in each group, select others
                for group in self._filtered_groups:
                    keeper_idx = min(
                        range(len(group.files)),
                        key=lambda i: group.files[i].size
                    )
                    for i in range(len(group.files)):
                        if i != keeper_idx:
                            item_id = f"{group.group_id}_{i}"
                            self._treeview.set_check(item_id, True, notify=False, update_display=False)

            elif rule == "select_except_newest":
                # Keep newest in each group, select others
                for group in self._filtered_groups:
                    keeper_idx = max(
                        range(len(group.files)),
                        key=lambda i: group.files[i].modified
                    )
                    for i in range(len(group.files)):
                        if i != keeper_idx:
                            item_id = f"{group.group_id}_{i}"
                            self._treeview.set_check(item_id, True, notify=False, update_display=False)

            elif rule == "select_except_oldest":
                # Keep oldest in each group, select others
                for group in self._filtered_groups:
                    keeper_idx = min(
                        range(len(group.files)),
                        key=lambda i: group.files[i].modified
                    )
                    for i in range(len(group.files)):
                        if i != keeper_idx:
                            item_id = f"{group.group_id}_{i}"
                            self._treeview.set_check(item_id, True, notify=False, update_display=False)

            elif rule == "select_except_first":
                # Keep first file in each group (index 0), select all others
                for group in self._filtered_groups:
                    for i in range(1, len(group.files)):
                        item_id = f"{group.group_id}_{i}"
                        self._treeview.set_check(item_id, True, notify=False, update_display=False)

            elif rule == "select_except_highest_resolution":
                # For image/video groups: keep highest resolution, select others
                for group in self._filtered_groups:
                    best_idx = 0
                    best_res = -1
                    for i, fd in enumerate(group.files):
                        meta = fd.get("metadata", {}) if isinstance(fd, dict) else getattr(fd, "metadata", {})
                        w = meta.get("width", 0) or 0
                        h = meta.get("height", 0) or 0
                        res = w * h
                        if res > best_res:
                            best_res = res
                            best_idx = i
                    for i in range(len(group.files)):
                        if i != best_idx:
                            item_id = f"{group.group_id}_{i}"
                            self._treeview.set_check(item_id, True, notify=False, update_display=False)

            elif rule == "select_in_folder":
                # Prompt user for a folder; select all files inside it
                from tkinter import filedialog
                folder = filedialog.askdirectory(title="Select folder — mark files inside it")
                if folder:
                    folder_path = Path(folder)
                    for group in self._filtered_groups:
                        for i, fd in enumerate(group.files):
                            path_str = fd.get("path", "") if isinstance(fd, dict) else str(getattr(fd, "path", ""))
                            try:
                                if Path(path_str).is_relative_to(folder_path):
                                    item_id = f"{group.group_id}_{i}"
                                    self._treeview.set_check(item_id, True, notify=False, update_display=False)
                            except (OSError, ValueError) as exc:
                                logger.debug("Path '%s' folder match failed: %s", path_str, exc)

            elif rule == "select_by_extension":
                # Prompt user for extensions (comma-separated); select matching files
                from tkinter.simpledialog import askstring
                raw = askstring(
                    "Select by Extension",
                    "Enter extensions to mark (comma-separated, e.g. .jpg,.png):"
                )
                if raw:
                    exts = {e.strip().lower().lstrip(".") for e in raw.split(",")}
                    exts = {f".{e}" if not e.startswith(".") else e for e in exts}
                    for group in self._filtered_groups:
                        for i, fd in enumerate(group.files):
                            path_str = fd.get("path", "") if isinstance(fd, dict) else str(getattr(fd, "path", ""))
                            if Path(path_str).suffix.lower() in exts:
                                item_id = f"{group.group_id}_{i}"
                                self._treeview.set_check(item_id, True, notify=False, update_display=False)

            elif rule == "clear_all":
                pass  # already cleared above

            elif rule == "invert_selection":
                self._treeview.invert_checks(notify=False)
        finally:
            self._bulk_selection_in_progress = False

        # Single batched Tk pass to flush all icon changes accumulated above
        self._treeview.refresh_check_icons()
        # Compute checked list once and reuse — avoids 3× O(n) scans
        checked_ids = self._treeview.get_checked()
        self._selected_count = len(checked_ids)
        self._update_status(checked_ids)
        self._sync_thumbnail_checks_from_tree()
        if self._on_selection_changed:
            self._on_selection_changed(checked_ids)

    def expand_all_groups(self) -> None:
        """Expand all groups in treeview."""
        self._treeview.expand_all()

    def collapse_all_groups(self) -> None:
        """Collapse all groups in treeview."""
        self._treeview.collapse_all()

    def on_selection_changed(self, callback: Callable[[List[str]], None]) -> None:
        """Set callback for selection changes."""
        self._on_selection_changed = callback

    def on_file_selected(self, callback: Callable[[Dict], None]) -> None:
        """Set callback for file selection."""
        self._on_file_selected = callback

    def on_file_double_clicked(self, callback: Callable[[Dict], None]) -> None:
        """Set callback for file double-click."""
        self._on_file_double_clicked = callback

    def set_mode(self, mode: str) -> None:
        """Set active scan mode, update columns, and show mode-specific warnings."""
        from cerebro.v2.ui.mode_tabs import ScanMode
        if mode not in ScanMode.all_modes():
            return
        self._current_mode = mode
        self._configure_columns_for_mode(mode)
        self._update_status()

    def show_ffmpeg_warning(self, visible: bool) -> None:
        """Show or hide the FFmpeg-missing warning banner."""
        if not hasattr(self, "_ffmpeg_banner"):
            import customtkinter as ctk
            self._ffmpeg_banner = ctk.CTkLabel(
                self,
                text="⚠  FFmpeg not found — running in metadata-only mode (duration+size).\n"
                     "Install FFmpeg for frame-accurate matching:  winget install ffmpeg",
                font=ctk.CTkFont(size=12),
                fg_color=("#FFF3CD", "#4A3800"),
                text_color=("#856404", "#FFD966"),
                corner_radius=6,
                anchor="w",
                justify="left",
                padx=12,
                pady=6,
            )
        if visible:
            if not self._ffmpeg_banner.winfo_ismapped():
                self._ffmpeg_banner.pack(fill="x", padx=8, pady=(4, 0), before=self._status_frame)
        else:
            if self._ffmpeg_banner.winfo_ismapped():
                self._ffmpeg_banner.pack_forget()

    def on_request_add_folder(self, cb: Callable[[], None]) -> None:
        """Wire getting-started 'Add Folder' button to MainWindow."""
        self._on_request_add_folder = cb

    def on_request_start_search(self, cb: Callable[[], None]) -> None:
        """Wire getting-started 'Search Now' button to MainWindow."""
        self._on_request_start_search = cb


# ---------------------------------------------------------------------------
# Getting-started / empty state view
# ---------------------------------------------------------------------------

class _GettingStartedView(CTkFrame):
    """
    Pre-scan onboarding view shown in the results area when no scan has run.

    Layout:
        ① Add a folder       [+ Add Folder]
        ② Click Search Now   [▶ Search Now]
        (brief tagline below)
    """

    def __init__(self, master=None, **kwargs):
        super().__init__(master, **kwargs)
        self._on_add_folder: Optional[Callable[[], None]] = None
        self._on_start_search: Optional[Callable[[], None]] = None

        subscribe_to_theme(self, self._apply_theme)
        self._build_ui()

    def _build_ui(self) -> None:
        self.configure(fg_color=theme_color("results.background"))

        # Centre-align everything vertically
        outer = CTkFrame(self, fg_color="transparent")
        outer.place(relx=0.5, rely=0.5, anchor="center")

        # Headline
        CTkLabel(
            outer,
            text="Find duplicate files",
            font=("", 22, "bold"),
            text_color=theme_color("base.foreground"),
        ).pack(pady=(0, Spacing.SM))

        CTkLabel(
            outer,
            text="Add the folders you want to scan, then hit Search Now.",
            font=Typography.FONT_MD,
            text_color=theme_color("base.foregroundSecondary"),
        ).pack(pady=(0, Spacing.XL if hasattr(Spacing, "XL") else 24))

        # Step rows
        steps_frame = CTkFrame(outer, fg_color="transparent")
        steps_frame.pack()

        self._add_step(steps_frame, "1", "Choose a folder to scan",
                       "+ Add Folder", "button.primary", "button.primaryHover",
                       self._click_add)

        # Spacer between steps
        CTkFrame(steps_frame, height=Spacing.MD,
                 fg_color="transparent").pack()

        self._search_btn_row = self._add_step(
            steps_frame, "2", "Start the search",
            "▶  Search Now", "feedback.success", "feedback.success",
            self._click_search)

        # Tagline
        CTkLabel(
            outer,
            text="Cerebro v2  —  fast duplicate finder",
            font=Typography.FONT_XS,
            text_color=theme_color("base.foregroundMuted"),
        ).pack(pady=(Spacing.XL if hasattr(Spacing, "XL") else 24, 0))

    def _add_step(self, parent, number: str, label: str,
                  btn_text: str, color_key: str, hover_key: str,
                  command) -> CTkFrame:
        row = CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x")

        # Step number badge
        badge = CTkLabel(
            row, text=number, width=28, height=28,
            font=("", 13, "bold"),
            text_color="white",
            fg_color=theme_color(color_key),
            corner_radius=14,
        )
        badge.pack(side="left", padx=(0, Spacing.SM))

        CTkLabel(
            row, text=label, font=Typography.FONT_MD,
            text_color=theme_color("base.foreground"),
        ).pack(side="left", padx=(0, Spacing.MD))

        btn = CTkButton(
            row, text=btn_text, width=140, height=36,
            font=Typography.FONT_MD,
            fg_color=theme_color(color_key),
            hover_color=theme_color(hover_key),
            corner_radius=Spacing.BORDER_RADIUS_SM,
        )
        btn.pack(side="left")
        btn.configure(command=command)
        return row

    def _apply_theme(self) -> None:
        try:
            self.configure(fg_color=theme_color("results.background"))
        except (tk.TclError, AttributeError) as exc:
            logger.debug("GettingStartedView theme application skipped: %s", exc)

    def _click_add(self) -> None:
        if self._on_add_folder:
            self._on_add_folder()

    def _click_search(self) -> None:
        if self._on_start_search:
            self._on_start_search()

    def on_add_folder(self, cb: Callable[[], None]) -> None:
        self._on_add_folder = cb

    def on_start_search(self, cb: Callable[[], None]) -> None:
        self._on_start_search = cb


class _FilterBar(CTkFrame):
    """
    Post-scan result filter tab row.

    Hidden by default; shown by ResultsPanel.load_results() once results arrive.
    Displays per-type counts:  All (347) | Images (120) | Videos (45) | Audio (89) | Docs (93) | Other (0)

    Emits the FilterType key (not display name) via on_filter_changed callback.
    """

    _TABS = [
        (FilterType.ALL,       "All"),
        (FilterType.IMAGES,    "Images"),
        (FilterType.VIDEOS,    "Videos"),
        (FilterType.AUDIO,     "Audio"),
        (FilterType.DOCUMENTS, "Docs"),
        (FilterType.OTHER,     "Other"),
    ]

    def __init__(self, master, on_filter_changed: Callable[[str], None], **kwargs):
        super().__init__(master, **kwargs)
        self._on_filter_changed = on_filter_changed
        self._current: str = FilterType.ALL
        self._counts: Dict[str, int] = {ft: 0 for ft, _ in self._TABS}
        self._btn_widgets: Dict[str, tk.Button] = {}
        subscribe_to_theme(self, self._apply_theme)
        self._build()

    def _build(self) -> None:
        self.configure(
            fg_color=theme_color("tabs.background"),
            height=32,
        )
        inner = tk.Frame(self, bg=theme_color("tabs.background"))
        inner.pack(side="left", padx=Spacing.XS, pady=2)
        self._inner = inner

        for ft, label in self._TABS:
            btn = tk.Button(
                inner,
                text=self._tab_text(label, 0),
                relief="flat",
                padx=Spacing.MD,
                pady=3,
                cursor="hand2",
                font=Typography.FONT_SM,
                command=lambda k=ft: self._select(k),
            )
            btn.pack(side="left")
            self._btn_widgets[ft] = btn

        self._refresh_styles()

    def _tab_text(self, label: str, count: int) -> str:
        return f"{label} ({count})"

    def update_counts(self, counts: Dict[str, int]) -> None:
        """Update displayed counts on each tab button."""
        self._counts = counts
        for ft, label in self._TABS:
            btn = self._btn_widgets.get(ft)
            if btn:
                btn.configure(text=self._tab_text(label, counts.get(ft, 0)))
        self._refresh_styles()

    def _select(self, filter_key: str) -> None:
        if filter_key == self._current:
            return
        self._current = filter_key
        self._refresh_styles()
        self._on_filter_changed(filter_key)

    def _refresh_styles(self) -> None:
        for ft, _ in self._TABS:
            btn = self._btn_widgets.get(ft)
            if not btn:
                continue
            if ft == self._current:
                btn.configure(
                    bg=theme_color("tabs.activeBackground"),
                    fg=theme_color("tabs.activeForeground"),
                    relief="solid",
                    bd=0,
                )
            else:
                btn.configure(
                    bg=theme_color("tabs.inactiveBackground"),
                    fg=theme_color("tabs.inactiveForeground"),
                    relief="flat",
                    bd=0,
                )

    def _apply_theme(self) -> None:
        try:
            self.configure(fg_color=theme_color("tabs.background"))
            self._inner.configure(bg=theme_color("tabs.background"))
        except (tk.TclError, AttributeError) as exc:
            logger.debug("Filter bar theme application skipped: %s", exc)
        self._refresh_styles()


