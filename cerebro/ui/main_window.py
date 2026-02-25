# cerebro/ui/main_window.py
"""
CEREBRO v5.0 — Main Window
Enhanced with proper ReviewPage → Pipeline → DeletionEngine → HistoryStore wiring
while preserving the existing v5 navigation shell (StateBus + StationNavigator).

Authoritative Target Architecture (implemented):
ReviewPage (UI) emits DeletionPlan (intent only)
    ↓
MainWindow confirms + dispatches to Pipeline
    ↓
core/pipeline.py validates + expands → ExecutableDeletePlan
    ↓
core/deletion.py executes (trash/permanent)
    ↓
history/store.py records audit (owned by pipeline)
"""

from __future__ import annotations

from typing import Dict, Any, Optional, List
from pathlib import Path

from PySide6.QtCore import QTimer, Qt, QThread, Signal, Slot
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QStackedWidget,
    QMessageBox, QFrame, QLabel
)

from cerebro.services.logger import log_info, log_error, log_debug
from cerebro.util.ui_utils import restore_main_window_geometry, ensure_window_on_screen
from cerebro.ui.pages.station_navigator import StationNavigator
from cerebro.ui.state_bus import get_state_bus
from cerebro.ui.theme_engine import get_theme_manager, current_colors
from cerebro.ui.widgets.toast import ToastOverlay, ToastAction

from cerebro.ui.pages.start_page import StartPage
from cerebro.ui.pages.scan_page import ScanPage
from cerebro.ui.pages.review_page import ReviewPage
from cerebro.ui.pages.history_page import HistoryPage
from cerebro.ui.pages.theme_page import ThemePage
from cerebro.ui.pages.settings_page import SettingsPage
from cerebro.ui.pages.audit_page import AuditPage
from cerebro.ui.pages.hub_page import HubPage

# Target-architecture core
from cerebro.core.pipeline import CerebroPipeline, ExecutableDeletePlan, DeletionResult


