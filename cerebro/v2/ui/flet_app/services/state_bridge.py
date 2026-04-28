"""State bridge: connects the existing StateStore to Flet's UI thread.

Subscribes to the StateStore and triggers page.update() on every state
change so Flet re-renders the affected controls. Also provides helpers
to read current state without direct store access.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING

import flet as ft

from cerebro.engines.base_engine import DuplicateGroup
from cerebro.v2.coordinator import CerebroCoordinator
from cerebro.v2.state import StateStore
from cerebro.v2.state.actions import ThemeChanged
from cerebro.v2.state.app_state import AppState
from cerebro.v2.ui.flet_app.services.stats_service import get_stats_service

if TYPE_CHECKING:
    from cerebro.v2.ui.flet_app.services.backend_service import BackendService

_log = logging.getLogger(__name__)

_SETTINGS_PATH = Path.home() / ".cerebro" / "flet_ui_settings.json"


class StateBridge:
    """Single bridge between StateStore and Flet page updates.

    Usage:
        bridge = StateBridge(page, store, coordinator, backend)
        bridge.subscribe()  # starts listening to store changes
    """

    def __init__(
        self,
        page: ft.Page,
        store: StateStore,
        coordinator: CerebroCoordinator,
        backend: "BackendService",
    ) -> None:
        self._page = page
        self._store = store
        self._coordinator = coordinator
        self._backend = backend
        self._unsubscribe: Optional[Callable[[], None]] = None
        self._on_state_change: Optional[Callable[[AppState, AppState, object], None]] = None
        self._on_theme_change: Optional[Callable[[str], None]] = None
        self._visual_theme: str = "light"
        self._scan_session: Dict[str, Any] = {}
        self._suppress_page_update: bool = False
        self._last_page_update_ts: float = 0.0  # B3: throttle progress-tick updates
        self._progress_controls: list[ft.Control] = []
        self._action_controls: dict[str, list[ft.Control]] = {}
        self._structural_actions: set[str] = {"SetActiveTab", "ScanCompleted"}
        self._stats_service = get_stats_service()
        self._stats_service.set_on_refresh(self._on_stats_refreshed)

    @property
    def app_theme(self) -> str:
        """Effective light/dark label for glass morphism overlays (always ``light`` or ``dark``)."""
        return self._visual_theme

    @property
    def flet_page(self) -> ft.Page:
        """Root Flet page — use this when a tab control may be off-screen (not mounted)."""
        return self._page

    def show_modal_dialog(self, dialog: ft.Control) -> None:
        """Open a modal dialog (Flet 0.25+ uses ``Page.show_dialog``, not ``Page.open``)."""
        self._page.show_dialog(dialog)

    def dismiss_top_dialog(self) -> None:
        """Close the top dialog opened with :meth:`show_modal_dialog`."""
        self._page.pop_dialog()

    @property
    def store(self) -> StateStore:
        return self._store

    @property
    def coordinator(self) -> CerebroCoordinator:
        return self._coordinator

    @property
    def backend(self) -> "BackendService":
        return self._backend

    @property
    def state(self) -> AppState:
        return self._store.get_state()

    def subscribe(self) -> None:
        """Start listening to store changes."""
        self._unsubscribe = self._store.subscribe(self._on_store_change)

    def unsubscribe(self) -> None:
        if self._unsubscribe:
            self._unsubscribe()
            self._unsubscribe = None

    def set_on_state_change(self, cb: Callable[[AppState, AppState, object], None]) -> None:
        """Register a callback fired on every state change (new, old, action)."""
        self._on_state_change = cb

    def set_on_theme_change(self, cb: Callable[[str], None]) -> None:
        """Register a callback fired when the user switches light/dark mode."""
        self._on_theme_change = cb

    def register_progress_control(self, ctrl: ft.Control) -> None:
        """Register a control to update on scan-progress actions."""
        if ctrl not in self._progress_controls:
            self._progress_controls.append(ctrl)

    def register_action_control(self, action_type_name: str, ctrl: ft.Control) -> None:
        """Register a control to update for a specific action type name."""
        bucket = self._action_controls.setdefault(str(action_type_name), [])
        if ctrl not in bucket:
            bucket.append(ctrl)

    def register_structural_action(self, action_type_name: str) -> None:
        self._structural_actions.add(str(action_type_name))

    def _on_store_change(self, new: AppState, old: AppState, action: object) -> None:
        """Store listener: triggers UI refresh. Progress events are throttled."""
        from cerebro.v2.state.actions import ScanProgressSnapshot
        is_progress = isinstance(action, ScanProgressSnapshot)
        action_name = type(action).__name__

        if self._on_state_change:
            try:
                self._on_state_change(new, old, action)
            except Exception:
                _log.exception("State change callback failed")

        if self._suppress_page_update:
            return

        if is_progress:
            # B3/F1: throttle scan progress to ≤4 page updates/second
            import time as _t
            now = _t.monotonic()
            if (now - self._last_page_update_ts) < 0.25:
                return
            self._last_page_update_ts = now
            updated = False
            for ctrl in list(self._progress_controls):
                try:
                    if ctrl is not None and ctrl.page is not None:
                        ctrl.update()
                        updated = True
                except Exception:
                    continue
            if updated:
                return

        dirty_controls = self._action_controls.get(action_name, [])
        dirty_updated = False
        for ctrl in list(dirty_controls):
            try:
                if ctrl is not None and ctrl.page is not None:
                    ctrl.update()
                    dirty_updated = True
            except Exception:
                continue
        if dirty_updated and action_name not in self._structural_actions:
            return

        try:
            self._page.update()
        except Exception:
            pass

    def _on_stats_refreshed(self, _stats: Dict[str, Any]) -> None:
        """Refresh UI when background stats cache finishes recomputing."""
        try:
            if hasattr(self._page, "run_thread"):
                self._page.run_thread(self._safe_page_update)
            else:
                self._safe_page_update()
        except Exception:
            pass

    def _safe_page_update(self) -> None:
        try:
            self._page.update()
        except Exception:
            pass

    # -- Convenience dispatchers -----------------------------------------------

    def navigate(self, key: str) -> None:
        self._suppress_page_update = True
        try:
            self._coordinator.set_active_tab(key)
        finally:
            self._suppress_page_update = False

    def set_visual_theme(self, mode: str) -> None:
        """Update the glass overlay hint without changing ``Page.theme_mode`` (e.g. color‑seed themes)."""
        self._visual_theme = "dark" if (mode or "").lower() == "dark" else "light"

    def set_theme(self, mode: str) -> None:
        self._visual_theme = "dark" if (mode or "").lower() == "dark" else "light"
        self._page.theme_mode = (
            ft.ThemeMode.DARK if mode == "dark" else ft.ThemeMode.LIGHT
        )
        self._page.update()
        if self._on_theme_change:
            try:
                self._on_theme_change(mode)
            except Exception:
                _log.exception("Theme change callback failed")

    def apply_preset_theme(self, preset_id: str) -> bool:
        """Apply a named palette (Material seed + light/dark shell) and sync app state."""
        from cerebro.v2.ui.flet_app.palette_themes import default_preset, preset_by_id

        preset = preset_by_id(preset_id) or default_preset()
        mode_str = "dark" if preset.is_dark else "light"

        from cerebro.v2.ui.flet_app.theme import build_flet_theme
        self._page.theme_mode = ft.ThemeMode.DARK if preset.is_dark else ft.ThemeMode.LIGHT
        self._page.theme = build_flet_theme(mode_str, seed=preset.seed)
        self._page.dark_theme = build_flet_theme(mode_str, seed=preset.seed)
        self._visual_theme = mode_str

        try:
            self._store.dispatch(ThemeChanged(mode_str))
        except Exception:
            _log.exception("ThemeChanged dispatch failed")

        self._page.update()
        if self._on_theme_change:
            try:
                self._on_theme_change(mode_str)
            except Exception:
                _log.exception("Theme change callback failed")
        return True

    def begin_scan_session(self, folders: List[Any], mode: str) -> None:
        """Record folders and start time so a completed scan can be written to scan history."""
        self._scan_session = {
            "folders": [str(p) for p in folders],
            "mode": mode or "files",
            "t0": time.monotonic(),
        }

    def abort_scan_session(self) -> None:
        """Clear a scan session when the job errors or is cancelled (no DB row)."""
        self._scan_session = {}

    def dispatch_scan_complete(
        self, groups: List[DuplicateGroup], mode: str
    ) -> None:
        self._coordinator.scan_completed(groups, mode)
        self._persist_scan_history(groups, mode or "files")
        self._scan_session = {}

    def _persist_scan_history(self, groups: List[DuplicateGroup], mode: str) -> None:
        try:
            from cerebro.v2.core.scan_history_db import get_scan_history_db

            ses = self._scan_session or {}
            folders = [str(x) for x in ses.get("folders", [])]
            t0 = ses.get("t0")
            duration = max(0.0, time.monotonic() - float(t0)) if t0 is not None else 0.0
            total_files = sum(len(g.files) for g in groups)
            reclaimable = sum(g.reclaimable for g in groups)
            get_scan_history_db().record_scan(
                mode=mode,
                folders=folders,
                groups_found=len(groups),
                files_found=total_files,
                bytes_reclaimable=int(reclaimable),
                duration_seconds=duration,
            )
        except Exception:
            _log.exception("Persist scan history failed")

    def get_stats(self) -> Dict[str, Any]:
        """Aggregate stats for the dashboard cards (cached + background refresh)."""
        return self._stats_service.get_stats()

    def invalidate_stats_cache(self) -> None:
        self._stats_service.invalidate()

    def get_recent_scans(self, limit: int = 5) -> List[Dict[str, Any]]:
        """Recent scans for the home page list (same shape as dashboard rows)."""
        return self.get_scan_history_table_rows(limit=limit)

    def get_scan_history_table_rows(self, limit: int = 500) -> List[Dict[str, Any]]:
        from cerebro.v2.core.scan_history_db import get_scan_history_db

        out: List[Dict[str, Any]] = []
        for e in get_scan_history_db().get_recent(int(limit)):
            folders = e.folders or []
            label = ", ".join(Path(x).name for x in folders[:3])
            if len(folders) > 3:
                label = f"{label}…" if label else "…"
            out.append(
                {
                    "date": datetime.fromtimestamp(e.timestamp).strftime("%Y-%m-%d %H:%M"),
                    "mode": e.mode,
                    "folder": label,
                    "groups_found": e.groups_found,
                    "files_scanned": e.files_found,
                    "bytes_reclaimable": e.bytes_reclaimable,
                    "duration": f"{e.duration_seconds:.1f}s",
                }
            )
        return out

    def get_deletion_history_table_rows(self, limit: int = 500) -> List[Dict[str, Any]]:
        from cerebro.v2.core.deletion_history_db import get_default_history_manager

        rows: List[Dict[str, Any]] = []
        for row in get_default_history_manager().get_recent_history(int(limit)):
            try:
                rows.append(
                    {
                        "date": str(row[4])[:22],
                        "policy": str(row[5]),
                        "count": 1,
                        "bytes": int(row[3]),
                        "status": "Deleted",
                    }
                )
            except (IndexError, TypeError, ValueError):
                continue
        return rows

    def clear_history(self, tab_key: str) -> None:
        if tab_key == "scan":
            from cerebro.v2.core.scan_history_db import get_scan_history_db

            get_scan_history_db().clear()
        elif tab_key == "deletion":
            from cerebro.v2.core.deletion_history_db import get_default_history_manager

            get_default_history_manager().clear_history()

    def open_last_session(self) -> None:
        """Restore the last in‑memory scan results, if the backend still holds them."""
        cached = self._backend.get_results()
        if cached:
            mode = self.state.scan_mode or "files"
            self._coordinator.scan_completed(list(cached), mode)
            self._coordinator.set_active_tab("duplicates")
            self.show_snackbar("Restored the last scan from memory.", success=True)
            return
        self.show_snackbar("No scan results in memory. Run a new scan from Home.", info=True)

    def get_settings(self) -> Dict[str, Any]:
        if not _SETTINGS_PATH.exists():
            return {}
        try:
            raw = _SETTINGS_PATH.read_text(encoding="utf-8")
            data = json.loads(raw)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError, TypeError):
            return {}

    def save_settings(self, data: Dict[str, Any]) -> None:
        _SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        _SETTINGS_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def is_reduce_motion_enabled(self) -> bool:
        settings = self.get_settings()
        accessibility = settings.get("accessibility") if isinstance(settings, dict) else {}
        return bool(isinstance(accessibility, dict) and accessibility.get("reduce_motion", False))

    def is_sound_enabled(self) -> bool:
        settings = self.get_settings()
        notifications = settings.get("notifications") if isinstance(settings, dict) else {}
        return bool(isinstance(notifications, dict) and notifications.get("sound_enabled", False))

    def play_sound(self, event: str = "default") -> None:
        if not self.is_sound_enabled():
            return
        if sys.platform != "win32":
            return
        try:
            import winsound

            if event == "success":
                winsound.MessageBeep(winsound.MB_OK)
            elif event == "error":
                winsound.MessageBeep(winsound.MB_ICONHAND)
            else:
                winsound.MessageBeep(winsound.MB_ICONASTERISK)
        except Exception:
            _log.exception("Failed to play sound event %s", event)

    def get_cache_path(self) -> str:
        p = Path.home() / ".cerebro" / "cache"
        p.mkdir(parents=True, exist_ok=True)
        return str(p)

    def show_snackbar(
        self,
        message: str,
        *,
        error: bool = False,
        success: bool = False,
        info: bool = False,
        action_label: str | None = None,
        on_action: Callable[[ft.ControlEvent], None] | None = None,
    ) -> None:
        if error:
            bg = "#B91C1C"
        elif success:
            bg = "#166534"
        elif info:
            bg = "#334155"
        else:
            bg = "#1E293B"
        self._page.snack_bar = ft.SnackBar(
            content=ft.Text(str(message)),
            bgcolor=bg,
            action=action_label,
            on_action=on_action,
        )
        self._page.snack_bar.open = True
        self._page.update()
