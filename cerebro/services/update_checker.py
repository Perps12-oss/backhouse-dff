# cerebro/services/update_checker.py

import json
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, asdict
from pathlib import Path
import threading
import hashlib
import zipfile
import tempfile
import shutil
import sys
import subprocess
import platform

from PySide6.QtCore import QObject, Signal, QThread, Slot

from cerebro.services.config import load_config, AppConfig


@dataclass
class UpdateInfo:
    """Information about an available update."""
    version: str
    release_date: str
    download_url: str
    changelog: str
    size_bytes: int
    checksum: str
    checksum_type: str = "sha256"
    mandatory: bool = False
    prerelease: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)
        
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'UpdateInfo':
        """Create from dictionary."""
        return cls(**data)


@dataclass
class UpdateStatus:
    """Current update status."""
    last_checked: Optional[datetime] = None
    update_available: bool = False
    current_version: str = ""
    latest_version: str = ""
    update_info: Optional[UpdateInfo] = None
    download_progress: float = 0.0
    download_status: str = "idle"  # idle, downloading, verifying, installing, completed, failed
    error_message: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'last_checked': self.last_checked.isoformat() if self.last_checked else None,
            'update_available': self.update_available,
            'current_version': self.current_version,
            'latest_version': self.latest_version,
            'update_info': self.update_info.to_dict() if self.update_info else None,
            'download_progress': self.download_progress,
            'download_status': self.download_status,
            'error_message': self.error_message
        }
        
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'UpdateStatus':
        """Create from dictionary."""
        update_info_data = data.get('update_info')
        update_info = UpdateInfo.from_dict(update_info_data) if update_info_data else None
        
        last_checked_str = data.get('last_checked')
        last_checked = datetime.fromisoformat(last_checked_str) if last_checked_str else None
        
        return cls(
            last_checked=last_checked,
            update_available=data.get('update_available', False),
            current_version=data.get('current_version', ''),
            latest_version=data.get('latest_version', ''),
            update_info=update_info,
            download_progress=data.get('download_progress', 0.0),
            download_status=data.get('download_status', 'idle'),
            error_message=data.get('error_message', '')
        )


class UpdateCheckerSignals(QObject):
    """Signals for update checker."""
    update_available = Signal(UpdateInfo)
    no_update_available = Signal()
    check_failed = Signal(str)
    download_progress = Signal(float, int, int)  # percent, downloaded, total
    download_complete = Signal(Path)
    download_failed = Signal(str)
    install_progress = Signal(float, str)
    install_complete = Signal()
    install_failed = Signal(str)
    status_changed = Signal(UpdateStatus)


