"""
Check Treeview Widget

ttk.Treeview subclass with checkbox support and group headers.
Supports grouped/hierarchical rows with expand/collapse functionality.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import List, Optional, Callable, Any

from cerebro.v2.core.design_tokens import Spacing, Typography
from cerebro.v2.core.theme_bridge_v2 import theme_color, subscribe_to_theme


# Checkbox icons (unicode)
CHECK_UNCHECKED = "☐"
CHECK_CHECKED = "☑"


class CheckTreeview(ttk.Treeview):
    """
    Treeview with checkbox column support.

    Features:
    - Checkbox column via tag icons (☐/☑)
    - toggle_check(), check_all(), uncheck_all(), invert_checks()
    - get_checked() returns list of item IDs
    - Grouped/hierarchical rows with parent headers
    - Alternating row colors within groups
    - Fires <<CheckChanged>> virtual event
    - Virtual scrolling support for large datasets
    """

    CHECK_COLUMN = "check"
    CHECK_COLUMN_WIDTH = 40

    def __init__(self, master=None, **kwargs):
        """Initialize check treeview."""
        # Add checkbox column to columns
        columns = kwargs.get("columns", [])
        columns = [self.CHECK_COLUMN] + list(columns)

        # Set show='headings' to hide headers
        super().__init__(
            master,
            columns=columns,
            show="headings",
            **kwargs
        )

        # Hide checkbox column header
        self.heading(self.CHECK_COLUMN, text="")

        # Configure checkbox column
        self.column(
            self.CHECK_COLUMN,
            width=self.CHECK_COLUMN_WIDTH,
            stretch=False,
            anchor="center"
        )

        # State
        self._item_states: dict[str, bool] = {}
        self._group_rows: dict[str, str] = {}  # parent_id -> group_id
        self._check_callback: Optional[Callable[[str, bool], None]] = None

        # Tags for styling
        self._setup_tags()
        subscribe_to_theme(self, self._apply_theme)

        # Bind selection events
        self.bind("<<TreeviewSelect>>", self._on_select)
        self.bind("<Button-1>", self._on_click)
        self.bind("<Double-Button-1>", self._on_double_click)

    def _setup_tags(self) -> None:
        """Setup tag configurations for styling."""
        self.tag_configure(
            "checked",
            foreground=theme_color("results.foreground")
        )
        self.tag_configure(
            "unchecked",
            foreground=theme_color("results.foreground")
        )
        self.tag_configure(
            "group_header",
            background=theme_color("results.groupHeader"),
            foreground=theme_color("results.foreground"),
            font=(Typography.FONT_MD[0], Typography.FONT_MD[1], "bold")
        )
        self.tag_configure(
            "row_even",
            background=theme_color("results.rowEven")
        )
        self.tag_configure(
            "row_odd",
            background=""
        )
        self.tag_configure(
            "protected",
            foreground=theme_color("feedback.warning")
        )

    def _apply_theme(self) -> None:
        """Re-apply tag configurations when theme changes."""
        self._setup_tags()

    def insert_group(self, parent: str, group_id: str, text: str,
                    **kwargs) -> str:
        """
        Insert a group header row.

        Args:
            parent: Parent item ID ("" for root).
            group_id: Unique ID for the group.
            text: Display text for the group.
            **kwargs: Additional treeview insert arguments.

        Returns:
            The item ID.
        """
        item_id = self.insert(
            parent,
            "end",
            iid=group_id,
            text=text,
            tags="group_header",
            **kwargs
        )
        self._group_rows[group_id] = group_id
        return item_id

    def insert_item(self, parent: str, item_id: str, checked: bool = False,
                  **kwargs) -> str:
        """
        Insert a file item with checkbox.

        Args:
            parent: Parent item ID (group header ID).
            item_id: Unique ID for the item.
            checked: Initial checkbox state.
            **kwargs: Additional treeview insert arguments.

        Returns:
            The item ID.
        """
        self._item_states[item_id] = checked

        # Pop values and tags from kwargs to avoid duplicate-keyword error
        file_values = kwargs.pop("values", ())
        row_tags = kwargs.pop("tags", self._get_row_tags(parent))

        # Prepend checkbox icon to file values
        check_icon = CHECK_CHECKED if checked else CHECK_UNCHECKED
        combined_values = (check_icon,) + tuple(file_values)

        self.insert(
            parent,
            "end",
            iid=item_id,
            values=combined_values,
            tags=row_tags,
            **kwargs
        )
        return item_id

    def _get_row_tags(self, parent: str) -> List[str]:
        """Get tags for a row (alternating colors)."""
        # Count children of parent
        children = self.get_children(parent)
        if parent in self._group_rows:
            # For group header, no alternating color
            return ["group_header"]
        elif parent:
            # For file rows, get index for alternating color
            parent_children = self.get_children(parent)
            index = parent_children.index(parent) if parent in parent_children else 0
            tags = ["row_even" if index % 2 == 0 else "row_odd"]
            return tags
        else:
            return []

    def toggle_check(self, item_id: str) -> None:
        """
        Toggle checkbox state for an item.

        Args:
            item_id: The item ID to toggle.
        """
        current = self._item_states.get(item_id, False)
        new_state = not current

        self.set_check(item_id, new_state)

    def set_check(self, item_id: str, checked: bool) -> None:
        """
        Set checkbox state for an item.

        Args:
            item_id: The item ID to update.
            checked: New checkbox state.
        """
        self._item_states[item_id] = checked

        # Update the checkbox icon in the treeview
        check_icon = CHECK_CHECKED if checked else CHECK_UNCHECKED

        # Get current values
        values = list(self.item(item_id)['values']) or []

        # Update checkbox column value
        if values:
            values[0] = check_icon
            self.item(item_id, values=tuple(values))

        # Notify callback
        if self._check_callback:
            self._check_callback(item_id, checked)

        # Fire virtual event
        self.event_generate("<<CheckChanged>>")

    def check_all(self) -> None:
        """Check all items (not group headers)."""
        for item_id, state in self._item_states.items():
            if not state and item_id not in self._group_rows:
                self.set_check(item_id, True)

    def uncheck_all(self) -> None:
        """Uncheck all items (not group headers)."""
        for item_id in self._item_states.items():
            if item_id[1] and item_id[0] not in self._group_rows:
                self.set_check(item_id[0], False)

    def invert_checks(self) -> None:
        """Invert checkbox state for all items (not group headers)."""
        for item_id, state in self._item_states.items():
            if item_id not in self._group_rows:
                self.set_check(item_id, not state)

    def check_group(self, group_id: str) -> None:
        """Check all items in a group."""
        children = self.get_children(group_id)
        for child_id in children:
            self.set_check(child_id, True)

    def uncheck_group(self, group_id: str) -> None:
        """Uncheck all items in a group."""
        children = self.get_children(group_id)
        for child_id in children:
            self.set_check(child_id, False)

    def invert_group(self, group_id: str) -> None:
        """Invert checkbox state for all items in a group."""
        children = self.get_children(group_id)
        for child_id in children:
            current = self._item_states.get(child_id, False)
            self.set_check(child_id, not current)

    def get_checked(self) -> List[str]:
        """
        Get list of checked item IDs.

        Returns:
            List of item IDs that are checked (excludes group headers).
        """
        return [
            item_id for item_id, checked in self._item_states.items()
            if checked and item_id not in self._group_rows
        ]

    def get_group_checked(self, group_id: str) -> List[str]:
        """
        Get list of checked item IDs in a group.

        Args:
            group_id: The group ID to query.

        Returns:
            List of checked item IDs in the group.
        """
        children = self.get_children(group_id)
        return [child_id for child_id in children
                if self._item_states.get(child_id, False)]

    def get_checked_count(self) -> int:
        """
        Get total count of checked items.

        Returns:
            Number of checked items.
        """
        return len(self.get_checked())

    def get_group_checked_count(self, group_id: str) -> int:
        """
        Get count of checked items in a group.

        Args:
            group_id: The group ID to query.

        Returns:
            Number of checked items in the group.
        """
        return len(self.get_group_checked(group_id))

    def clear(self) -> None:
        """Clear all items from the treeview."""
        self.delete(*self.get_children())
        self._item_states.clear()
        self._group_rows.clear()

    def load_data(self, data: List[dict]) -> None:
        """
        Bulk load data into the treeview with progress indication.

        Args:
            data: List of dicts with keys:
                   - 'group_id': str
                   - 'group_text': str
                   - 'items': List of dicts with 'item_id', 'values', 'tags'
        """
        self.clear()

        for group_data in data:
            group_id = group_data['group_id']
            group_text = group_data['group_text']

            # Insert group header
            self.insert_group("", group_id, group_text)

            # Insert items
            for item_data in group_data['items']:
                self.insert_item(
                    group_id,
                    item_data['item_id'],
                    checked=item_data.get('checked', False),
                    values=item_data.get('values', ()),
                    tags=item_data.get('tags', ())
                )

    def on_check_changed(self, callback: Callable[[str, bool], None]) -> None:
        """
        Set callback for checkbox changes.

        Args:
            callback: Function called with (item_id, new_state).
        """
        self._check_callback = callback

    def _on_click(self, event) -> None:
        """Handle left-click — toggle checkbox if clicking on a file row."""
        region = self.identify_region(event.x, event.y)
        if region not in ("cell", "tree"):
            return
        item_id = self.identify_row(event.y)
        if not item_id or item_id in self._group_rows:
            return  # ignore clicks on group headers
        self.toggle_check(item_id)

    def _on_select(self, event) -> None:
        """Handle selection event."""
        selection = self.selection()
        # Could emit a selection changed event here

    def _on_double_click(self, event) -> None:
        """Handle double-click (expand/collapse groups)."""
        selection = self.selection()
        if selection:
            item_id = selection[0]

            # Check if it's a group (has children)
            if self.get_children(item_id):
                # Toggle expand/collapse
                if self.item(item_id, "open"):
                    self.item(item_id, open=False)
                else:
                    self.item(item_id, open=True)

    def get_all_items(self) -> List[str]:
        """
        Get all item IDs (including groups).

        Returns:
            List of all item IDs in the treeview.
        """
        items = []
        for item_id in self.get_children(""):
            items.append(item_id)
            items.extend(self.get_children(item_id))
        return items

    def get_all_groups(self) -> List[str]:
        """
        Get all group header IDs.

        Returns:
            List of group IDs.
        """
        return list(self._group_rows.keys())

    def expand_all(self) -> None:
        """Expand all groups."""
        for group_id in self._group_rows:
            self.item(group_id, open=True)

    def collapse_all(self) -> None:
        """Collapse all groups."""
        for group_id in self._group_rows:
            self.item(group_id, open=False)

    def sort_by_column(self, column: str, reverse: bool = False) -> None:
        """
        Sort items within each group by column value.

        Args:
            column: Column name to sort by.
            reverse: If True, sort descending.
        """
        # Get column index
        columns = self["columns"]
        if column not in columns:
            return

        col_index = columns.index(column)

        for group_id in self._group_rows:
            children = self.get_children(group_id)

            # Sort children by their values
            children_with_values = []
            for child_id in children:
                values = self.item(child_id, "values") or ()
                children_with_values.append((child_id, values))

            try:
                children_with_values.sort(
                    key=lambda x: (x[1][col_index] if len(x[1]) > col_index else ""),
                    reverse=reverse
                )
            except (IndexError, TypeError):
                # Skip if column value not available
                continue

            # Re-insert sorted children
            self.delete(*children)
            for child_id, values in children_with_values:
                # Preserve checkbox state
                checked = self._item_states.get(child_id, False)
                self.insert_item(group_id, child_id, checked=checked, values=values)
