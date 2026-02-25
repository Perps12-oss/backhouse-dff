# cerebro/core/config.py

import json
import yaml
from pathlib import Path
from typing import Dict, List, Optional, Any, Union
from dataclasses import dataclass, field, asdict
from enum import Enum
import sys
import os
import shutil
from datetime import datetime
import re
import tempfile

# Theme validation: run discovery once, log fallback once (no logger import to avoid recursion)
_valid_themes_cache: Optional[set] = None
_theme_fallback_logged = False
class ThemeMode(Enum):
    """Theme modes."""
    DARK = "dark"
    LIGHT = "light"
    SYSTEM = "system"
    CUSTOM = "custom"


class ScanMode(Enum):
    """Scan modes."""
    STANDARD = "standard"
    DEEP = "deep"
    QUICK = "quick"
    CUSTOM = "custom"


class HashAlgorithm(Enum):
    """Hash algorithms."""
    MD5 = "md5"
    SHA1 = "sha1"
    SHA256 = "sha256"
    SHA512 = "sha512"


class CacheMode(Enum):
    """Cache modes."""
    DISABLED = 0
    ENABLED = 1
    AGGRESSIVE = 2


@dataclass
class PathFilter:
    """Filters for scan paths."""
    include_patterns: List[str] = field(default_factory=list)
    exclude_patterns: List[str] = field(default_factory=list)
    include_extensions: List[str] = field(default_factory=list)
    exclude_extensions: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)
        
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'PathFilter':
        """Create from dictionary."""
        if not isinstance(data, dict):
            data = {}
        return cls(**data)


@dataclass
class PerformanceSettings:
    """Performance-related settings."""
    max_workers: int = 4
    io_buffer_size: int = 8192
    hash_chunk_size: int = 65536
    memory_limit_mb: int = 1024
    disk_cache_size_mb: int = 100
    thread_pool_size: int = 8
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)
        
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'PerformanceSettings':
        """Create from dictionary."""
        return cls(**data)


@dataclass
class UISettings:
    """UI-related settings."""
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
        """Convert to dictionary."""
        return asdict(self)
        
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'UISettings':
        """Create from dictionary."""
        return cls(**data)


@dataclass
class ScanSettings:
    """Scan-related settings."""
    default_mode: str = "standard"
    min_file_size_kb: int = 100
    max_file_size_mb: int = 0  # 0 = unlimited
    default_hash_algorithm: str = "md5"
    cache_mode: int = 1  # CacheMode.ENABLED
    recursive: bool = True
    follow_symlinks: bool = False
    include_hidden: bool = False
    skip_system_folders: bool = True
    verify_after_copy: bool = True
    default_filters: PathFilter = field(default_factory=PathFilter)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        data = asdict(self)
        data['default_filters'] = self.default_filters.to_dict()
        return data
        
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ScanSettings':
        """Create from dictionary."""
        filters_data = data.pop('default_filters', {})
        if not isinstance(filters_data, dict):
            filters_data = {}
        instance = cls(**data)
        instance.default_filters = PathFilter.from_dict(filters_data)
        return instance


@dataclass
class NotificationSettings:
    """Notification settings."""
    enabled: bool = True
    scan_complete: bool = True
    scan_error: bool = True
    update_available: bool = True
    sound_enabled: bool = False
    system_tray_notifications: bool = True
    email_notifications: bool = False
    email_address: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)
        
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'NotificationSettings':
        """Create from dictionary."""
        return cls(**data)


@dataclass
class UpdateSettings:
    """Update settings."""
    check_for_updates: bool = True
    auto_download_updates: bool = False
    update_channel: str = "stable"  # stable, beta, nightly
    update_server_url: str = ""
    last_check_time: Optional[datetime] = None
    skipped_versions: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        data = asdict(self)
        data['last_check_time'] = self.last_check_time.isoformat() if self.last_check_time else None
        return data
        
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'UpdateSettings':
        """Create from dictionary."""
        last_check_str = data.pop('last_check_time', None)
        if last_check_str:
            data['last_check_time'] = datetime.fromisoformat(last_check_str)
        return cls(**data)


