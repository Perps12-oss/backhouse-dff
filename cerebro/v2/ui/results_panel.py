"""
Results Panel Widget

Center panel with grouped results display using CheckTreeview.
Features sub-filtering by file type and sortable columns.
"""

from __future__ import annotations

import tkinter as tk
from typing import Optional, Callable, List, Dict, Any
from pathlib import Path

try:
    import customtkinter as ctk
    CTkFrame = ctk.CTkFrame
    CTkLabel = ctk.CTkLabel
    CTkSegmentedButton = ctk.CTkSegmentedButton
except ImportError:
    CTkFrame = tk.Frame
    CTkLabel = tk.Label
    CTkSegmentedButton = tk.Frame

from cerebro.v2.core.design_tokens import (
    Colors, Spacing, Typography, Dimensions
)
from cerebro.v2.ui.widgets.check_treeview import CheckTreeview


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


class DuplicateGroup:
    """Represents a duplicate group in results."""

    def __init__(
        self,
        group_id: int,
        files: List[Dict[str, Any]],
        total_size: int = 0,
        reclaimable: int = 0
    ):
        self.group_id = group_id
        self.files = files
        self.total_size = total_size
        self.reclaimable = reclaimable

    @property
    def file_count(self) -> int:
        """Get number of files in group."""
        return len(self.files)

    def get_keeper_index(self) -> int:
        """Get index of the keeper file (largest by default)."""
        if not self.files:
            return 0
        return max(
            range(len(self.files)),
            key=lambda i: self.files[i].get("size", 0)
        )


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

        # State
        self._current_filter: str = FilterType.ALL
        self._groups: List[DuplicateGroup] = []
        self._filtered_groups: List[DuplicateGroup] = []
        self._total_items: int = 0
        self._selected_count: int = 0

        # Widgets
        self._filter_tabs: Optional[CTkSegmentedButton] = None
        self._treeview: Optional[CheckTreeview] = None
        self._empty_label: Optional[CTkLabel] = None
        self._status_frame: Optional[CTkFrame] = None
        self._results_count_label: Optional[CTkLabel] = None

        # Callbacks
        self._on_selection_changed: Optional[Callable[[List[str]], None]] = None
        self._on_file_selected: Optional[Callable[[Dict], None]] = None
        self._on_file_double_clicked: Optional[Callable[[Dict], None]] = None

        # Build UI
        self._build_ui()
        self._show_empty_state()

    def _build_ui(self) -> None:
        """Build results panel UI."""
        self.configure(
            fg_color=Colors.BG_SECONDARY.hex
        )

        # Filter tabs bar
        self._build_filter_tabs()

        # Status bar (results count)
        self._build_status_bar()

        # Treeview container
        tree_container = CTkFrame(self)
        tree_container.pack(fill="both", expand=True, padx=Spacing.XS)

        # CheckTreeview
        self._treeview = CheckTreeview(
            tree_container,
            columns=("name", "extension", "size", "modified", "similarity"),
            selectmode="extended",
            height=20
        )
        self._treeview.pack(fill="both", expand=True)

        # Configure columns
        self._configure_columns()

        # Bind events
        self._treeview.on_check_changed(self._on_check_changed)
        self._treeview.bind("<Double-Button-1>", self._on_double_click)
        self._treeview.bind("<Button-3>", self._on_right_click)  # Right-click

        # Empty state label
        self._empty_label = CTkLabel(
            self,
            text="No results to display.\nAdd folders and click 'Start Search' to begin.",
            font=Typography.FONT_MD,
            text_color=Colors.TEXT_MUTED.hex
        )

    def _build_filter_tabs(self) -> None:
        """Build filter tabs bar."""
        filter_frame = CTkFrame(
            self,
            height=Dimensions.MODE_TABS_HEIGHT
        )
        filter_frame.pack(fill="x", padx=Spacing.XS, pady=(Spacing.SM, 0))

        self._filter_tabs = CTkSegmentedButton(
            filter_frame,
            values=FilterType.display_names(),
            font=Typography.FONT_SM
        )
        self._filter_tabs.pack(fill="x", padx=Spacing.SM, pady=Spacing.XS)

        # Configure filter tabs callback
        try:
            self._filter_tabs.configure(command=self._on_filter_changed)
        except AttributeError:
            # Fallback for non-CustomTkinter
            pass

    def _build_status_bar(self) -> None:
        """Build results count status bar."""
        self._status_frame = CTkFrame(
            self,
            height=28,
            fg_color=Colors.BG_TERTIARY.hex
        )
        self._status_frame.pack(fill="x", padx=Spacing.XS, pady=(0, Spacing.XS))

        self._results_count_label = CTkLabel(
            self._status_frame,
            text="0 groups, 0 files",
            font=Typography.FONT_SM,
            text_color=Colors.TEXT_SECONDARY.hex
        )
        self._results_count_label.pack(side="left", padx=Spacing.MD)

    def _configure_columns(self) -> None:
        """Configure treeview columns."""
        # Column settings
        columns = self._treeview["columns"]

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

    def _on_filter_changed(self, value: str) -> None:
        """Handle filter tab change."""
        # Convert display name back to filter type
        filter_map = {
            "All": FilterType.ALL,
            "Images": FilterType.IMAGES,
            "Videos": FilterType.VIDEOS,
            "Docs": FilterType.DOCUMENTS,
            "Audio": FilterType.AUDIO,
            "Other": FilterType.OTHER
        }

        new_filter = filter_map.get(value, FilterType.ALL)
        if new_filter != self._current_filter:
            self._current_filter = new_filter
            self._apply_filter()

    def _on_check_changed(self, item_id: str, checked: bool) -> None:
        """Handle checkbox state change."""
        if checked:
            self._selected_count += 1
        else:
            self._selected_count = max(0, self._selected_count - 1)

        # Notify callback
        if self._on_selection_changed:
            checked_items = self._treeview.get_checked()
            self._on_selection_changed(checked_items)

    def _on_double_click(self, event) -> None:
        """Handle double-click on file."""
        selection = self._treeview.selection()
        if selection:
            item_id = selection[0]
            # TODO: Get file data and notify callback
            print(f"Double-clicked: {item_id}")

    def _on_right_click(self, event) -> None:
        """Handle right-click context menu."""
        # TODO: Show context menu with:
        # - Open file
        # - Open containing folder
        # - Copy path
        # - Select group
        # - Deselect group
        # - Properties
        print("Right-click context menu")

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
        self._apply_filter()
        self._update_status()

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
                    if Path(f.get("path", "")).suffix.lower() in filter_extensions
                ]
                if filtered_files:
                    # Create new group with filtered files
                    filtered_group = DuplicateGroup(
                        group_id=group.group_id,
                        files=filtered_files,
                        total_size=sum(f.get("size", 0) for f in filtered_files),
                        reclaimable=sum(f.get("size", 0) for f in filtered_files[1:])  # Exclude keeper
                    )
                    self._filtered_groups.append(filtered_group)

        self._refresh_treeview()

    def _refresh_treeview(self) -> None:
        """Refresh treeview with filtered results."""
        self._treeview.clear()

        if not self._filtered_groups:
            self._show_empty_state()
            return

        self._show_results()

        # Load groups into treeview
        for group in self._filtered_groups:
            # Format size for display
            size_str = self._format_bytes(group.total_size)
            reclaimable_str = self._format_bytes(group.reclaimable)

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
                checked = file_data.get("checked", False)

                # Format values
                path = Path(file_data.get("path", ""))
                values = (
                    path.name,
                    path.suffix,
                    self._format_bytes(file_data.get("size", 0)),
                    self._format_date(file_data.get("modified", 0)),
                    f"{int(file_data.get('similarity', 1.0) * 100)}%"
                )

                # Determine keeper
                is_keeper = (i == group.get_keeper_index())
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

    def _show_empty_state(self) -> None:
        """Show empty state message."""
        if self._treeview.winfo_ismapped():
            self._treeview.pack_forget()
        if self._empty_label.winfo_ismapped():
            self._empty_label.pack_forget()
        self._empty_label.pack(expand=True)

    def _show_results(self) -> None:
        """Show results (treeview)."""
        if self._empty_label.winfo_ismapped():
            self._empty_label.pack_forget()
        if not self._treeview.winfo_ismapped():
            self._treeview.pack(fill="both", expand=True)

    def _update_status(self) -> None:
        """Update results count label."""
        total_files = sum(g.file_count for g in self._filtered_groups)
        self._results_count_label.configure(
            text=f"{len(self._filtered_groups)} groups, {total_files} files"
        )

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
        self._show_empty_state()
        self._update_status()

    def get_selected_files(self) -> List[Dict[str, Any]]:
        """
        Get list of selected (checked) files.

        Returns:
            List of file data dictionaries for checked items.
        """
        checked_ids = self._treeview.get_checked()
        files = []

        for item_id in checked_ids:
            # Parse item_id: group_index_file_index
            parts = item_id.split("_")
            if len(parts) == 2:
                group_id = int(parts[0])
                file_index = int(parts[1])

                # Find group
                group = next((g for g in self._filtered_groups if g.group_id == group_id), None)
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
        return sum(f.get("size", 0) for f in files)

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
        # Clear current selection
        self._treeview.uncheck_all()
        self._selected_count = 0

        if rule == "select_all":
            self._treeview.check_all()
            self._selected_count = self._total_items

        elif rule == "select_except_largest":
            # Keep largest in each group, select others
            for group in self._filtered_groups:
                keeper_idx = group.get_keeper_index()
                for i, file_data in enumerate(group.files):
                    if i != keeper_idx:
                        item_id = f"{group.group_id}_{i}"
                        self._treeview.set_check(item_id, True)
                        self._selected_count += 1

        elif rule == "select_except_smallest":
            # Keep smallest in each group, select others
            for group in self._filtered_groups:
                keeper_idx = min(
                    range(len(group.files)),
                    key=lambda i: group.files[i].get("size", float('inf'))
                )
                for i, file_data in enumerate(group.files):
                    if i != keeper_idx:
                        item_id = f"{group.group_id}_{i}"
                        self._treeview.set_check(item_id, True)
                        self._selected_count += 1

        elif rule == "select_except_newest":
            # Keep newest in each group, select others
            for group in self._filtered_groups:
                keeper_idx = max(
                    range(len(group.files)),
                    key=lambda i: group.files[i].get("modified", 0)
                )
                for i, file_data in enumerate(group.files):
                    if i != keeper_idx:
                        item_id = f"{group.group_id}_{i}"
                        self._treeview.set_check(item_id, True)
                        self._selected_count += 1

        elif rule == "select_except_oldest":
            # Keep oldest in each group, select others
            for group in self._filtered_groups:
                keeper_idx = min(
                    range(len(group.files)),
                    key=lambda i: group.files[i].get("modified", float('inf'))
                )
                for i, file_data in enumerate(group.files):
                    if i != keeper_idx:
                        item_id = f"{group.group_id}_{i}"
                        self._treeview.set_check(item_id, True)
                        self._selected_count += 1

        elif rule == "invert_selection":
            self._treeview.invert_checks()
            self._selected_count = self._total_items - self._selected_count

        # Notify callback
        if self._on_selection_changed:
            checked_items = self._treeview.get_checked()
            self._on_selection_changed(checked_items)

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
        """
        Set active scan mode and update columns.

        Args:
            mode: The scan mode from ScanMode class.
        """
        from cerebro.v2.ui.mode_tabs import ScanMode

        if mode not in ScanMode.all_modes():
            return

        self._configure_columns_for_mode(mode)


# Simple logger fallback
logger = __import__('logging').getLogger(__name__)
