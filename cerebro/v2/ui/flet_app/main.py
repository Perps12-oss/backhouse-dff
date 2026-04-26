"""Cerebro Flet app entrypoint.

Creates the backend services, state bridge, page builders, and launches
the Flet application with the navigation-rail layout.
"""

from __future__ import annotations

import logging
import sys
from typing import Callable, Dict

import flet as ft

from cerebro.v2.state import StateStore
from cerebro.v2.state.actions import ResultsFilesRemoved, ScanCompleted, SetActiveTab
from cerebro.v2.state.app_state import AppState, create_initial_state
from cerebro.v2.coordinator import CerebroCoordinator
from cerebro.v2.ui.flet_app.layout import AppLayout
from cerebro.v2.ui.flet_app.routes import default_route, key_for_route
from cerebro.v2.ui.flet_app.services.backend_service import BackendService
from cerebro.v2.ui.flet_app.services.state_bridge import StateBridge
from cerebro.v2.ui.flet_app.theme import theme_for_mode

_log = logging.getLogger(__name__)


def run_flet_app() -> None:
    """Launch the Cerebro Flet UI."""
    ft.app(target=_main)


def _main(page: ft.Page) -> None:
    """Configure the page and wire up all services."""
    page.title = "Cerebro — Duplicate File Finder"
    page.window.width = 1200
    page.window.height = 800
    page.window.min_width = 800
    page.window.min_height = 600
    page.theme_mode = ft.ThemeMode.SYSTEM
    page.bgcolor = "#0A0E14"
    page.padding = 0
    page.spacing = 0

    theme = theme_for_mode("light")
    page.theme = ft.Theme(
        color_scheme_seed=theme.colors.primary,
        font_family=theme.typography.family,
    )
    dark_theme = theme_for_mode("dark")
    page.dark_theme = ft.Theme(
        color_scheme_seed=dark_theme.colors.primary,
        font_family=dark_theme.typography.family,
    )

    store = StateStore(create_initial_state())
    coordinator = CerebroCoordinator(store)
    backend = BackendService(page)
    bridge = StateBridge(page, store, coordinator, backend)
    settings = bridge.get_settings()
    if not isinstance(settings, dict):
        settings = {}

    def _detect_os_reduce_motion() -> bool:
        if sys.platform != "win32":
            return False
        try:
            import winreg

            key_path = r"Control Panel\Accessibility"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                value, _ = winreg.QueryValueEx(key, "Animation")
                return str(value).strip() == "0"
        except Exception:
            return False

    # Ensure feature settings exist with OS-aware defaults.
    changed_settings = False
    accessibility = settings.get("accessibility")
    if not isinstance(accessibility, dict):
        accessibility = {}
        settings["accessibility"] = accessibility
        changed_settings = True
    if "reduce_motion" not in accessibility:
        accessibility["reduce_motion"] = _detect_os_reduce_motion()
        changed_settings = True

    notifications = settings.get("notifications")
    if not isinstance(notifications, dict):
        notifications = {}
        settings["notifications"] = notifications
        changed_settings = True
    if "sound_enabled" not in notifications:
        notifications["sound_enabled"] = False
        changed_settings = True

    onboarding = settings.get("onboarding")
    if not isinstance(onboarding, dict):
        onboarding = {}
        settings["onboarding"] = onboarding
        changed_settings = True
    if "completed" not in onboarding:
        onboarding["completed"] = False
        changed_settings = True

    if changed_settings:
        bridge.save_settings(settings)

    # Restore persisted window geometry/state when present.
    win_settings = settings.get("window") if isinstance(settings, dict) else {}
    if isinstance(win_settings, dict):
        try:
            w = win_settings.get("width")
            h = win_settings.get("height")
            x = win_settings.get("left")
            y = win_settings.get("top")
            if isinstance(w, (int, float)):
                page.window.width = max(int(w), int(page.window.min_width or 800))
            if isinstance(h, (int, float)):
                page.window.height = max(int(h), int(page.window.min_height or 600))
            if isinstance(x, (int, float)):
                page.window.left = int(x)
            if isinstance(y, (int, float)):
                page.window.top = int(y)
            if bool(win_settings.get("maximized")):
                page.window.maximized = True
        except Exception:
            _log.exception("Failed restoring persisted window state")

    # Singleton pages so scan results / state survive tab switches.
    from cerebro.v2.ui.flet_app.pages.dashboard_page import DashboardPage
    from cerebro.v2.ui.flet_app.pages.results_page import ResultsPage
    from cerebro.v2.ui.flet_app.pages.review_page import ReviewPage
    from cerebro.v2.ui.flet_app.pages.history_page import HistoryPage
    from cerebro.v2.ui.flet_app.pages.settings_page import SettingsPage

    # FilePicker is a Service: attach via page.services (not overlay) for Flet 0.80+.
    folder_picker = ft.FilePicker()
    page.services.append(folder_picker)

    dashboard_page = DashboardPage(bridge, folder_picker)
    results_page = ResultsPage(bridge)
    review_page = ReviewPage(bridge)
    history_page = HistoryPage(bridge)
    settings_page = SettingsPage(bridge)

    builders: Dict[str, Callable[[], ft.Control]] = {
        "dashboard": lambda: dashboard_page,
        "duplicates": lambda: results_page,
        "review": lambda: review_page,
        "history": lambda: history_page,
        "settings": lambda: settings_page,
    }

    layout = AppLayout(page, bridge, builders)
    page.add(layout)

    def _persist_window_state() -> None:
        try:
            s = bridge.get_settings()
            if not isinstance(s, dict):
                s = {}
            window = s.get("window")
            if not isinstance(window, dict):
                window = {}
            window["width"] = int(page.window.width or 1200)
            window["height"] = int(page.window.height or 800)
            window["left"] = int(page.window.left or 0)
            window["top"] = int(page.window.top or 0)
            window["maximized"] = bool(page.window.maximized)
            s["window"] = window
            bridge.save_settings(s)
        except Exception:
            _log.exception("Failed to persist window state")

    def _show_shortcuts_overlay() -> None:
        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("Keyboard Shortcuts"),
            content=ft.Column(
                [
                    ft.Text("Ctrl+,   Open Settings"),
                    ft.Text("Ctrl+N   New scan (Home)"),
                    ft.Text("Ctrl+R   Open Last Session"),
                    ft.Text("Ctrl+K   Command palette"),
                    ft.Text("?        Show this help"),
                    ft.Text("Left/Right  Previous/Next tab"),
                    ft.Text("Space    Open Review from Results"),
                ],
                tight=True,
                spacing=6,
            ),
            actions=[ft.TextButton("Close", on_click=lambda _e: bridge.dismiss_top_dialog())],
        )
        bridge.show_modal_dialog(dlg)

    def _show_command_palette() -> None:
        def _reset_onboarding_for_next_start() -> None:
            cfg = bridge.get_settings()
            if not isinstance(cfg, dict):
                cfg = {}
            onb = cfg.get("onboarding")
            if not isinstance(onb, dict):
                onb = {}
            onb["completed"] = False
            cfg["onboarding"] = onb
            bridge.save_settings(cfg)
            bridge.show_snackbar("Onboarding reset. It will appear on next app start.", info=True)

        actions: list[tuple[str, Callable[[], None]]] = [
            ("Go to Home", lambda: layout.navigate_to("dashboard")),
            ("Go to Results", lambda: layout.navigate_to("duplicates")),
            ("Go to Review", lambda: layout.navigate_to("review")),
            ("Go to History", lambda: layout.navigate_to("history")),
            ("Go to Settings", lambda: layout.navigate_to("settings")),
            ("Open Last Session", bridge.open_last_session),
            ("Show Keyboard Shortcuts", _show_shortcuts_overlay),
            ("Show Onboarding", lambda: _show_onboarding_if_needed(force=True)),
            ("Reset Onboarding (show on next start)", _reset_onboarding_for_next_start),
        ]

        search = ft.TextField(
            hint_text="Type an action...",
            autofocus=True,
            text_size=13,
            border_radius=8,
            content_padding=ft.padding.symmetric(horizontal=10, vertical=8),
        )
        list_view = ft.ListView(expand=True, spacing=4, padding=0, height=260)

        def _run_action(action: Callable[[], None]) -> None:
            bridge.dismiss_top_dialog()
            try:
                action()
            except Exception:
                _log.exception("Command palette action failed")

        def _row(label: str, action: Callable[[], None]) -> ft.Control:
            return ft.ListTile(
                title=ft.Text(label, size=13),
                dense=True,
                on_click=lambda _e: _run_action(action),
            )

        def _refresh_actions(_e=None) -> None:
            q = (search.value or "").strip().lower()
            filtered = [
                (label, action)
                for label, action in actions
                if not q or q in label.lower()
            ]
            list_view.controls = [_row(label, action) for label, action in filtered]
            if not list_view.controls:
                list_view.controls = [ft.Text("No matching actions.", size=12, color="#94A3B8")]
            try:
                if list_view.page is not None:
                    list_view.update()
            except RuntimeError:
                # Dialog not mounted yet; controls will render once shown.
                pass

        def _submit_first(_e: ft.ControlEvent) -> None:
            q = (search.value or "").strip().lower()
            for label, action in actions:
                if not q or q in label.lower():
                    _run_action(action)
                    return

        search.on_change = _refresh_actions
        search.on_submit = _submit_first

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("Command Palette"),
            content=ft.Container(
                content=ft.Column([search, list_view], spacing=8, tight=True),
                width=520,
                height=340,
            ),
            actions=[ft.TextButton("Close", on_click=lambda _e: bridge.dismiss_top_dialog())],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        bridge.show_modal_dialog(dlg)
        _refresh_actions()

    def _show_onboarding_if_needed(force: bool = False) -> None:
        s = bridge.get_settings()
        if not isinstance(s, dict):
            s = {}
        onboarding_cfg = s.get("onboarding")
        if not isinstance(onboarding_cfg, dict):
            onboarding_cfg = {}
        if (not force) and bool(onboarding_cfg.get("completed", False)):
            return

        steps = [
            ("Select scan folders", "Start on Home using Browse Folders or Quick Add presets."),
            ("Run your first scan", "Use Start Scan to detect duplicate groups and recoverable space."),
            ("Review and clean safely", "Open Results/Review, confirm selections, then move to Trash."),
        ]
        step_idx = {"value": 0}
        step_badge = ft.Container(
            content=ft.Text("Step 1 of 3", size=11, weight=ft.FontWeight.W_600, color="#22D3EE"),
            bgcolor=ft.Colors.with_opacity(0.14, "#22D3EE"),
            border=ft.border.all(1, ft.Colors.with_opacity(0.35, "#22D3EE")),
            border_radius=999,
            padding=ft.padding.symmetric(horizontal=10, vertical=4),
        )
        title_text = ft.Text(
            steps[0][0],
            size=20,
            weight=ft.FontWeight.BOLD,
            color="#E6EDF3",
        )
        desc_text = ft.Text(
            steps[0][1],
            size=13,
            color="#9FB0C2",
        )
        progress = ft.ProgressBar(
            value=1 / 3,
            bar_height=6,
            color="#22D3EE",
            bgcolor=ft.Colors.with_opacity(0.18, "#FFFFFF"),
            border_radius=999,
        )
        dont_show_again = ft.Checkbox(
            label="Don't show again",
            value=False,
            label_style=ft.TextStyle(size=12, color="#9FB0C2"),
        )

        def _render_step() -> None:
            idx = step_idx["value"]
            step_badge.content.value = f"Step {idx + 1} of {len(steps)}"
            title_text.value = steps[idx][0]
            desc_text.value = steps[idx][1]
            progress.value = (idx + 1) / len(steps)
            for ctrl in (step_badge, title_text, desc_text, progress):
                if ctrl.page is not None:
                    ctrl.update()

        def _finish() -> None:
            cfg = bridge.get_settings()
            if not isinstance(cfg, dict):
                cfg = {}
            onb = cfg.get("onboarding")
            if not isinstance(onb, dict):
                onb = {}
            onb["completed"] = bool(dont_show_again.value)
            cfg["onboarding"] = onb
            bridge.save_settings(cfg)
            bridge.dismiss_top_dialog()
            if bool(dont_show_again.value):
                bridge.show_snackbar("Onboarding hidden for future sessions.", info=True)
            else:
                bridge.show_snackbar("Onboarding closed. Press ? for shortcuts anytime.", info=True)

        def _next(_e: ft.ControlEvent) -> None:
            if step_idx["value"] < len(steps) - 1:
                step_idx["value"] += 1
                _render_step()
            else:
                _finish()

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Row(
                [
                    ft.Container(
                        content=ft.Icon(ft.icons.Icons.AUTO_AWESOME, size=18, color="#22D3EE"),
                        width=32,
                        height=32,
                        alignment=ft.Alignment(0, 0),
                        bgcolor=ft.Colors.with_opacity(0.12, "#22D3EE"),
                        border=ft.border.all(1, ft.Colors.with_opacity(0.30, "#22D3EE")),
                        border_radius=8,
                    ),
                    ft.Text("Welcome to Cerebro", size=18, weight=ft.FontWeight.W_700),
                ],
                spacing=10,
            ),
            content=ft.Container(
                width=560,
                padding=16,
                border_radius=14,
                gradient=ft.LinearGradient(
                    begin=ft.Alignment(-1, -1),
                    end=ft.Alignment(1, 1),
                    colors=["#111A24", "#0B121A"],
                ),
                border=ft.border.all(1, ft.Colors.with_opacity(0.16, "#FFFFFF")),
                content=ft.Column(
                    [step_badge, title_text, desc_text, progress, dont_show_again],
                    spacing=12,
                    tight=True,
                ),
            ),
            actions=[
                ft.TextButton(
                    "Skip",
                    on_click=lambda _e: _finish(),
                    style=ft.ButtonStyle(color="#9FB0C2"),
                ),
                ft.FilledButton(
                    "Next",
                    on_click=_next,
                    style=ft.ButtonStyle(
                        bgcolor="#22D3EE",
                        color="#0A0E14",
                        shape=ft.RoundedRectangleBorder(radius=10),
                    ),
                ),
            ],
            bgcolor="#0B121A",
            shape=ft.RoundedRectangleBorder(radius=18),
        )
        bridge.show_modal_dialog(dlg)

    def _cycle_tab(step: int) -> None:
        keys = list(builders.keys())
        if not keys:
            return
        try:
            idx = keys.index(layout.current_key)
        except ValueError:
            idx = 0
        layout.navigate_to(keys[(idx + step) % len(keys)])

    def _on_key_event(e: ft.KeyboardEvent) -> None:
        key = (e.key or "").lower().replace(" ", "")
        ctrl = bool(getattr(e, "ctrl", False) or getattr(e, "meta", False))
        if key in ("?", "slash") and bool(getattr(e, "shift", False)):
            _show_shortcuts_overlay()
            return
        if ctrl and key == "comma":
            layout.navigate_to("settings")
            return
        if ctrl and key == "n":
            layout.navigate_to("dashboard")
            return
        if ctrl and key == "r":
            bridge.open_last_session()
            return
        if ctrl and key == "k":
            _show_command_palette()
            return
        if key in ("arrowleft", "left"):
            _cycle_tab(-1)
            return
        if key in ("arrowright", "right"):
            _cycle_tab(1)
            return
        if key == "space" and layout.current_key == "duplicates":
            try:
                if results_page.get_groups():
                    layout.navigate_to("review")
            except Exception:
                _log.exception("Failed opening Review from Space shortcut")

    page.on_keyboard_event = _on_key_event

    def _on_window_event(e: ft.WindowEvent) -> None:
        if e.data in {"close", "resized", "moved", "maximize", "unmaximize"}:
            _persist_window_state()

    page.window.on_event = _on_window_event

    def _on_route_change(e: ft.RouteChangeEvent) -> None:
        key = key_for_route(e.route)
        layout.navigate_to(key)

    page.on_route_change = _on_route_change
    page.route = default_route()
    # Some Flet builds do not fire on_route_change for initial route assignment.
    # Force initial mount so the content host is never left blank on startup.
    layout.navigate_to(key_for_route(page.route or default_route()))

    def _sync_groups_from_state(s: AppState) -> None:
        groups = list(s.groups)
        mode = s.scan_mode or "files"
        if not groups:
            results_page.load_results([], mode)
            review_page.load_results([], mode, defer_render=(layout.current_key != "review"))
            return
        results_page.load_results(groups, mode)
        if layout.current_key == "review":
            review_page.apply_pruned_groups(groups, mode)
        else:
            # Avoid expensive review-grid construction when user is not on Review.
            review_page.load_results(groups, mode, defer_render=True)

    def _on_state_change(new_state: AppState, _old: AppState, action: object) -> None:
        tab = new_state.active_tab
        # Only tab-changing actions should drive the shell; other dispatches still
        # carry active_tab (e.g. duplicates) and would otherwise yank the user back
        # from Review/Settings while the rail already matched the new selection.
        take_nav = (
            tab
            and tab in builders
            and tab != layout.current_key
            and isinstance(action, (SetActiveTab, ScanCompleted))
        )
        if take_nav:
            layout.navigate_to(tab)
        if isinstance(action, (ScanCompleted, ResultsFilesRemoved)):
            _sync_groups_from_state(new_state)
        if isinstance(action, ScanCompleted):
            history_page.load_history(bridge.get_scan_history_table_rows())
        if isinstance(action, (ScanCompleted, ResultsFilesRemoved)):
            history_page.load_deletion_history(bridge.get_deletion_history_table_rows())

    bridge.set_on_state_change(_on_state_change)
    bridge.subscribe()

    def _on_theme_change(mode: str) -> None:
        for p in (dashboard_page, results_page, review_page, history_page, settings_page):
            try:
                p.apply_theme(mode)
            except Exception:
                _log.exception("apply_theme failed on %s", type(p).__name__)

    bridge.set_on_theme_change(_on_theme_change)

    history_page.load_history(bridge.get_scan_history_table_rows())
    history_page.load_deletion_history(bridge.get_deletion_history_table_rows())

    appearance = bridge.get_settings().get("appearance") or {}
    bridge.apply_preset_theme(str(appearance.get("ui_theme_preset", "arctic")))
    _show_onboarding_if_needed()

    _log.info("Cerebro Flet UI initialized")