@dataclass
class BackupSettings:
    """Backup settings."""
    enabled: bool = True
    interval_hours: int = 24
    max_backups: int = 10
    backup_location: str = ""
    include_config: bool = True
    include_cache: bool = False
    include_history: bool = True
    compress_backups: bool = True
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)
        
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'BackupSettings':
        """Create from dictionary."""
        return cls(**data)


@dataclass
class AppConfig:
    """
    Main application configuration.
    
    This is a comprehensive configuration class that stores all application settings.
    """
    
    # Versioning
    config_version: str = "2.0.0"
    app_version: str = "5.0.0"
    
    # Paths
    data_dir: str = str(Path.home() / ".cerebro")
    cache_dir: str = str(Path.home() / ".cerebro" / "cache")
    log_dir: str = str(Path.home() / ".cerebro" / "logs")
    backup_dir: str = str(Path.home() / ".cerebro" / "backups")
    
    # Component settings
    ui: UISettings = field(default_factory=UISettings)
    scan: ScanSettings = field(default_factory=ScanSettings)
    performance: PerformanceSettings = field(default_factory=PerformanceSettings)
    notifications: NotificationSettings = field(default_factory=NotificationSettings)
    updates: UpdateSettings = field(default_factory=UpdateSettings)
    backup: BackupSettings = field(default_factory=BackupSettings)
    
    # Window state
    window_geometry: Optional[bytes] = None
    window_state: Optional[bytes] = None
    last_station: str = "mission"
    
    # Recent items
    recent_scans: List[str] = field(default_factory=list)
    recent_paths: List[str] = field(default_factory=list)
    
    # Advanced
    debug_mode: bool = False
    log_level: str = "INFO"
    telemetry_enabled: bool = False
    auto_save: bool = True
    minimize_to_tray: bool = True
    start_minimized: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary."""
        data = asdict(self)
        
        # Handle nested dataclasses
        data['ui'] = self.ui.to_dict()
        data['scan'] = self.scan.to_dict()
        data['performance'] = self.performance.to_dict()
        data['notifications'] = self.notifications.to_dict()
        data['updates'] = self.updates.to_dict()
        data['backup'] = self.backup.to_dict()
        
        # Handle binary data
        if self.window_geometry:
            data['window_geometry'] = self.window_geometry.hex()
        if self.window_state:
            data['window_state'] = self.window_state.hex()
            
        return data
        
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AppConfig':
        """Create configuration from dictionary."""
        # Extract nested dataclasses
        ui_data = data.pop('ui', {})
        scan_data = data.pop('scan', {})
        performance_data = data.pop('performance', {})
        notifications_data = data.pop('notifications', {})
        updates_data = data.pop('updates', {})
        backup_data = data.pop('backup', {})
        
        # Handle binary data
        geometry_hex = data.pop('window_geometry', None)
        state_hex = data.pop('window_state', None)
        
        # Create instance
        instance = cls(**data)
        
        # Set nested dataclasses
        instance.ui = UISettings.from_dict(ui_data)
        instance.scan = ScanSettings.from_dict(scan_data)
        instance.performance = PerformanceSettings.from_dict(performance_data)
        instance.notifications = NotificationSettings.from_dict(notifications_data)
        instance.updates = UpdateSettings.from_dict(updates_data)
        instance.backup = BackupSettings.from_dict(backup_data)
        
        # Convert hex strings back to bytes
        if geometry_hex:
            instance.window_geometry = bytes.fromhex(geometry_hex)
        if state_hex:
            instance.window_state = bytes.fromhex(state_hex)
            
        return instance
        
    def validate(self) -> List[str]:
        """
        Validate configuration.
        
        Returns:
            List of validation errors (empty if valid)
        """
        errors = []
        
        # Validate paths
        try:
            data_path = Path(self.data_dir)
            if not data_path.parent.exists():
                errors.append(f"Parent directory for data_dir does not exist: {data_path.parent}")
        except Exception:
            errors.append(f"Invalid data_dir path: {self.data_dir}")

        # Validate other paths (best-effort)
        for label, p_str in (("cache_dir", self.cache_dir), ("log_dir", self.log_dir), ("backup_dir", self.backup_dir)):
            try:
                p = Path(p_str)
                if not p.parent.exists():
                    errors.append(f"Parent directory for {label} does not exist: {p.parent}")
            except Exception:
                errors.append(f"Invalid {label} path: {p_str}")

            
        # Validate numeric ranges
        if self.scan.min_file_size_kb < 0:
            errors.append("min_file_size_kb cannot be negative")
            
        if self.scan.max_file_size_mb < 0:
            errors.append("max_file_size_mb cannot be negative")
            
        if self.performance.max_workers < 1:
            errors.append("max_workers must be at least 1")
            
        if self.performance.memory_limit_mb < 100:
            errors.append("memory_limit_mb must be at least 100")
        # Validate theme without importing theme_engine (avoids recursion: theme_engine calls load_config).
        # Use base set + built-in themes + theme JSON files; discovery runs once at startup.
        global _valid_themes_cache, _theme_fallback_logged
        if _valid_themes_cache is None:
            # Include all built-in themes defined in theme_engine.py
            valid_themes = {
                "dark", "light", "custom", "system",
                # Built-in themes from _get_builtin_themes()
                "cyberpunk", "neon_nights", "forest_canopy", "ocean_depths",
                "sunset_desert", "arctic_frost", "violet_vault", "ember_glow",
                "lavender_dream", "mint_fresh", "coral_reef", "ice_cream"
            }
            try:
                themes_dir = Path(__file__).resolve().parents[1] / "ui" / "themes"
                if themes_dir.exists():
                    for p in themes_dir.glob("*.json"):
                        valid_themes.add(p.stem)
            except Exception:
                pass
            _valid_themes_cache = valid_themes
        else:
            valid_themes = _valid_themes_cache

        theme_name = (self.ui.theme or "").strip()
        if theme_name and theme_name not in valid_themes:
            alt = theme_name.replace("_", "-") if "_" in theme_name else (theme_name.replace("-", "_") if "-" in theme_name else None)
            if not alt or alt not in valid_themes:
                self.ui.theme = "dark"
                if not _theme_fallback_logged:
                    print("[CEREBRO] Invalid theme '%s'; falling back to 'dark'." % theme_name)
                    _theme_fallback_logged = True
            # do not append to errors; already fixed in memory

        # Validate UI ranges
        if self.ui.font_size < 6 or self.ui.font_size > 48:
            errors.append("font_size out of range (6..48)")

        if self.ui.thumbnail_size < 16 or self.ui.thumbnail_size > 512:
            errors.append("thumbnail_size out of range (16..512)")

        if self.ui.max_recent_scans < 0 or self.ui.max_recent_scans > 100:
            errors.append("max_recent_scans out of range (0..100)")

        # Validate update channel
        valid_channels = ["stable", "beta", "nightly"]
        if self.updates.update_channel not in valid_channels:
            errors.append(f"Invalid update channel: {self.updates.update_channel}")
            
        return errors
        
    def apply_defaults(self):
        """Apply default values to missing fields."""
        defaults = AppConfig()
        
        # Merge defaults for missing fields
        for field_name, default_value in asdict(defaults).items():
            if getattr(self, field_name) is None:
                setattr(self, field_name, default_value)
                
        # Ensure nested dataclasses are initialized
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


class ConfigManager:
    """Manages application configuration loading, saving, and migration."""
    
    def __init__(self, config_dir: Optional[Path] = None):
        """
        Initialize configuration manager.
        
        Args:
            config_dir: Configuration directory (uses default if None)
        """
        if config_dir is None:
            config_dir = Path.home() / ".cerebro"
        self._cached_config = None    
        self.config_dir = config_dir
        self.config_dir.mkdir(parents=True, exist_ok=True)
        
        self.config_file = config_dir / "config.json"
        self.backup_dir = config_dir / "backups"
        self.backup_dir.mkdir(exist_ok=True)
        
        # Migration support
        self.migrations = {
            "1.0.0": self._migrate_1_0_0_to_2_0_0,
        }
        
    def load_config(self) -> AppConfig:
        """
        Load configuration from file.
        
        Returns:
            AppConfig instance
        """
        # Check if config file exists
        if not self.config_file.exists():
            # Create default config
            config = AppConfig()
            self.save_config(config)
            return config
            
        try:
            # Read config file
            with open(self.config_file, 'r') as f:
                data = json.load(f)
                
            # Check config version
            config_version = data.get('config_version', '1.0.0')
            
            # Migrate if needed
            if config_version != AppConfig.config_version:
                data = self._migrate_config(data, config_version)
                
            # Create config from data
            config = AppConfig.from_dict(data)
            
            # Apply defaults for any missing fields
            config.apply_defaults()
            
            # Validate
            errors = config.validate()
            if errors:
                print(f"Configuration validation errors: {errors}")
                # Fix obvious errors
                for error in errors:
                    if "min_file_size_kb" in error:
                        config.scan.min_file_size_kb = 100
                    elif "max_file_size_mb" in error:
                        config.scan.max_file_size_mb = 0
                    elif "Invalid theme:" in error:
                        config.ui.theme = "dark"
                        
            self._cached_config = config
            return config
            
        except Exception as e:
            print(f"Failed to load config: {e}")
            # Create backup of corrupted config
            self._backup_corrupted_config()
            # Return default config
            return AppConfig()
            
    def save_config(self, config: AppConfig) -> bool:
        """
        Save configuration to file.
        
        Args:
            config: AppConfig instance
            
        Returns:
            True if save successful
        """
        try:
            # Create backup of current config
            if self.config_file.exists():
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                backup_file = self.backup_dir / f"config_backup_{timestamp}.json"
                shutil.copy2(self.config_file, backup_file)
                
                # Cleanup old backups (keep last 5)
                self._cleanup_old_backups()
                
            # Convert to dictionary
            data = config.to_dict()
            
            # Write to file (atomic)
            self.config_dir.mkdir(parents=True, exist_ok=True)
            self.backup_dir.mkdir(exist_ok=True)

            tmp_fd, tmp_path = tempfile.mkstemp(prefix="config_", suffix=".json", dir=str(self.config_dir))
            try:
                with os.fdopen(tmp_fd, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp_path, self.config_file)
            finally:
                try:
                    if os.path.exists(tmp_path):
                        os.remove(tmp_path)
                except Exception:
                    pass

            return True
            
        except Exception as e:
            print(f"Failed to save config: {e}")
            return False
            
    def _migrate_config(self, data: Dict[str, Any], from_version: str) -> Dict[str, Any]:
        """
        Migrate configuration from older version.
        
        Args:
            data: Configuration data
            from_version: Source version
            
        Returns:
            Migrated configuration data
        """
        current_version = from_version
        
        while current_version != AppConfig.config_version:
            if current_version in self.migrations:
                print(f"Migrating config from {current_version}")
                data = self.migrations[current_version](data)
                
                # Update version in data
                if current_version == "1.0.0":
                    current_version = "2.0.0"
                else:
                    current_version = AppConfig.config_version
            else:
                # No migration path, return as-is with updated version
                data['config_version'] = AppConfig.config_version
                break
                
        return data
        
    def _migrate_1_0_0_to_2_0_0(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Migrate from version 1.0.0 to 2.0.0.
        
        Args:
            data: Old configuration data
            
        Returns:
            Migrated configuration data
        """
        migrated = {}
        
        # Copy basic fields
        for field in ['app_version', 'data_dir', 'last_station', 
                     'recent_scans', 'recent_paths', 'debug_mode',
                     'log_level', 'telemetry_enabled']:
            if field in data:
                migrated[field] = data[field]
                
        # Set new version
        migrated['config_version'] = "2.0.0"
        
        # Migrate UI settings
        migrated['ui'] = {
            'theme': data.get('theme', 'dark'),
            'font_size': data.get('font_size', 12),
            'font_family': data.get('font_family', 'Segoe UI'),
            'animation_enabled': True,
            'tooltips_enabled': True,
            'confirm_deletions': True,
            'auto_expand_results': False,
            'show_hidden_files': False,
            'thumbnail_size': 64,
            'max_recent_scans': 10
        }
        
        # Migrate scan settings
        migrated['scan'] = {
            'default_mode': data.get('scan_mode', 'standard'),
            'min_file_size_kb': data.get('min_file_size_kb', 100),
            'max_file_size_mb': data.get('max_file_size_mb', 0),
            'default_hash_algorithm': data.get('hash_algorithm', 'md5'),
            'cache_mode': data.get('cache_mode', 1),
            'recursive': data.get('recursive', True),
            'follow_symlinks': data.get('follow_symlinks', False),
            'include_hidden': data.get('include_hidden', False),
            'skip_system_folders': data.get('skip_system_folders', True),
            'verify_after_copy': True,
            'default_filters': {
                'include_patterns': [],
                'exclude_patterns': [],
                'include_extensions': data.get('allowed_extensions', []),
                'exclude_extensions': []
            }
        }
        
        # Migrate performance settings
        migrated['performance'] = {
            'max_workers': data.get('max_workers', 4),
            'io_buffer_size': 8192,
            'hash_chunk_size': 65536,
            'memory_limit_mb': 1024,
            'disk_cache_size_mb': 100,
            'thread_pool_size': 8
        }
        
        # Migrate notification settings
        migrated['notifications'] = {
            'enabled': True,
            'scan_complete': True,
            'scan_error': True,
            'update_available': True,
            'sound_enabled': False,
            'system_tray_notifications': True,
            'email_notifications': False,
            'email_address': ""
        }
        
        # Migrate update settings
        migrated['updates'] = {
            'check_for_updates': data.get('check_for_updates', True),
            'auto_download_updates': False,
            'update_channel': 'stable',
            'update_server_url': "",
            'last_check_time': None,
            'skipped_versions': []
        }
        
        # Migrate backup settings
        migrated['backup'] = {
            'enabled': True,
            'interval_hours': 24,
            'max_backups': 10,
            'backup_location': "",
            'include_config': True,
            'include_cache': False,
            'include_history': True,
            'compress_backups': True
        }
        
        # Window state
        if 'window_geometry' in data:
            migrated['window_geometry'] = data['window_geometry']
        if 'window_state' in data:
            migrated['window_state'] = data['window_state']
            
        # Additional settings
        migrated['cache_dir'] = str(Path(data.get('data_dir', str(Path.home() / ".cerebro"))) / "cache")
        migrated['log_dir'] = str(Path(data.get('data_dir', str(Path.home() / ".cerebro"))) / "logs")
        migrated['backup_dir'] = str(Path(data.get('data_dir', str(Path.home() / ".cerebro"))) / "backups")
        migrated['auto_save'] = True
        migrated['minimize_to_tray'] = True
        migrated['start_minimized'] = False
        
        return migrated
        
    def _backup_corrupted_config(self):
        """Create backup of corrupted configuration file."""
        if self.config_file.exists():
            try:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                backup_file = self.backup_dir / f"corrupted_config_{timestamp}.json"
                shutil.copy2(self.config_file, backup_file)
            except Exception:
                pass
                
    def _cleanup_old_backups(self):
        """Cleanup old backup files."""
        try:
            backup_files = list(self.backup_dir.glob("config_backup_*.json"))
            backup_files.sort(key=lambda x: x.stat().st_mtime)
            
            # Keep only last 5 backups
            if len(backup_files) > 5:
                for old_file in backup_files[:-5]:
                    old_file.unlink()
        except Exception:
            pass
            
    def export_config(self, export_path: Path, include_sensitive: bool = False) -> bool:
        """
        Export configuration to file.
        
        Args:
            export_path: Path to export file
            include_sensitive: Include sensitive data (email, etc.)
            
        Returns:
            True if export successful
        """
        try:
            config = self.load_config()
            data = config.to_dict()
            
            # Remove sensitive data if requested
            if not include_sensitive:
                if 'notifications' in data:
                    data['notifications'].pop('email_address', None)
                    
            with open(export_path, 'w') as f:
                json.dump(data, f, indent=2)
                
            return True
            
        except Exception as e:
            print(f"Failed to export config: {e}")
            return False
            
    def import_config(self, import_path: Path, merge: bool = True) -> bool:
        """
        Import configuration from file.
        
        Args:
            import_path: Path to import file
            merge: Merge with existing config (False = replace)
            
        Returns:
            True if import successful
        """
        try:
            with open(import_path, 'r') as f:
                import_data = json.load(f)
                
            if merge:
                # Load current config and merge
                current_config = self.load_config()
                current_data = current_config.to_dict()
                
                # Merge dictionaries (import data takes precedence)
                merged_data = self._deep_merge(current_data, import_data)
                
                # Create merged config
                merged_config = AppConfig.from_dict(merged_data)
                
                # Save merged config
                return self.save_config(merged_config)
            else:
                # Replace with imported config
                imported_config = AppConfig.from_dict(import_data)
                return self.save_config(imported_config)
                
        except Exception as e:
            print(f"Failed to import config: {e}")
            return False
            
    def _deep_merge(self, dict1: Dict, dict2: Dict) -> Dict:
        """Deep merge two dictionaries."""
        result = dict1.copy()
        
        for key, value in dict2.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._deep_merge(result[key], value)
            else:
                result[key] = value
                
        return result
        
    def reset_to_defaults(self) -> bool:
        """
        Reset configuration to defaults.
        
        Returns:
            True if reset successful
        """
        try:
            default_config = AppConfig()
            return self.save_config(default_config)
        except Exception as e:
            print(f"Failed to reset config: {e}")
            return False


