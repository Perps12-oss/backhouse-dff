"""
Settings Dialog Widget

CTkToplevel modal with settings organized in tabs.
Supports: General, Appearance, Performance, Deletion, About.
"""

from __future__ import annotations

import tkinter as tk
from typing import Optional, Callable, Dict, Any
import json
from pathlib import Path

try:
    import customtkinter as ctk
    CTkToplevel = ctk.CTkToplevel
    CTkFrame = ctk.CTkFrame
    CTkButton = ctk.CTkButton
    CTkLabel = ctk.CTkLabel
    CTkTabview = ctk.CTkTabview
    CTkOptionMenu = ctk.CTkOptionMenu
    CTkSlider = ctk.CTkSlider
    CTkCheckBox = ctk.CTkCheckBox
    CTkEntry = ctk.CTkEntry
except ImportError:
    CTkToplevel = tk.Toplevel
    CTkFrame = tk.Frame
    CTkButton = tk.Button
    CTkLabel = tk.Label
    CTkTabview = tk.Frame  # Simple fallback
    CTkOptionMenu = tk.OptionMenu
    CTkSlider = tk.Scale
    CTkCheckBox = tk.Checkbutton
    CTkEntry = tk.Entry

from cerebro.v2.core.design_tokens import (
    Spacing, Typography, Dimensions
)
from cerebro.v2.core.theme_bridge_v2 import theme_color, subscribe_to_theme


class Settings:
    """Application settings container."""

    def __init__(self):
        self.general = {
            "default_mode": "files",
            "confirm_before_delete": True,
            "remember_folders": True,
            "last_folders": [],
            "last_protected": [],
            "show_hidden_files": False
        }
        self.appearance = {
            "theme": "dark_navy_cyan",
            "font_size": 13,
            "preview_panel_height": 200,
            "left_panel_width": 250
        }
        self.performance = {
            "max_threads": 0,
            "max_processes": 0,
            "hash_cache_enabled": True,
            "hash_cache_max_mb": 500,
            "hash_cache_prune_days": 90
        }
        self.file_mode = {
            "hash_algorithm": "sha256",
            "min_size_bytes": 0,
            "max_size_bytes": 0,
            "skip_extensions": [".sys", ".dll", ".tmp"]
        }
        self.photo_mode = {
            "phash_threshold": 8,
            "dhash_threshold": 10,
            "min_resolution": 0,
            "formats": ["jpg", "png", "gif", "bmp", "tiff", "webp", "heic", "raw"]
        }
        self.video_mode = {
            "duration_tolerance_sec": 3,
            "frame_count": 5,
            "hash_threshold": 12,
            "formats": ["mp4", "avi", "mkv", "mov", "wmv", "flv", "webm"]
        }
        self.music_mode = {
            "match_fields": ["artist", "title"],
            "similarity_threshold": 0.85,
            "duration_tolerance_sec": 2,
            "formats": ["mp3", "flac", "ogg", "wav", "aac", "m4a", "wma"]
        }
        self.deletion = {
            "method": "recycle_bin",
            "auto_mark_rule": "keep_largest"
        }
        self.window_state = {
            "width": 1280,
            "height": 800,
            "x": 100,
            "y": 100,
            "maximized": False,
            "panel_proportions": {
                "left": 0.2,
                "preview": 0.25
            }
        }

    def to_dict(self) -> Dict:
        """Convert settings to dictionary."""
        return {
            "version": 2,
            "general": self.general,
            "appearance": self.appearance,
            "performance": self.performance,
            "file_mode": self.file_mode,
            "photo_mode": self.photo_mode,
            "video_mode": self.video_mode,
            "music_mode": self.music_mode,
            "deletion": self.deletion,
            "window_state": self.window_state
        }

    def from_dict(self, data: Dict) -> None:
        """Load settings from dictionary."""
        if "general" in data:
            self.general.update(data["general"])
        if "appearance" in data:
            self.appearance.update(data["appearance"])
        if "performance" in data:
            self.performance.update(data["performance"])
        if "file_mode" in data:
            self.file_mode.update(data["file_mode"])
        if "photo_mode" in data:
            self.photo_mode.update(data["photo_mode"])
        if "video_mode" in data:
            self.video_mode.update(data["video_mode"])
        if "music_mode" in data:
            self.music_mode.update(data["music_mode"])
        if "deletion" in data:
            self.deletion.update(data["deletion"])
        if "window_state" in data:
            self.window_state.update(data["window_state"])

    def save(self, path: Path) -> None:
        """Save settings to file."""
        with open(path, 'w') as f:
            json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def load(cls, path: Path) -> "Settings":
        """Load settings from file."""
        settings = cls()
        if path.exists():
            try:
                with open(path, 'r') as f:
                    data = json.load(f)
                    settings.from_dict(data)
            except (json.JSONDecodeError, IOError):
                pass
        return settings


