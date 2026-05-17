"""Dashboard page — home/landing page with quick-start scan controls, stats, and recent activity."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import re
from pathlib import Path
from typing import TYPE_CHECKING, Optional

import flet as ft

from cerebro.v2.ui.flet_app.pill_button_styles import (
    pill_filled_accent,
    pill_outlined_button_style,
    pill_text_button_style,
)
from cerebro.v2.ui.flet_app.components.scan.scan_hud import ScanHUD, ScanHUDCallbacks
from cerebro.v2.ui.flet_app.components.dashboard.checkpoint_restore_card import (
    build_checkpoint_restore_card,
)
from cerebro.v2.ui.flet_app.components.dashboard.collapsible_section import CollapsibleSection
from cerebro.v2.ui.flet_app.components.dashboard.hero_button import HeroScanButton
from cerebro.v2.ui.flet_app.components.dashboard.folder_panel import DashboardFolderPanel
from cerebro.v2.ui.flet_app.components.dashboard.home_chrome import DashboardHomeChrome
from cerebro.v2.ui.flet_app.components.dashboard.home_shell import DashboardHomeShell
from cerebro.v2.ui.flet_app.components.dashboard.scan_complete_banner import ScanCompleteBanner
from cerebro.v2.ui.flet_app.components.dashboard.scan_options_panel import DashboardScanOptionsPanel
from cerebro.v2.ui.flet_app.components.dashboard.stats_presence import DashboardStatsPresence
from cerebro.v2.ui.flet_app.design_system.glass import glass_container
from cerebro.v2.ui.flet_app.design_system.cards import apply_flat_style
from cerebro.v2.ui.flet_app.theme import theme_for_mode, fmt_size, SCAN_MODES
from cerebro.v2.ui.flet_app.utils.time_keeper import TimeKeeper

if TYPE_CHECKING:
    from cerebro.v2.ui.flet_app.services.state_bridge import StateBridge

_log = logging.getLogger(__name__)

_INCOMPLETE_SCAN_PATH = Path.home() / ".cerebro" / "incomplete_scan.json"

_SCAN_MODE_ICON_MAP = {
    "description": ft.icons.Icons.DESCRIPTION,
    "image": ft.icons.Icons.IMAGE,
    "image_search": ft.icons.Icons.IMAGE_SEARCH,
    "videocam": ft.icons.Icons.VIDEOCAM,
    "music_note": ft.icons.Icons.MUSIC_NOTE,
}


class DashboardPage(ft.Column):
    """Home page with scan configuration, stats, and quick-start."""

    def __init__(self, bridge: "StateBridge", folder_picker: ft.FilePicker):
        super().__init__(expand=True, scroll=ft.ScrollMode.AUTO)
        self._bridge = bridge
        self._folder_picker = folder_picker
        self._folders: list[Path] = []  # Enforce Path objects
        self._picker_active: bool = False  # guard against concurrent picker opens
        self._selected_mode = "files"
        self._selected_modes: set[str] = {"files"}
        self._scan_options: dict = {
            "scan_archives": False,
            "min_size_bytes": 0,
            "exclude_paths": [],
            "include_subfolders": True,
            "index_only": False,
            "verify_duplicates": False,
        }
        self._stats = {"scans": 0, "dupes": 0, "bytes_reclaimed": 0}
        self._initial_load_done = False
        self._stats_fetch_generation = 0
        self._last_on_show_ts = 0.0
        # Initial Theme Load
        self._t = theme_for_mode(self._bridge.app_theme)
        self._reduce_motion: bool = self._bridge.is_reduce_motion_enabled()

        # UI References (to update without rebuilding)
        self._hero: ft.Container
        self._hero_tagline_icon: ft.Icon
        self._folder_section_icon: ft.Icon
        self._stats_row: ft.Row
        self._mode_label: ft.Text
        self._mode_row: ft.Column
        self._scan_type_summary: ft.Text
        self._scan_type_checkboxes: dict[str, ft.Checkbox]
        self._scan_safety_note: ft.Text
        self._folder_chips_row: ft.Row
        self._folder_container: ft.Container
        self._actions: ft.Row
        self._last_session_btn: ft.TextButton
        self._start_btn: HeroScanButton
        self._pause_scan_btn: ft.OutlinedButton
        self._status: ft.Text
        self._cancelled_results_banner: ft.Container
        self._cancelled_results_text: ft.Text
        self._cancelled_results_btn: ft.TextButton
        self._main_panels: list
        self._scan_archives_sw: ft.Switch
        self._archives_warning: ft.Text
        self._advanced_options_visible: bool
        self._scan_options_dropdown_open: bool
        self._scan_options_toggle_btn: ft.OutlinedButton
        self._scan_options_dropdown: ft.Container
        self._advanced_panel: ft.Container
        self._min_size_slider: ft.Slider
        self._min_size_label: ft.Text
        self._exclude_paths_tf: ft.TextField
        self._exclude_paths_browse_btn: ft.OutlinedButton
        self._include_subfolders_sw: ft.Switch
        self._scan_options_row: ft.Container
        self._scan_hud: ScanHUD
        # Cancellation state: track whether we're in a cancel flow and cache
        # partial results so the user can choose to view them post-cancel.
        self._was_cancelled: bool = False
        self._pending_partial_results: list = []
        self._pending_partial_mode: str = "files"
        self._cancel_complete_handled: bool = False
        self._cancel_user_dismissed_choice: bool = False
        self._resume_interrupted_scan_once: bool = False
        self._last_incomplete_persist_ts: float = 0.0
        # Elapsed clock + ETA line (1 Hz); snapshot updated from progress callbacks.
        # Last engine-reported wall elapsed (monotonic-based in TurboFileEngine); used when the
        # 1 Hz UI timer thread does not advance the clock on some hosts.
        self._status_token: int = 0
        self._cancelled_banner_token: int = 0
        self._cancel_watchdog_token: int = 0
        self._io_failure_hits_by_root: dict[str, int] = {}
        self._io_pause_dialog_open: bool = False
        self._io_paused_root: str = ""
        self._scan_network_warn_shown: bool = False
        # Largest file-catalogue count seen (discovery + grouping); explains hashing denominator.
        # After ``_on_scan_complete`` / ``_on_scan_error``, ignore queued progress callbacks so the
        # HUD cannot show mid-scan bars while "View Results" / completion chrome is already up.
        self._scan_accept_progress: bool = True
        # Canvas chunk bar state
        self._build_ui()
        self._load_scan_options_for_mode(self._selected_mode)

    def _is_mounted(self) -> bool:
        """True only when this control is attached to a :class:`ft.Page` (safe before ``page.add``)."""
        try:
            return self.page is not None
        except RuntimeError:
            return False

    @staticmethod
    def _safe_update(ctrl: ft.Control | None) -> None:
        if ctrl is None:
            return
        try:
            if ctrl.page is not None:
                ctrl.update()
        except RuntimeError:
            pass

    @property
    def _scan_view(self) -> ft.Container:
        return self._scan_hud

    @property
    def _scan_hud_snap(self) -> dict:
        return self._scan_hud.progress_snapshot

    def _set_main_panels_visible(self, visible: bool) -> None:
        for panel in self._main_panels:
            panel.visible = visible

    def _bump_cancel_watchdog_token(self) -> None:
        self._cancel_watchdog_token += 1

    def _scan_hud_callbacks(self) -> ScanHUDCallbacks:
        return ScanHUDCallbacks(
            on_cancel_scan=self._stop_scan,
            on_pause_scan=self._on_hero_pause_toggle,
            on_view_results=self._go_to_results,
            on_view_partial_results=self._go_to_partial_results,
            on_home=self._go_to_home,
            on_request_page_update=self._do_page_update,
            on_sync_pause_scan_hero_button=self._sync_pause_scan_hero_button,
            on_persist_incomplete_scan=self._persist_incomplete_scan_session,
            on_show_snackbar=self._bridge.show_snackbar,
            on_handle_repeated_io_failure=self._handle_repeated_io_failure,
            on_set_main_panels_visible=self._set_main_panels_visible,
            on_show_cancelled_status=self._show_cancelled_status,
            on_show_cancelled_results_banner=self._show_cancelled_results_banner,
            on_hide_cancelled_results_banner=self._hide_cancelled_results_banner,
            on_abort_scan_session=self._bridge.abort_scan_session,
            get_was_cancelled=lambda: self._was_cancelled,
            set_was_cancelled=lambda value: setattr(self, "_was_cancelled", value),
            get_cancel_complete_handled=lambda: self._cancel_complete_handled,
            set_cancel_complete_handled=lambda value: setattr(self, "_cancel_complete_handled", value),
            get_cancel_user_dismissed_choice=lambda: self._cancel_user_dismissed_choice,
            set_cancel_user_dismissed_choice=lambda value: setattr(self, "_cancel_user_dismissed_choice", value),
            get_cancel_watchdog_token=lambda: self._cancel_watchdog_token,
            bump_cancel_watchdog_token=self._bump_cancel_watchdog_token,
            get_scan_accept_progress=lambda: self._scan_accept_progress,
            set_scan_accept_progress=lambda value: setattr(self, "_scan_accept_progress", value),
            get_scan_network_warn_shown=lambda: self._scan_network_warn_shown,
            set_scan_network_warn_shown=lambda value: setattr(self, "_scan_network_warn_shown", value),
            get_pending_partial_results=lambda: self._pending_partial_results,
            set_pending_partial_results=lambda value: setattr(self, "_pending_partial_results", value),
            get_pending_partial_mode=lambda: self._pending_partial_mode,
            set_pending_partial_mode=lambda value: setattr(self, "_pending_partial_mode", value),
            get_last_incomplete_persist_ts=lambda: self._last_incomplete_persist_ts,
            set_last_incomplete_persist_ts=lambda value: setattr(self, "_last_incomplete_persist_ts", value),
        )

    def _is_dark_theme(self) -> bool:
        try:
            return "dark" in str(getattr(self._bridge, "app_theme", "")).lower()
        except Exception:
            return True

    def _hover_glow_color(self, variant: str = "primary") -> str:
        if self._is_dark_theme():
            if variant == "secondary":
                return "#A78BFA"
            return str(self._t.colors.accent)
        if variant == "secondary":
            return "#4F46E5"
        return str(self._t.colors.accent)

    def _hover_shadow(self, color: str, strong: bool = False) -> ft.BoxShadow:
        return ft.BoxShadow(
            blur_radius=24 if strong else 14,
            spread_radius=0,
            color=ft.Colors.with_opacity(0.42 if strong else 0.26, color),
            offset=ft.Offset(0, 3 if strong else 2),
        )

    def _set_container_glow(self, container: ft.Container, hovering: bool, *, variant: str = "primary", strong: bool = False) -> None:
        _ = variant, strong
        if hovering:
            container.border = ft.border.all(1, self._t.colors.primary)
        else:
            container.border = ft.border.all(1, self._t.colors.border)
        container.shadow = None
        DashboardPage._safe_update(container)

    # ------------------------------------------------------------------
    # Construction (Runs Once)
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        t = self._t
        s = t.spacing

        page = self._bridge.flet_page
        chrome = DashboardHomeChrome.build(
            self._bridge,
            t,
            page,
            on_open_last_session=self._open_last_session,
            on_start_scan=self._start_scan,
            on_pause_scan=self._on_hero_pause_toggle,
            on_partial_results=self._go_to_partial_results,
            set_container_glow=self._set_container_glow,
        )
        self._hero = chrome.hero
        self._hero_tagline_icon = chrome.hero_tagline_icon
        self._last_session_btn = chrome.last_session_btn
        self._start_btn = chrome.start_btn
        self._pause_scan_btn = chrome.pause_scan_btn
        self._scan_safety_note = chrome.scan_safety_note
        self._actions = chrome.actions
        self._status = chrome.status
        self._cancelled_results_text = chrome.cancelled_results_text
        self._cancelled_results_btn = chrome.cancelled_results_btn
        self._cancelled_results_banner = chrome.cancelled_results_banner
        self._paused_scans_col = chrome.paused_scans_col
        self._paused_scans_section = chrome.paused_scans_section
        self._home_chrome = chrome
        self._checkpoint_timer_ids = []

        # Stat cards and operational presence
        self._stats_presence = DashboardStatsPresence(
            self._bridge,
            t,
            safe_update=DashboardPage._safe_update,
            set_container_glow=self._set_container_glow,
        )
        self._stats_row = self._stats_presence.stats_row
        self._presence_row = self._stats_presence.presence_row
        self._presence_mtime = self._stats_presence.presence_mtime
        self._update_stats_ui()

        # Scan mode selector and advanced settings
        self._scan_opts = DashboardScanOptionsPanel(
            t,
            on_archives_change=self._on_archives_cb_change,
            on_toggle_dropdown=self._toggle_scan_options_dropdown,
            on_min_size_change=self._on_min_size_change,
            on_exclude_paths_blur=self._on_exclude_paths_blur,
            on_browse_exclude_path=self._browse_exclude_path,
            on_include_subfolders_change=self._on_include_subfolders_change,
            on_index_only_change=self._on_index_only_change,
            on_verify_duplicates_change=self._on_verify_duplicates_change,
        )
        self._mode_label = self._scan_opts.mode_label
        self._mode_row = self._scan_opts.mode_row
        self._scan_type_summary = self._scan_opts.scan_type_summary
        self._scan_archives_sw = self._scan_opts.scan_archives_sw
        self._archives_warning = self._scan_opts.archives_warning
        self._advanced_panel = self._scan_opts.advanced_panel
        self._min_size_slider = self._scan_opts.min_size_slider
        self._min_size_label = self._scan_opts.min_size_label
        self._exclude_paths_tf = self._scan_opts.exclude_paths_tf
        self._exclude_paths_browse_btn = self._scan_opts.exclude_paths_browse_btn
        self._include_subfolders_sw = self._scan_opts.include_subfolders_sw
        self._scan_options_row = self._scan_opts.scan_options_row
        self._scan_options_toggle_btn = self._scan_opts.scan_options_toggle_btn
        self._scan_options_dropdown = self._scan_opts.scan_options_dropdown
        self._advanced_options_visible = False
        self._scan_options_dropdown_open = False
        self._scan_type_checkboxes = {}
        self._update_modes_ui()

        self._folder_panel = DashboardFolderPanel(
            self._bridge,
            t,
            page,
            on_browse=self._browse_folders,
            on_quick_add=self._quick_add_desktop_downloads,
            on_hover=lambda e, _panel=None: self._set_container_glow(
                self._folder_panel._inner_container,
                e.data == "true",
                variant="primary",
            ),
            on_remove_folder=self._remove_folder,
        )
        self._folder_container = self._folder_panel.container
        self._folder_chips_row = self._folder_panel.chips_row
        self._folder_section_icon = self._folder_panel.section_icon

        self._workflow_stack = DashboardHomeShell.build_workflow_stack(
            t,
            page=page,
            hero=self._hero,
            folder_panel=self._folder_container,
            actions=self._actions,
            scan_options_toggle_btn=self._scan_options_toggle_btn,
            scan_options_dropdown=self._scan_options_dropdown,
        )

        self._scan_complete_banner = ScanCompleteBanner(
            t,
            on_open_workspace=self._open_workspace_from_scan_complete,
        )

        self._scan_section = CollapsibleSection(
            self._bridge, t, "Scan", self._workflow_stack, expanded=True
        )
        self._recent_section = CollapsibleSection(
            self._bridge,
            t,
            "Recent activity",
            ft.Column(
                [
                    self._paused_scans_section,
                    ft.Container(content=self._status, width=520, padding=ft.padding.only(top=s.xs)),
                    ft.Container(content=self._cancelled_results_banner, width=460, padding=ft.padding.only(top=s.xs)),
                ],
                spacing=s.xs,
            ),
            expanded=True,
        )
        self._summary_section = CollapsibleSection(
            self._bridge,
            t,
            "Summary",
            ft.Column(
                [
                    ft.Container(content=self._stats_row, width=360),
                    ft.Container(content=self._presence_row, width=620, padding=ft.padding.only(top=s.xs)),
                ],
                spacing=s.xs,
            ),
            expanded=False,
            on_toggle=self._on_summary_section_toggle,
        )

        home_content = ft.Container(
            alignment=ft.Alignment(0, -1),
            padding=ft.padding.only(top=4),
            content=ft.Column(
                [
                    ft.Container(content=self._scan_complete_banner.container, width=840),
                    self._scan_section,
                    self._recent_section,
                    self._summary_section,
                ],
                spacing=s.sm,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        )
        self.controls = [home_content]
        self._main_panels = list(self.controls)  # snapshot for hide/show swap
        self._scan_hud = ScanHUD(self._bridge, self._t, self._scan_hud_callbacks())
        self.controls.append(self._scan_hud)     # scan HUD always last, starts hidden
        self._refresh_folder_chips()
        self._apply_dashboard_pill_chrome()

        # Initial data fetch (async so first layout is not blocked)
        self._schedule_dashboard_data_fetch()

    # ------------------------------------------------------------------
    # Theme Helpers
    # ------------------------------------------------------------------


    def _get_button_style(self, base_color: str = None) -> ft.ButtonStyle:
        t = self._t
        bg = (
            ft.Colors.with_opacity(0.2, base_color or t.colors.primary)
            if base_color
            else ft.Colors.with_opacity(0.15, t.colors.primary)
        )
        return ft.ButtonStyle(
            bgcolor=bg,
            color=t.colors.fg,
            overlay_color=ft.Colors.with_opacity(0.3, t.colors.primary),
            shape=ft.RoundedRectangleBorder(radius=12),
            padding=ft.Padding.symmetric(horizontal=16, vertical=10),
        )

    # ------------------------------------------------------------------
    # Data & UI Updates (No Rebuild)
    # ------------------------------------------------------------------
    def _schedule_dashboard_data_fetch(self) -> None:
        self._stats_fetch_generation += 1
        gen = self._stats_fetch_generation
        page = self._bridge.flet_page
        if hasattr(page, "run_task"):
            page.run_task(self._fetch_dashboard_data_async, gen)
        else:
            self._fetch_dashboard_data_sync()

    def _fetch_dashboard_data_sync(self) -> None:
        try:
            stats = self._bridge.get_stats()
            if stats:
                self._stats = stats
        except Exception:
            _log.error("Failed to fetch dashboard data", exc_info=True)
        self._update_stats_ui()
        self._stats_presence.set_mtime_caption("")

    async def _fetch_dashboard_data_async(self, gen: int) -> None:
        import asyncio

        loop = asyncio.get_event_loop()
        try:
            stats = await loop.run_in_executor(None, self._bridge.get_stats)
            if gen != self._stats_fetch_generation:
                return
            if stats:
                self._stats = stats
        except Exception:
            _log.error("Failed to fetch dashboard data", exc_info=True)
        self._update_stats_ui()
        try:
            from cerebro.v2.core.index_presence import (
                count_files_newer_than,
                latest_scan_entry,
            )

            entry = latest_scan_entry()
            if entry and gen == self._stats_fetch_generation:
                self._stats_presence.set_mtime_caption("Checking folders for files modified since then…")

                def _mtime_job():
                    return count_files_newer_than(
                        entry.folders,
                        entry.timestamp,
                        budget_seconds=2.0,
                        max_files=200_000,
                    )

                count, truncated = await loop.run_in_executor(None, _mtime_job)
                if gen != self._stats_fetch_generation:
                    return
                if truncated:
                    self._stats_presence.set_mtime_caption(
                        f"≥{count:,}+ paths look newer than your last analysis "
                        "(quick check stopped early for responsiveness)."
                    )
                elif count == 0:
                    self._stats_presence.set_mtime_caption(
                        "No newer files spotted under the last scanned paths — "
                        "a rescan should mostly hit the hash cache."
                    )
                else:
                    self._stats_presence.set_mtime_caption(
                        f"{count:,} files have a newer modified time since that run — "
                        "start a scan to refresh duplicate groups."
                    )
                DashboardPage._safe_update(self._presence_row)
        except Exception:
            _log.debug("Presence mtime check failed", exc_info=True)
            if gen == self._stats_fetch_generation:
                self._stats_presence.set_mtime_caption("")

    def _update_stats_ui(self, *, refresh_presence_force: bool = False) -> None:
        self._stats_presence.update_stats(self._stats, refresh_presence_force=refresh_presence_force)

    def _update_modes_ui(self) -> None:
        t = self._t
        controls: list[ft.Control] = []
        self._scan_type_checkboxes = {}
        has_specific = any(m != "files" for m in self._selected_modes)

        for m in SCAN_MODES:
            key = str(m.get("key", ""))
            if not key:
                continue
            label = str(m.get("label", key))
            if key == "files":
                label = "Full Scan"
            cb = ft.Checkbox(
                label=label,
                value=(key in self._selected_modes),
                active_color="#22D3EE",
                label_style=ft.TextStyle(color=t.colors.fg2, size=t.typography.size_sm),
                on_change=lambda e, k=key: self._on_scan_type_selected(k, e),
                disabled=(key == "files" and has_specific),
            )
            self._scan_type_checkboxes[key] = cb
            controls.append(cb)
        self._mode_row.controls = controls
        self._update_scan_type_summary()
        DashboardPage._safe_update(self._mode_row)
        DashboardPage._safe_update(self._scan_type_summary)

    def _on_scan_type_selected(self, key: str, e: ft.ControlEvent) -> None:
        prev_mode = self._selected_mode
        next_selected = set(self._selected_modes)
        checked = bool(e.control.value)
        if key == "files":
            if checked:
                next_selected = {"files"}
            else:
                next_selected = set(self._selected_modes) or {"files"}
        else:
            if checked:
                next_selected.discard("files")
                next_selected.add(key)
            else:
                next_selected.discard(key)
                if not next_selected:
                    next_selected = {"files"}

        self._save_scan_options_for_mode(prev_mode)
        self._selected_modes = next_selected
        self._selected_mode = self._primary_selected_mode()
        self._load_scan_options_for_mode(self._selected_mode)
        self._update_modes_ui()
        self._update_scan_type_summary()
        _log.info("scan_type_selected modes=%s", sorted(self._selected_modes))

    def _update_scan_type_summary(self) -> None:
        selected = len(self._selected_modes)
        noun = "type" if selected == 1 else "types"
        self._scan_type_summary.value = f"{selected} {noun} selected"

    def _primary_selected_mode(self) -> str:
        if "files" in self._selected_modes:
            return "files"
        if self._selected_modes:
            return sorted(self._selected_modes)[0]
        return "files"

    def _selected_modes_for_scan(self) -> list[str]:
        if "files" in self._selected_modes:
            return ["files"]
        modes = [m for m in sorted(self._selected_modes) if m]
        return modes or ["files"]

    def _scan_modes_display_label(self, modes: list[str]) -> str:
        label_by_key = {
            str(m.get("key", "")): str(m.get("label", m.get("key", "")))
            for m in SCAN_MODES
            if str(m.get("key", "")).strip()
        }
        names = [label_by_key.get(k, str(k)) for k in modes if str(k).strip()]
        if not names:
            names = ["Full Scan"]
        return "Running: " + " + ".join(names)

    def _open_last_session(self, e=None):
        try:
            self._bridge.open_last_session()
        except Exception as err:
            _log.error(f"Failed to open last session: {err}")

    # ------------------------------------------------------------------
    # User Interactions
    # ------------------------------------------------------------------
    def _on_archives_cb_change(self, e: ft.ControlEvent) -> None:
        enabled = bool(e.control.value)
        self._scan_options["scan_archives"] = enabled
        self._archives_warning.visible = enabled
        DashboardPage._safe_update(self._archives_warning)
        self._save_scan_options_for_mode(self._selected_mode)

    def _on_summary_section_toggle(self, expanded: bool) -> None:
        if expanded:
            self._stats_presence.animate_stat_counts_on_first_expand()

    def _toggle_scan_options_dropdown(self, _e: ft.ControlEvent) -> None:
        self._scan_opts.toggle_dropdown(DashboardPage._safe_update)

    def _on_min_size_change(self, e: ft.ControlEvent) -> None:
        mb = int(e.control.value or 0)
        self._scan_options["min_size_bytes"] = mb * 1024 * 1024
        self._min_size_label.value = f"Min file size: {mb} MB"
        DashboardPage._safe_update(self._min_size_label)
        self._save_scan_options_for_mode(self._selected_mode)

    def _on_exclude_paths_blur(self, _e: ft.ControlEvent) -> None:
        raw = str(self._exclude_paths_tf.value or "")
        lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
        self._scan_options["exclude_paths"] = lines
        _log.info("exclude_paths_updated count=%d", len(lines))
        self._save_scan_options_for_mode(self._selected_mode)

    def _on_include_subfolders_change(self, e: ft.ControlEvent) -> None:
        self._scan_options["include_subfolders"] = bool(e.control.value)
        self._save_scan_options_for_mode(self._selected_mode)

    def _on_index_only_change(self, e: ft.ControlEvent) -> None:
        self._scan_options["index_only"] = bool(e.control.value)
        self._save_scan_options_for_mode(self._selected_mode)

    def _on_verify_duplicates_change(self, e: ft.ControlEvent) -> None:
        self._scan_options["verify_duplicates"] = bool(e.control.value)
        self._save_scan_options_for_mode(self._selected_mode)

    def _browse_exclude_path(self, _e: ft.ControlEvent) -> None:
        if self._picker_active:
            return
        page = getattr(self._bridge, "flet_page", None)
        if page:
            page.run_task(self._browse_exclude_path_async)

    async def _browse_exclude_path_async(self) -> None:
        if self._picker_active:
            return
        self._picker_active = True
        try:
            result = await self._folder_picker.get_directory_path(
                dialog_title="Select folder path to exclude"
            )
            if not result:
                return
            lines = list(self._scan_options.get("exclude_paths", []) or [])
            path_s = str(result).strip()
            if path_s and path_s not in lines:
                lines.append(path_s)
                self._scan_options["exclude_paths"] = lines
                self._exclude_paths_tf.value = "\n".join(lines)
                DashboardPage._safe_update(self._exclude_paths_tf)
                self._save_scan_options_for_mode(self._selected_mode)
        except Exception as exc:
            msg = str(exc).lower()
            if "session" not in msg and "closed" not in msg:
                _log.error("Exclude-path picker failed: %s", exc)
        finally:
            self._picker_active = False

    def _save_scan_options_for_mode(self, mode_key: str) -> None:
        if not mode_key:
            return
        settings = self._bridge.get_settings()
        if not isinstance(settings, dict):
            settings = {}
        scan_cfg = settings.get("scan")
        if not isinstance(scan_cfg, dict):
            scan_cfg = {}
        adv = scan_cfg.get("advanced_by_mode")
        if not isinstance(adv, dict):
            adv = {}
        adv[str(mode_key)] = {
            "min_size_bytes": int(self._scan_options.get("min_size_bytes", 0) or 0),
            "exclude_paths": list(self._scan_options.get("exclude_paths", []) or []),
            "scan_archives": bool(self._scan_options.get("scan_archives", False)),
            "include_subfolders": bool(self._scan_options.get("include_subfolders", True)),
            "index_only": bool(self._scan_options.get("index_only", False)),
            "verify_duplicates": bool(self._scan_options.get("verify_duplicates", False)),
        }
        scan_cfg["advanced_by_mode"] = adv
        settings["scan"] = scan_cfg
        self._bridge.save_settings(settings)

    def _load_scan_options_for_mode(self, mode_key: str) -> None:
        settings = self._bridge.get_settings()
        scan_cfg = settings.get("scan") if isinstance(settings, dict) else {}
        adv = scan_cfg.get("advanced_by_mode") if isinstance(scan_cfg, dict) else {}
        conf = adv.get(str(mode_key), {}) if isinstance(adv, dict) else {}
        if not isinstance(conf, dict):
            conf = {}

        self._scan_options["min_size_bytes"] = int(conf.get("min_size_bytes", 0) or 0)
        ex = conf.get("exclude_paths", [])
        self._scan_options["exclude_paths"] = [str(x) for x in ex] if isinstance(ex, list) else []
        self._scan_options["scan_archives"] = bool(conf.get("scan_archives", False))
        self._scan_options["include_subfolders"] = bool(conf.get("include_subfolders", True))
        self._scan_options["index_only"] = bool(conf.get("index_only", False))
        self._scan_options["verify_duplicates"] = bool(conf.get("verify_duplicates", False))

        min_mb = max(0, min(1024, int(self._scan_options["min_size_bytes"]) // (1024 * 1024)))
        self._min_size_slider.value = min_mb
        self._min_size_label.value = f"Min file size: {min_mb} MB"
        self._exclude_paths_tf.value = "\n".join(self._scan_options["exclude_paths"])
        self._scan_archives_sw.value = bool(self._scan_options["scan_archives"])
        self._archives_warning.visible = bool(self._scan_options["scan_archives"])
        self._include_subfolders_sw.value = bool(self._scan_options["include_subfolders"])
        DashboardPage._safe_update(self._min_size_slider)
        DashboardPage._safe_update(self._min_size_label)
        DashboardPage._safe_update(self._exclude_paths_tf)
        DashboardPage._safe_update(self._scan_archives_sw)
        DashboardPage._safe_update(self._archives_warning)
        DashboardPage._safe_update(self._include_subfolders_sw)
        DashboardPage._safe_update(self._scan_opts.index_only_sw)
        DashboardPage._safe_update(self._scan_opts.verify_duplicates_sw)
        self._scan_opts.index_only_sw.value = bool(self._scan_options["index_only"])
        self._scan_opts.verify_duplicates_sw.value = bool(self._scan_options["verify_duplicates"])

    def _effective_scan_options(self) -> dict:
        """Merge per-mode Home options with global Performance settings for the turbo file engine."""
        opts = dict(self._scan_options)
        try:
            s = self._bridge.get_settings()
            perf = s.get("performance") if isinstance(s, dict) else None
            if isinstance(perf, dict):
                opts["max_threads"] = max(0, min(256, int(perf.get("max_threads", 0) or 0)))
                opts["incremental_scan"] = bool(perf.get("hash_cache_enabled", True))
            gen = s.get("general") if isinstance(s, dict) else None
            if isinstance(gen, dict):
                opts["skip_system_folders"] = bool(gen.get("skip_system_folders", True))
        except Exception:
            _log.debug("effective_scan_options: could not read performance settings", exc_info=True)
        opts.setdefault("max_threads", 0)
        opts.setdefault("incremental_scan", True)
        # Full-file hashing with auto pick among xxhash / blake3 / sha256 (see turbo_scanner).
        opts.setdefault("hash_algorithm", "auto")
        opts.setdefault("skip_system_folders", True)
        opts.setdefault("index_only", False)
        opts.setdefault("verify_duplicates", False)
        if getattr(self, "_resume_interrupted_scan_once", False):
            opts = dict(opts)
            opts["index_only"] = False
            opts = dict(opts)
            opts["resume_interrupted_scan"] = True
        return opts

    def _select_mode(self, key: str) -> None:
        if self._selected_mode == key and key in self._selected_modes:
            return
        self._selected_modes = {str(key or "files")}
        self._selected_mode = key
        self._update_modes_ui()

    def _browse_folders(self, e: ft.ControlEvent) -> None:
        if self._picker_active:
            return
        page = getattr(self._bridge, "flet_page", None)
        if page:
            page.run_task(self._browse_folders_async)

    async def _browse_folders_async(self) -> None:
        if self._picker_active:
            return
        self._picker_active = True
        try:
            result = await self._folder_picker.get_directory_path(
                dialog_title="Select folder to scan"
            )
            if result:
                self._add_folder(Path(result))
        except Exception as exc:
            # "Session closed" is Flet's normal cancellation signal when the
            # user dismisses the dialog — not a real error.
            msg = str(exc).lower()
            if "session" not in msg and "closed" not in msg:
                _log.error("Folder picker failed: %s", exc)
        finally:
            self._picker_active = False

    def _add_folder(self, path: Path) -> None:
        if path in self._folders:
            return
        self._folders.append(path)
        self._refresh_folder_chips()

    def _refresh_folder_chips(self) -> None:
        self._folder_panel.refresh_chips(self._folders, mounted=self._is_mounted())
        self._sync_start_button_state()

    def _remove_folder(self, path: Path) -> None:
        if path in self._folders:
            self._folders.remove(path)
        self._refresh_folder_chips()

    def _sync_start_button_state(self) -> None:
        self._start_btn.set_disabled(False)
        DashboardPage._safe_update(self._start_btn)

    def _apply_dashboard_pill_chrome(self) -> None:
        """Match shell nav pill styling; call after theme changes."""
        t = self._t
        self._last_session_btn.style = pill_text_button_style(t, variant="muted")
        self._pause_scan_btn.style = pill_outlined_button_style(t)
        self._sync_start_button_state()
        self._exclude_paths_browse_btn.style = pill_outlined_button_style(t)
        self._scan_options_toggle_btn.style = pill_outlined_button_style(t)
        self._cancelled_results_btn.style = pill_text_button_style(t, variant="primary")
        for ctrl in (
            self._last_session_btn,
            self._pause_scan_btn,
            self._exclude_paths_browse_btn,
            self._scan_options_toggle_btn,
            self._cancelled_results_btn,
        ):
            DashboardPage._safe_update(ctrl)
        self._scan_hud.apply_pill_chrome()

    def _quick_add_desktop_downloads(self, _e: ft.ControlEvent | None = None) -> None:
        home = Path.home()
        candidates = [
            home / "Desktop",
            home / "Downloads",
            home / "OneDrive" / "Desktop",
            home / "OneDrive" / "Downloads",
        ]
        added = 0
        for p in candidates:
            if p.is_dir() and p not in self._folders:
                self._folders.append(p)
                added += 1
        self._refresh_folder_chips()
        if added:
            self._bridge.show_snackbar("Desktop/Downloads added.", info=True)
        else:
            self._bridge.show_snackbar("No quick-add folders found.", info=True)

    async def _flash_folder_validation(self) -> None:
        inner = self._folder_panel._inner_container
        original = inner.border
        original_bg = inner.bgcolor
        inner.border = ft.border.all(2, "#EF4444")
        inner.bgcolor = ft.Colors.with_opacity(0.12, "#EF4444")
        DashboardPage._safe_update(inner)
        await asyncio.sleep(0.35)
        inner.border = original
        inner.bgcolor = original_bg
        DashboardPage._safe_update(inner)

    def _start_scan(self, e: ft.ControlEvent) -> None:
        if not self._folders:
            self._status.value = "Please add a folder to continue."
            self._status.update()
            try:
                self._bridge.show_snackbar("Please add a folder to continue.", info=True)
                self._bridge.flet_page.run_task(self._flash_folder_validation)
            except Exception:
                pass
            return

        root_drive = self._root_drive_selection()
        if root_drive and not self._is_root_drive_warning_acknowledged(root_drive):
            _log.info("root_drive_warning drive=%s", root_drive)
            self._show_root_drive_warning(root_drive)
            return
        self._begin_scan()

    def _begin_scan(self) -> None:
        resume_interrupted = bool(getattr(self, "_resume_interrupted_scan_once", False))
        self._was_cancelled = False
        self._pending_partial_results = []
        self._scan_hud.reset_cancel_choice_for_new_scan()
        scan_modes = self._selected_modes_for_scan()
        self._pending_partial_mode = "+".join(scan_modes)
        self._hide_cancelled_results_banner()
        self._io_failure_hits_by_root.clear()
        self._io_pause_dialog_open = False
        self._io_paused_root = ""
        self._scan_network_warn_shown = False
        self._scan_accept_progress = True
        self._scan_hud.prepare_for_scan(self._scan_modes_display_label(scan_modes))
        self._persist_incomplete_scan_session(status="in_progress")
        _log.info(
            "scan_start folders=%d modes=%s archives=%s resume_interrupted=%s",
            len(self._folders),
            scan_modes,
            bool(self._scan_options.get("scan_archives", False)),
            resume_interrupted,
        )

        self._bridge.begin_scan_session(self._folders, "+".join(scan_modes))

        try:
            backend = self._bridge.backend
            backend.set_on_progress(self._on_scan_progress)
            backend.set_on_complete(self._on_scan_complete)
            backend.set_on_error(self._on_scan_error)
            scan_opts = self._effective_scan_options()
            backend.start_scan(self._folders, mode=scan_modes, options=scan_opts)
            self._sync_pause_scan_hero_button()
            self._resume_interrupted_scan_once = False
            if resume_interrupted:
                try:
                    self._bridge.show_snackbar(
                        "Continuing interrupted scan — hash and folder caches reuse finished work when paths and filters match.",
                        info=True,
                    )
                except Exception:
                    pass
        except Exception as err:
            self._on_scan_error(f"Backend communication error: {err}")

    def _root_drive_selection(self) -> str:
        for p in self._folders:
            try:
                resolved = Path(p).resolve()
            except OSError:
                resolved = Path(p)
            anchor = str(resolved.anchor or "").upper()
            if not anchor:
                continue
            norm = str(resolved).replace("/", "\\").rstrip("\\")
            root = anchor.rstrip("\\")
            if norm == root:
                return anchor
        return ""

    def _is_root_drive_warning_acknowledged(self, drive_anchor: str) -> bool:
        settings = self._bridge.get_settings()
        scan_cfg = settings.get("scan") if isinstance(settings, dict) else {}
        warned = scan_cfg.get("warned_root_drives") if isinstance(scan_cfg, dict) else []
        if not isinstance(warned, list):
            return False
        needle = str(drive_anchor).upper()
        return needle in [str(x).upper() for x in warned]

    def _ack_root_drive_warning(self, drive_anchor: str) -> None:
        settings = self._bridge.get_settings()
        if not isinstance(settings, dict):
            settings = {}
        scan_cfg = settings.get("scan")
        if not isinstance(scan_cfg, dict):
            scan_cfg = {}
        warned = scan_cfg.get("warned_root_drives")
        if not isinstance(warned, list):
            warned = []
        anchor = str(drive_anchor).upper()
        if anchor not in [str(x).upper() for x in warned]:
            warned.append(anchor)
            scan_cfg["warned_root_drives"] = warned
            settings["scan"] = scan_cfg
            self._bridge.save_settings(settings)

    def _show_root_drive_warning(self, drive_anchor: str) -> None:
        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Root drive scan warning"),
            content=ft.Text(
                f"Scanning {drive_anchor} can take hours and includes system folders unless excluded. "
                "Enable 'Skip system folders' in Settings → General for faster scans. Continue?"
            ),
            actions=[
                ft.TextButton("Cancel", on_click=lambda _e: self._bridge.dismiss_top_dialog()),
                ft.FilledButton(
                    "Continue",
                    on_click=lambda _e, d=drive_anchor: self._confirm_root_drive_scan(d),
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self._bridge.show_modal_dialog(dialog)

    def _confirm_root_drive_scan(self, drive_anchor: str) -> None:
        self._bridge.dismiss_top_dialog()
        self._ack_root_drive_warning(drive_anchor)
        _log.info("root_drive_warning_acknowledged drive=%s", drive_anchor)
        self._begin_scan()

    def _persist_incomplete_scan_session(
        self,
        *,
        status: str,
        progress_snapshot: Optional[dict] = None,
    ) -> None:
        snap = progress_snapshot if progress_snapshot is not None else dict(getattr(self, "_scan_hud_snap", None) or {})
        last_progress: dict = {}
        if snap:
            last_progress = {
                "stage": str(snap.get("stage") or ""),
                "scanned": int(snap.get("scanned") or 0),
                "total": int(snap.get("total") or 0),
                "total_files_in_scope": int(snap.get("total_files_in_scope") or 0),
                "files_processed": int(snap.get("files_processed") or 0),
                "candidates_found": int(snap.get("candidates_found") or 0),
            }
        try:
            modes_list = list(self._selected_modes_for_scan())
        except (AttributeError, TypeError):
            modes_list = [str(getattr(self, "_selected_mode", "files") or "files")]
        payload = {
            "status": str(status),
            "timestamp": time.time(),
            "folders": [str(p) for p in getattr(self, "_folders", []) or []],
            "mode": str(getattr(self, "_selected_mode", None) or "files"),
            "modes": modes_list,
            "options": dict(getattr(self, "_scan_options", {}) or {}),
        }
        if last_progress:
            payload["last_progress"] = last_progress
        try:
            _INCOMPLETE_SCAN_PATH.parent.mkdir(parents=True, exist_ok=True)
            _INCOMPLETE_SCAN_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except OSError:
            _log.exception("Failed writing incomplete scan snapshot")

    def _clear_incomplete_scan_session(self) -> None:
        try:
            if _INCOMPLETE_SCAN_PATH.exists():
                _INCOMPLETE_SCAN_PATH.unlink()
        except OSError:
            _log.exception("Failed clearing incomplete scan snapshot")

    def _sync_checkpoint_timers(self) -> None:
        keeper = TimeKeeper.instance()
        for tid in self._checkpoint_timer_ids:
            keeper.unregister(tid)
        self._checkpoint_timer_ids.clear()

    def _refresh_paused_scans(self) -> None:
        """Populate the checkpoint-restore cards from checkpoint DB (non-blocking)."""
        self._sync_checkpoint_timers()
        try:
            from cerebro.v2.core.checkpoint_db import get_checkpoint_db
            ckpt = get_checkpoint_db()
            manifests = ckpt.list_resumable_manifests()
        except Exception:
            manifests = []

        t = self._t
        reduce_motion = self._bridge.is_reduce_motion_enabled()
        self._paused_scans_col.controls.clear()
        keeper = TimeKeeper.instance()

        for m in manifests:
            total, pending = 0, 0
            try:
                from cerebro.v2.core.checkpoint_db import get_checkpoint_db
                total, pending = get_checkpoint_db().get_counts(m.scan_id)
            except Exception:
                pass
            if total == 0:
                continue
            completed = total - pending
            folders_preview = ", ".join(Path(p).name for p in m.root_paths[:2])
            if len(m.root_paths) > 2:
                folders_preview += f" +{len(m.root_paths) - 2}"

            def _make_resume_cb(manifest=m):
                return lambda _e: self._resume_checkpoint_manifest(manifest)

            def _make_discard_cb(manifest=m):
                return lambda _e: self._discard_checkpoint_manifest(manifest)

            built = build_checkpoint_restore_card(
                t,
                scan_id=m.scan_id,
                folders_preview=folders_preview,
                completed=completed,
                total=total,
                pending=pending,
                created_at=float(m.created_at),
                on_discard=_make_discard_cb(),
                on_restore=_make_resume_cb(),
                page=self._bridge.flet_page,
                reduce_motion=reduce_motion,
            )
            timer_id = f"ckpt_{m.scan_id}"
            keeper.register(timer_id, built.update_relative)
            self._checkpoint_timer_ids.append(timer_id)
            self._paused_scans_col.controls.append(built.container)

        has_items = bool(self._paused_scans_col.controls)
        self._paused_scans_section.visible = has_items
        self._paused_scans_col.visible = has_items
        if self._is_mounted():
            try:
                self._paused_scans_section.update()
            except Exception:
                pass

    def prompt_resume_incomplete_scan_if_needed(self) -> None:
        """Show resume prompt from checkpoint DB or fall back to incomplete_scan.json."""
        try:
            self._refresh_paused_scans()
        except Exception:
            pass

        # Legacy JSON fallback for users upgrading from prior build
        if not _INCOMPLETE_SCAN_PATH.exists():
            return
        try:
            data = json.loads(_INCOMPLETE_SCAN_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            self._clear_incomplete_scan_session()
            return
        if not isinstance(data, dict):
            self._clear_incomplete_scan_session()
            return
        folders = data.get("folders")
        if not isinstance(folders, list) or not folders:
            self._clear_incomplete_scan_session()
            return

        # Migrate to checkpoint DB then clear the JSON file
        try:
            from cerebro.v2.core.checkpoint_db import get_checkpoint_db
            import json as _json
            _scope = {k: data.get("options", {}).get(k) for k in
                      ("min_size_bytes", "max_size_bytes", "skip_hidden", "recursive", "exclude_paths", "scan_archives")}
            get_checkpoint_db().create_manifest(folders, _scope, label="(migrated)")
        except Exception:
            pass
        self._clear_incomplete_scan_session()
        try:
            self._refresh_paused_scans()
        except Exception:
            pass

    def _discard_checkpoint_manifest(self, manifest) -> None:
        try:
            from cerebro.v2.core.checkpoint_db import get_checkpoint_db
            ckpt = get_checkpoint_db()
            ckpt.update_manifest_status(manifest.scan_id, "completed")
        except Exception:
            pass
        self._refresh_paused_scans()
        _log.info("checkpoint manifest discarded: scan_id=%s", manifest.scan_id)

    def _resume_checkpoint_manifest(self, manifest) -> None:
        folders = [Path(p) for p in manifest.root_paths if Path(p).exists()]
        if not folders:
            self._bridge.show_snackbar("Scan folders are no longer available.", info=True)
            return
        self._folders = folders
        try:
            scope = json.loads(manifest.scope_json)
            min_bytes = int(scope.get("min_size_bytes") or scope.get("min_size") or 0)
            merged = dict(self._scan_options)
            merged["min_size_bytes"] = min_bytes
            merged["scan_archives"] = bool(scope.get("scan_archives", False))
            merged["include_subfolders"] = bool(scope.get("recursive", True))
            ex = scope.get("exclude_paths", [])
            merged["exclude_paths"] = list(ex) if isinstance(ex, list) else []
            self._scan_options = merged
            min_mb = max(0, min(1024, min_bytes // (1024 * 1024)))
            self._min_size_slider.value = min_mb
            self._min_size_label.value = f"Min file size: {min_mb} MB"
            self._exclude_paths_tf.value = "\n".join(merged["exclude_paths"])
            self._scan_archives_sw.value = merged["scan_archives"]
            self._archives_warning.visible = merged["scan_archives"]
            self._include_subfolders_sw.value = merged["include_subfolders"]
        except Exception:
            _log.debug("Could not restore scope from manifest (non-fatal)", exc_info=True)
        self._refresh_folder_chips()
        self._update_modes_ui()
        self._resume_interrupted_scan_once = True
        _log.info("resume_checkpoint_manifest scan_id=%s folders=%d", manifest.scan_id, len(folders))
        self._begin_scan()

    def _discard_incomplete_resume_prompt(self) -> None:
        self._bridge.dismiss_top_dialog()
        self._clear_incomplete_scan_session()
        _log.info("resume_incomplete_scan discarded")

    def _resume_incomplete_scan(self, data: dict) -> None:
        self._bridge.dismiss_top_dialog()
        folders_raw = data.get("folders", [])
        mode = str(data.get("mode", "files") or "files")
        modes = data.get("modes", [])
        options = data.get("options", {})
        folders = [Path(str(p)) for p in folders_raw if Path(str(p)).exists()]
        if not folders:
            self._clear_incomplete_scan_session()
            self._bridge.show_snackbar(
                "Saved scan folders are unavailable. Restore from checkpoint was skipped.",
                info=True,
            )
            return
        self._folders = folders
        if isinstance(modes, list):
            restored_modes = {str(m).strip() for m in modes if str(m).strip()}
        else:
            restored_modes = set()
        if not restored_modes:
            restored_modes = {mode or "files"}
        self._selected_modes = {"files"} if "files" in restored_modes else restored_modes
        self._selected_mode = self._primary_selected_mode()
        merged_options = dict(self._scan_options)
        if isinstance(options, dict):
            merged_options.update(options)
        merged_options["scan_archives"] = bool(merged_options.get("scan_archives", False))
        merged_options["min_size_bytes"] = int(merged_options.get("min_size_bytes", 0) or 0)
        raw_ex = merged_options.get("exclude_paths", [])
        merged_options["exclude_paths"] = [str(x) for x in raw_ex] if isinstance(raw_ex, list) else []
        merged_options["include_subfolders"] = bool(merged_options.get("include_subfolders", True))
        self._scan_options = merged_options

        min_bytes = int(self._scan_options.get("min_size_bytes", 0) or 0)
        min_mb = max(0, min(1024, min_bytes // (1024 * 1024)))
        self._min_size_slider.value = min_mb
        self._min_size_label.value = f"Min file size: {min_mb} MB"
        self._exclude_paths_tf.value = "\n".join(self._scan_options.get("exclude_paths", []))
        self._scan_archives_sw.value = bool(self._scan_options.get("scan_archives", False))
        self._archives_warning.visible = bool(self._scan_options.get("scan_archives", False))
        self._include_subfolders_sw.value = bool(self._scan_options.get("include_subfolders", True))
        self._refresh_folder_chips()
        self._update_modes_ui()
        self._resume_interrupted_scan_once = True
        _log.info("resume_incomplete_scan folders=%d mode=%s", len(self._folders), self._selected_mode)
        self._begin_scan()


    def _on_scan_progress(self, data: dict) -> None:
        self._scan_hud.update_progress(data)

    def _do_page_update(self) -> None:
        """Call page.update() and log any failure instead of silently ignoring it."""
        try:
            self._bridge.flet_page.update()
        except Exception as exc:
            _log.debug("page.update() failed in progress callback: %s", exc)

    def _on_scan_complete(self, results: list, mode: str) -> None:
        self._scan_accept_progress = False
        self._bump_cancel_watchdog_token()
        self._pause_scan_btn.visible = False
        eng_wall = self._scan_hud.last_progress_elapsed_seconds
        frozen_scan_elapsed = ScanHUD._fmt_elapsed_compact(
            max(0.0, time.monotonic() - self._scan_hud.scan_elapsed_start, eng_wall)
        )
        self._scan_hud.stop_elapsed_timer()
        if self._was_cancelled:
            self._scan_hud.complete_cancelled(list(results), mode, frozen_scan_elapsed)
            return

        self._clear_incomplete_scan_session()
        try:
            self._refresh_paused_scans()
        except Exception:
            pass
        self._scan_hud.complete_success(results, frozen_scan_elapsed)

        self._bridge.dispatch_scan_complete(results, mode)
        try:
            reclaimed = int(sum(getattr(g, "reclaimable", 0) for g in results))
        except Exception:
            reclaimed = 0
        try:
            self._scan_complete_banner.show(
                group_count=len(results),
                reclaimable=reclaimed,
                elapsed_label=frozen_scan_elapsed,
            )
        except Exception:
            pass
        if reclaimed >= 1_073_741_824:
            self._bridge.show_snackbar(
                f"Great cleanup! Reclaimable space exceeds 1 GB ({fmt_size(reclaimed)}).",
                success=True,
            )
        self._bridge.play_sound("success")

    def _on_scan_error(self, msg: str) -> None:
        self._scan_accept_progress = False
        self._bump_cancel_watchdog_token()
        if "network path unreachable:" in str(msg or "").lower():
            root = self._extract_unreachable_root(str(msg))
            if root:
                self._handle_repeated_io_failure(root)
                return
        self._pause_scan_btn.visible = False
        self._scan_hud.on_scan_error()
        try:
            self._persist_incomplete_scan_session(
                status="error",
                progress_snapshot=dict(self._scan_hud_snap or {}),
            )
        except Exception:
            self._persist_incomplete_scan_session(status="error")
        self._bridge.abort_scan_session()
        self._status.value = f"Scan error: {msg}"
        DashboardPage._safe_update(self)
        self._bridge.play_sound("error")

    def _folders_readable_for_continue_scan(self) -> tuple[bool, str]:
        """Return (True, '') if every scan folder exists and is readable; else (False, hint path)."""
        for raw in list(getattr(self, "_folders", []) or []):
            p = Path(raw)
            try:
                resolved = p.resolve()
            except OSError:
                resolved = p
            try:
                if not resolved.exists():
                    return False, str(p)
                if not os.access(os.fspath(resolved), os.R_OK):
                    return False, str(p)
            except OSError:
                return False, str(p)
        return True, ""

    def _sync_pause_scan_hero_button(self) -> None:
        """Show Pause / Continue scan under START when a scan is active; hide when idle or cancelling."""
        btn = self._pause_scan_btn
        try:
            scanning = bool(self._bridge.backend.is_scanning)
        except Exception:
            scanning = False
        show = scanning and bool(self._scan_view.visible) and not self._was_cancelled
        if not show:
            btn.visible = False
            btn.text = "Pause scan"
            btn.icon = ft.icons.Icons.PAUSE
            btn.style = pill_outlined_button_style(self._t)
            btn.disabled = False
            DashboardPage._safe_update(btn)
            return
        paused = False
        try:
            paused = bool(self._bridge.backend.is_paused)
        except Exception:
            paused = False
        if paused:
            btn.text = "Continue scan"
            btn.icon = ft.icons.Icons.PLAY_ARROW
            btn.style = pill_outlined_button_style(self._t, success=True)
        else:
            btn.text = "Pause scan"
            btn.icon = ft.icons.Icons.PAUSE
            btn.style = pill_outlined_button_style(self._t)
        btn.visible = True
        btn.disabled = False
        DashboardPage._safe_update(btn)
        try:
            self._scan_hud.sync_pause_button(is_paused=paused, is_scanning=show)
        except Exception:
            pass

    def _on_hero_pause_toggle(self, _e: ft.ControlEvent) -> None:
        if self._was_cancelled:
            return
        try:
            if not self._bridge.backend.is_scanning:
                return
        except Exception:
            return
        try:
            if self._bridge.backend.is_paused:
                ok, bad = self._folders_readable_for_continue_scan()
                if not ok:
                    try:
                        self._bridge.show_snackbar(
                            f"Cannot continue — folder not accessible ({bad}). Reconnect the drive and try again.",
                            info=True,
                        )
                    except Exception:
                        pass
                    return
                self._bridge.backend.resume_scan()
                try:
                    self._persist_incomplete_scan_session(status="in_progress")
                except Exception:
                    _log.debug("persist after continue scan failed", exc_info=True)
            else:
                self._bridge.backend.pause_scan()
                try:
                    self._persist_incomplete_scan_session(status="in_progress")
                except Exception:
                    _log.debug("persist after pause scan failed", exc_info=True)
        except Exception:
            _log.exception("Hero pause/continue")
        self._sync_pause_scan_hero_button()

    def _stop_scan(self, e: ft.ControlEvent) -> None:
        elapsed_minutes = max(0, int((time.monotonic() - self._scan_hud.scan_elapsed_start) / 60))
        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Cancel scanning?"),
            content=ft.Text(
                f"{elapsed_minutes} minute(s) of progress will be lost."
            ),
            actions=[
                ft.TextButton("Keep Scanning", on_click=lambda _ev: self._bridge.dismiss_top_dialog()),
                ft.FilledButton("Cancel Scan", on_click=self._confirm_stop_scan),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self._bridge.show_modal_dialog(dialog)

    def _confirm_stop_scan(self, _e: ft.ControlEvent) -> None:
        self._bridge.dismiss_top_dialog()
        self._persist_incomplete_scan_session(status="cancel_requested")
        snap = dict(self._scan_hud_snap or {})
        _log.info(
            "cancel_requested stage=%s scanned=%s total=%s candidates=%s",
            snap.get("stage", ""),
            snap.get("scanned", 0),
            snap.get("total", 0),
            snap.get("candidates_found", 0),
        )
        self._was_cancelled = True
        self._sync_pause_scan_hero_button()
        self._scan_hud.show_cancelling()
        self._bump_cancel_watchdog_token()
        token = self._cancel_watchdog_token
        DashboardPage._safe_update(self)
        try:
            self._bridge.flet_page.update()
        except Exception:
            pass
        try:
            self._bridge.backend.cancel_scan()
            try:
                self._bridge.flet_page.run_task(self._cancel_watchdog_tick, token)
            except Exception:
                pass
        except Exception as err:
            _log.error("Failed to stop scan: %s", err)

    async def _cancel_watchdog_tick(self, token: int) -> None:
        """Keep users informed if engine cancellation takes longer than expected."""
        await asyncio.sleep(15.0)
        if token != self._cancel_watchdog_token:
            return
        if not self._scan_view.visible or not self._was_cancelled:
            return
        stage = str((self._scan_hud_snap or {}).get("stage") or "")
        scanned = int((self._scan_hud_snap or {}).get("scanned") or 0)
        total = int((self._scan_hud_snap or {}).get("total") or 0)
        backend_running = False
        try:
            backend_running = bool(getattr(self._bridge.backend, "is_scanning", False))
        except Exception:
            backend_running = False
        _log.warning(
            "cancel_waiting stage=%s scanned=%d total=%d backend_scanning=%s",
            stage,
            scanned,
            total,
            backend_running,
        )
        self._scan_hud.update_cancel_watchdog()
        DashboardPage._safe_update(self)
        # Keep notifying while cancellation is still pending.
        if backend_running:
            try:
                self._bridge.flet_page.run_task(self._cancel_watchdog_tick, token)
            except Exception:
                pass

    @staticmethod
    def _extract_unreachable_root(message: str) -> str:
        text = str(message or "").strip()
        m = re.search(r"Network path unreachable:\s*(.+)$", text)
        if not m:
            return ""
        return str(m.group(1)).strip()

    def _handle_repeated_io_failure(self, root: str) -> None:
        key = str(root).strip()
        if not key:
            return
        hits = int(self._io_failure_hits_by_root.get(key, 0)) + 1
        self._io_failure_hits_by_root[key] = hits
        self._status.value = f"I/O issue on {key} (attempt {hits})"
        DashboardPage._safe_update(self._status)
        if hits < 3 or self._io_pause_dialog_open:
            return

        self._io_pause_dialog_open = True
        self._io_paused_root = key
        try:
            self._bridge.backend.pause_scan()
        except Exception:
            _log.exception("Failed to pause scan after repeated I/O failures")
        self._sync_pause_scan_hero_button()

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Drive disconnected"),
            content=ft.Text(
                f"Repeated read failures were detected at:\n{key}\n\n"
                "The scan is paused. Choose Continue scan to keep trying, or Cancel to stop now and keep partial results."
            ),
            actions=[
                ft.TextButton("Continue scan", on_click=self._resume_after_io_pause),
                ft.FilledButton("Cancel & Keep Partial Results", on_click=self._cancel_after_io_pause),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self._bridge.show_modal_dialog(dialog)

    def _resume_after_io_pause(self, _e: ft.ControlEvent) -> None:
        self._bridge.dismiss_top_dialog()
        self._io_pause_dialog_open = False
        if self._io_paused_root:
            self._io_failure_hits_by_root[self._io_paused_root] = 0
        self._io_paused_root = ""
        ok, bad = self._folders_readable_for_continue_scan()
        if not ok:
            try:
                self._bridge.show_snackbar(
                    f"Cannot continue — folder not accessible ({bad}). Reconnect the drive and try again.",
                    info=True,
                )
            except Exception:
                pass
            self._sync_pause_scan_hero_button()
            return
        try:
            self._bridge.backend.resume_scan()
            try:
                self._persist_incomplete_scan_session(status="in_progress")
            except Exception:
                _log.debug("persist after I/O continue failed", exc_info=True)
        except Exception:
            _log.exception("Failed to continue scan after I/O pause")
        self._sync_pause_scan_hero_button()

    def _cancel_after_io_pause(self, _e: ft.ControlEvent) -> None:
        self._bridge.dismiss_top_dialog()
        self._io_pause_dialog_open = False
        paused_root = self._io_paused_root
        self._io_paused_root = ""
        self._persist_incomplete_scan_session(status="cancel_requested")
        self._was_cancelled = True
        try:
            self._bridge.backend.cancel_scan()
        except Exception:
            _log.exception("Failed to cancel scan after I/O pause")
        self._scan_hud.show_cancelling()
        if paused_root:
            self._status.value = f"Drive disconnected at {paused_root}. Cancelling and preserving partial results."
            DashboardPage._safe_update(self._status)
        self._sync_pause_scan_hero_button()

    def _open_workspace_from_scan_complete(self) -> None:
        """Hand off to Workspace with the latest scan groups loaded."""
        self._scan_complete_banner.hide()
        self._pause_scan_btn.visible = False
        self._scan_hud.dismiss_to_home()
        self._status.value = "Preparing workspace…"
        DashboardPage._safe_update(self._status)
        try:
            state = self._bridge.state
            groups = list(state.groups)
            mode = str(state.scan_mode or "files")
            if groups:
                self._bridge.dispatch_scan_complete(groups, mode)
            self._bridge.navigate("review")
        except Exception as err:
            _log.error("Open Workspace from scan-complete banner failed: %s", err)

    def _go_to_results(self, e: ft.ControlEvent) -> None:
        """Navigate to results after a successful scan completion."""
        self._pause_scan_btn.visible = False
        self._scan_hud.dismiss_to_home()
        self._status.value = "Scan complete."
        DashboardPage._safe_update(self)
        try:
            self._bridge.navigate("review")
        except Exception:
            pass

    def _go_to_partial_results(self, e: ft.ControlEvent) -> None:
        """Navigate to results page with whatever groups the scanner found before cancel."""
        results = self._pending_partial_results
        mode = self._pending_partial_mode
        if not results:
            try:
                self._bridge.show_snackbar(
                    "No duplicate groups could be built before cancellation — nothing to review.",
                    info=True,
                )
            except Exception:
                pass
            return
        self._pause_scan_btn.visible = False
        self._scan_hud.dismiss_to_home()
        self._hide_cancelled_results_banner()
        self._status.value = f"Scan cancelled — {len(results):,} partial groups available."
        DashboardPage._safe_update(self)
        try:
            self._bridge.dispatch_scan_complete(results, mode)
            self._bridge.navigate("review")
        except Exception as err:
            _log.error("Navigate to partial results failed: %s", err)

    def _go_to_home(self, e: ft.ControlEvent) -> None:
        """Dismiss the scan view and return to the main panels."""
        self._cancel_user_dismissed_choice = True
        self._pause_scan_btn.visible = False
        pending = list(self._pending_partial_results or [])
        had_partial = len(pending) > 0 and self._was_cancelled
        self._bridge.abort_scan_session()
        self._scan_hud.dismiss_to_home()
        if had_partial:
            self._show_cancelled_results_banner(
                f"Partial scan: {len(pending):,} duplicate group(s) are still available — open from this banner when you are ready."
            )
        self._show_cancelled_status()
        DashboardPage._safe_update(self)


    @staticmethod
    def _format_folder_chip_label(path: Path) -> str:
        return str(path)

    async def _clear_status_after(self, token: int, seconds: float) -> None:
        await asyncio.sleep(seconds)
        if token != self._status_token:
            return
        self._status.value = ""
        DashboardPage._safe_update(self._status)

    def _show_cancelled_status(self) -> None:
        ts = time.strftime("%H:%M:%S")
        self._status_token += 1
        token = self._status_token
        self._status.value = f"Scan cancelled at {ts}."
        DashboardPage._safe_update(self._status)
        try:
            self._bridge.flet_page.run_task(self._clear_status_after, token, 5.0)
        except Exception:
            pass

    async def _hide_cancelled_banner_after(self, token: int, seconds: float) -> None:
        await asyncio.sleep(seconds)
        if token != self._cancelled_banner_token:
            return
        self._cancelled_results_banner.visible = False
        DashboardPage._safe_update(self._cancelled_results_banner)

    def _cancelled_banner_timeout_settings(self) -> tuple[bool, float]:
        auto_hide = True
        timeout_seconds = 60.0
        try:
            settings = self._bridge.get_settings()
            general = settings.get("general", {}) if isinstance(settings, dict) else {}
            auto_hide = bool(general.get("partial_results_banner_auto_hide", True))
            raw_timeout = int(general.get("partial_results_banner_timeout_seconds", 60) or 60)
            timeout_seconds = 30.0 if raw_timeout == 30 else 60.0
        except Exception:
            pass
        return auto_hide, timeout_seconds

    def _show_cancelled_results_banner(self, message: str) -> None:
        self._cancelled_banner_token += 1
        token = self._cancelled_banner_token
        self._cancelled_results_text.value = str(message)
        self._cancelled_results_banner.visible = True
        DashboardPage._safe_update(self._cancelled_results_banner)
        auto_hide, timeout_seconds = self._cancelled_banner_timeout_settings()
        if not auto_hide:
            return
        try:
            self._bridge.flet_page.run_task(self._hide_cancelled_banner_after, token, timeout_seconds)
        except Exception:
            pass

    def _hide_cancelled_results_banner(self) -> None:
        self._cancelled_banner_token += 1
        self._cancelled_results_banner.visible = False
        DashboardPage._safe_update(self._cancelled_results_banner)

    @staticmethod
    def _shorten_path(path: str, max_len: int = 88) -> str:
        p = str(path)
        if len(p) <= max_len:
            return f"Current: {p}"
        head = max_len // 2 - 2
        tail = max_len - head - 3
        return f"Current: {p[:head]}...{p[-tail:]}"

    def _refresh_reduce_motion(self) -> None:
        """Re-read accessibility.reduce_motion and push to motion-gated Home controls."""
        enabled = self._bridge.is_reduce_motion_enabled()
        if enabled == self._reduce_motion:
            return
        self._reduce_motion = enabled
        self._home_chrome.set_reduce_motion(enabled)
        self._folder_panel.set_reduce_motion(enabled)
        for section in (self._scan_section, self._recent_section, self._summary_section):
            section.set_reduce_motion(enabled)

    def on_show(self) -> None:
        import time

        self._refresh_reduce_motion()

        # Home is a singleton page. If a scan already finished, returning to Home
        # from top navigation should always restore the normal dashboard shell.
        try:
            is_scanning = bool(self._bridge.backend.is_scanning)
        except Exception:
            is_scanning = False
        # ``is_scanning`` can briefly disagree with the HUD; if the chunk bar already latched
        # complete, treat the run as finished so Home does not resurrect a zombie scan surface.
        if self._scan_hud.visible and (not is_scanning or self._scan_hud.bar_is_complete):
            self._pause_scan_btn.visible = False
            self._scan_hud.hide_if_idle(is_scanning=is_scanning)
            self._status.value = ""
            DashboardPage._safe_update(self)

        # F11: avoid repeated heavy refresh; first show does full async load,
        # later shows lightweight cache-backed refresh and throttled UI refreshes.
        self._schedule_dashboard_data_fetch()
        now = time.monotonic()
        should_refresh_lists = (not self._initial_load_done) or ((now - self._last_on_show_ts) > 1.5)
        if should_refresh_lists:
            self._last_on_show_ts = now
            try:
                self._refresh_paused_scans()
            except Exception:
                _log.debug("checkpoint refresh on show failed", exc_info=True)
        self._initial_load_done = True
        # Do not call super().update() here unnecessarily if _fetch handled updates

    def apply_theme(self, mode: str) -> None:
        """Updates theme properties without destroying UI controls."""
        preset_id = None
        try:
            appearance = (self._bridge.get_settings() or {}).get("appearance") or {}
            preset_id = str(appearance.get("ui_theme_preset", "") or "") or None
        except Exception:
            preset_id = None
        self._t = theme_for_mode(mode, preset_id)
        self._refresh_reduce_motion()

        self._home_chrome.sync_theme(self._t)
        apply_flat_style(self._workflow_stack, self._t)
        self._scan_section.sync_theme(self._t)
        self._recent_section.sync_theme(self._t)
        self._summary_section.sync_theme(self._t)
        self._scan_complete_banner.sync_theme(self._t)

        # Refresh text colors and stats to match new theme
        self._mode_label.color = self._t.colors.fg_muted
        self._scan_hud.apply_theme(self._t)
        self._stats_presence.sync_theme(self._t)
        self._scan_opts.sync_theme(self._t)
        self._update_stats_ui(refresh_presence_force=True)
        self._update_modes_ui()
        self._folder_panel.sync_theme(self._t)
        self._refresh_folder_chips()
        self._apply_dashboard_pill_chrome()
        self._folder_section_icon.color = self._t.colors.accent
        DashboardPage._safe_update(self._hero_tagline_icon)
        DashboardPage._safe_update(self._folder_section_icon)

        if self._is_mounted():
            self.update()
