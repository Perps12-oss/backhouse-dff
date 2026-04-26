"""Settings page — general, appearance, performance, deletion & about tabs (glass morphism)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict

import flet as ft

from cerebro.v2.ui.flet_app.palette_themes import PRESET_THEMES
from cerebro.v2.ui.flet_app.theme import theme_for_mode

if TYPE_CHECKING:
    from cerebro.v2.ui.flet_app.services.state_bridge import StateBridge

_log = logging.getLogger(__name__)

# Deletion method options
_DELETE_METHODS = [
    ("recycle_bin", "Recycle Bin"),
    ("permanent", "Delete Permanently"),
    ("move_to_folder", "Move to Folder"),
]

# Auto‑mark rules
_AUTO_MARK_RULES = [
    ("keep_largest", "Keep Largest"),
    ("keep_smallest", "Keep Smallest"),
    ("keep_newest", "Keep Newest"),
    ("keep_oldest", "Keep Oldest"),
    ("keep_first", "Keep First"),
]

# Scan mode options (matching old dialog)
_SCAN_MODES = [
    ("files", "Files"),
    ("photos", "Photos"),
    ("videos", "Videos"),
    ("music", "Music"),
    ("empty_folders", "Empty Folders"),
    ("large_files", "Large Files"),
]


class SettingsPage(ft.Column):
    """Application settings with tabbed interface."""

    def __init__(self, bridge: "StateBridge"):
        super().__init__(expand=True, scroll=ft.ScrollMode.AUTO)
        self._bridge = bridge
        self._t = theme_for_mode("dark")
        self._settings: Dict[str, Any] = {}  # loaded from bridge
        self._glass_cache: dict = {}
        
        # UI References
        self._header: ft.Container
        self._tabs: ft.SegmentedButton
        self._tab_keys: tuple[str, ...]
        self._tab_contents: Dict[str, ft.Container]
        self._save_btn: ft.ElevatedButton
        self._cancel_btn: ft.OutlinedButton
        
        # Control References (General)
        self._general_mode: ft.Dropdown
        self._general_confirm: ft.Checkbox
        self._general_remember: ft.Checkbox
        self._general_collapse: ft.Checkbox
        self._general_hidden: ft.Checkbox
        self._general_reduce_motion: ft.Checkbox
        self._general_sound: ft.Checkbox

        # Control References (Appearance)
        self._appearance_font_slider: ft.Slider
        self._appearance_font_label: ft.Text

        # Control References (Performance)
        self._perf_threads_slider: ft.Slider
        self._perf_threads_label: ft.Text
        self._perf_cache_enabled: ft.Checkbox
        self._perf_cache_slider: ft.Slider
        self._perf_cache_size_label: ft.Text
        self._clear_cache_btn: ft.OutlinedButton
        self._cache_status: ft.Text

        # Control References (Deletion)
        self._deletion_method: ft.Dropdown
        self._deletion_rule: ft.Dropdown
        self._deletion_phash_slider: ft.Slider
        self._deletion_phash_label: ft.Text
        self._deletion_dhash_slider: ft.Slider
        self._deletion_dhash_label: ft.Text

        self._theme_chips: Dict[str, ft.Container] = {}

        self._build_ui()

    def _is_mounted(self) -> bool:
        try:
            return self.page is not None
        except RuntimeError:
            return False

    # ------------------------------------------------------------------
    # Glass helper
    # ------------------------------------------------------------------
    def _get_glass_style(self, opacity: float = 0.06) -> dict:
        is_light = "light" in self._bridge.app_theme.lower() if hasattr(self._bridge, 'app_theme') else False
        cache_key = (opacity, is_light)
        if cache_key in self._glass_cache:
            return self._glass_cache[cache_key]
        bg_base = ft.Colors.BLACK if is_light else ft.Colors.WHITE
        border_base = ft.Colors.BLACK if is_light else ft.Colors.WHITE
        bg = ft.Colors.with_opacity(opacity, bg_base)
        border_color = ft.Colors.with_opacity(0.12, border_base)
        result = dict(
            bgcolor=bg,
            border=ft.border.all(1, border_color),
            border_radius=ft.border_radius.all(12),
        )
        self._glass_cache[cache_key] = result
        return result

    # ------------------------------------------------------------------
    # Build (Runs Once)
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        t = self._t
        self._load_settings()

        # Header
        self._header = ft.Container(
            content=ft.Text("Settings", size=t.typography.size_xl, weight=ft.FontWeight.BOLD, color=t.colors.fg),
            padding=ft.padding.only(left=t.spacing.xl, top=t.spacing.xl, bottom=t.spacing.md),
        )

        # Section switcher (replaces legacy Tabs(tabs=...) — Flet 0.25+ Tabs use content+length+TabBar/TabBarView)
        self._tab_keys = ("general", "appearance", "performance", "deletion", "about")
        self._tabs = ft.SegmentedButton(
            segments=[
                ft.Segment(value="general", label="General"),
                ft.Segment(value="appearance", label="Appearance"),
                ft.Segment(value="performance", label="Performance"),
                ft.Segment(value="deletion", label="Deletion"),
                ft.Segment(value="about", label="About"),
            ],
            selected=["general"],
            show_selected_icon=False,
            on_change=self._on_tab_changed,
        )

        # Tab content containers (glass)
        self._tab_contents = {
            "general": ft.Container(padding=t.spacing.xl, **self._get_glass_style(0.04)),
            "appearance": ft.Container(padding=t.spacing.xl, **self._get_glass_style(0.04)),
            "performance": ft.Container(padding=t.spacing.xl, **self._get_glass_style(0.04)),
            "deletion": ft.Container(padding=t.spacing.xl, **self._get_glass_style(0.04)),
            "about": ft.Container(padding=t.spacing.xl, **self._get_glass_style(0.04)),
        }

        # Build each tab's inner content
        self._build_general_tab()
        self._build_appearance_tab()
        self._build_performance_tab()
        self._build_deletion_tab()
        self._build_about_tab()

        # Save / Cancel buttons (glass row)
        self._save_btn = ft.ElevatedButton(
            "Save Settings",
            icon=ft.icons.Icons.SAVE,
            on_click=self._on_save,
            style=ft.ButtonStyle(
                bgcolor=ft.Colors.with_opacity(0.15, t.colors.primary),
                color=t.colors.fg,
                shape=ft.RoundedRectangleBorder(radius=8),
            ),
        )
        self._cancel_btn = ft.OutlinedButton(
            "Cancel",
            icon=ft.icons.Icons.CANCEL,
            on_click=self._on_cancel,
            style=ft.ButtonStyle(color=t.colors.fg2),
        )
        self._button_row = ft.Row(
            [self._save_btn, self._cancel_btn],
            alignment=ft.MainAxisAlignment.END,
            spacing=t.spacing.md,
        )

        # Assemble layout
        self.controls = [
            self._header,
            ft.Container(content=self._tabs, padding=ft.padding.symmetric(horizontal=t.spacing.xl)),
            ft.Container(
                content=ft.Column([
                    self._tab_contents["general"],
                    self._tab_contents["appearance"],
                    self._tab_contents["performance"],
                    self._tab_contents["deletion"],
                    self._tab_contents["about"],
                ]),
                padding=ft.padding.symmetric(horizontal=t.spacing.xl, vertical=t.spacing.md),
            ),
            ft.Container(content=self._button_row, padding=ft.padding.only(right=t.spacing.xl, bottom=t.spacing.xl)),
        ]
        self._switch_tab(0)

    # ------------------------------------------------------------------
    # Data loading / saving
    # ------------------------------------------------------------------
    def _load_settings(self) -> None:
        """Retrieve current settings from the bridge."""
        try:
            self._settings = self._bridge.get_settings()  # assume returns dict
        except Exception:
            self._settings = {}
        # Ensure default sections exist
        self._settings.setdefault("general", {})
        self._settings.setdefault("appearance", {})
        self._settings.setdefault("performance", {})
        self._settings.setdefault("deletion", {})
        self._settings.setdefault("photo_mode", {})
        self._settings.setdefault("file_mode", {})
        self._settings.setdefault("accessibility", {})
        self._settings.setdefault("notifications", {})
        self._settings["appearance"].setdefault("ui_theme_preset", "arctic")

    def _apply_saved_values_to_controls(self) -> None:
        """Push current settings values into the UI controls."""
        # General
        self._general_mode.value = self._settings["general"].get("default_mode", "files")
        self._general_confirm.value = self._settings["general"].get("confirm_before_delete", True)
        self._general_remember.value = self._settings["general"].get("remember_folders", True)
        self._general_collapse.value = self._settings["general"].get("auto_collapse", True)
        self._general_hidden.value = self._settings["general"].get("show_hidden_files", False)
        self._general_reduce_motion.value = self._settings["accessibility"].get("reduce_motion", False)
        self._general_sound.value = self._settings["notifications"].get("sound_enabled", False)

        # Appearance
        self._appearance_font_slider.value = self._settings["appearance"].get("font_size", 13)
        self._appearance_font_label.value = f"Font size: {int(self._appearance_font_slider.value)}"

        # Performance
        self._perf_threads_slider.value = self._settings["performance"].get("max_threads", 0)
        self._perf_cache_enabled.value = self._settings["performance"].get("hash_cache_enabled", True)
        self._perf_cache_slider.value = self._settings["performance"].get("hash_cache_max_mb", 500)
        self._perf_cache_size_label.value = f"Cache size: {int(self._perf_cache_slider.value)} MB"

        # Deletion
        method = self._settings["deletion"].get("method", "recycle_bin")
        self._deletion_method.value = method if method in dict(_DELETE_METHODS) else "recycle_bin"
        rule = self._settings["deletion"].get("auto_mark_rule", "keep_largest")
        self._deletion_rule.value = rule if rule in dict(_AUTO_MARK_RULES) else "keep_largest"
        self._deletion_phash_slider.value = self._settings["photo_mode"].get("phash_threshold", 8)
        self._deletion_dhash_slider.value = self._settings["photo_mode"].get("dhash_threshold", 10)
        self._deletion_phash_label.value = f"pHash threshold: {int(self._deletion_phash_slider.value)}"
        self._deletion_dhash_label.value = f"dHash threshold: {int(self._deletion_dhash_slider.value)}"

        preset_id = str(self._settings["appearance"].get("ui_theme_preset", "arctic"))
        self._bridge.apply_preset_theme(preset_id)

    # ------------------------------------------------------------------
    # Tab builders
    # ------------------------------------------------------------------
    def _build_general_tab(self) -> None:
        t = self._t
        content = ft.Column(spacing=t.spacing.md)

        # Default scan mode
        content.controls.append(ft.Text("Default Scan Mode", weight=ft.FontWeight.W_600, color=t.colors.fg))
        content.controls.append(ft.Text("Which engine runs when you click Start Scan.", size=t.typography.size_xs, color=t.colors.fg_muted, italic=True))
        self._general_mode = ft.Dropdown(
            options=[ft.dropdown.Option(key=val, text=label) for val, label in _SCAN_MODES],
            value=self._settings["general"].get("default_mode", "files"),
            width=200,
            border_radius=8,
            bgcolor=ft.Colors.with_opacity(0.08, t.colors.primary),
        )
        content.controls.append(self._general_mode)

        # Checkboxes
        self._general_confirm = ft.Checkbox(
            label="Confirm before deleting files",
            value=self._settings["general"].get("confirm_before_delete", True),
        )
        self._general_remember = ft.Checkbox(
            label="Remember folder selections",
            value=self._settings["general"].get("remember_folders", True),
        )
        self._general_collapse = ft.Checkbox(
            label="Auto-collapse folder panel while scanning",
            value=self._settings["general"].get("auto_collapse", True),
        )
        self._general_hidden = ft.Checkbox(
            label="Show hidden files",
            value=self._settings["general"].get("show_hidden_files", False),
        )
        self._general_reduce_motion = ft.Checkbox(
            label="Reduce motion (minimize animations)",
            value=self._settings["accessibility"].get("reduce_motion", False),
        )
        self._general_sound = ft.Checkbox(
            label="Enable sound effects",
            value=self._settings["notifications"].get("sound_enabled", False),
        )
        for cb in [
            self._general_confirm,
            self._general_remember,
            self._general_collapse,
            self._general_hidden,
            self._general_reduce_motion,
            self._general_sound,
        ]:
            content.controls.append(cb)

        self._tab_contents["general"].content = content

    def _build_appearance_tab(self) -> None:
        t = self._t
        content = ft.Column(spacing=t.spacing.md)

        # Font size slider
        content.controls.append(ft.Text("Font Size", weight=ft.FontWeight.W_600, color=t.colors.fg))
        self._appearance_font_slider = ft.Slider(
            min=10,
            max=18,
            divisions=8,
            value=self._settings["appearance"].get("font_size", 13),
            on_change=lambda e: setattr(self._appearance_font_label, 'value', f"Font size: {int(e.control.value)}"),
        )
        self._appearance_font_label = ft.Text(f"Font size: {int(self._appearance_font_slider.value)}", color=t.colors.fg2)
        content.controls.append(self._appearance_font_label)
        content.controls.append(self._appearance_font_slider)

        content.controls.append(
            ft.Text(
                "Color theme",
                weight=ft.FontWeight.W_600,
                color=t.colors.fg,
            )
        )
        self._theme_chips.clear()
        selected_pid = str(self._settings["appearance"].get("ui_theme_preset", "arctic"))
        chips_wrap = ft.Row(wrap=True, spacing=t.spacing.sm, run_spacing=t.spacing.sm)
        for preset in PRESET_THEMES:
            is_sel = preset.id == selected_pid
            chip = ft.Container(
                width=112,
                padding=8,
                border=ft.border.all(
                    2 if is_sel else 1,
                    t.colors.primary if is_sel else t.colors.border,
                ),
                border_radius=10,
                ink=True,
                on_click=lambda e, pid=preset.id: self._on_preset_selected(pid),
                content=ft.Column(
                    [
                        ft.Container(height=28, border_radius=6, bgcolor=preset.seed),
                        ft.Text(
                            preset.name,
                            size=10,
                            color=t.colors.fg,
                            text_align=ft.TextAlign.CENTER,
                            max_lines=2,
                        ),
                    ],
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=6,
                ),
            )
            self._theme_chips[preset.id] = chip
            chips_wrap.controls.append(chip)
        content.controls.append(chips_wrap)

        self._tab_contents["appearance"].content = content

    def _build_performance_tab(self) -> None:
        t = self._t
        content = ft.Column(spacing=t.spacing.md)

        # Max threads
        content.controls.append(ft.Text("Max Threads (0 = auto)", weight=ft.FontWeight.W_600, color=t.colors.fg))
        self._perf_threads_slider = ft.Slider(
            min=0, max=16, divisions=16,
            value=self._settings["performance"].get("max_threads", 0),
            on_change=lambda e: setattr(self._perf_threads_label, 'value', f"Threads: {int(e.control.value)}"),
        )
        self._perf_threads_label = ft.Text(f"Threads: {int(self._perf_threads_slider.value)}", color=t.colors.fg2)
        content.controls.append(self._perf_threads_label)
        content.controls.append(self._perf_threads_slider)

        # Hash cache
        content.controls.append(ft.Text("Hash Cache", weight=ft.FontWeight.W_600, color=t.colors.fg))
        self._perf_cache_enabled = ft.Checkbox(
            label="Enable hash cache (faster re-scans)",
            value=self._settings["performance"].get("hash_cache_enabled", True),
        )
        content.controls.append(self._perf_cache_enabled)

        self._perf_cache_slider = ft.Slider(
            min=50, max=5000, divisions=99,
            value=self._settings["performance"].get("hash_cache_max_mb", 500),
            on_change=lambda e: setattr(self._perf_cache_size_label, 'value', f"Cache size: {int(e.control.value)} MB"),
        )
        self._perf_cache_size_label = ft.Text(f"Cache size: {int(self._perf_cache_slider.value)} MB", color=t.colors.fg2)
        content.controls.append(self._perf_cache_size_label)
        content.controls.append(self._perf_cache_slider)

        # Clear cache button + status
        self._clear_cache_btn = ft.OutlinedButton(
            "Clear Cache",
            icon=ft.icons.Icons.DELETE_SWEEP,
            on_click=self._on_clear_cache,
            style=ft.ButtonStyle(color=t.colors.danger),
        )
        self._cache_status = ft.Text("", color=t.colors.success, size=t.typography.size_sm)
        content.controls.append(ft.Row([self._clear_cache_btn, self._cache_status], spacing=t.spacing.md))

        self._tab_contents["performance"].content = content

    def _build_deletion_tab(self) -> None:
        t = self._t
        content = ft.Column(spacing=t.spacing.md)

        # Deletion method
        content.controls.append(ft.Text("Deletion Method", weight=ft.FontWeight.W_600, color=t.colors.fg))
        self._deletion_method = ft.Dropdown(
            options=[ft.dropdown.Option(key=val, text=label) for val, label in _DELETE_METHODS],
            value="recycle_bin",
            width=200,
            border_radius=8,
            bgcolor=ft.Colors.with_opacity(0.08, t.colors.primary),
        )
        content.controls.append(self._deletion_method)

        # Auto-mark rule
        content.controls.append(ft.Text("Auto-Mark Rule", weight=ft.FontWeight.W_600, color=t.colors.fg))
        self._deletion_rule = ft.Dropdown(
            options=[ft.dropdown.Option(key=val, text=label) for val, label in _AUTO_MARK_RULES],
            value="keep_largest",
            width=200,
            border_radius=8,
            bgcolor=ft.Colors.with_opacity(0.08, t.colors.primary),
        )
        content.controls.append(self._deletion_rule)

        # Photo thresholds
        content.controls.append(ft.Text("Photo Thresholds (bits)", weight=ft.FontWeight.W_600, color=t.colors.fg))
        self._deletion_phash_slider = ft.Slider(
            min=0, max=64, divisions=64,
            value=self._settings["photo_mode"].get("phash_threshold", 8),
            on_change=lambda e: setattr(self._deletion_phash_label, 'value', f"pHash threshold: {int(e.control.value)}"),
        )
        self._deletion_phash_label = ft.Text(f"pHash threshold: {int(self._deletion_phash_slider.value)}", color=t.colors.fg2)
        content.controls.append(self._deletion_phash_label)
        content.controls.append(self._deletion_phash_slider)

        self._deletion_dhash_slider = ft.Slider(
            min=0, max=64, divisions=64,
            value=self._settings["photo_mode"].get("dhash_threshold", 10),
            on_change=lambda e: setattr(self._deletion_dhash_label, 'value', f"dHash threshold: {int(e.control.value)}"),
        )
        self._deletion_dhash_label = ft.Text(f"dHash threshold: {int(self._deletion_dhash_slider.value)}", color=t.colors.fg2)
        content.controls.append(self._deletion_dhash_label)
        content.controls.append(self._deletion_dhash_slider)

        # Warning notice
        content.controls.append(
            ft.Text(
                "⚠ Deletion always uses Recycle Bin when available.\n"
                "Files in protected folders are never auto-marked for deletion.",
                size=t.typography.size_sm,
                color=t.colors.warning,
                italic=True,
            )
        )

        self._tab_contents["deletion"].content = content

    def _build_about_tab(self) -> None:
        t = self._t
        content = ft.Column(
            [
                ft.Container(
                    content=ft.Icon(ft.icons.Icons.AUTO_AWESOME, size=36, color="#22D3EE"),
                    bgcolor=ft.Colors.with_opacity(0.08, "#22D3EE"),
                    border_radius=14,
                    padding=16,
                ),
                ft.Text("Cerebro", size=t.typography.size_xxxl, weight=ft.FontWeight.BOLD, color=t.colors.fg),
                ft.Row(
                    [
                        ft.Container(
                            content=ft.Text("v2.0.0", size=9, color="#22D3EE", weight=ft.FontWeight.W_600),
                            bgcolor=ft.Colors.with_opacity(0.12, "#22D3EE"),
                            border_radius=4,
                            padding=ft.padding.symmetric(horizontal=8, vertical=3),
                        ),
                        ft.Container(
                            content=ft.Text("Flet + Flutter", size=9, color="#A78BFA", weight=ft.FontWeight.W_600),
                            bgcolor=ft.Colors.with_opacity(0.12, "#A78BFA"),
                            border_radius=4,
                            padding=ft.padding.symmetric(horizontal=8, vertical=3),
                        ),
                    ],
                    alignment=ft.MainAxisAlignment.CENTER,
                    spacing=t.spacing.sm,
                ),
                ft.Text(
                    "Find and remove duplicate files to reclaim disk space.\n"
                    "Supports files, images, videos, music, empty folders and large files.",
                    color=t.colors.fg2,
                    text_align=ft.TextAlign.CENTER,
                    size=t.typography.size_base,
                ),
                ft.Divider(color=ft.Colors.with_opacity(0.1, ft.Colors.WHITE), height=1),
                ft.Text("Thanks for using Cerebro. ✨", color=t.colors.fg_muted, size=t.typography.size_sm, italic=True),
            ],
            alignment=ft.MainAxisAlignment.CENTER,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=t.spacing.md,
        )
        self._tab_contents["about"].content = content

    # ------------------------------------------------------------------
    # Theme picker
    # ------------------------------------------------------------------
    def _on_preset_selected(self, preset_id: str) -> None:
        self._bridge.apply_preset_theme(preset_id)
        self._settings.setdefault("appearance", {})["ui_theme_preset"] = preset_id
        self._update_theme_chip_highlights(preset_id)

    def _update_theme_chip_highlights(self, selected_id: str) -> None:
        t = self._t
        for pid, chip in self._theme_chips.items():
            sel = pid == selected_id
            chip.border = ft.border.all(
                2 if sel else 1,
                t.colors.primary if sel else t.colors.border,
            )
        if self._is_mounted():
            for chip in self._theme_chips.values():
                chip.update()

    # ------------------------------------------------------------------
    # Tab switching
    # ------------------------------------------------------------------
    def _on_tab_changed(self, e: ft.ControlEvent) -> None:
        data = getattr(e, "data", None)
        if isinstance(data, list) and data:
            key = str(data[0])
        else:
            sel = getattr(e.control, "selected", None) or ["general"]
            key = str(sel[0]) if sel else "general"
        if key not in self._tab_keys:
            key = "general"
        self._switch_tab(self._tab_keys.index(key))

    def _switch_tab(self, idx: int) -> None:
        for i, key in enumerate(self._tab_keys):
            self._tab_contents[key].visible = i == idx
        if self._is_mounted():
            self.update()

    # ------------------------------------------------------------------
    # Save / Cancel
    # ------------------------------------------------------------------
    def _on_save(self, e):
        # Gather values from controls
        self._settings["general"]["default_mode"] = self._general_mode.value
        self._settings["general"]["confirm_before_delete"] = self._general_confirm.value
        self._settings["general"]["remember_folders"] = self._general_remember.value
        self._settings["general"]["auto_collapse"] = self._general_collapse.value
        self._settings["general"]["show_hidden_files"] = self._general_hidden.value
        self._settings["accessibility"]["reduce_motion"] = bool(self._general_reduce_motion.value)
        self._settings["notifications"]["sound_enabled"] = bool(self._general_sound.value)

        self._settings["appearance"]["font_size"] = int(self._appearance_font_slider.value)
        self._settings["appearance"]["ui_theme_preset"] = str(
            self._settings["appearance"].get("ui_theme_preset", "arctic")
        )

        self._settings["performance"]["max_threads"] = int(self._perf_threads_slider.value)
        self._settings["performance"]["hash_cache_enabled"] = self._perf_cache_enabled.value
        self._settings["performance"]["hash_cache_max_mb"] = int(self._perf_cache_slider.value)

        self._settings["deletion"]["method"] = self._deletion_method.value
        self._settings["deletion"]["auto_mark_rule"] = self._deletion_rule.value
        self._settings["photo_mode"]["phash_threshold"] = int(self._deletion_phash_slider.value)
        self._settings["photo_mode"]["dhash_threshold"] = int(self._deletion_dhash_slider.value)

        try:
            self._bridge.save_settings(self._settings)
        except Exception as exc:
            # Show error feedback
            self._bridge.show_snackbar(f"Save failed: {exc}", error=True)
            return
        self._bridge.show_snackbar("Settings saved successfully.", success=True)

    def _on_cancel(self, e):
        # Reload original settings to discard changes
        self._load_settings()
        self._apply_saved_values_to_controls()
        self.update()
        self._bridge.show_snackbar("Changes discarded.", info=True)

    # ------------------------------------------------------------------
    # Clear cache
    # ------------------------------------------------------------------
    def _on_clear_cache(self, e):
        # Use bridge to get cache path to ensure we hit the right directory
        try:
            cache_path = self._bridge.get_cache_path()
            if not cache_path:
                raise ValueError("Cache path not returned by bridge")
            cache_path = Path(cache_path)
        except Exception:
            # Fallback if bridge method missing or fails
            cache_path = Path.home() / ".cerebro" / "cache"

        cleared = False
        # Try to delete specific DB files or the whole cache dir
        targets = [
            cache_path / "hash_cache.sqlite",
            cache_path / "hash_cache.db",
        ]
        
        # If individual files not found, try clearing the directory (carefully)
        if not any(p.exists() for p in targets):
             targets.append(cache_path)

        for p in targets:
            if p.exists():
                try:
                    if p.is_dir():
                        import shutil
                        shutil.rmtree(p)
                    else:
                        p.unlink()
                    cleared = True
                except OSError:
                    pass # Permission denied or file in use
                    
        self._cache_status.value = "Cache cleared." if cleared else "Cache already empty or inaccessible."
        self._cache_status.update()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def on_show(self) -> None:
        """Refresh values from bridge when page becomes visible."""
        self._load_settings()
        self._apply_saved_values_to_controls()
        if self._is_mounted():
            self.update()

    def apply_theme(self, mode: str) -> None:
        """Updates theme properties without destroying UI controls or losing pending input state."""
        self._glass_cache = {}
        self._t = theme_for_mode(mode)
        
        # Update Header
        self._header.content.color = self._t.colors.fg
        
        # Update all Tab Containers (Glass styles)
        new_glass = self._get_glass_style(0.04)
        for container in self._tab_contents.values():
            container.bgcolor = new_glass['bgcolor']
            container.border = new_glass['border']
            
        # Helper to update text colors in specific controls
        # Note: This is a broad update. For perfection, we'd update every Text control individually.
        # However, since we don't have refs to labels inside build_general_tab etc, we rely on Flet's 
        # somewhat automatic color inheritance or we update the container backgrounds which creates the contrast.
        
        # To ensure Sliders/Dropdowns update:
        # Dropdowns are tricky to update dynamically without rebuilding options, 
        # but the background color is set at init. We try to update it.
        dropdown_bg = ft.Colors.with_opacity(0.08, self._t.colors.primary)
        for dd in [self._general_mode, self._deletion_method, self._deletion_rule]:
            if dd: dd.bgcolor = dropdown_bg

        # Buttons
        self._save_btn.style = ft.ButtonStyle(
            bgcolor=ft.Colors.with_opacity(0.15, self._t.colors.primary),
            color=self._t.colors.fg,
            shape=ft.RoundedRectangleBorder(radius=8),
        )
        self._cancel_btn.style = ft.ButtonStyle(color=self._t.colors.fg2)

        pid = str(self._settings.get("appearance", {}).get("ui_theme_preset", "arctic"))
        self._update_theme_chip_highlights(pid)

        if self._is_mounted():
            self.update()