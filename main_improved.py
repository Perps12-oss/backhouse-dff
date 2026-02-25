# path: main_improved.py
"""
CEREBRO Application Entry Point - Improved Version

This is a refactored version with:
- Proper logging instead of print statements
- Configuration-driven setup
- Better error handling
- Performance monitoring
- Dependency validation
"""
from __future__ import annotations

import sys
import os
import traceback
from pathlib import Path
from typing import Optional, List
from dataclasses import dataclass
import time
import platform

# ============================================================================
# APPLICATION METADATA
# ============================================================================
@dataclass
class AppMetadata:
    """Application metadata and version information."""
    name: str = "CEREBRO"
    version: str = "5.0.0"
    organization: str = "CEREBRO Labs"
    python_required: tuple = (3, 8)
    pyside_required: str = "6.0.0"
    
    def validate_environment(self) -> List[str]:
        """Validate runtime environment. Returns list of errors."""
        errors = []
        
        # Check Python version
        if sys.version_info < self.python_required:
            errors.append(
                f"Python {self.python_required[0]}.{self.python_required[1]}+ required, "
                f"but {sys.version_info.major}.{sys.version_info.minor} found"
            )
        
        # Check OS compatibility
        if sys.platform not in ['win32', 'linux', 'darwin']:
            errors.append(f"Unsupported platform: {sys.platform}")
        
        return errors


# ============================================================================
# EARLY INITIALIZATION
# ============================================================================
ROOT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT_DIR))

# Load debug mode from environment or config
DEBUG_MODE = os.environ.get("CEREBRO_DEBUG", "").strip().lower() in ("1", "true", "yes")

# ============================================================================
# IMPORT CEREBRO MODULES
# ============================================================================
try:
    from cerebro.services.logger import (
        get_logger,
        configure as configure_logging,
        flush_all_handlers,
        get_current_log_file
    )
    from cerebro.services.config import load_config, AppConfig
except ImportError as e:
    print(f"FATAL: Failed to import CEREBRO core modules: {e}")
    print("Ensure the cerebro package is properly installed.")
    input("Press ENTER to exit...")
    sys.exit(1)

# Configure logger
logger = get_logger("main", level=10 if DEBUG_MODE else 20)  # DEBUG=10, INFO=20

# ============================================================================
# DEPENDENCY CHECKER
# ============================================================================
class DependencyChecker:
    """Check and validate application dependencies."""
    
    @staticmethod
    def check_pyside6() -> tuple[bool, Optional[str]]:
        """Check if PySide6 is available. Returns (success, error_message)."""
        try:
            from PySide6.QtCore import __version__
            logger.info(f"PySide6 version {__version__} detected")
            return True, None
        except ImportError as e:
            error = (
                "PySide6 is not installed.\n\n"
                "Install with:\n"
                "  pip install PySide6\n\n"
                "Or install all dependencies:\n"
                "  pip install -r requirements.txt"
            )
            return False, error
    
    @staticmethod
    def check_all_dependencies() -> tuple[bool, List[str]]:
        """Check all required dependencies. Returns (success, errors)."""
        errors = []
        
        # Check PySide6
        success, error = DependencyChecker.check_pyside6()
        if not success:
            errors.append(error)
        
        # Add more dependency checks here as needed
        # Example: Pillow, numpy, etc.
        
        return len(errors) == 0, errors


