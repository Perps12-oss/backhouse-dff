"""
Selection Bar Widget

Selection assistant strip with rules and bulk action buttons.
Provides: Rule dropdown, Apply button, selected counter, Select All/Deselect All/Invert, Delete Selected.
"""

from __future__ import annotations

import tkinter as tk
from typing import Optional, Callable, List

try:
    import customtkinter as ctk
    CTkFrame = ctk.CTkFrame
    CTkButton = ctk.CTkButton
    CTkLabel = ctk.CTkLabel
    CTkOptionMenu = ctk.CTkOptionMenu
except ImportError:
    # Fallback to standard tkinter
    CTkFrame = tk.Frame
    CTkButton = tk.Button
    CTkLabel = tk.Label
    CTkOptionMenu = tk.OptionMenu

from cerebro.v2.core.design_tokens import Colors, Spacing, Typography, Dimensions


class SelectionRule:
    """Available selection assistant rules."""

    SELECT_ALL_EXCEPT_NEWEST = "select_except_newest"
    SELECT_ALL_EXCEPT_OLDEST = "select_except_oldest"
    SELECT_ALL_EXCEPT_LARGEST = "select_except_largest"
    SELECT_ALL_EXCEPT_SMALLEST = "select_except_smallest"
    SELECT_ALL_EXCEPT_HIGHEST_RES = "select_except_highest_res"
    SELECT_ALL_IN_FOLDER = "select_in_folder"
    SELECT_BY_EXTENSION = "select_by_extension"
    SELECT_ALL_EXCEPT_FIRST = "select_except_first"
    INVERT_SELECTION = "invert_selection"
    CLEAR_SELECTION = "clear_selection"
    SELECT_ALL = "select_all"

    @classmethod
    def display_name(cls, rule: str) -> str:
        """Get human-readable name for a rule."""
        names = {
            cls.SELECT_ALL_EXCEPT_NEWEST: "Select all except newest",
            cls.SELECT_ALL_EXCEPT_OLDEST: "Select all except oldest",
            cls.SELECT_ALL_EXCEPT_LARGEST: "Select all except largest",
            cls.SELECT_ALL_EXCEPT_SMALLEST: "Select all except smallest",
            cls.SELECT_ALL_EXCEPT_HIGHEST_RES: "Select all except highest res",
            cls.SELECT_ALL_IN_FOLDER: "Select all in folder…",
            cls.SELECT_BY_EXTENSION: "Select by extension…",
            cls.SELECT_ALL_EXCEPT_FIRST: "Select all except first in group",
            cls.INVERT_SELECTION: "Invert selection",
            cls.CLEAR_SELECTION: "Clear selection",
            cls.SELECT_ALL: "Select All",
        }
        return names.get(rule, rule)

    @classmethod
    def all_rules(cls) -> List[str]:
        """Get list of all selection rules."""
        return [
            cls.SELECT_ALL_EXCEPT_NEWEST,
            cls.SELECT_ALL_EXCEPT_OLDEST,
            cls.SELECT_ALL_EXCEPT_LARGEST,
            cls.SELECT_ALL_EXCEPT_SMALLEST,
            cls.SELECT_ALL_EXCEPT_HIGHEST_RES,
            cls.SELECT_ALL_IN_FOLDER,
            cls.SELECT_BY_EXTENSION,
            cls.SELECT_ALL_EXCEPT_FIRST,
        ]


