# path: main.py
from __future__ import annotations

import sys
import os
import traceback
from pathlib import Path

# ============================================================================
# FORCE DEBUG MODE
# ============================================================================
os.environ["CEREBRO_DEBUG"] = "1"
os.environ["CEREBRO_PAUSE_EXIT"] = "1"

# ============================================================================
# GLOBAL VARIABLES
# ============================================================================
ROOT_DIR = Path(__file__).resolve().parent
APP_NAME = "CEREBRO"
APP_VERSION = "5.0.0"
APP_ORG = "CEREBRO Labs"

# ============================================================================
# DEBUG UTILITIES
# ============================================================================
def pause(reason: str = "Press ENTER to exit...") -> None:
    """Force pause - ALWAYS works."""
    try:
        print(f"\n⏸ {reason}")
        input()
    except (EOFError, KeyboardInterrupt):
        print("\n⏸ Pause interrupted")
    except Exception:
        print("\n⚠️  Could not pause (maybe running in non-interactive console)")

def print_step(step: str, success: bool = True) -> None:
    """Print a step with status."""
    status = "✓" if success else "✗"
    print(f"{status} {step}")

# ============================================================================
# CRASH HANDLER
# ============================================================================
def install_crash_handlers() -> None:
    """Install handlers to catch crashes."""
    original_excepthook = sys.excepthook
    
    def crash_handler(exc_type, exc_value, exc_traceback):
        print("\n" + "!" * 60)
        print("CEREBRO CRASHED!")
        print("!" * 60)
        traceback.print_exception(exc_type, exc_value, exc_traceback)
        
        # Save crash log
        try:
            crash_file = ROOT_DIR / "crash_report.txt"
            with open(crash_file, 'w', encoding='utf-8') as f:
                f.write(f"CEREBRO Crash Report\n")
                f.write(f"Time: {__import__('datetime').datetime.now()}\n\n")
                traceback.print_exception(exc_type, exc_value, exc_traceback, file=f)
            print(f"\n📄 Crash log saved to: {crash_file}")
        except Exception:
            pass
        
        # Force pause
        pause("Crash detected. Press ENTER to exit...")
        
        # Call original handler
        original_excepthook(exc_type, exc_value, exc_traceback)
    
    sys.excepthook = crash_handler

# ============================================================================
# SIMPLE MAIN FUNCTION
# ============================================================================
def main() -> int:
    """Simple main function that definitely pauses."""
    print(f"\n{'=' * 60}")
    print(f"{APP_NAME} v{APP_VERSION}")
    print(f"{'=' * 60}")
    print("Starting in DEBUG mode...")
    
    # Install crash handlers
    install_crash_handlers()
    
    try:
        # Step 1: Import Qt
        print_step("Importing PySide6...")
        try:
            from PySide6.QtWidgets import QApplication
            from PySide6.QtCore import QTimer
            print_step("PySide6 imported successfully", True)
        except ImportError as e:
            print_step(f"Failed to import PySide6: {e}", False)
            pause("Install PySide6 with: pip install PySide6")
            return 1
        
        # Step 2: Create Qt Application
        print_step("Creating Qt application...")
        app = QApplication(sys.argv)
        app.setApplicationName(APP_NAME)
        app.setApplicationVersion(APP_VERSION)
        app.setOrganizationName(APP_ORG)
        print_step("Qt application created", True)
        
        # Step 3: Import CEREBRO modules
        print_step("Importing CEREBRO modules...")
        try:
            # Try minimal imports first
            from cerebro.ui.main_window import MainWindow
            print_step("MainWindow imported", True)
        except ImportError as e:
            print_step(f"Failed to import MainWindow: {e}", False)
            traceback.print_exc()
            pause("CEREBRO module import failed")
            return 1
        
        # Step 4: Create main window
        print_step("Creating main window...")
        try:
            window = MainWindow()
            print_step("Main window created", True)
        except Exception as e:
            print_step(f"Failed to create main window: {e}", False)
            traceback.print_exc()
            pause("Main window creation failed")
            return 1
        
        # Step 5: Show window
        print_step("Showing main window...")
        window.show()
        
        # Add a debug timer to check window status
        def check_window():
            if window.isVisible():
                print_step("Window is visible", True)
                print("\n✅ Application is running!")
                print("✅ Window should be visible on screen")
                print("✅ Close the window to exit")
            else:
                print_step("Window is NOT visible!", False)
                print("\n⚠️  WARNING: Window is not visible")
                print("⚠️  This usually means it closed immediately")
                print("⚠️  Check for errors in the console above")
        
        QTimer.singleShot(500, check_window)
        
        # Step 6: Run application
        print("\n" + "=" * 60)
        print("Starting Qt event loop...")
        print("=" * 60 + "\n")
        
        result = app.exec()
        
        print(f"\n📤 Application exited with code: {result}")
        pause("Application closed. Press ENTER to exit console...")
        
        return result
        
    except Exception as e:
        print(f"\n❌ UNEXPECTED ERROR: {e}")
        traceback.print_exc()
        pause("Unexpected error. Press ENTER to exit...")
        return 1

# ============================================================================
# EXECUTION GUARD
# ============================================================================
if __name__ == "__main__":
    # This will always pause, no matter what
    exit_code = main()
    sys.exit(exit_code)