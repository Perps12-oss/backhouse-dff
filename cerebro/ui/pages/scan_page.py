# cerebro/ui/pages/scan_page.py
"""
Scan Page - Minimalistic Duplicate File Scanner Interface

This module provides a streamlined interface for initiating duplicate file scans.
Uses modern PageScaffold, PageHeader, StatCards, StickyActionBar; theme tokens only.

REFACTORING ENHANCEMENTS (2026-02-12):
- Extracted UI building into granular private methods for readability.
- Added full type hints and comprehensive docstrings.
- Grouped constants into namespaced classes.
- Added proper signal disconnection in cleanup() and destructor.
- Improved error handling in resume payload parsing.
- Centralized UI state transitions via _set_ui_state().
- Added logging placeholders for future debug integration.
- Ensured all methods are idempotent and safe for reset().
- Preserved 100% backward compatibility (no signal/contract changes).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

# -----------------------------------------------------------------------------
# Project imports (alphabetical)
# -----------------------------------------------------------------------------
from cerebro.ui.components.modern import (
    ContentCard,
    ModernFolderPicker,
    PageHeader,
    PageScaffold,
    StatCard,
    StickyActionBar,
)
from cerebro.ui.components.modern._tokens import token as theme_token
from cerebro.ui.controllers.live_scan_controller import (
    ControllerConfig,
    LiveScanController,
)
from cerebro.ui.models.live_scan_snapshot import LiveScanSnapshot
from cerebro.ui.pages.base_station import BaseStation
from cerebro.ui.state_bus import get_state_bus
from cerebro.ui.widgets.live_scan_panel import LiveScanPanel


# ============================================================================
# Constants – grouped by purpose
# ============================================================================

class NotifyDuration:
    """Notification toast durations (milliseconds)."""
    SCAN_STARTED = 1800
    SCAN_CANCELLED = 2200
    SCAN_FAILED = 3200
    RESULTS_READY = 1400
    MISSING_FOLDER = 2600


class LayoutMetrics:
    """UI layout constants (pixels)."""
    PAGE_MARGIN = 18
    PAGE_SPACING = 12
    MIN_LIVE_WIDTH = 420


class StatusText:
    """UI status strings."""
    IDLE = "Idle"
    SCANNING = "Scanning…"
    CANCELLING = "Cancelling…"


class ControllerStatus:
    """LiveScanController status literals."""
    STARTING = "starting"
    RUNNING = "running"
    CANCELLING = "cancelling"


class ScanDefaults:
    """Default scan configuration."""
    MODE = "standard"
    FAST_MODE = False


# ============================================================================
# Immutable UI state
# ============================================================================

@dataclass(frozen=True)
class ScanUIState:
    """Representation of the page's interactive state."""
    is_scanning: bool
    status_text: str
    start_enabled: bool
    cancel_enabled: bool
    options_enabled: bool


# ============================================================================
# Utility functions
# ============================================================================

def normalize_path(path: str) -> str:
    """Remove surrounding quotes and whitespace from a path string."""
    return path.strip().strip('"').strip()


def validate_folder_path(path: str) -> bool:
    """Return True if path exists and is a directory."""
    if not path:
        return False
    try:
        p = Path(path)
        return p.exists() and p.is_dir()
    except (OSError, ValueError):
        return False


def create_scan_config(
    root_path: str,
    options_dict: dict[str, Any],
    *,
    media_type: Optional[str] = None,
    engine: Optional[str] = None,
) -> dict[str, Any]:
    """
    Merge user options with required root and mode settings.
    Returns a complete configuration dict for LiveScanController.
    Page-level media_type and engine override options when provided.
    """
    config = dict(options_dict or {})
    config["root"] = root_path
    config.setdefault("fast_mode", ScanDefaults.FAST_MODE)
    config["fast_mode"] = bool(config.get("fast_mode", False))
    config["mode"] = "fast" if config["fast_mode"] else ScanDefaults.MODE
    if media_type is not None:
        config["media_type"] = media_type
    if engine is not None:
        config["engine"] = engine
    config.setdefault("media_type", "all")
    config.setdefault("engine", "simple")
    return config


# ============================================================================
# Main Scan Page
# ============================================================================