class SelectionBar(CTkFrame):
    """
    Selection assistant strip below results.

    Features:
    - Rule dropdown (CTkOptionMenu) with 8+ auto-mark rules
    - Apply button to execute selected rule
    - Selected counter (X of Y selected)
    - Select All / Deselect All / Invert buttons
    - Delete Selected button (danger color)
    """

    def __init__(self, master=None, **kwargs):
        """Initialize selection bar."""
        super().__init__(master, **kwargs)

        # State
        self._total_items: int = 0
        self._selected_items: int = 0
        self._current_rule: str = SelectionRule.SELECT_ALL_EXCEPT_LARGEST

        # Widgets
        self._rule_menu: Optional[CTkOptionMenu] = None
        self._apply_btn: Optional[CTkButton] = None
        self._selected_label: Optional[CTkLabel] = None
        self._select_all_btn: Optional[CTkButton] = None
        self._deselect_all_btn: Optional[CTkButton] = None
        self._invert_btn: Optional[CTkButton] = None
        self._delete_btn: Optional[CTkButton] = None

        # Callbacks
        self._on_apply_rule: Optional[Callable[[str], None]] = None
        self._on_select_all: Optional[Callable[[], None]] = None
        self._on_deselect_all: Optional[Callable[[], None]] = None
        self._on_invert: Optional[Callable[[], None]] = None
        self._on_delete_selected: Optional[Callable[[], None]] = None

        # Build UI
        self._build_widgets()
        self._layout_widgets()

    def _build_widgets(self) -> None:
        """Build all selection bar widgets."""
        # Rule dropdown
        rule_names = [SelectionRule.display_name(r) for r in SelectionRule.all_rules()]
        self._rule_menu = CTkOptionMenu(
            self,
            values=rule_names,
            default_value=SelectionRule.display_name(self._current_rule),
            width=200,
            height=Dimensions.BUTTON_HEIGHT_MD,
            font=Typography.FONT_MD,
            fg_color=Colors.TEXT_PRIMARY.hex,
            button_color=Colors.BG_TERTIARY.hex,
            button_hover_color=Colors.BG_QUATERNARY.hex,
            dropdown_fg_color=Colors.TEXT_PRIMARY.hex,
            dropdown_hover_color=Colors.ACCENT.hex
        )

        # Apply button
        self._apply_btn = CTkButton(
            self,
            text="Apply",
            width=80,
            height=Dimensions.BUTTON_HEIGHT_MD,
            font=Typography.FONT_MD,
            fg_color=Colors.ACCENT.hex,
            hover_color=Colors.ACCENT_HOVER.hex,
            command=self.trigger_apply_rule
        )

        # Selected counter
        self._selected_label = CTkLabel(
            self,
            text="0 of 0 selected",
            font=Typography.FONT_MD,
            text_color=Colors.TEXT_SECONDARY.hex
        )

        # Separator
        separator1 = CTkLabel(self, text="│", text_color=Colors.BORDER.hex)

        # Select All button
        self._select_all_btn = CTkButton(
            self,
            text="Select All",
            width=100,
            height=Dimensions.BUTTON_HEIGHT_MD,
            font=Typography.FONT_SM,
            fg_color=Colors.BG_TERTIARY.hex,
            hover_color=Colors.BG_QUATERNARY.hex,
            command=self.trigger_select_all
        )

        # Deselect All button
        self._deselect_all_btn = CTkButton(
            self,
            text="Deselect All",
            width=110,
            height=Dimensions.BUTTON_HEIGHT_MD,
            font=Typography.FONT_SM,
            fg_color=Colors.BG_TERTIARY.hex,
            hover_color=Colors.BG_QUATERNARY.hex,
            command=self.trigger_deselect_all
        )

        # Invert button
        self._invert_btn = CTkButton(
            self,
            text="Invert",
            width=80,
            height=Dimensions.BUTTON_HEIGHT_MD,
            font=Typography.FONT_SM,
            fg_color=Colors.BG_TERTIARY.hex,
            hover_color=Colors.BG_QUATERNARY.hex,
            command=self.trigger_invert
        )

        # Separator
        separator2 = CTkLabel(self, text="│", text_color=Colors.BORDER.hex)

        # Delete Selected button
        self._delete_btn = CTkButton(
            self,
            text="🗑 Delete Selected",
            width=160,
            height=Dimensions.BUTTON_HEIGHT_MD,
            font=Typography.FONT_MD,
            fg_color=Colors.DANGER.hex,
            hover_color=Colors.DANGER_HOVER.hex,
            command=self.trigger_delete_selected
        )

    def _layout_widgets(self) -> None:
        """Layout the selection bar widgets."""
        self.configure(
            height=Dimensions.BUTTON_HEIGHT_LG,
            fg_color=Colors.BG_SECONDARY.hex
        )

        self._rule_menu.pack(
            side="left",
            padx=Spacing.MD,
            pady=(Spacing.SM, Spacing.SM)
        )

        self._apply_btn.pack(
            side="left",
            padx=Spacing.SM,
            pady=(Spacing.SM, Spacing.SM)
        )

        self._selected_label.pack(
            side="left",
            padx=Spacing.LG,
            pady=(Spacing.SM, Spacing.SM)
        )

        separator1.pack(side="left", padx=Spacing.XS)
        self._select_all_btn.pack(
            side="left",
            padx=Spacing.SM,
            pady=(Spacing.SM, Spacing.SM)
        )

        self._deselect_all_btn.pack(
            side="left",
            padx=Spacing.SM,
            pady=(Spacing.SM, Spacing.SM)
        )

        self._invert_btn.pack(
            side="left",
            padx=Spacing.SM,
            pady=(Spacing.SM, Spacing.SM)
        )

        separator2.pack(side="left", padx=Spacing.XS)
        self._delete_btn.pack(
            side="left",
            padx=Spacing.MD,
            pady=(Spacing.SM, Spacing.SM)
        )

        # Spacer
        spacer = CTkLabel(self, text="")
        spacer.pack(side="right", padx=Spacing.LG)

    def _refresh_selected_label(self) -> None:
        """Refresh the selected counter label."""
        self._selected_label.configure(
            text=f"{self._selected_items} of {self._total_items} selected"
        )

    def set_total_items(self, count: int) -> None:
        """
        Set the total number of items available for selection.

        Args:
            count: Total item count.
        """
        self._total_items = count
        self._refresh_selected_label()

    def set_selected_count(self, count: int) -> None:
        """
        Set the number of currently selected items.

        Args:
            count: Number of selected items.
        """
        self._selected_items = count
        self._refresh_selected_label()

    def increment_selected(self, amount: int = 1) -> None:
        """
        Add to the selected count.

        Args:
            amount: Amount to add (default 1).
        """
        self._selected_items += amount
        self._refresh_selected_label()

    def decrement_selected(self, amount: int = 1) -> None:
        """
        Subtract from the selected count.

        Args:
            amount: Amount to subtract (default 1).
        """
        self._selected_items = max(0, self._selected_items - amount)
        self._refresh_selected_label()

    def reset_selection(self) -> None:
        """Reset selection to zero."""
        self._selected_items = 0
        self._refresh_selected_label()

    def get_selected_count(self) -> int:
        """Get the current selected count."""
        return self._selected_items

    def get_total_items(self) -> int:
        """Get the total items count."""
        return self._total_items

    def set_rule(self, rule: str) -> None:
        """
        Set the current selection rule.

        Args:
            rule: The rule identifier (from SelectionRule class).
        """
        if rule not in SelectionRule.all_rules() and rule not in [
            SelectionRule.INVERT_SELECTION,
            SelectionRule.CLEAR_SELECTION,
            SelectionRule.SELECT_ALL
        ]:
            raise ValueError(f"Invalid selection rule: {rule}")

        self._current_rule = rule
        display_name = SelectionRule.display_name(rule)

        try:
            self._rule_menu.set(display_name)
        except AttributeError:
            pass

    def get_rule(self) -> str:
        """Get the current selection rule."""
        return self._current_rule

    def on_apply_rule(self, callback: Callable[[str], None]) -> None:
        """
        Set callback for Apply button.

        Args:
            callback: Function called with (rule_id).
        """
        self._on_apply_rule = callback

    def on_select_all(self, callback: Callable[[], None]) -> None:
        """
        Set callback for Select All button.

        Args:
            callback: Function to call when Select All is clicked.
        """
        self._on_select_all = callback

    def on_deselect_all(self, callback: Callable[[], None]) -> None:
        """
        Set callback for Deselect All button.

        Args:
            callback: Function to call when Deselect All is clicked.
        """
        self._on_deselect_all = callback

    def on_invert(self, callback: Callable[[], None]) -> None:
        """
        Set callback for Invert button.

        Args:
            callback: Function to call when Invert is clicked.
        """
        self._on_invert = callback

    def on_delete_selected(self, callback: Callable[[], None]) -> None:
        """
        Set callback for Delete Selected button.

        Args:
            callback: Function to call when Delete Selected is clicked.
        """
        self._on_delete_selected = callback

    def trigger_apply_rule(self) -> None:
        """Trigger the apply rule callback."""
        if self._on_apply_rule and self._current_rule:
            self._on_apply_rule(self._current_rule)

    def trigger_select_all(self) -> None:
        """Trigger the select all callback."""
        if self._on_select_all:
            self._on_select_all()

    def trigger_deselect_all(self) -> None:
        """Trigger the deselect all callback."""
        if self._on_deselect_all:
            self._on_deselect_all()

    def trigger_invert(self) -> None:
        """Trigger the invert callback."""
        if self._on_invert:
            self._on_invert()

    def trigger_delete_selected(self) -> None:
        """Trigger the delete selected callback."""
        if self._on_delete_selected:
            self._on_delete_selected()

    def set_delete_enabled(self, enabled: bool) -> None:
        """
        Enable/disable the delete selected button.

        Args:
            enabled: Whether the button should be enabled.
        """
        try:
            state = "normal" if enabled else "disabled"
            self._delete_btn.configure(state=state)
        except AttributeError:
            pass


# Simple logger fallback
logger = __import__('logging').getLogger(__name__)