# Global configuration instance
_config_instance: Optional[AppConfig] = None
_config_manager: Optional[ConfigManager] = None


def load_config(config_dir: Optional[Path] = None) -> AppConfig:
    """
    Load application configuration.
    
    Args:
        config_dir: Optional configuration directory
        
    Returns:
        AppConfig instance
    """
    global _config_instance, _config_manager
    
    if _config_instance is None:
        _config_manager = ConfigManager(config_dir)
        _config_instance = _config_manager.load_config()
        
    return _config_instance


def save_config(config: AppConfig) -> bool:
    """
    Save application configuration.
    
    Args:
        config: AppConfig instance
        
    Returns:
        True if save successful
    """
    global _config_manager
    
    if _config_manager is None:
        _config_manager = ConfigManager()
        
    return _config_manager.save_config(config)


def get_config_manager() -> ConfigManager:
    """
    Get configuration manager instance.
    
    Returns:
        ConfigManager instance
    """
    global _config_manager
    
    if _config_manager is None:
        _config_manager = ConfigManager()
        
    return _config_manager


def reload_config() -> AppConfig:
    """
    Reload configuration from disk.
    
    Returns:
        Reloaded AppConfig instance
    """
    global _config_instance, _config_manager
    
    if _config_manager is None:
        _config_manager = ConfigManager()
        
    _config_instance = _config_manager.load_config()
    return _config_instance