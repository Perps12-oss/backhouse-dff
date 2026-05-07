# cerebro/services/config.py
"""
ConfigManager — loads, saves, migrates, and validates AppConfig.

Domain types live in config_types.py.
Migration logic lives in config_migration.py.
All public symbols are re-exported here for backwards-compatible imports:
  from cerebro.services.config import AppConfig, load_config, save_config, ...
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from cerebro.services.config_migration import migrate_config
from cerebro.services.config_types import (  # noqa: F401 — re-exported for callers
    AppConfig,
    BackupSettings,
    CacheMode,
    HashAlgorithm,
    NotificationSettings,
    PathFilter,
    PerformanceSettings,
    ScanMode,
    ScanSettings,
    ThemeMode,
    UISettings,
    UpdateSettings,
)

logger = logging.getLogger(__name__)

# Theme fallback: discover valid names once, log the fallback once.
_valid_themes_cache: Optional[set] = None
_theme_fallback_logged = False


def _resolve_valid_themes() -> set:
    global _valid_themes_cache
    if _valid_themes_cache is not None:
        return _valid_themes_cache
    valid: set = {
        "dark", "light", "custom", "system",
        "cyberpunk", "neon_nights", "forest_canopy", "ocean_depths",
        "sunset_desert", "arctic_frost", "violet_vault", "ember_glow",
        "lavender_dream", "mint_fresh", "coral_reef", "ice_cream",
    }
    try:
        themes_dir = Path(__file__).resolve().parents[1] / "ui" / "themes"
        if themes_dir.exists():
            for p in themes_dir.glob("*.json"):
                valid.add(p.stem)
    except OSError:
        pass
    _valid_themes_cache = valid
    return valid


def _apply_theme_fallback(config: AppConfig) -> None:
    global _theme_fallback_logged
    valid = _resolve_valid_themes()
    theme = (config.ui.theme or "").strip()
    if not theme or theme in valid:
        return
    alt = (
        theme.replace("_", "-") if "_" in theme
        else theme.replace("-", "_") if "-" in theme
        else None
    )
    if alt and alt in valid:
        return
    config.ui.theme = "dark"
    if not _theme_fallback_logged:
        logger.info("Invalid theme %r; falling back to 'dark'", theme)
        _theme_fallback_logged = True


class ConfigManager:
    """Loads, saves, migrates, and validates AppConfig on disk."""

    def __init__(self, config_dir: Optional[Path] = None) -> None:
        self.config_dir: Path = config_dir or (Path.home() / ".cerebro")
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.config_file: Path = self.config_dir / "config.json"
        self.backup_dir: Path = self.config_dir / "backups"
        self.backup_dir.mkdir(exist_ok=True)
        self._cached_config: Optional[AppConfig] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_config(self) -> AppConfig:
        if not self.config_file.exists():
            config = AppConfig()
            self.save_config(config)
            return config
        try:
            with open(self.config_file, "r", encoding="utf-8") as f:
                data: Dict[str, Any] = json.load(f)
            data = migrate_config(data, AppConfig.config_version)
            config = AppConfig.from_dict(data)
            config.apply_defaults()
            self._fix_validation_errors(config)
            _apply_theme_fallback(config)
            self._cached_config = config
            return config
        except (OSError, ValueError, KeyError, TypeError) as exc:
            logger.warning("Failed to load config (%s); using defaults", exc)
            self._backup_corrupted_config()
            return AppConfig()

    def save_config(self, config: AppConfig) -> bool:
        try:
            if self.config_file.exists():
                stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                shutil.copy2(self.config_file, self.backup_dir / f"config_backup_{stamp}.json")
                self._cleanup_old_backups()

            self.config_dir.mkdir(parents=True, exist_ok=True)
            self.backup_dir.mkdir(exist_ok=True)

            tmp_fd, tmp_path = tempfile.mkstemp(
                prefix="config_", suffix=".json", dir=str(self.config_dir)
            )
            try:
                with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                    json.dump(config.to_dict(), f, indent=2)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp_path, self.config_file)
            finally:
                try:
                    if Path(tmp_path).exists():
                        Path(tmp_path).unlink()
                except OSError:
                    pass
            return True
        except (OSError, ValueError, TypeError) as exc:
            logger.warning("Failed to save config: %s", exc)
            return False

    def export_config(self, export_path: Path, include_sensitive: bool = False) -> bool:
        try:
            config = self.load_config()
            data = config.to_dict()
            if not include_sensitive:
                data.get("notifications", {}).pop("email_address", None)
            with open(export_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            return True
        except (OSError, ValueError, TypeError) as exc:
            logger.warning("Failed to export config: %s", exc)
            return False

    def import_config(self, import_path: Path, merge: bool = True) -> bool:
        try:
            with open(import_path, "r", encoding="utf-8") as f:
                import_data: Dict[str, Any] = json.load(f)
            if merge:
                current_data = self.load_config().to_dict()
                merged = _deep_merge(current_data, import_data)
                return self.save_config(AppConfig.from_dict(merged))
            return self.save_config(AppConfig.from_dict(import_data))
        except (OSError, ValueError, TypeError) as exc:
            logger.warning("Failed to import config: %s", exc)
            return False

    def reset_to_defaults(self) -> bool:
        try:
            return self.save_config(AppConfig())
        except (OSError, ValueError, TypeError) as exc:
            logger.warning("Failed to reset config: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _fix_validation_errors(self, config: AppConfig) -> None:
        errors = config.validate()
        if not errors:
            return
        logger.info("Config validation errors: %s", errors)
        for err in errors:
            if "min_file_size_kb" in err:
                config.scan.min_file_size_kb = 100
            elif "max_file_size_mb" in err:
                config.scan.max_file_size_mb = 0

    def _backup_corrupted_config(self) -> None:
        if not self.config_file.exists():
            return
        try:
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            shutil.copy2(self.config_file, self.backup_dir / f"corrupted_config_{stamp}.json")
        except OSError:
            pass

    def _cleanup_old_backups(self) -> None:
        try:
            files = sorted(
                self.backup_dir.glob("config_backup_*.json"),
                key=lambda p: p.stat().st_mtime,
            )
            for old in files[:-5]:
                old.unlink(missing_ok=True)
        except OSError:
            pass


def _deep_merge(base: Dict, override: Dict) -> Dict:
    result = base.copy()
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = val
    return result


# ---------------------------------------------------------------------------
# Module-level singletons (backwards-compatible)
# ---------------------------------------------------------------------------

_config_instance: Optional[AppConfig] = None
_config_manager: Optional[ConfigManager] = None


def load_config(config_dir: Optional[Path] = None) -> AppConfig:
    global _config_instance, _config_manager
    if _config_instance is None:
        _config_manager = ConfigManager(config_dir)
        _config_instance = _config_manager.load_config()
    return _config_instance


def save_config(config: AppConfig) -> bool:
    global _config_manager
    if _config_manager is None:
        _config_manager = ConfigManager()
    return _config_manager.save_config(config)


def get_config_manager() -> ConfigManager:
    global _config_manager
    if _config_manager is None:
        _config_manager = ConfigManager()
    return _config_manager


def reload_config() -> AppConfig:
    global _config_instance, _config_manager
    if _config_manager is None:
        _config_manager = ConfigManager()
    _config_instance = _config_manager.load_config()
    return _config_instance
