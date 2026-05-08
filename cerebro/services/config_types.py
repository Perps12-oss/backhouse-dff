# cerebro/services/config_types.py
"""
Domain dataclasses and enums for CEREBRO configuration.

Kept separate from ConfigManager (config.py) so type definitions can be
imported without pulling in file I/O, migration logic, or the logger.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict, fields
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional


class ThemeMode(Enum):
    DARK = "dark"
    LIGHT = "light"
    SYSTEM = "system"
    CUSTOM = "custom"


class ScanMode(Enum):
    STANDARD = "standard"
    DEEP = "deep"
    QUICK = "quick"
    CUSTOM = "custom"


class HashAlgorithm(Enum):
    MD5 = "md5"
    SHA1 = "sha1"
    SHA256 = "sha256"
    SHA512 = "sha512"


class CacheMode(Enum):
    DISABLED = 0
    ENABLED = 1
    AGGRESSIVE = 2


@dataclass
class PathFilter:
    include_patterns: List[str] = field(default_factory=list)
    exclude_patterns: List[str] = field(default_factory=list)
    include_extensions: List[str] = field(default_factory=list)
    exclude_extensions: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PathFilter":
        if not isinstance(data, dict):
            data = {}
        return cls(**data)


@dataclass
class PerformanceSettings:
    max_workers: int = 4
    io_buffer_size: int = 8192
    hash_chunk_size: int = 65536
    memory_limit_mb: int = 1024
    disk_cache_size_mb: int = 100
    thread_pool_size: int = 8

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PerformanceSettings":
        return cls(**data)


@dataclass
class UISettings:
    theme: str = "dark"
    font_size: int = 12
    font_family: str = "Segoe UI"
    animation_enabled: bool = True
    tooltips_enabled: bool = True
    confirm_deletions: bool = True
    auto_expand_results: bool = False
    show_hidden_files: bool = False
    thumbnail_size: int = 64
    max_recent_scans: int = 10

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UISettings":
        return cls(**data)


@dataclass
class ScanSettings:
    default_mode: str = "standard"
    min_file_size_kb: int = 100
    max_file_size_mb: int = 0
    default_hash_algorithm: str = "auto"
    cache_mode: int = 1
    recursive: bool = True
    follow_symlinks: bool = False
    include_hidden: bool = False
    skip_system_folders: bool = True
    verify_after_copy: bool = True
    default_filters: PathFilter = field(default_factory=PathFilter)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["default_filters"] = self.default_filters.to_dict()
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ScanSettings":
        filters_data = data.pop("default_filters", {})
        if not isinstance(filters_data, dict):
            filters_data = {}
        instance = cls(**data)
        instance.default_filters = PathFilter.from_dict(filters_data)
        return instance


@dataclass
class NotificationSettings:
    enabled: bool = True
    scan_complete: bool = True
    scan_error: bool = True
    update_available: bool = True
    sound_enabled: bool = False
    system_tray_notifications: bool = True
    email_notifications: bool = False
    email_address: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "NotificationSettings":
        return cls(**data)


@dataclass
class UpdateSettings:
    check_for_updates: bool = True
    auto_download_updates: bool = False
    update_channel: str = "stable"
    update_server_url: str = ""
    last_check_time: Optional[datetime] = None
    skipped_versions: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["last_check_time"] = self.last_check_time.isoformat() if self.last_check_time else None
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UpdateSettings":
        last_check_str = data.pop("last_check_time", None)
        if last_check_str:
            data["last_check_time"] = datetime.fromisoformat(last_check_str)
        return cls(**data)


@dataclass
class BackupSettings:
    enabled: bool = True
    interval_hours: int = 24
    max_backups: int = 10
    backup_location: str = ""
    include_config: bool = True
    include_cache: bool = False
    include_history: bool = True
    compress_backups: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BackupSettings":
        return cls(**data)


@dataclass
class AppConfig:
    """Root application configuration — all settings in one place."""

    config_version: str = "2.0.0"
    app_version: str = "5.0.0"

    data_dir: str = str(Path.home() / ".cerebro")
    cache_dir: str = str(Path.home() / ".cerebro" / "cache")
    log_dir: str = str(Path.home() / ".cerebro" / "logs")
    backup_dir: str = str(Path.home() / ".cerebro" / "backups")

    ui: UISettings = field(default_factory=UISettings)
    scan: ScanSettings = field(default_factory=ScanSettings)
    performance: PerformanceSettings = field(default_factory=PerformanceSettings)
    notifications: NotificationSettings = field(default_factory=NotificationSettings)
    updates: UpdateSettings = field(default_factory=UpdateSettings)
    backup: BackupSettings = field(default_factory=BackupSettings)

    window_geometry: Optional[bytes] = None
    window_state: Optional[bytes] = None
    last_station: str = "mission"

    recent_scans: List[str] = field(default_factory=list)
    recent_paths: List[str] = field(default_factory=list)

    debug_mode: bool = False
    log_level: str = "INFO"
    telemetry_enabled: bool = False
    auto_save: bool = True
    minimize_to_tray: bool = True
    start_minimized: bool = False

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["ui"] = self.ui.to_dict()
        data["scan"] = self.scan.to_dict()
        data["performance"] = self.performance.to_dict()
        data["notifications"] = self.notifications.to_dict()
        data["updates"] = self.updates.to_dict()
        data["backup"] = self.backup.to_dict()
        if self.window_geometry:
            data["window_geometry"] = self.window_geometry.hex()
        if self.window_state:
            data["window_state"] = self.window_state.hex()
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AppConfig":
        ui_data = data.pop("ui", {})
        scan_data = data.pop("scan", {})
        performance_data = data.pop("performance", {})
        notifications_data = data.pop("notifications", {})
        updates_data = data.pop("updates", {})
        backup_data = data.pop("backup", {})
        geometry_hex = data.pop("window_geometry", None)
        state_hex = data.pop("window_state", None)

        known = {f.name for f in fields(cls)}
        data = {k: v for k, v in data.items() if k in known}
        instance = cls(**data)

        instance.ui = UISettings.from_dict(ui_data)
        instance.scan = ScanSettings.from_dict(scan_data)
        instance.performance = PerformanceSettings.from_dict(performance_data)
        instance.notifications = NotificationSettings.from_dict(notifications_data)
        instance.updates = UpdateSettings.from_dict(updates_data)
        instance.backup = BackupSettings.from_dict(backup_data)

        if geometry_hex:
            instance.window_geometry = bytes.fromhex(geometry_hex)
        if state_hex:
            instance.window_state = bytes.fromhex(state_hex)
        return instance

    def validate(self) -> List[str]:
        """Return a list of validation error strings (empty = valid)."""
        errors: List[str] = []
        for label, p_str in (
            ("data_dir", self.data_dir),
            ("cache_dir", self.cache_dir),
            ("log_dir", self.log_dir),
            ("backup_dir", self.backup_dir),
        ):
            try:
                if not Path(p_str).parent.exists():
                    errors.append(f"Parent directory for {label} does not exist: {Path(p_str).parent}")
            except (OSError, ValueError):
                errors.append(f"Invalid {label} path: {p_str}")

        if self.scan.min_file_size_kb < 0:
            errors.append("min_file_size_kb cannot be negative")
        if self.scan.max_file_size_mb < 0:
            errors.append("max_file_size_mb cannot be negative")
        if self.performance.max_workers < 1:
            errors.append("max_workers must be at least 1")
        if self.performance.memory_limit_mb < 100:
            errors.append("memory_limit_mb must be at least 100")
        if self.ui.font_size < 6 or self.ui.font_size > 48:
            errors.append("font_size out of range (6..48)")
        if self.ui.thumbnail_size < 16 or self.ui.thumbnail_size > 512:
            errors.append("thumbnail_size out of range (16..512)")
        if self.ui.max_recent_scans < 0 or self.ui.max_recent_scans > 100:
            errors.append("max_recent_scans out of range (0..100)")
        if self.updates.update_channel not in ("stable", "beta", "nightly"):
            errors.append(f"Invalid update channel: {self.updates.update_channel}")
        return errors

    def apply_defaults(self) -> None:
        defaults = AppConfig()
        for f in fields(defaults):
            if getattr(self, f.name) is None:
                setattr(self, f.name, getattr(defaults, f.name))
        if self.ui is None:
            self.ui = UISettings()
        if self.scan is None:
            self.scan = ScanSettings()
        if self.performance is None:
            self.performance = PerformanceSettings()
        if self.notifications is None:
            self.notifications = NotificationSettings()
        if self.updates is None:
            self.updates = UpdateSettings()
        if self.backup is None:
            self.backup = BackupSettings()