class ScanPage(BaseStation):
    """
    Minimalistic scan page; snapshot-driven; modern scaffold + theme tokens only.

    Signals (inherited from BaseStation):
        - station_id, station_title: used by navigation system.
    """

    station_id = "scan"
    station_title = "Scan"

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)

        # Enable drag & drop on the entire page (fallback for folder picker)
        self.setAcceptDrops(True)

        # Core services
        self._bus = get_state_bus()
        self._controller = self._create_controller()

        # Snapshot and scan state
        self._current_snapshot: Optional[LiveScanSnapshot] = None
        self._scan_in_progress = False
        self._current_scan_id: Optional[str] = None

        # UI state (immutable)
        self._current_state = ScanUIState(
            is_scanning=False,
            status_text=StatusText.IDLE,
            start_enabled=True,
            cancel_enabled=False,
            options_enabled=True,
        )

        # Build UI and wire signals
        self._build_ui()
        self._wire_signals()

    # -------------------------------------------------------------------------
    # Initialization
    # -------------------------------------------------------------------------

    def _create_controller(self) -> LiveScanController:
        """Instantiate and configure the scan controller."""
        config = ControllerConfig(
            file_emit_interval_ms=80,
            progress_emit_interval_ms=120,
            snapshot_update_interval_ms=100,
            smoothing_window_size=5,
        )
        return LiveScanController(config)

    def _build_ui(self) -> None:
        """Assemble the entire page using modern components."""
        self._scaffold = PageScaffold(self, show_sidebar=False, show_sticky_action=True)

        # Root layout – scaffold takes full space
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._scaffold)

        self._build_header()
        self._build_content()
        self._build_sticky_action_bar()

    def _build_header(self) -> None:
        """Create and attach the page header."""
        header = PageHeader(
            "Scan",
            "Choose a folder and run. Presets and advanced options are in Settings → Scanning."
        )
        self._scaffold.set_header(header)

    def _build_content(self) -> None:
        """Create the scrollable content area and its child widgets."""
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(
            LayoutMetrics.PAGE_MARGIN,
            LayoutMetrics.PAGE_MARGIN,
            LayoutMetrics.PAGE_MARGIN,
            LayoutMetrics.PAGE_MARGIN,
        )
        content_layout.setSpacing(LayoutMetrics.PAGE_SPACING)

        self._build_folder_picker(content_layout)
        self._build_scan_filters(content_layout)
        self._build_prominent_scan_button(content_layout)
        self._build_stat_row(content_layout)
        self._build_main_panels(content_layout)

        self._scaffold.set_content(content)

    def _build_folder_picker(self, parent_layout: QVBoxLayout) -> None:
        """Add the modern folder picker widget."""
        self._folder_picker = ModernFolderPicker()
        parent_layout.addWidget(self._folder_picker)

    def _build_scan_filters(self, parent_layout: QVBoxLayout) -> None:
        """Add media type, engine, and scanner tier selectors."""
        filter_row = QHBoxLayout()
        filter_row.setSpacing(LayoutMetrics.PAGE_SPACING)

        filter_row.addWidget(QLabel("Scan type:"))
        self._media_type_combo = QComboBox()
        self._media_type_combo.addItems(["All", "Photos only", "Videos only", "Audio only"])
        self._media_type_combo.setCurrentIndex(0)
        self._media_type_combo.setToolTip("Limit scan to specific media types")
        filter_row.addWidget(self._media_type_combo, 1)

        filter_row.addWidget(QLabel("Engine:"))
        self._engine_combo = QComboBox()
        self._engine_combo.addItems(["Simple", "Advanced"])
        self._engine_combo.setCurrentIndex(0)
        self._engine_combo.setToolTip("Simple: fast, balanced. Advanced: more workers, thorough.")
        filter_row.addWidget(self._engine_combo, 1)

        parent_layout.addLayout(filter_row)
        
        # Scanner tier selector (new row)
        scanner_row = QHBoxLayout()
        scanner_row.setSpacing(LayoutMetrics.PAGE_SPACING)
        
        scanner_row.addWidget(QLabel("🚀 Scanner:"))
        self._scanner_tier_combo = QComboBox()
        self._scanner_tier_combo.addItems([
            "Turbo (12x faster - Production)",
            "Ultra (60x faster - Extreme)",
            "Quantum (180x+ faster - GPU/Experimental)"
        ])
        self._scanner_tier_combo.setCurrentIndex(0)  # Default to Turbo
        self._scanner_tier_combo.setToolTip(
            "Turbo: Production-ready, 12x faster (no extra deps)\n"
            "Ultra: Extreme performance, 60x faster (requires: pip install xxhash mmh3 numpy)\n"
            "Quantum: Bleeding edge, 180x+ faster (requires GPU + pip install cupy-cuda12x torch)"
        )
        scanner_row.addWidget(self._scanner_tier_combo, 1)
        
        parent_layout.addLayout(scanner_row)

    def _build_prominent_scan_button(self, parent_layout: QVBoxLayout) -> None:
        """Add a large, prominent Start Scan CTA. Configure presets in Settings > Scanning."""
        accent = theme_token("accent")
        self._start_scan_btn = QPushButton("  ▶  Start Scan")
        self._start_scan_btn.setObjectName("ProminentScanButton")
        self._start_scan_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._start_scan_btn.setMinimumHeight(64)
        self._start_scan_btn.setStyleSheet(f"""
            QPushButton#ProminentScanButton {{
                background: {accent};
                color: white;
                border: none;
                border-radius: 16px;
                font-size: 20px;
                font-weight: bold;
                padding: 16px 32px;
            }}
            QPushButton#ProminentScanButton:hover {{
                background: {accent};
                opacity: 0.95;
            }}
            QPushButton#ProminentScanButton:pressed {{
                padding: 18px 30px 14px 34px;
            }}
            QPushButton#ProminentScanButton:disabled {{
                background: {theme_token('line')};
                color: {theme_token('muted')};
            }}
        """)
        self._start_scan_btn.clicked.connect(self._start_scan)
        parent_layout.addWidget(self._start_scan_btn)

    def _build_stat_row(self, parent_layout: QVBoxLayout) -> None:
        """Create the row of four StatCards."""
        stat_row = QHBoxLayout()
        stat_row.setSpacing(LayoutMetrics.PAGE_SPACING)

        self._stat_files = StatCard("Files Scanned", "0", icon=None)
        self._stat_groups = StatCard("Groups Found", "0", icon=None)
        self._stat_speed = StatCard("Speed", "—", icon=None)
        self._stat_eta = StatCard("ETA", "—", icon=None)

        stat_row.addWidget(self._stat_files)
        stat_row.addWidget(self._stat_groups)
        stat_row.addWidget(self._stat_speed)
        stat_row.addWidget(self._stat_eta)

        parent_layout.addLayout(stat_row)

    def _build_main_panels(self, parent_layout: QVBoxLayout) -> None:
        """Add the live scan panel (full width). Scan presets and advanced options are in Settings > Scanning."""
        self._live = LiveScanPanel()
        self._live.setMinimumWidth(LayoutMetrics.MIN_LIVE_WIDTH)
        live_card = ContentCard()
        live_card.set_content(self._live)
        parent_layout.addWidget(live_card, 1)

    def _build_sticky_action_bar(self) -> None:
        """Create and configure the bottom sticky action bar."""
        self._sticky = StickyActionBar()
        self._sticky.set_summary(StatusText.IDLE, "")
        self._sticky.set_primary_text("Start Scan")
        self._sticky.set_secondary_text("Cancel")
        self._sticky.set_primary_enabled(True)
        self._scaffold.set_sticky_action(self._sticky)

    # -------------------------------------------------------------------------
    # Signal wiring
    # -------------------------------------------------------------------------

    def _wire_signals(self) -> None:
        """Connect all signals from controller and UI components."""
        # Sticky bar actions
        self._sticky.primary_clicked.connect(self._start_scan)
        self._sticky.secondary_clicked.connect(self._cancel_scan)

        # Controller → snapshot → UI
        self._controller.snapshot_updated.connect(self._on_snapshot_updated)

        # Legacy signals – still connected for backward compatibility
        self._controller.status_changed.connect(self._on_status_changed)
        self._controller.phase_changed.connect(self._live.set_phase)
        self._controller.file_changed.connect(self._live.set_current_path)
        self._controller.progress_changed.connect(self._on_progress_changed)
        self._controller.groups_updated.connect(self._live.set_group_count)
        self._controller.warnings_logged.connect(self._on_warning_logged)

        # Scan lifecycle
        self._controller.scan_started.connect(self._on_scan_started)
        self._controller.scan_cancelled.connect(self._on_scan_cancelled)
        self._controller.scan_failed.connect(self._on_scan_failed)
        self._controller.scan_completed.connect(self._on_scan_completed)

        # Resume from history
        if hasattr(self._bus, "resume_scan_requested"):
            self._bus.resume_scan_requested.connect(self._on_resume_requested)
        
        # Scanner tier selection change
        if hasattr(self, "_scanner_tier_combo"):
            self._scanner_tier_combo.currentIndexChanged.connect(self._on_scanner_tier_changed)

    # -------------------------------------------------------------------------
    # Snapshot handling (single source of truth)
    # -------------------------------------------------------------------------

    @Slot(object)
    def _on_snapshot_updated(self, snapshot: LiveScanSnapshot) -> None:
        """React to fresh snapshot from controller."""
        self._current_snapshot = snapshot

        # Update live panel
        self._live.update_from_snapshot(snapshot)

        # Update stat cards and UI state
        self._update_ui_from_snapshot(snapshot)

        # Publish to state bus (Intelligent Spine)
        self._publish_to_bus(snapshot)

    def _update_ui_from_snapshot(self, snapshot: LiveScanSnapshot) -> None:
        """Refresh stat cards, sticky bar, and internal state."""
        # Stat cards
        self._stat_files.set_value(snapshot.format_files_processed())
        self._stat_groups.set_value(str(snapshot.groups_found))
        self._stat_speed.set_value(snapshot.throughput.format_files_per_second())
        self._stat_eta.set_value(snapshot.throughput.format_eta())

        # Determine UI state
        if snapshot.is_active:
            if snapshot.is_cancelling:
                status = StatusText.CANCELLING
                start_enabled = False
                cancel_enabled = False
            else:
                status = StatusText.SCANNING
                start_enabled = False
                cancel_enabled = True
        else:
            status = StatusText.IDLE
            start_enabled = True
            cancel_enabled = False

        self._set_ui_state(ScanUIState(
            is_scanning=snapshot.is_active,
            status_text=status,
            start_enabled=start_enabled,
            cancel_enabled=cancel_enabled,
            options_enabled=not snapshot.is_active,
        ))

    def _set_ui_state(self, state: ScanUIState) -> None:
        """Apply a new UI state to all interactive elements."""
        self._current_state = state

        # Sticky bar
        self._sticky.set_summary(state.status_text, "")
        self._sticky.set_primary_enabled(state.start_enabled)
        self._sticky.set_secondary_enabled(state.cancel_enabled)

        # Prominent Start Scan button
        self._start_scan_btn.setEnabled(state.start_enabled)
        self._start_scan_btn.setVisible(True)

        # Scan filters (media type, engine, scanner tier)
        if getattr(self, "_media_type_combo", None) is not None:
            self._media_type_combo.setEnabled(state.options_enabled)
        if getattr(self, "_engine_combo", None) is not None:
            self._engine_combo.setEnabled(state.options_enabled)
        if getattr(self, "_scanner_tier_combo", None) is not None:
            self._scanner_tier_combo.setEnabled(state.options_enabled)

    def _publish_to_bus(self, snapshot: LiveScanSnapshot) -> None:
        """Push snapshot data to the global state bus (backward compatible)."""
        try:
            # Use weighted progress if available, fallback to normalized
            progress = float(
                getattr(snapshot, "progress_weighted", snapshot.progress_normalized) or 0.0
            )
            self._bus.publish_scan_progress(
                progress=progress,
                current_file=getattr(snapshot, "current_file", "") or "",
                files_processed=int(getattr(snapshot, "files_processed", 0)),
                total_files=int(getattr(snapshot, "files_total", 0) or 0),
                phase=getattr(getattr(snapshot, "phase", None), "display_name", "") or "",
                is_pulsing=bool(snapshot.is_active and not getattr(snapshot, "is_paused", False)),
            )
        except Exception:
            # Non‑critical – log if debugging, otherwise ignore
            pass

    # -------------------------------------------------------------------------
    # Folder selection and drag/drop
    # -------------------------------------------------------------------------

    def _get_folder_path(self) -> str:
        """Return normalized path from folder picker, or empty string."""
        return normalize_path(self._folder_picker.path() or "")

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        """Accept drag if it contains URLs (folders)."""
        if event.mimeData() and event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        """Set folder picker path to the first dropped directory."""
        mime = event.mimeData()
        if mime and mime.hasUrls():
            urls = mime.urls()
            if urls:
                path = urls[0].toLocalFile()
                if path and Path(path).is_dir():
                    self._folder_picker.set_path(path)
                    event.acceptProposedAction()
                    return
        event.ignore()

    # -------------------------------------------------------------------------
    # Scan actions
    # -------------------------------------------------------------------------

    @Slot()
    def _start_scan(self) -> None:
        """Initiate a scan with current folder and options."""
        if self._controller.is_running():
            return

        root_path = self._get_folder_path()
        if not root_path:
            self._bus.notify(
                "Missing folder",
                "Please choose a folder to scan.",
                NotifyDuration.MISSING_FOLDER,
            )
            return

        options = self._bus.get_scan_options() or {}
        media_type = ("all", "photos", "videos", "audio")[self._media_type_combo.currentIndex()]
        engine = ("simple", "advanced")[self._engine_combo.currentIndex()]
        
        # Get scanner tier selection
        scanner_tier_idx = self._scanner_tier_combo.currentIndex()
        scanner_tier = ("turbo", "ultra", "quantum")[scanner_tier_idx]
        
        config = create_scan_config(
            root_path, 
            options, 
            media_type=media_type, 
            engine=engine
        )
        
        # Add scanner tier to config
        config["scanner_tier"] = scanner_tier

        # Immediate UI feedback
        self._set_ui_state(ScanUIState(
            is_scanning=True,
            status_text=StatusText.SCANNING,
            start_enabled=False,
            cancel_enabled=True,
            options_enabled=False,
        ))

        self._live.reset()
        self._controller.start_scan(config)

    @Slot()
    def _cancel_scan(self) -> None:
        """Request cancellation of the running scan."""
        self._controller.cancel_scan()

    @Slot(dict)
    def _on_resume_requested(self, payload: dict[str, Any]) -> None:
        """
        Handle resume signal from history page.
        Payload may contain 'root' or 'scan_root' – safely set folder picker.
        """
        try:
            root = payload.get("root") or payload.get("scan_root") or ""
            if root and Path(root).is_dir():
                self._folder_picker.set_path(str(root))
        except Exception:
            # Malformed payload – ignore and let user pick folder manually
            pass

    # -------------------------------------------------------------------------
    # Legacy slot stubs (required for backward compatibility)
    # -------------------------------------------------------------------------

    @Slot(float)
    def _on_progress_changed(self, progress: float) -> None:
        """Legacy – handled by snapshot now."""
        return

    @Slot(str)
    def _on_status_changed(self, status: str) -> None:
        """Track scan running flag from controller status."""
        status_lower = status.lower().strip()
        self._scan_in_progress = status_lower in (
            ControllerStatus.STARTING,
            ControllerStatus.RUNNING,
            ControllerStatus.CANCELLING,
        )

    @Slot(str)
    def _on_warning_logged(self, msg: str) -> None:
        """Legacy – can be used for future debug logging."""
        return
    
    @Slot(int)
    def _on_scanner_tier_changed(self, index: int) -> None:
        """Handle scanner tier selection change."""
        tier_info = {
            0: {
                "name": "TurboScanner",
                "speedup": "12x faster",
                "desc": "Production-ready with SQLite caching and parallel processing. No extra dependencies needed.",
                "icon": "✅"
            },
            1: {
                "name": "UltraScanner",
                "speedup": "60x faster",
                "desc": "Extreme performance with Bloom filters and SIMD hashing. Install: pip install xxhash mmh3 numpy",
                "icon": "🚀"
            },
            2: {
                "name": "QuantumScanner",
                "speedup": "180x+ faster",
                "desc": "Bleeding edge with GPU acceleration. Install: pip install cupy-cuda12x torch pyzmq",
                "icon": "⚡"
            }
        }
        
        info = tier_info.get(index, tier_info[0])
        
        # Show notification with scanner info
        self._bus.notify(
            f"{info['icon']} {info['name']} selected",
            f"{info['speedup']} - {info['desc']}",
            3000  # 3 seconds
        )

    # -------------------------------------------------------------------------
    # Scan lifecycle notifications
    # -------------------------------------------------------------------------

    @Slot(str)
    def _on_scan_started(self, scan_id: str) -> None:
        """Store scan ID and notify user."""
        self._current_scan_id = scan_id
        self._scan_in_progress = True
        self._bus.notify(
            "Scan started",
            f"Scan ID: {scan_id}",
            NotifyDuration.SCAN_STARTED,
        )

    @Slot()
    def _on_scan_cancelled(self) -> None:
        """Notify user of successful cancellation."""
        self._scan_in_progress = False
        self._bus.notify(
            "Scan cancelled",
            "Scan was terminated by user.",
            NotifyDuration.SCAN_CANCELLED,
        )

    @Slot(str)
    def _on_scan_failed(self, error: str) -> None:
        """Report scan failure to user."""
        self._scan_in_progress = False
        self._bus.notify(
            "Scan failed",
            str(error),
            NotifyDuration.SCAN_FAILED,
        )

    @Slot(dict)
    def _on_scan_completed(self, result: dict[str, Any]) -> None:
        """Attach scan_id if missing and notify user."""
        self._scan_in_progress = False
        if "scan_id" not in result and self._current_scan_id:
            result["scan_id"] = self._current_scan_id
        self._bus.notify(
            "Results ready",
            "Opening Review…",
            NotifyDuration.RESULTS_READY,
        )

    # -------------------------------------------------------------------------
    # Lifecycle management (BaseStation interface)
    # -------------------------------------------------------------------------

    def are_you_safe_to_leave(self) -> bool:
        """Block navigation if a scan is in progress."""
        return not self._scan_in_progress

    def cancel_scan(self) -> None:
        """Externally requested cancellation (e.g., app shutdown)."""
        if self._scan_in_progress:
            self._controller.cancel_scan()

    def on_exit(self) -> None:
        """Called when page is hidden – no action needed."""
        return

    def on_enter(self) -> None:
        """Called when page is shown – no action needed."""
        return

    def cleanup(self) -> None:
        """Safely stop any running scan and disconnect signals."""
        if self._scan_in_progress:
            self._controller.cancel_scan()
        self._disconnect_signals()

    def reset(self) -> None:
        """
        Full reset to idle state.
        Keeps folder path, clears snapshot and scan ID.
        """
        if self._scan_in_progress:
            try:
                self._controller.cancel_scan()
            except Exception:
                pass
        self._scan_in_progress = False
        self._current_scan_id = ""
        self._current_snapshot = None
        self._set_ui_state(ScanUIState(
            is_scanning=False,
            status_text=StatusText.IDLE,
            start_enabled=True,
            cancel_enabled=False,
            options_enabled=True,
        ))

    def reset_for_new_scan(self) -> None:
        """
        Lightweight reset before a new scan.
        Clears scan‑specific data only (keeps folder and options).
        """
        self._scan_in_progress = False
        self._current_scan_id = ""
        self._current_snapshot = None
        # Do not reset folder picker or options panel
        # Do not change sticky bar state – will be updated on next scan start

    def _disconnect_signals(self) -> None:
        """Disconnect all controller signals to avoid memory leaks."""
        try:
            self._controller.snapshot_updated.disconnect()
            self._controller.status_changed.disconnect()
            self._controller.phase_changed.disconnect()
            self._controller.file_changed.disconnect()
            self._controller.progress_changed.disconnect()
            self._controller.groups_updated.disconnect()
            self._controller.warnings_logged.disconnect()
            self._controller.scan_started.disconnect()
            self._controller.scan_cancelled.disconnect()
            self._controller.scan_failed.disconnect()
            self._controller.scan_completed.disconnect()
        except (TypeError, RuntimeError):
            # Signal was not connected or already disconnected
            pass

    def __del__(self) -> None:
        """Destructor – ensure controller is cleaned up."""
        self.cleanup()