# ============================================================================
# CRASH HANDLER
# ============================================================================
class CrashHandler:
    """Handle application crashes gracefully."""
    
    def __init__(self, app_metadata: AppMetadata):
        self.app_metadata = app_metadata
        self.original_excepthook = sys.excepthook
    
    def install(self) -> None:
        """Install crash handler."""
        sys.excepthook = self._handle_crash
        logger.debug("Crash handler installed")
    
    def _handle_crash(self, exc_type, exc_value, exc_traceback):
        """Handle uncaught exceptions."""
        logger.critical("=" * 60)
        logger.critical(f"{self.app_metadata.name} CRASHED!")
        logger.critical("=" * 60)
        
        # Log the exception
        logger.exception("Uncaught exception", exc_info=(exc_type, exc_value, exc_traceback))
        
        # Save crash report
        try:
            crash_file = ROOT_DIR / "crash_report.txt"
            with open(crash_file, 'w', encoding='utf-8') as f:
                f.write(f"{self.app_metadata.name} Crash Report\n")
                f.write(f"Version: {self.app_metadata.version}\n")
                f.write(f"Python: {sys.version}\n")
                f.write(f"Platform: {platform.platform()}\n")
                f.write(f"Time: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                traceback.print_exception(exc_type, exc_value, exc_traceback, file=f)
            
            logger.info(f"Crash report saved to: {crash_file}")
        except Exception as e:
            logger.error(f"Failed to save crash report: {e}")
        
        # Flush logs
        flush_all_handlers()
        
        # Pause if configured
        if os.environ.get("CEREBRO_PAUSE_EXIT", "").strip() == "1":
            try:
                input("\n⏸ Press ENTER to exit...")
            except:
                pass
        
        # Call original handler
        self.original_excepthook(exc_type, exc_value, exc_traceback)


# ============================================================================
# STARTUP MONITOR
# ============================================================================
class StartupMonitor:
    """Monitor application startup performance."""
    
    def __init__(self):
        self.steps: List[tuple[str, float]] = []
        self.start_time = time.time()
    
    def step(self, name: str) -> None:
        """Record a startup step."""
        elapsed = time.time() - self.start_time
        self.steps.append((name, elapsed))
        logger.info(f"✓ {name} ({elapsed:.3f}s)")
    
    def print_summary(self) -> None:
        """Print startup summary."""
        total = time.time() - self.start_time
        logger.info("=" * 60)
        logger.info(f"Startup completed in {total:.3f}s")
        logger.info("=" * 60)
        
        if DEBUG_MODE:
            for name, elapsed in self.steps:
                logger.debug(f"  {name}: {elapsed:.3f}s")


# ============================================================================
# APPLICATION LAUNCHER
# ============================================================================
class ApplicationLauncher:
    """Main application launcher with proper initialization."""
    
    def __init__(self):
        self.metadata = AppMetadata()
        self.config: Optional[AppConfig] = None
        self.monitor = StartupMonitor()
        self.crash_handler = CrashHandler(self.metadata)
    
    def run(self) -> int:
        """Run the application. Returns exit code."""
        logger.info("=" * 60)
        logger.info(f"{self.metadata.name} v{self.metadata.version}")
        logger.info("=" * 60)
        logger.info(f"Python: {sys.version}")
        logger.info(f"Platform: {platform.platform()}")
        
        if DEBUG_MODE:
            logger.info("⚠️  Running in DEBUG mode")
        
        log_file = get_current_log_file()
        if log_file:
            logger.info(f"Logging to: {log_file}")
        
        try:
            # Step 1: Install crash handler
            self.crash_handler.install()
            self.monitor.step("Crash handler installed")
            
            # Step 2: Validate environment
            env_errors = self.metadata.validate_environment()
            if env_errors:
                for error in env_errors:
                    logger.error(f"Environment check failed: {error}")
                return 1
            self.monitor.step("Environment validated")
            
            # Step 3: Check dependencies
            deps_ok, dep_errors = DependencyChecker.check_all_dependencies()
            if not deps_ok:
                for error in dep_errors:
                    logger.error(error)
                self._pause("Dependency check failed")
                return 1
            self.monitor.step("Dependencies validated")
            
            # Step 4: Load configuration
            try:
                self.config = load_config()
                logger.info(f"Configuration loaded (theme: {self.config.ui.theme})")
            except Exception as e:
                logger.warning(f"Failed to load config, using defaults: {e}")
                from cerebro.services.config import AppConfig
                self.config = AppConfig()
            self.monitor.step("Configuration loaded")
            
            # Step 5: Import Qt
            try:
                from PySide6.QtWidgets import QApplication
                from PySide6.QtCore import QTimer, Qt
            except ImportError as e:
                logger.error(f"Failed to import PySide6: {e}")
                self._pause("PySide6 import failed")
                return 1
            self.monitor.step("PySide6 imported")
            
            # Step 6: Create Qt application
            # Note: AA_EnableHighDpiScaling and AA_UseHighDpiPixmaps are deprecated in Qt 6
            # High DPI is enabled by default in Qt 6, no need to set these attributes
            
            app = QApplication(sys.argv)
            app.setApplicationName(self.metadata.name)
            app.setApplicationVersion(self.metadata.version)
            app.setOrganizationName(self.metadata.organization)
            self.monitor.step("Qt application created")
            
            # Step 7: Import main window
            try:
                from cerebro.ui.main_window import MainWindow
            except ImportError as e:
                logger.error(f"Failed to import MainWindow: {e}")
                logger.error(traceback.format_exc())
                self._pause("MainWindow import failed")
                return 1
            self.monitor.step("MainWindow imported")
            
            # Step 8: Create main window
            try:
                window = MainWindow()
                
                # Restore window geometry if available
                if self.config and self.config.window_geometry:
                    try:
                        window.restoreGeometry(self.config.window_geometry)
                    except Exception as e:
                        logger.warning(f"Failed to restore window geometry: {e}")
                
                if self.config and self.config.window_state:
                    try:
                        window.restoreState(self.config.window_state)
                    except Exception as e:
                        logger.warning(f"Failed to restore window state: {e}")
                
            except Exception as e:
                logger.error(f"Failed to create MainWindow: {e}")
                logger.error(traceback.format_exc())
                self._pause("MainWindow creation failed")
                return 1
            self.monitor.step("MainWindow created")
            
            # Step 9: Show window
            window.show()
            self.monitor.step("Window displayed")
            
            # Step 10: Verify window visibility
            def check_window():
                if window.isVisible():
                    logger.info("✅ Application started successfully")
                    logger.info(f"✅ Window visible on screen")
                    self.monitor.print_summary()
                else:
                    logger.warning("⚠️  Window not visible - may have closed immediately")
            
            QTimer.singleShot(500, check_window)
            
            # Step 11: Run event loop
            logger.info("=" * 60)
            logger.info("Starting Qt event loop...")
            logger.info("=" * 60)
            
            exit_code = app.exec()
            
            logger.info(f"Application exited with code: {exit_code}")
            
            # Save window state before exit
            if self.config:
                try:
                    self.config.window_geometry = window.saveGeometry()
                    self.config.window_state = window.saveState()
                    from cerebro.services.config import save_config
                    save_config(self.config)
                except Exception as e:
                    logger.warning(f"Failed to save window state: {e}")
            
            self._pause("Application closed")
            return exit_code
            
        except Exception as e:
            logger.exception(f"Unexpected error during startup: {e}")
            self._pause("Unexpected error occurred")
            return 1
        finally:
            flush_all_handlers()
    
    def _pause(self, reason: str = "Press ENTER to exit...") -> None:
        """Pause execution if configured."""
        if os.environ.get("CEREBRO_PAUSE_EXIT", "").strip() == "1":
            try:
                logger.info(f"⏸ {reason}")
                input()
            except (EOFError, KeyboardInterrupt):
                pass


# ============================================================================
# ENTRY POINT
# ============================================================================
def main() -> int:
    """Application entry point."""
    launcher = ApplicationLauncher()
    return launcher.run()


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
