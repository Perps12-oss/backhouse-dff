# cerebro/services/config_migration.py
"""
Config schema migration logic.

Each migration function transforms raw JSON data from an old schema version
to the next. ConfigManager calls these in sequence via migrate_config().
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict

_log = logging.getLogger(__name__)

# Map from-version → migration function
_MIGRATIONS: Dict[str, Any] = {}


def _migration(from_version: str):
    """Decorator to register a migration function."""
    def decorator(fn):
        _MIGRATIONS[from_version] = fn
        return fn
    return decorator


def migrate_config(data: Dict[str, Any], target_version: str) -> Dict[str, Any]:
    """Walk the migration chain from data's current version to target_version."""
    current = data.get("config_version", "1.0.0")
    while current != target_version:
        fn = _MIGRATIONS.get(current)
        if fn is None:
            _log.warning("No migration path from %s; forcing version to %s", current, target_version)
            data["config_version"] = target_version
            break
        _log.info("Migrating config from %s", current)
        data = fn(data)
        current = data.get("config_version", target_version)
    return data


@_migration("1.0.0")
def _migrate_1_0_0_to_2_0_0(data: Dict[str, Any]) -> Dict[str, Any]:
    """Migrate flat v1 config to nested v2 domain structure."""
    home = Path(data.get("data_dir", str(Path.home() / ".cerebro")))
    migrated: Dict[str, Any] = {
        "config_version": "2.0.0",
        "app_version": data.get("app_version", "5.0.0"),
        "data_dir": str(home),
        "cache_dir": str(home / "cache"),
        "log_dir": str(home / "logs"),
        "backup_dir": str(home / "backups"),
        "last_station": data.get("last_station", "mission"),
        "recent_scans": data.get("recent_scans", []),
        "recent_paths": data.get("recent_paths", []),
        "debug_mode": data.get("debug_mode", False),
        "log_level": data.get("log_level", "INFO"),
        "telemetry_enabled": data.get("telemetry_enabled", False),
        "auto_save": True,
        "minimize_to_tray": True,
        "start_minimized": False,
        "ui": {
            "theme": data.get("theme", "dark"),
            "font_size": data.get("font_size", 12),
            "font_family": data.get("font_family", "Segoe UI"),
            "animation_enabled": True,
            "tooltips_enabled": True,
            "confirm_deletions": True,
            "auto_expand_results": False,
            "show_hidden_files": False,
            "thumbnail_size": 64,
            "max_recent_scans": 10,
        },
        "scan": {
            "default_mode": data.get("scan_mode", "standard"),
            "min_file_size_kb": data.get("min_file_size_kb", 100),
            "max_file_size_mb": data.get("max_file_size_mb", 0),
            "default_hash_algorithm": data.get("hash_algorithm", "auto"),
            "cache_mode": data.get("cache_mode", 1),
            "recursive": data.get("recursive", True),
            "follow_symlinks": data.get("follow_symlinks", False),
            "include_hidden": data.get("include_hidden", False),
            "skip_system_folders": data.get("skip_system_folders", True),
            "verify_after_copy": True,
            "default_filters": {
                "include_patterns": [],
                "exclude_patterns": [],
                "include_extensions": data.get("allowed_extensions", []),
                "exclude_extensions": [],
            },
        },
        "performance": {
            "max_workers": data.get("max_workers", 4),
            "io_buffer_size": 8192,
            "hash_chunk_size": 65536,
            "memory_limit_mb": 1024,
            "disk_cache_size_mb": 100,
            "thread_pool_size": 8,
        },
        "notifications": {
            "enabled": True,
            "scan_complete": True,
            "scan_error": True,
            "update_available": True,
            "sound_enabled": False,
            "system_tray_notifications": True,
            "email_notifications": False,
            "email_address": "",
        },
        "updates": {
            "check_for_updates": data.get("check_for_updates", True),
            "auto_download_updates": False,
            "update_channel": "stable",
            "update_server_url": "",
            "last_check_time": None,
            "skipped_versions": [],
        },
        "backup": {
            "enabled": True,
            "interval_hours": 24,
            "max_backups": 10,
            "backup_location": "",
            "include_config": True,
            "include_cache": False,
            "include_history": True,
            "compress_backups": True,
        },
    }
    if "window_geometry" in data:
        migrated["window_geometry"] = data["window_geometry"]
    if "window_state" in data:
        migrated["window_state"] = data["window_state"]
    return migrated
