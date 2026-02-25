# cerebro/ui/state_bus.py
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Callable, Dict, List, Optional

from PySide6.QtCore import QObject, Signal


@dataclass
class ScanOptions:
    """Central scan options used by Settings, state_bus, and scan flow."""
    mode: str = "exact"
    min_size_bytes: int = 1024 * 100
    hash_bytes: int = 1024 * 4
    max_workers: int = 8
    follow_symlinks: bool = False
    include_hidden: bool = False
    skip_system_folders: bool = True
    cache_mode: int = 0
    file_types: List[str] = field(default_factory=list)
    fast_mode: bool = True
    media_type: str = "all"
    engine: str = "simple"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Optional[Dict[str, Any]]) -> "ScanOptions":
        if not d:
            return cls()
        return cls(
            mode=str(d.get("mode", "exact")),
            min_size_bytes=int(d.get("min_size_bytes", 102400)),
            hash_bytes=int(d.get("hash_bytes", 4096)),
            max_workers=int(d.get("max_workers", 8)),
            follow_symlinks=bool(d.get("follow_symlinks", False)),
            include_hidden=bool(d.get("include_hidden", False)),
            skip_system_folders=bool(d.get("skip_system_folders", True)),
            cache_mode=int(d.get("cache_mode", 0)),
            file_types=list(d.get("file_types", []) or []),
            fast_mode=bool(d.get("fast_mode", True)),
            media_type=str(d.get("media_type", "all")),
            engine=str(d.get("engine", "simple")),
        )


@dataclass
class ScanProgressData:
    station_id: str = "scan"
    progress: float = 0.0
    current_file: str = ""
    files_processed: int = 0
    total_files: int = 0
    phase: str = ""
    is_pulsing: bool = False


@dataclass
class StationStatusData:
    station_id: str
    badge_count: Optional[int] = None
    progress: Optional[float] = None
    is_locked: bool = False
    lock_reason: str = ""
    is_current: bool = False
    is_pulsing: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)


# Media type filter: extensions for photos, videos, audio (used when media_type is set)
MEDIA_EXTENSIONS: Dict[str, list] = {
    "photos": [".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff", ".tif", ".heic", ".heif", ".raw", ".cr2", ".nef", ".arw"],
    "videos": [".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v", ".mpeg", ".mpg", ".3gp", ".ogv"],
    "audio": [".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".wma", ".opus", ".ape", ".alac"],
}

def _default_scan_options_dict() -> Dict[str, Any]:
    return ScanOptions().to_dict()


class StateBus(QObject):
    """
    Global pub/sub for UI components.

    Backward-compat:
    - module exports `bus` singleton
    - module exports `get_state_bus()` singleton accessor
    - provides both publish_* helpers AND legacy convenience names (notify, confirm)
    """

    # Lifecycle / nav
    station_changed = Signal(str)     # station_id
    mode_changed = Signal(str)        # "guided" | "expert"
    theme_changed = Signal(str)       # theme name

    # Scan
    scan_requested = Signal(dict)           # config
    scan_started = Signal(str)              # scan_id
    scan_progress = Signal(ScanProgressData)
    scan_completed = Signal(dict)           # results
    scan_cancelled = Signal(str)            # scan_id
    scan_failed = Signal(str)               # error
    resume_scan_requested = Signal(dict)    # resume payload (history → scan)

    # Station status (for Intelligent Spine)
    station_status_updated = Signal(StationStatusData)

    # UI messaging
    notification_requested = Signal(dict)
    modal_requested = Signal(dict)

    def __init__(self) -> None:
        super().__init__()
        self._scan_options: Dict[str, Any] = _default_scan_options_dict()

    def get_scan_options(self) -> Dict[str, Any]:
        """Return current scan options (from Settings > Scanning)."""
        return dict(self._scan_options)

    def get_scan_options_typed(self) -> ScanOptions:
        """Return current scan options as ScanOptions."""
        return ScanOptions.from_dict(self._scan_options)

    def set_scan_options(self, options: Dict[str, Any]) -> None:
        """Update scan options (called by Settings when user changes Scanning)."""
        if options:
            self._scan_options = ScanOptions.from_dict(options).to_dict()

    @staticmethod
    def allowed_extensions_for_media_type(media_type: str) -> Optional[List[str]]:
        """Return list of extensions for the given media_type, or None for 'all'."""
        if not media_type or str(media_type).lower() == "all":
            return None
        return list(MEDIA_EXTENSIONS.get(str(media_type).lower(), []))

    # ----------------------------
    # Convenience publishers
    # ----------------------------
    def publish_scan_progress(
        self,
        progress: float,
        current_file: str = "",
        files_processed: int = 0,
        total_files: int = 0,
        phase: str = "",
        is_pulsing: bool = False,
    ) -> None:
        data = ScanProgressData(
            progress=float(progress),
            current_file=current_file or "",
            files_processed=int(files_processed),
            total_files=int(total_files),
            phase=phase or "",
            is_pulsing=bool(is_pulsing),
        )
        self.scan_progress.emit(data)

        # Also update the spine
        self.station_status_updated.emit(
            StationStatusData(
                station_id="scan",
                progress=data.progress,
                is_pulsing=data.is_pulsing,
            )
        )

    def publish_station_status(
        self,
        station_id: str,
        badge_count: Optional[int] = None,
        progress: Optional[float] = None,
        is_locked: bool = False,
        lock_reason: str = "",
        is_current: bool = False,
        is_pulsing: bool = False,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.station_status_updated.emit(
            StationStatusData(
                station_id=station_id,
                badge_count=badge_count,
                progress=progress,
                is_locked=is_locked,
                lock_reason=lock_reason,
                is_current=is_current,
                is_pulsing=is_pulsing,
                metadata=metadata or {},
            )
        )

    def publish_notification(
        self,
        title: str,
        message: str,
        level: str = "info",
        duration: int = 3000,
        action: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.notification_requested.emit(
            {
                "title": title,
                "message": message,
                "level": level,
                "duration": int(duration),
                "action": action,
            }
        )

    def request_confirmation(
        self,
        title: str,
        message: str,
        on_confirm: Callable[[], None],
        on_cancel: Optional[Callable[[], None]] = None,
    ) -> None:
        self.modal_requested.emit(
            {
                "type": "confirmation",
                "title": title,
                "message": message,
                "on_confirm": on_confirm,
                "on_cancel": on_cancel,
            }
        )

    # ----------------------------
    # Legacy aliases (critical for stability)
    # ----------------------------
    def notify(
        self,
        title: str,
        message: str,
        duration: int = 3000,
        action: Optional[Dict[str, Any]] = None,
        level: str = "info",
    ) -> None:
        """
        Legacy convenience alias used by older UI code.
        """
        self.publish_notification(title=title, message=message, level=level, duration=duration, action=action)

    def confirm(
        self,
        title: str,
        message: str,
        on_confirm: Callable[[], None],
        on_cancel: Optional[Callable[[], None]] = None,
    ) -> None:
        """
        Legacy convenience alias.
        """
        self.request_confirmation(title=title, message=message, on_confirm=on_confirm, on_cancel=on_cancel)


_bus_instance: Optional[StateBus] = None


def get_state_bus() -> StateBus:
    global _bus_instance
    if _bus_instance is None:
        _bus_instance = StateBus()
    return _bus_instance


# Legacy singleton import style
bus = get_state_bus()