class ThemedStack(QStackedWidget):
    """Stacked widget that propagates theme changes to all children."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("pageStack")

    def propagate_theme(self) -> None:
        """Force theme refresh on all pages."""
        colors = current_colors()
        for i in range(self.count()):
            widget = self.widget(i)
            if widget:
                if hasattr(widget, 'refresh_theme'):
                    widget.refresh_theme()
                elif hasattr(widget, 'on_theme_changed'):
                    widget.on_theme_changed()
                else:
                    bg = colors.get('bg', '#0f1115')
                    widget.setStyleSheet(f"""
                        QWidget {{
                            background-color: {bg};
                        }}
                    """)


class PipelineCleanupWorker(QThread):
    """
    Background worker that executes a validated ExecutableDeletePlan through the pipeline.

    Important:
    - Pipeline owns execution + audit.
    - UI only receives progress and results.
    """
    progress = Signal(int, int, str)   # current, total, current_file_name
    finished = Signal(object)          # DeletionResult
    error = Signal(str)
    cancelled = Signal()

    def __init__(self, pipeline: CerebroPipeline, plan: ExecutableDeletePlan, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._pipeline = pipeline
        self._plan = plan
        self._cancel_requested = False

    def cancel(self) -> None:
        self._cancel_requested = True

    def run(self) -> None:
        try:
            # Temporary debug: worker lifecycle logging
            try:
                log_debug("[DEBUG] CleanupWorker.run start")
            except Exception:
                pass

            def progress_cb(current: int, total: int, current_file: str) -> bool:
                self.progress.emit(current, total, current_file)
                return not self._cancel_requested

            try:
                log_debug(
                    f"[DEBUG] CleanupWorker calling execute_delete_plan ops={len(getattr(self._plan, 'operations', []) )}"
                )
            except Exception:
                pass

            result = self._pipeline.execute_delete_plan(self._plan, progress_cb=progress_cb)

            try:
                deleted_count = len(getattr(result, "deleted", []))
                failed_count = len(getattr(result, "failed", []))
                log_debug(
                    f"[DEBUG] CleanupWorker execute_delete_plan returned deleted={deleted_count} failed={failed_count}"
                )
            except Exception:
                pass

            if self._cancel_requested:
                self.cancelled.emit()
                return
            self.finished.emit(result)
        except Exception as e:
            try:
                log_debug(f"[DEBUG] CleanupWorker.run exception: {e}")
            except Exception:
                pass
            self.error.emit(str(e))


class MainWindow(QMainWindow):
    """Main application window with safe navigation and authoritative cleanup integration."""

    def __init__(self):
        super().__init__()
        self.setObjectName("MainWindow")
        self.setWindowTitle("CEREBRO v5.0")
        
        # Enable window resizing and standard controls (minimize, maximize, close)
        self.setWindowFlags(
            Qt.WindowType.Window |                    # Standard window
            Qt.WindowType.WindowMinMaxButtonsHint |  # Enable min/max buttons
            Qt.WindowType.WindowCloseButtonHint |    # Enable close button
            Qt.WindowType.WindowSystemMenuHint       # Enable system menu (context menu on title bar)
        )
        
        # Set initial size (resizable, not fixed)
        self.resize(1400, 900)
        
        # Set minimum and maximum sizes (reasonable bounds)
        self.setMinimumSize(800, 600)    # Minimum usable size
        # Don't set maximum size - let it scale to screen size
        
        self._bus = get_state_bus()
        self._theme = get_theme_manager()

        self._toast = ToastOverlay(self)
        self._toast.bind_action_handler(self._on_toast_action)

        self._pages: Dict[str, QWidget] = {}
        self._page_stack = ThemedStack()

        self._nav = StationNavigator()
        self._nav.station_requested.connect(self.navigate_to)

        # Subtle banner indicating background scan activity.
        self._scan_banner: Optional[QFrame] = None
        self._scan_banner_label: Optional[QLabel] = None

        # Target architecture: pipeline is the authoritative deletion orchestrator
        self._pipeline = CerebroPipeline()

        # New: pipeline-driven cleanup worker
        self._cleanup_worker: Optional[PipelineCleanupWorker] = None
        self._geometry_restored = False

        self._build_layout()
        self._build_pages()
        self._wire_bus()
        self._wire_theme()

        # Apply theme and propagate to all pages
        self._theme.apply_theme(self._theme.current_theme_key)
        self._force_theme_refresh()

        self.navigate_to("mission")
        log_info("[UI] MainWindow initialized")

    def showEvent(self, event):
        """Restore saved geometry/state on first show (clamped to screen)."""
        super().showEvent(event)
        if not self._geometry_restored:
            self._geometry_restored = True
            try:
                from cerebro.services.config import load_config
                config = load_config()
                if config.window_geometry or config.window_state:
                    restore_main_window_geometry(
                        self,
                        geometry=config.window_geometry,
                        state=config.window_state,
                    )
                # Always clamp to current screen so window never exceeds visible area
                ensure_window_on_screen(self)
            except Exception:
                pass

    def _build_layout(self) -> None:
        """Build the main window layout."""
        root = QWidget()
        root.setObjectName("rootWidget")
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Background scan banner (hidden by default)
        self._scan_banner = QFrame()
        self._scan_banner.setObjectName("ScanBanner")
        self._scan_banner.setVisible(False)
        banner_layout = QHBoxLayout(self._scan_banner)
        banner_layout.setContentsMargins(16, 6, 16, 6)
        banner_layout.setSpacing(8)

        self._scan_banner_label = QLabel("Scan running in background…")
        banner_layout.addWidget(self._scan_banner_label, 1)

        outer.addWidget(self._scan_banner)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)

        row.addWidget(self._nav, 0)
        row.addWidget(self._page_stack, 1)

        outer.addLayout(row)

        self.setCentralWidget(root)
        self._apply_root_theme()

    def _apply_root_theme(self) -> None:
        """Apply theme to root widgets."""
        colors = current_colors()
        bg = colors.get('bg', '#0f1115')
        banner_bg = colors.get('warning_bg', 'rgba(234,179,8,0.12)')
        banner_text = colors.get('warning_text', '#facc15')

        self.setStyleSheet(f"""
            QMainWindow {{
                background-color: {bg};
            }}
            QWidget#rootWidget {{
                background-color: {bg};
            }}
            QWidget#MainWindow {{
                background-color: {bg};
            }}
            QFrame#ScanBanner {{
                background-color: {banner_bg};
                border-bottom: 1px solid rgba(148,163,184,0.35);
            }}
            QFrame#ScanBanner QLabel {{
                color: {banner_text};
                font-size: 12px;
            }}
        """)

    def _register(self, station_id: str, page: QWidget) -> None:
        """Register a page with the stack."""
        self._pages[station_id] = page
        self._page_stack.addWidget(page)

    def _build_pages(self) -> None:
        """Build and register all pages."""
        # Start page
        start = StartPage()
        start.navigate_requested.connect(self.navigate_to)
        self._register("mission", start)

        # Scan page
        self._register("scan", ScanPage())

        # Review page - cleanup wiring (intent only)
        review = ReviewPage()
        # ReviewPage must emit a DeletionPlan dict.
        # We preserve the signal name cleanup_confirmed.
        review.cleanup_confirmed.connect(self._on_cleanup_confirmed)
        self._register("review", review)

        # Other pages
        self._register("history", HistoryPage())
        self._register("themes", ThemePage())
        self._register("settings", SettingsPage())
        self._register("audit", AuditPage())
        self._register("hub", HubPage())

    def _wire_theme(self) -> None:
        """Connect theme changes to propagate to all pages."""
        self._theme.theme_applied.connect(self._on_theme_changed)
        self._theme.theme_previewed.connect(self._on_theme_changed)

    def _on_theme_changed(self, theme_key: str) -> None:
        """Handle theme changes."""
        log_info(f"[UI] Theme changed: {theme_key}")

        # Update root styling
        self._apply_root_theme()

        # Propagate to all pages
        self._force_theme_refresh()

        # Notify current page specifically
        current = self._page_stack.currentWidget()
        if current and hasattr(current, 'refresh_theme'):
            current.refresh_theme()
        if current and hasattr(current, 'on_theme_changed'):
            current.on_theme_changed()

    def _force_theme_refresh(self) -> None:
        """Force theme refresh across all components."""
        # Update page stack
        self._page_stack.propagate_theme()

        # Update navigator
        if hasattr(self._nav, 'refresh_theme'):
            self._nav.refresh_theme()
        else:
            colors = current_colors()
            self._nav.setStyleSheet(f"""
                QWidget {{
                    background-color: {colors.get('panel', '#151922')};
                    color: {colors.get('text', '#e7ecf2')};
                }}
            """)

    def navigate_to(self, station_id: str) -> None:
        """Navigate to a station without gating."""
        if station_id not in self._pages:
            station_id = "hub"

        current = self._page_stack.currentWidget()

        # Notify current page it's leaving
        if current and hasattr(current, 'on_exit'):
            try:
                current.on_exit()
            except Exception as e:
                log_error(f"[UI] on_exit failed: {e}")

        # Switch station
        self._nav.set_current_station(station_id)
        self._page_stack.setCurrentWidget(self._pages[station_id])

        # Notify new page it's entering
        new_page = self._pages[station_id]
        if hasattr(new_page, 'on_enter'):
            try:
                new_page.on_enter()
            except Exception as e:
                log_error(f"[UI] on_enter failed: {e}")

        self._bus.station_changed.emit(station_id)
        log_info(f"[UI] Navigated to {station_id}")

        # Clamp window to screen after page switch (avoids setGeometry warnings when new page has large min size)
        QTimer.singleShot(0, self._clamp_geometry)

    def _clamp_geometry(self) -> None:
        """Clamp window to screen and cap max size so it cannot grow off-screen (e.g. scan → review)."""
        try:
            ensure_window_on_screen(self)
        except Exception:
            pass

    def _wire_bus(self) -> None:
        """Wire state bus signals."""
        self._bus.notification_requested.connect(self._on_notification)
        self._bus.scan_completed.connect(self._on_scan_completed)
        self._bus.scan_failed.connect(self._on_scan_failed)
        self._bus.scan_started.connect(self._on_scan_started)

    def _on_scan_started(self, scan_id: str) -> None:
        """Handle scan started - update UI accordingly."""
        log_info(f"[UI] Scan started: {scan_id}")
        # Show background scan banner
        if self._scan_banner and self._scan_banner_label:
            self._scan_banner_label.setText("Scan running in background…")
            self._scan_banner.setVisible(True)

        # Reset review page state for a fresh result
        review = self._pages.get("review")
        if hasattr(review, "reset_for_new_scan"):
            try:
                review.reset_for_new_scan()
            except Exception as e:
                log_error(f"[UI] Review reset_for_new_scan failed: {e}")

    def _on_notification(self, payload: Dict[str, Any]) -> None:
        """Handle notification request."""
        title = str(payload.get("title") or "CEREBRO")
        msg = str(payload.get("message") or "")
        duration = int(payload.get("duration", 2600))
        action = payload.get("action")
        toast_action = None
        if isinstance(action, dict) and action.get("name") and action.get("text"):
            toast_action = ToastAction(text=str(action["text"]), callback_name=str(action["name"]))
        self._toast.show_toast(title, msg, duration_ms=duration, action=toast_action)

    def _on_scan_completed(self, result: Dict[str, Any]) -> None:
        """Handle scan completion - navigate to review."""
        self._toast.show_toast(
            "Results ready ✅",
            "Scan finished. Opening Review…",
            duration_ms=1400,
            action=ToastAction(text="Open now", callback_name="open_review"),
        )
        # Hide scan banner now that the scan is complete
        if self._scan_banner:
            self._scan_banner.setVisible(False)

        QTimer.singleShot(650, lambda: self.navigate_to("review"))

        review = self._pages.get("review")
        if hasattr(review, "load_scan_result"):
            try:
                review.load_scan_result(result)
            except Exception as e:
                log_error(f"[UI] Review load failed: {e}")

        # Save to history page UI if it supports ingest
        try:
            hist = self._pages.get("history")
            if hasattr(hist, "ingest_scan_result"):
                hist.ingest_scan_result(result)
        except Exception as e:
            log_error(f"[UI] History ingest failed: {e}")

    def _on_scan_failed(self, err: str) -> None:
        """Handle scan failure."""
        self._toast.show_toast("Scan failed ❌", str(err or "Unknown error"), duration_ms=3200)
        # Hide scan banner on failure
        if self._scan_banner:
            self._scan_banner.setVisible(False)

    def _on_toast_action(self, action_name: str) -> None:
        """Handle toast action click."""
        if action_name == "open_review":
            self.navigate_to("review")

    # ==============================================================================
    # AUTHORITATIVE CLEANUP (ReviewPage → Pipeline → DeletionEngine → HistoryStore)
    # ==============================================================================

    def _normalize_deletion_plan(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize payload from ReviewPage into a strict DeletionPlan.

        Expected Target DeletionPlan shape:
        {
          "scan_id": "...",
          "policy": {"mode": "trash"|"permanent"},
          "groups": [{"group_index":0,"keep":"...","delete":[...]}],
          "source": "review_page"
        }

        For safety:
        - If a group lacks "keep" or "delete", we do NOT guess.
          We refuse and request that ReviewPage emit proper intent.
        """
        scan_id = str(payload.get("scan_id") or "")
        policy = dict(payload.get("policy", {}) or {})
        mode = str(policy.get("mode", "trash"))
        groups_in = payload.get("groups") or []
        source = str(payload.get("source") or "review_page")

        groups_out: List[Dict[str, Any]] = []

        if not isinstance(groups_in, list):
            groups_in = []

        for g in groups_in:
            if not isinstance(g, dict):
                continue

            group_index = int(g.get("group_index", 0) or 0)

            # Target keys
            keep = g.get("keep")
            delete = g.get("delete")

            if isinstance(keep, str) and isinstance(delete, list):
                groups_out.append({
                    "group_index": group_index,
                    "keep": keep,
                    "delete": [str(p) for p in delete if str(p)],
                })
                continue

            # Legacy/old payload patterns (NOT SAFE to guess intent)
            # Some old code used "paths" for candidates; that is ambiguous without keep.
            if "paths" in g and ("keep" not in g or "delete" not in g):
                raise ValueError(
                    "ReviewPage emitted an ambiguous cleanup payload (missing keep/delete). "
                    "Please update ReviewPage to emit DeletionPlan groups with keys: keep + delete."
                )

        if not groups_out:
            raise ValueError("No valid deletion groups in payload (expected keep/delete per group).")

        return {
            "scan_id": scan_id,
            "policy": {"mode": mode, **policy},
            "groups": groups_out,
            "source": source,
        }

    def _on_cleanup_confirmed(self, payload: Dict[str, Any]) -> None:
        """
        Receive DeletionPlan intent from ReviewPage and execute through pipeline.
        Pipeline owns validation, execution, and audit write-through.
        """
        try:
            # Normalize and validate payload shape (no guessing)
            deletion_plan = self._normalize_deletion_plan(payload)

            groups = deletion_plan.get("groups", [])
            mode = str(deletion_plan.get("policy", {}).get("mode", "trash"))
            total_files = sum(len(g.get("delete", []) or []) for g in groups)

            # Temporary debug: log normalized deletion plan summary
            try:
                first = groups[0] if groups else {}
                log_debug(
                    f"[DEBUG] MainWindow._on_cleanup_confirmed normalized groups={len(groups)} "
                    f"total_files={total_files} first_keep={first.get('keep')} "
                    f"first_delete_count={len(first.get('delete', []))}"
                )
            except Exception:
                pass

            if total_files <= 0:
                self._toast.show_toast("Nothing to delete", "No delete candidates were selected.", duration_ms=2200)
                return

            # Build executable plan (authoritative validation in pipeline)
            executable_plan = self._pipeline.build_delete_plan(deletion_plan)

            # Temporary debug: log executable plan summary
            try:
                log_debug(
                    f"[DEBUG] MainWindow._on_cleanup_confirmed executable "
                    f"ops_len={len(getattr(executable_plan, 'operations', []))} "
                    f"total_files={executable_plan.total_files} "
                    f"stats_files={getattr(executable_plan, 'stats', {}).get('files')}"
                )
            except Exception:
                pass

            # Prevent parallel cleanups
            if self._cleanup_worker is not None:
                try:
                    self._cleanup_worker.cancel()
                except Exception:
                    pass
                self._cleanup_worker = None

            self._toast.show_toast(
                "Cleanup started 🧹",
                f"Deleting {executable_plan.total_files} file(s) ({mode})…",
                duration_ms=1800,
            )

            w = PipelineCleanupWorker(self._pipeline, executable_plan, self)
            self._cleanup_worker = w
            w.progress.connect(self._on_cleanup_progress)
            w.finished.connect(self._on_cleanup_finished)
            w.error.connect(self._on_cleanup_error)
            w.cancelled.connect(self._on_cleanup_cancelled)
            w.start()

        except Exception as e:
            log_error(f"[UI] Cleanup start failed: {e}")
            self._toast.show_toast("Cleanup blocked ❌", str(e), duration_ms=4200)

    @Slot(int, int, str)
    def _on_cleanup_progress(self, current: int, total: int, current_file: str) -> None:
        """Handle cleanup progress update (via StateBus)."""
        try:
            pct = 0
            if total > 0:
                pct = int((current / total) * 100)
            self._bus.publish_station_status(
                "review",
                progress=float(max(0, min(100, pct))) / 100.0,
                is_pulsing=True
            )
        except Exception:
            pass

        # Also update the active CleanupProgressDialog on the ReviewPage, if present.
        try:
            review = self._pages.get("review")
            dialog = getattr(review, "_progress_dialog", None)
            if dialog is not None:
                try:
                    dialog.update_progress(current, current_file or "", success=True)
                except Exception:
                    # Never allow dialog update issues to break cleanup flow
                    pass
        except Exception:
            # Defensive: ignore any issues resolving the review page/dialog
            pass

    @Slot(object)
    def _on_cleanup_finished(self, result: Any) -> None:
        """Handle cleanup completion."""
        w = self._cleanup_worker
        if w is not None:
            try:
                w.progress.disconnect()
                w.finished.disconnect()
                w.error.disconnect()
                w.cancelled.disconnect()
            except Exception:
                pass
            self._cleanup_worker = None
        try:
            if not isinstance(result, DeletionResult):
                # Defensive: show something but don't crash
                self._toast.show_toast("Cleanup complete ✅", "Cleanup finished.", duration_ms=2600)
            else:
                self._toast.show_toast(
                    "Cleanup complete ✅",
                    f"Deleted: {len(result.deleted)} · Failed: {len(result.failed)}",
                    duration_ms=3200,
                )

            # Refresh review page to show updated state (if supported)
            review = self._pages.get("review")
            if review and hasattr(review, "refresh_after_deletion") and isinstance(result, DeletionResult):
                try:
                    review.refresh_after_deletion(result.deleted)
                except Exception as e:
                    log_error(f"[UI] Review refresh_after_deletion failed: {e}")
            elif review and hasattr(review, "load_scan_result") and hasattr(review, "_result"):
                # fallback: reload last result
                try:
                    review.load_scan_result(review._result)  # type: ignore[attr-defined]
                except Exception as e:
                    log_error(f"[UI] Review reload failed: {e}")

            try:
                self._bus.publish_station_status("review", is_pulsing=False)
            except Exception:
                pass

            # Finalize and close the CleanupProgressDialog if it is still open.
            try:
                review = self._pages.get("review")
                dialog = getattr(review, "_progress_dialog", None)
                if dialog is not None:
                    # Prefer authoritative counts from the result when available.
                    if isinstance(result, DeletionResult):
                        success_count = len(result.deleted)
                        fail_count = len(result.failed)
                    else:
                        # Fallback to dialog's own counters if result shape is unexpected.
                        success_count = max(0, int(getattr(dialog, "processed_files", 0)) - int(getattr(dialog, "failed_files", 0)))
                        fail_count = int(getattr(dialog, "failed_files", 0))
                    try:
                        dialog.set_complete(success_count, fail_count)
                    except Exception:
                        pass
                    try:
                        dialog.accept()
                    except Exception:
                        pass
                    try:
                        setattr(review, "_progress_dialog", None)
                    except Exception:
                        pass
            except Exception:
                pass

        except Exception as e:
            log_error(f"[UI] Cleanup finished handler error: {e}")

    @Slot(str)
    def _on_cleanup_error(self, trace: str) -> None:
        """Handle cleanup error."""
        w = self._cleanup_worker
        if w is not None:
            try:
                w.progress.disconnect()
                w.finished.disconnect()
                w.error.disconnect()
                w.cancelled.disconnect()
            except Exception:
                pass
            self._cleanup_worker = None
        self._toast.show_toast("Cleanup failed ❌", "See logs for details.", duration_ms=4200)
        log_error(f"[UI] Cleanup error:\n{trace}")
        try:
            self._bus.publish_station_status("review", is_pulsing=False)
        except Exception:
            pass

        # Best-effort: mark the CleanupProgressDialog as failed and close it.
        try:
            review = self._pages.get("review")
            dialog = getattr(review, "_progress_dialog", None)
            if dialog is not None:
                try:
                    if hasattr(dialog, "title"):
                        dialog.title.setText("❌ Cleanup failed")
                    if hasattr(dialog, "subtitle"):
                        dialog.subtitle.setText("See logs for details.")
                except Exception:
                    pass
                try:
                    dialog.accept()
                except Exception:
                    pass
                try:
                    setattr(review, "_progress_dialog", None)
                except Exception:
                    pass
        except Exception:
            pass

    @Slot()
    def _on_cleanup_cancelled(self) -> None:
        """Handle cleanup cancellation."""
        w = self._cleanup_worker
        if w is not None:
            try:
                w.progress.disconnect()
                w.finished.disconnect()
                w.error.disconnect()
                w.cancelled.disconnect()
            except Exception:
                pass
            self._cleanup_worker = None
        self._toast.show_toast("Cleanup cancelled", "Deletion was cancelled.", duration_ms=2400)
        try:
            self._bus.publish_station_status("review", is_pulsing=False)
        except Exception:
            pass

    def closeEvent(self, event) -> None:
        """Handle window close - save geometry/state and check for unsafe operations."""
        try:
            from cerebro.services.config import load_config, save_config
            config = load_config()
            geom = self.saveGeometry()
            state = self.saveState()
            config.window_geometry = bytes(geom) if geom.size() else None
            config.window_state = bytes(state) if state.size() else None
            save_config(config)
        except Exception:
            pass
        unsafe_pages = []
        for station_id, page in self._pages.items():
            if hasattr(page, 'are_you_safe_to_leave') and not page.are_you_safe_to_leave():
                unsafe_pages.append(station_id)

        if unsafe_pages:
            res = QMessageBox.question(
                self,
                "Operations running",
                f"Active operations in: {', '.join(unsafe_pages)}. Quit anyway?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if res != QMessageBox.Yes:
                event.ignore()
                return

        # Cancel cleanup if running
        if self._cleanup_worker is not None:
            try:
                self._cleanup_worker.cancel()
            except Exception:
                pass

        # Cleanup all pages
        for page in self._pages.values():
            if hasattr(page, 'cleanup'):
                try:
                    page.cleanup()
                except Exception as e:
                    log_error(f"[UI] Cleanup error: {e}")

        event.accept()


# Export
__all__ = ['MainWindow', 'ThemedStack']