class UpdateChecker(QObject):
    """Checks for and manages application updates."""
    
    # Default update server URL
    DEFAULT_UPDATE_URL = "https://updates.cerebroapp.com/api/v1/check"
    
    def __init__(self, config: Optional[AppConfig] = None):
        super().__init__()
        
        self.config = config or load_config()
        self.signals = UpdateCheckerSignals()
        
        # Current status
        self.status = UpdateStatus(
            current_version=self._get_current_version()
        )
        
        # Cache directory for updates
        self.cache_dir = Path.home() / ".cerebro" / "updates"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        # Download state
        self._download_thread: Optional[threading.Thread] = None
        self._install_thread: Optional[threading.Thread] = None
        self._is_downloading = False
        self._is_installing = False
        
        # Load saved status
        self._load_status()
        
    def _get_current_version(self) -> str:
        """Get current application version."""
        # Try to get from package metadata
        try:
            import pkg_resources
            return pkg_resources.get_distribution("cerebro").version
        except:
            pass
            
        # Try to get from __version__ module
        try:
            from cerebro import __version__
            return __version__
        except:
            pass
            
        # Default fallback
        return "5.0.0"
        
    def _load_status(self):
        """Load update status from disk."""
        status_file = self.cache_dir / "status.json"
        if status_file.exists():
            try:
                with open(status_file, 'r') as f:
                    data = json.load(f)
                    self.status = UpdateStatus.from_dict(data)
            except Exception as e:
                print(f"Failed to load update status: {e}")
                
    def _save_status(self):
        """Save update status to disk."""
        status_file = self.cache_dir / "status.json"
        try:
            with open(status_file, 'w') as f:
                json.dump(self.status.to_dict(), f, indent=2)
        except Exception as e:
            print(f"Failed to save update status: {e}")
            
    def check_async(self, force: bool = False):
        """
        Check for updates asynchronously.
        
        Args:
            force: Force check even if recently checked
        """
        # Check if we should skip due to recent check
        if (not force and self.status.last_checked and 
            datetime.now() - self.status.last_checked < timedelta(hours=1)):
            self.signals.no_update_available.emit()
            return
            
        # Start check in background thread
        thread = threading.Thread(target=self._check_updates_thread, daemon=True)
        thread.start()
        
    def _check_updates_thread(self):
        """Background thread for checking updates."""
        try:
            # Update status
            self.status.last_checked = datetime.now()
            self.status.download_status = "checking"
            self.signals.status_changed.emit(self.status)
            
            # Get update info
            update_info = self._fetch_update_info()
            
            if update_info:
                # Check if version is newer
                if self._is_version_newer(update_info.version, self.status.current_version):
                    self.status.update_available = True
                    self.status.latest_version = update_info.version
                    self.status.update_info = update_info
                    
                    self.signals.update_available.emit(update_info)
                else:
                    self.status.update_available = False
                    self.signals.no_update_available.emit()
            else:
                self.status.update_available = False
                self.signals.no_update_available.emit()
                
        except urllib.error.URLError as e:
            error_msg = f"Network error: {e.reason}"
            self.signals.check_failed.emit(error_msg)
        except Exception as e:
            error_msg = f"Update check failed: {str(e)}"
            self.signals.check_failed.emit(error_msg)
        finally:
            self.status.download_status = "idle"
            self._save_status()
            self.signals.status_changed.emit(self.status)
            
    def _fetch_update_info(self) -> Optional[UpdateInfo]:
        """Fetch update information from server."""
        if not self.config.update_server_url:
            # Use local update file for testing/offline
            return self._get_local_update_info()
            
        # Prepare request
        request_data = {
            'version': self.status.current_version,
            'platform': platform.system().lower(),
            'architecture': platform.machine(),
            'channel': self.config.update_channel
        }
        
        headers = {
            'User-Agent': f'Cerebro/{self.status.current_version}',
            'Content-Type': 'application/json'
        }
        
        # Make request
        req = urllib.request.Request(
            self.config.update_server_url,
            data=json.dumps(request_data).encode('utf-8'),
            headers=headers,
            method='POST'
        )
        
        with urllib.request.urlopen(req, timeout=10) as response:
            if response.status == 200:
                data = json.loads(response.read().decode('utf-8'))
                
                if data.get('update_available', False):
                    return UpdateInfo(
                        version=data['version'],
                        release_date=data['release_date'],
                        download_url=data['download_url'],
                        changelog=data['changelog'],
                        size_bytes=data['size_bytes'],
                        checksum=data.get('checksum', ''),
                        checksum_type=data.get('checksum_type', 'sha256'),
                        mandatory=data.get('mandatory', False),
                        prerelease=data.get('prerelease', False)
                    )
                    
        return None
        
    def _get_local_update_info(self) -> Optional[UpdateInfo]:
        """Get update info from local file (for testing)."""
        update_file = self.cache_dir / "local_update.json"
        if update_file.exists():
            try:
                with open(update_file, 'r') as f:
                    data = json.load(f)
                    return UpdateInfo.from_dict(data)
            except Exception:
                pass
                
        return None
        
    def _is_version_newer(self, new_version: str, current_version: str) -> bool:
        """
        Check if new version is newer than current version.
        
        Args:
            new_version: New version string
            current_version: Current version string
            
        Returns:
            True if new version is newer
        """
        # Simple semantic version comparison
        def parse_version(version: str) -> List[int]:
            parts = version.replace('-', '.').split('.')
            numeric_parts = []
            for part in parts:
                try:
                    numeric_parts.append(int(part))
                except ValueError:
                    break
            return numeric_parts
            
        new_parts = parse_version(new_version)
        current_parts = parse_version(current_version)
        
        # Compare parts
        for i in range(max(len(new_parts), len(current_parts))):
            new_part = new_parts[i] if i < len(new_parts) else 0
            current_part = current_parts[i] if i < len(current_parts) else 0
            
            if new_part > current_part:
                return True
            elif new_part < current_part:
                return False
                
        return False
        
    def download_update(self, update_info: Optional[UpdateInfo] = None):
        """
        Download available update.
        
        Args:
            update_info: Update info to download (uses cached if None)
        """
        if self._is_downloading:
            return
            
        if update_info is None:
            if not self.status.update_info:
                self.signals.download_failed.emit("No update information available")
                return
            update_info = self.status.update_info
            
        # Start download in background thread
        self._is_downloading = True
        self._download_thread = threading.Thread(
            target=self._download_update_thread,
            args=(update_info,),
            daemon=True
        )
        self._download_thread.start()
        
    def _download_update_thread(self, update_info: UpdateInfo):
        """Background thread for downloading updates."""
        try:
            self.status.download_status = "downloading"
            self.status.download_progress = 0.0
            self.signals.status_changed.emit(self.status)
            
            # Determine download path
            download_path = self.cache_dir / f"update_{update_info.version}.zip"
            
            # Download file with progress tracking
            def report_progress(block_num, block_size, total_size):
                if total_size > 0:
                    downloaded = block_num * block_size
                    progress = min(100.0, (downloaded / total_size) * 100)
                    
                    self.status.download_progress = progress
                    self.signals.download_progress.emit(
                        progress, downloaded, total_size
                    )
                    
            # Download the file
            urllib.request.urlretrieve(
                update_info.download_url,
                download_path,
                reporthook=report_progress
            )
            
            # Verify checksum
            if update_info.checksum:
                if not self._verify_checksum(download_path, update_info):
                    raise ValueError("Checksum verification failed")
                    
            # Update status
            self.status.download_status = "downloaded"
            self.status.download_progress = 100.0
            self._save_status()
            self.signals.status_changed.emit(self.status)
            
            # Emit completion signal
            self.signals.download_complete.emit(download_path)
            
        except Exception as e:
            error_msg = f"Download failed: {str(e)}"
            self.status.error_message = error_msg
            self.status.download_status = "failed"
            self.signals.status_changed.emit(self.status)
            self.signals.download_failed.emit(error_msg)
        finally:
            self._is_downloading = False
            
    def _verify_checksum(self, file_path: Path, update_info: UpdateInfo) -> bool:
        """Verify file checksum."""
        if update_info.checksum_type == "sha256":
            hash_func = hashlib.sha256
        elif update_info.checksum_type == "sha1":
            hash_func = hashlib.sha1
        elif update_info.checksum_type == "md5":
            hash_func = hashlib.md5
        else:
            return False  # Unknown checksum type
            
        # Calculate checksum
        hash_obj = hash_func()
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b''):
                hash_obj.update(chunk)
                
        calculated = hash_obj.hexdigest()
        return calculated == update_info.checksum
        
    def install_update(self, update_path: Path):
        """
        Install downloaded update.
        
        Args:
            update_path: Path to downloaded update file
        """
        if self._is_installing:
            return
            
        # Start installation in background thread
        self._is_installing = True
        self._install_thread = threading.Thread(
            target=self._install_update_thread,
            args=(update_path,),
            daemon=True
        )
        self._install_thread.start()
        
    def _install_update_thread(self, update_path: Path):
        """Background thread for installing updates."""
        try:
            self.status.download_status = "installing"
            self.status.download_progress = 0.0
            self.signals.status_changed.emit(self.status)
            
            # Extract update
            temp_dir = tempfile.mkdtemp(prefix="cerebro_update_")
            self.signals.install_progress.emit(10.0, "Extracting update...")
            
            with zipfile.ZipFile(update_path, 'r') as zip_ref:
                for member in zip_ref.namelist():
                    member_path = os.path.realpath(os.path.join(temp_dir, member))
                    if not member_path.startswith(os.path.realpath(temp_dir) + os.sep) and member_path != os.path.realpath(temp_dir):
                        raise ValueError(f"Zip path traversal detected: {member}")
                zip_ref.extractall(temp_dir)
                
            self.signals.install_progress.emit(30.0, "Verifying files...")
            
            # Read installation instructions
            instructions_file = Path(temp_dir) / "install.json"
            if not instructions_file.exists():
                raise ValueError("Missing installation instructions")
                
            with open(instructions_file, 'r') as f:
                instructions = json.load(f)
                
            # Determine installation method
            install_method = instructions.get('install_method', 'copy')
            
            if install_method == 'copy':
                self._install_copy_method(Path(temp_dir), instructions)
            elif install_method == 'script':
                self._install_script_method(Path(temp_dir), instructions)
            else:
                raise ValueError(f"Unknown install method: {install_method}")
                
            # Cleanup
            shutil.rmtree(temp_dir)
            
            # Update status
            self.status.download_status = "completed"
            self.status.update_available = False
            self.status.update_info = None
            self._save_status()
            
            self.signals.install_progress.emit(100.0, "Installation complete!")
            self.signals.install_complete.emit()
            self.signals.status_changed.emit(self.status)
            
        except Exception as e:
            error_msg = f"Installation failed: {str(e)}"
            self.status.error_message = error_msg
            self.status.download_status = "failed"
            self.signals.status_changed.emit(self.status)
            self.signals.install_failed.emit(error_msg)
        finally:
            self._is_installing = False
            
    def _install_copy_method(self, temp_dir: Path, instructions: Dict[str, Any]):
        """Install using copy method."""
        # Get target installation directory
        if getattr(sys, 'frozen', False):
            # Running as bundled executable
            install_dir = Path(sys.executable).parent
        else:
            # Running from source
            install_dir = Path(__file__).parent.parent.parent
            
        # Copy files
        files_to_copy = instructions.get('files', [])
        
        for i, file_info in enumerate(files_to_copy):
            src = temp_dir / file_info['source']
            dst = install_dir / file_info['destination']
            
            # Create destination directory if needed
            dst.parent.mkdir(parents=True, exist_ok=True)
            
            # Copy file
            if src.is_file():
                shutil.copy2(src, dst)
            elif src.is_dir():
                shutil.copytree(src, dst, dirs_exist_ok=True)
                
            # Update progress
            progress = 30.0 + (i / len(files_to_copy)) * 60.0
            self.signals.install_progress.emit(
                progress,
                f"Copying {file_info['source']}..."
            )
            
    def _install_script_method(self, temp_dir: Path, instructions: Dict[str, Any]):
        """Install using script method."""
        # Run pre-install script if exists
        pre_script = temp_dir / "pre_install.sh"
        if pre_script.exists():
            self.signals.install_progress.emit(40.0, "Running pre-install script...")
            
            if platform.system() == "Windows":
                subprocess.run(["cmd", "/c", str(pre_script)], check=True)
            else:
                subprocess.run(["bash", str(pre_script)], check=True)
                
        # Copy files (similar to copy method but with restart handling)
        self._install_copy_method(temp_dir, instructions)
        
        # Run post-install script if exists
        post_script = temp_dir / "post_install.sh"
        if post_script.exists():
            self.signals.install_progress.emit(90.0, "Running post-install script...")
            
            if platform.system() == "Windows":
                subprocess.run(["cmd", "/c", str(post_script)], check=True)
            else:
                subprocess.run(["bash", str(post_script)], check=True)
                
    def skip_version(self, version: str):
        """
        Skip a specific version (don't notify about it again).
        
        Args:
            version: Version to skip
        """
        skipped_file = self.cache_dir / "skipped_versions.json"
        skipped_versions = []
        
        if skipped_file.exists():
            try:
                with open(skipped_file, 'r') as f:
                    skipped_versions = json.load(f)
            except Exception:
                pass
                
        if version not in skipped_versions:
            skipped_versions.append(version)
            
        with open(skipped_file, 'w') as f:
            json.dump(skipped_versions, f, indent=2)
            
    def is_version_skipped(self, version: str) -> bool:
        """Check if a version was previously skipped."""
        skipped_file = self.cache_dir / "skipped_versions.json"
        
        if skipped_file.exists():
            try:
                with open(skipped_file, 'r') as f:
                    skipped_versions = json.load(f)
                    return version in skipped_versions
            except Exception:
                pass
                
        return False
        
    def get_changelog(self) -> str:
        """Get changelog for available update."""
        if self.status.update_info:
            return self.status.update_info.changelog
        return ""
        
    def cancel_download(self):
        """Cancel current download."""
        # Note: This is a simple implementation
        # In production, you'd need proper download cancellation
        self._is_downloading = False
        self.status.download_status = "idle"
        self.signals.status_changed.emit(self.status)
        
    def cleanup_old_downloads(self):
        """Cleanup old downloaded update files."""
        try:
            for file in self.cache_dir.glob("update_*.zip"):
                # Keep files less than 7 days old
                if file.stat().st_mtime < time.time() - (7 * 86400):
                    file.unlink()
        except Exception:
            pass


# Singleton instance
_update_checker_instance: Optional[UpdateChecker] = None


def get_update_checker(config: Optional[AppConfig] = None) -> UpdateChecker:
    """
    Get or create global update checker instance.
    
    Args:
        config: Optional AppConfig instance
        
    Returns:
        UpdateChecker instance
    """
    global _update_checker_instance
    
    if _update_checker_instance is None:
        _update_checker_instance = UpdateChecker(config)
        
    return _update_checker_instance