class SettingsDialog(CTkToplevel):
    """
    Modal settings dialog with tabbed interface.

    Features:
    - General tab: default mode, startup behavior, confirm delete
    - Appearance tab: theme, font size
    - Performance tab: max threads, hash cache settings
    - Deletion tab: deletion method, auto-mark rule
    - About tab: version, credits, links
    - Save/Cancel buttons
    """

    def __init__(self, parent, settings: Optional[Settings] = None, **kwargs):
        super().__init__(parent, **kwargs)
        subscribe_to_theme(self, self._apply_theme)

        self._settings = settings or Settings()
        self._parent = parent

        # Widgets
        self._tabview: Optional[CTkTabview] = None
        self._save_btn: Optional[CTkButton] = None
        self._cancel_btn: Optional[CTkButton] = None

        # Callbacks
        self._on_save: Optional[Callable[[Settings], None]] = None

        # Build UI
        self._setup_window()
        self._build_ui()

    def _setup_window(self) -> None:
        """Configure dialog window."""
        self.title("Settings")
        self.geometry("600x450")
        self.resizable(True, True)

        # Make modal (block parent)
        self.transient(self._parent)
        self.grab_set()

        # Center on parent
        self.update_idletasks()
        x = self._parent.winfo_x() + (self._parent.winfo_width() // 2) - 300
        y = self._parent.winfo_y() + (self._parent.winfo_height() // 2) - 225
        self.geometry(f"600x450+{x}+{y}")

    def _build_ui(self) -> None:
        """Build settings dialog UI."""
        # Main container
        main_frame = CTkFrame(self)
        main_frame.pack(fill="both", expand=True, padx=Spacing.MD, pady=Spacing.MD)

        # Tabview
        try:
            self._tabview = CTkTabview(
                main_frame,
                width=550,
                height=340
            )
            self._tabview.pack(fill="both", expand=True, pady=(0, Spacing.MD))

            # Build tabs
            self._build_general_tab()
            self._build_appearance_tab()
            self._build_performance_tab()
            self._build_deletion_tab()
            self._build_about_tab()

        except AttributeError:
            # Fallback for non-CustomTkinter
            CTkLabel(
                main_frame,
                text="Tabview not available in fallback mode",
                text_color=theme_color("feedback.warning")
            ).pack(expand=True)

        # Button frame
        button_frame = CTkFrame(main_frame)
        button_frame.pack(fill="x")

        # Save button
        self._save_btn = CTkButton(
            button_frame,
            text="Save",
            width=100,
            height=Dimensions.BUTTON_HEIGHT_MD,
            font=Typography.FONT_MD,
            fg_color=theme_color("feedback.success"),
            hover_color=theme_color("feedback.success")
        )
        self._save_btn.pack(side="right", padx=Spacing.MD, pady=(0, 0))
        self._save_btn.configure(command=self._on_save_clicked)

        # Cancel button
        self._cancel_btn = CTkButton(
            button_frame,
            text="Cancel",
            width=100,
            height=Dimensions.BUTTON_HEIGHT_MD,
            font=Typography.FONT_MD,
            fg_color=theme_color("base.backgroundTertiary"),
            hover_color=theme_color("base.backgroundElevated")
        )
        self._cancel_btn.pack(side="right", padx=Spacing.SM, pady=(0, 0))
        self._cancel_btn.configure(command=self._on_cancel_clicked)

    def _build_general_tab(self) -> None:
        """Build General settings tab."""
        tab = self._tabview.add("General")

        # Default scan mode
        CTkLabel(
            tab,
            text="Default Scan Mode",
            font=Typography.FONT_SM,
            text_color=theme_color("base.foreground"),
            anchor="w"
        ).pack(fill="x", padx=Spacing.SM, pady=(Spacing.SM, 0))

        mode_menu = CTkOptionMenu(
            tab,
            values=["Files", "Photos", "Videos", "Music", "Empty Folders", "Large Files"],
            default_value="Files",
            font=Typography.FONT_SM,
            fg_color=theme_color("base.foreground"),
            button_color=theme_color("base.backgroundElevated"),
            dropdown_fg_color=theme_color("base.foreground")
        )
        mode_menu.pack(fill="x", padx=Spacing.SM, pady=(Spacing.XS, Spacing.MD))

        # Confirm before delete
        confirm_frame = CTkFrame(tab)
        confirm_frame.pack(fill="x", padx=Spacing.SM, pady=(0, Spacing.SM))

        confirm_check = CTkCheckBox(
            confirm_frame,
            text="Confirm before deleting files",
            font=Typography.FONT_SM,
            onvalue=True,
            offvalue=False
        )
        confirm_check.pack(side="left", padx=Spacing.SM)
        if self._settings.general.get("confirm_before_delete", True):
            confirm_check.select()

        # Remember folders
        remember_check = CTkCheckBox(
            confirm_frame,
            text="Remember folder selections",
            font=Typography.FONT_SM,
            onvalue=True,
            offvalue=False
        )
        remember_check.pack(side="left", padx=Spacing.LG)
        if self._settings.general.get("remember_folders", True):
            remember_check.select()

    def _build_appearance_tab(self) -> None:
        """Build Appearance settings tab."""
        tab = self._tabview.add("Appearance")

        # Theme selection — reads from ThemeEngineV3
        CTkLabel(
            tab,
            text="Theme",
            font=Typography.FONT_SM,
            text_color=theme_color("base.foreground"),
            anchor="w"
        ).pack(fill="x", padx=Spacing.SM, pady=(Spacing.SM, 0))

        theme_names = self._get_available_themes()
        current_theme = self._get_active_theme()

        self._theme_menu = CTkOptionMenu(
            tab,
            values=theme_names if theme_names else ["default"],
            font=Typography.FONT_SM,
            fg_color=theme_color("base.backgroundSecondary"),
            button_color=theme_color("base.backgroundElevated"),
            dropdown_fg_color=theme_color("base.backgroundSecondary"),
            command=self._on_theme_changed,
        )
        if current_theme in theme_names:
            self._theme_menu.set(current_theme)
        elif theme_names:
            self._theme_menu.set(theme_names[0])
        self._theme_menu.pack(fill="x", padx=Spacing.SM, pady=(Spacing.XS, 0))

        # Edit / New Theme buttons
        btn_row = CTkFrame(tab, fg_color="transparent")
        btn_row.pack(fill="x", padx=Spacing.SM, pady=(Spacing.XS, Spacing.MD))

        CTkButton(
            btn_row, text="✏ Edit Theme", width=120, height=28,
            font=Typography.FONT_SM,
            fg_color=theme_color("button.secondary"),
            hover_color=theme_color("button.secondaryHover"),
            corner_radius=Spacing.BORDER_RADIUS_SM,
            command=self._open_theme_editor_current,
        ).pack(side="left", padx=(0, Spacing.SM))

        CTkButton(
            btn_row, text="+ New Theme", width=120, height=28,
            font=Typography.FONT_SM,
            fg_color=theme_color("button.secondary"),
            hover_color=theme_color("button.secondaryHover"),
            corner_radius=Spacing.BORDER_RADIUS_SM,
            command=self._open_theme_editor_new,
        ).pack(side="left")

        # Font size
        CTkLabel(
            tab,
            text="Font Size",
            font=Typography.FONT_SM,
            text_color=theme_color("base.foreground"),
            anchor="w"
        ).pack(fill="x", padx=Spacing.SM, pady=(0, Spacing.SM))

        font_size_slider = CTkSlider(
            tab,
            from_=10,
            to=18,
            number_of_steps=8,
            font=Typography.FONT_SM
        )
        font_size_slider.set(self._settings.appearance.get("font_size", 13))
        font_size_slider.pack(fill="x", padx=Spacing.SM, pady=(Spacing.XS, Spacing.MD))

    # ------------------------------------------------------------------
    # Theme helpers
    # ------------------------------------------------------------------

    def _get_available_themes(self):
        """Return sorted list of theme names from ThemeEngineV3."""
        try:
            from cerebro.core.theme_engine_v3 import ThemeEngineV3
            return sorted(ThemeEngineV3.get().all_theme_names())
        except Exception:
            return ["dark", "light"]

    def _get_active_theme(self) -> str:
        """Return the currently active theme name."""
        try:
            from cerebro.core.theme_engine_v3 import ThemeEngineV3
            return ThemeEngineV3.get().active_theme_name
        except Exception:
            return ""

    def _on_theme_changed(self, theme_name: str) -> None:
        """Apply theme immediately when selected from the dropdown."""
        try:
            from cerebro.core.theme_engine_v3 import ThemeEngineV3
            ThemeEngineV3.get().set_theme(theme_name)
            from cerebro.v2.core.theme_bridge_v2 import set_ctk_appearance_mode
            set_ctk_appearance_mode()
            # Persist selection
            self._settings.appearance["theme"] = theme_name
        except Exception:
            pass

    def _open_theme_editor_current(self) -> None:
        """Open theme editor pre-loaded with the currently selected theme."""
        from cerebro.v2.ui.theme_editor_dialog import ThemeEditorDialog
        current = self._get_active_theme()
        ThemeEditorDialog.show(parent=self, base_theme_name=current or None)

    def _open_theme_editor_new(self) -> None:
        """Open theme editor starting from a blank slate."""
        from cerebro.v2.ui.theme_editor_dialog import ThemeEditorDialog
        ThemeEditorDialog.show(parent=self)

    def _build_performance_tab(self) -> None:
        """Build Performance settings tab."""
        tab = self._tabview.add("Performance")

        # Max threads
        CTkLabel(
            tab,
            text="Max Threads (0 = auto)",
            font=Typography.FONT_SM,
            text_color=theme_color("base.foreground"),
            anchor="w"
        ).pack(fill="x", padx=Spacing.SM, pady=(Spacing.SM, 0))

        threads_slider = CTkSlider(
            tab,
            from_=0,
            to=16,
            number_of_steps=16,
            font=Typography.FONT_SM
        )
        threads_slider.set(self._settings.performance.get("max_threads", 0))
        threads_slider.pack(fill="x", padx=Spacing.SM, pady=(Spacing.XS, Spacing.MD))

        # Hash cache enabled
        cache_frame = CTkFrame(tab)
        cache_frame.pack(fill="x", padx=Spacing.SM, pady=(0, Spacing.SM))

        cache_check = CTkCheckBox(
            cache_frame,
            text="Enable hash cache (faster re-scans)",
            font=Typography.FONT_SM,
            onvalue=True,
            offvalue=False
        )
        cache_check.pack(side="left", padx=Spacing.SM)
        if self._settings.performance.get("hash_cache_enabled", True):
            cache_check.select()

        # Cache size
        size_label = CTkLabel(
            cache_frame,
            text="Cache Size (MB):",
            font=Typography.FONT_SM,
            text_color=theme_color("base.foreground")
        )
        size_label.pack(side="left", padx=Spacing.LG)

        CTkLabel(
            cache_frame,
            text=str(self._settings.performance.get("hash_cache_max_mb", 500)),
            font=Typography.FONT_SM,
            text_color=theme_color("base.foregroundSecondary")
        ).pack(side="left", padx=Spacing.XS)

    def _build_deletion_tab(self) -> None:
        """Build Deletion settings tab."""
        tab = self._tabview.add("Deletion")

        # Deletion method
        CTkLabel(
            tab,
            text="Deletion Method",
            font=Typography.FONT_SM,
            text_color=theme_color("base.foreground"),
            anchor="w"
        ).pack(fill="x", padx=Spacing.SM, pady=(Spacing.SM, 0))

        method_menu = CTkOptionMenu(
            tab,
            values=["Recycle Bin", "Delete Permanently", "Move to Folder"],
            default_value="Recycle Bin",
            font=Typography.FONT_SM,
            fg_color=theme_color("base.foreground"),
            button_color=theme_color("base.backgroundElevated"),
            dropdown_fg_color=theme_color("base.foreground")
        )
        method_menu.pack(fill="x", padx=Spacing.SM, pady=(Spacing.XS, Spacing.MD))

        # Auto-mark rule
        CTkLabel(
            tab,
            text="Auto-Mark Rule",
            font=Typography.FONT_SM,
            text_color=theme_color("base.foreground"),
            anchor="w"
        ).pack(fill="x", padx=Spacing.SM, pady=(0, Spacing.SM))

        rule_menu = CTkOptionMenu(
            tab,
            values=["Keep Largest", "Keep Smallest", "Keep Newest", "Keep Oldest", "Keep First"],
            default_value="Keep Largest",
            font=Typography.FONT_SM,
            fg_color=theme_color("base.foreground"),
            button_color=theme_color("base.backgroundElevated"),
            dropdown_fg_color=theme_color("base.foreground")
        )
        rule_menu.pack(fill="x", padx=Spacing.SM, pady=(Spacing.XS, Spacing.MD))

        # Warning notice
        CTkLabel(
            tab,
            text="⚠ Deletion always uses Recycle Bin when available.\n"
                "Files in protected folders are never auto-marked for deletion.",
            font=Typography.FONT_XS,
            text_color=theme_color("feedback.warning"),
            wraplength=500
        ).pack(fill="x", padx=Spacing.SM, pady=Spacing.MD)

    def _build_about_tab(self) -> None:
        """Build About tab with version info and credits."""
        tab = self._tabview.add("About")

        # App info
        CTkLabel(
            tab,
            text="Cerebro v2",
            font=Typography.FONT_XL,
            text_color=theme_color("base.accent")
        ).pack(pady=Spacing.LG)

        CTkLabel(
            tab,
            text="Ashisoft Edition",
            font=Typography.FONT_SM,
            text_color=theme_color("base.foregroundSecondary")
        ).pack()

        # Version
        CTkLabel(
            tab,
            text="Version: 2.0.0",
            font=Typography.FONT_SM,
            text_color=theme_color("base.foregroundSecondary")
        ).pack(pady=(Spacing.MD, 0))

        # Description
        CTkLabel(
            tab,
            text="Duplicate file finder with pluggable scan engines.\n"
                "Supports files, images, videos, music, empty folders,\n"
                "and large files detection.",
            font=Typography.FONT_SM,
            text_color=theme_color("base.foregroundSecondary"),
            justify="center"
        ).pack(pady=Spacing.MD)

        # Repository link
        CTkLabel(
            tab,
            text="Repository: github.com/Perps12-oss/dedup",
            font=Typography.FONT_SM,
            text_color=theme_color("base.accent")
        ).pack(pady=Spacing.MD)

        # Credits
        CTkLabel(
            tab,
            text="Built with CustomTkinter + ttk",
            font=Typography.FONT_XS,
            text_color=theme_color("base.foregroundMuted")
        ).pack(pady=Spacing.LG)

    # ===================
    # THEME
    # ===================

    def _apply_theme(self) -> None:
        """Re-apply theme colors to tracked widgets (Save/Cancel buttons)."""
        if self._save_btn:
            self._save_btn.configure(
                fg_color=theme_color("feedback.success"),
                hover_color=theme_color("feedback.success"),
            )
        if self._cancel_btn:
            self._cancel_btn.configure(
                fg_color=theme_color("base.backgroundTertiary"),
                hover_color=theme_color("base.backgroundElevated"),
            )

    # ===================
    # EVENT HANDLERS
    # ===================

    def _on_save_clicked(self) -> None:
        """Handle Save button click."""
        # TODO: Collect values from all widgets and update settings
        print("Settings saved")

        # Notify callback
        if self._on_save:
            self._on_save(self._settings)

        self.destroy()

    def _on_cancel_clicked(self) -> None:
        """Handle Cancel button click."""
        self.destroy()

    # ===================
    # PUBLIC API
    # ===================

    def on_save(self, callback: Callable[[Settings], None]) -> None:
        """Set callback for save action."""
        self._on_save = callback

    def show(self) -> None:
        """Show the dialog (modal)."""
        self.deiconify()
        self.focus_set()
        self.wait_window()

    @staticmethod
    def show_dialog(parent, settings: Optional[Settings] = None) -> Optional[Settings]:
        """
        Show settings dialog and return updated settings.

        Args:
            parent: Parent window.
            settings: Initial settings to display.

        Returns:
            Updated settings if saved, None if cancelled.
        """
        dialog = SettingsDialog(parent, settings)

        result = [None]

        def on_save(settings: Settings) -> None:
            result[0] = settings

        dialog.on_save(on_save)
        dialog.show()

        return result[0]


# Simple logger fallback
logger = __import__('logging').getLogger(__name__)
