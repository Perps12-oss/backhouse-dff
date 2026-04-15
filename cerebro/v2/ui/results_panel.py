"""
Results Panel Widget

Center panel with grouped results display using CheckTreeview.
Features sub-filtering by file type and sortable columns.
"""

from __future__ import annotations

import logging
import tkinter as tk
from typing import Optional, Callable, List, Dict, Any
from pathlib import Path

try:
    import customtkinter as ctk
    CTkFrame = ctk.CTkFrame
    CTkLabel = ctk.CTkLabel
    CTkButton = ctk.CTkButton
except ImportError:
    CTkFrame = tk.Frame
    CTkLabel = tk.Label
    CTkButton = tk.Button

from cerebro.v2.core.design_tokens import Spacing, Typography, Dimensions
from cerebro.v2.core.theme_bridge_v2 import theme_color, subscribe_to_theme
from cerebro.v2.ui.feedback import FeedbackPanel, show_text_panel
from cerebro.v2.ui.widgets.check_treeview import CheckTreeview
from cerebro.engines.base_engine import DuplicateGroup, DuplicateFile
from cerebro.services.logger import get_logger
from cerebro.utils.formatting import format_bytes

logger = get_logger(__name__)  # wraps logging.getLogger(__name__)


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
            fg_color=theme_color("results.background")
        )

        # Filter tab bar — hidden until load_results() is called with data
        self._filter_bar = _FilterBar(self, on_filter_changed=self._on_filter_changed)
        # NOT packed here — shown only post-scan

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
        self._treeview.bind("<<TreeviewSelect>>", self._on_single_click)
        self._treeview.bind("<Double-Button-1>", self._on_double_click)
        self._treeview.bind("<Button-3>", self._on_right_click)  # Right-click

        # Getting-started / empty state view
        self._empty_view = _GettingStartedView(self)
        self._empty_view.on_add_folder(self._on_gs_add_folder)
        self._empty_view.on_start_search(self._on_gs_start_search)

        # Callbacks that MainWindow wires up for getting-started actions
        self._on_request_add_folder: Optional[Callable[[], None]] = None
        self._on_request_start_search: Optional[Callable[[], None]] = None

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

    def _build_status_bar(self) -> None:
        """Build results count status bar."""
        self._status_frame = CTkFrame(
            self,
            height=28,
            fg_color=theme_color("base.backgroundTertiary")
        )
        self._status_frame.pack(fill="x", padx=Spacing.XS, pady=(0, Spacing.XS))

        self._results_count_label = CTkLabel(
            self._status_frame,
            text="0 groups, 0 files",
            font=Typography.FONT_SM,
            text_color=theme_color("results.foreground")
        )
        self._results_count_label.pack(side="left", padx=Spacing.MD)

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
                subprocess.Popen(["explorer", "/select,", path])
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

    def _refresh_treeview(self) -> None:
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
                checked = not is_keeper

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
            if group_idx % 15 == 0:
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
        self._empty_view.pack(fill="both", expand=True)

    def _show_results(self) -> None:
        """Show results treeview, hide empty state."""
        self._empty_view.pack_forget()
        self._treeview.pack(fill="both", expand=True)

    def _on_gs_add_folder(self) -> None:
        if self._on_request_add_folder:
            self._on_request_add_folder()

    def _on_gs_start_search(self) -> None:
        if self._on_request_start_search:
            self._on_request_start_search()

    def _update_status(self) -> None:
        """Update results count label."""
        total_files = sum(g.file_count for g in self._filtered_groups)
        self._results_count_label.configure(
            text=f"{len(self._filtered_groups)} groups, {total_files} files"
        )

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
        self._show_empty_state()
        self._update_status()

    # Compatibility helpers used by main window wiring.
    def show_welcome_screen(self) -> None:
        self.clear()

    def show_scanning_progress(self, message: str = "Scanning...") -> None:
        self._show_empty_state()
        self._results_count_label.configure(text=message)

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
                    key=lambda i: group.files[i].size
                )
                for i in range(len(group.files)):
                    if i != keeper_idx:
                        item_id = f"{group.group_id}_{i}"
                        self._treeview.set_check(item_id, True)
                        self._selected_count += 1

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
                        self._treeview.set_check(item_id, True)
                        self._selected_count += 1

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
                        self._treeview.set_check(item_id, True)
                        self._selected_count += 1

        elif rule == "select_except_first":
            # Keep first file in each group (index 0), select all others
            for group in self._filtered_groups:
                for i in range(1, len(group.files)):
                    item_id = f"{group.group_id}_{i}"
                    self._treeview.set_check(item_id, True)
                    self._selected_count += 1

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
                        self._treeview.set_check(item_id, True)
                        self._selected_count += 1

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
                                self._treeview.set_check(item_id, True)
                                self._selected_count += 1
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
                            self._treeview.set_check(item_id, True)
                            self._selected_count += 1

        elif rule == "clear_all":
            pass  # already cleared above

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
        """Set active scan mode, update columns, and show mode-specific warnings."""
        from cerebro.v2.ui.mode_tabs import ScanMode
        if mode not in ScanMode.all_modes():
            return
        self._current_mode = mode
        self._configure_columns_for_mode(mode)

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


