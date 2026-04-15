# path: cerebro/workers/base_worker.py
"""
base_worker.py — Enhanced Worker Base Class

Provides common functionality for all workers:
1. Progress tracking
2. Error handling
3. Cancellation
4. Result reporting
"""

from __future__ import annotations

import traceback
import threading
from abc import ABC, ABCMeta, abstractmethod
from typing import Any, Optional, Callable

from PySide6.QtCore import QThread, Signal, Slot


# --- FIX FOR METACLASS CONFLICT ---
# QThread has a specific metaclass for Qt's signal/slot mechanism.
# ABC uses the 'abc.ABCMeta' metaclass to enforce abstract methods.
# To inherit from both, we must create a combined metaclass that
# inherits from the metaclasses of both base classes.
class CombinedMeta(type(QThread), ABCMeta):
    """
    A metaclass that combines Qt's metaclass and ABCMeta.
    This resolves the metaclass conflict when inheriting from QThread and ABC.
    """
    pass
# --- END OF FIX ---


class BaseWorker(QThread, ABC, metaclass=CombinedMeta):
    """
    Base class for all workers.
    
    Usage:
        class MyWorker(BaseWorker):
            def __init__(self, task_data):
                super().__init__()
                self.task_data = task_data
            
            def execute(self):
                # Do work
                for i in range(100):
                    self.check_cancelled()
                    self.update_progress(i, f"Processing {i}%")
                
                return result
    
        worker = MyWorker(data)
        worker.progress.connect(handle_progress)
        worker.finished.connect(handle_finished)
        worker.start()
    """
    
    # Signals
    progress = Signal(int, str)      # percent, message
    finished = Signal(object)        # result
    error = Signal(str)              # error message
    cancelled = Signal()             # cancellation signal
    
    def __init__(self):
        super().__init__()
        self._cancel_event = threading.Event()
        self._result: Any = None
        self._error: Optional[str] = None
    
    def run(self):
        """Main execution loop."""
        try:
            # Execute worker task
            self._result = self.execute()
            
            # Check if cancelled during execution
            if self._cancel_event.is_set():
                self.cancelled.emit()
                return
            
            # Emit result
            self.finished.emit(self._result)
            
        except CancelledError:
            self.cancelled.emit()
            
        except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError) as e:
            self._error = traceback.format_exc()
            self.error.emit(self._error)
    
    @abstractmethod
    def execute(self) -> Any:
        """Execute worker task. Override in subclasses."""
        raise NotImplementedError
    
    def cancel(self):
        """Request cancellation."""
        self._cancel_event.set()
    
    def check_cancelled(self):
        """Check if cancellation requested."""
        if self._cancel_event.is_set():
            raise CancelledError("Operation cancelled by user")
    
    def update_progress(self, percent: int, message: str = ""):
        """Update progress (thread-safe)."""
        percent = max(0, min(100, percent))
        self.progress.emit(percent, message)
    
    @property
    def result(self) -> Any:
        """Get execution result."""
        return self._result
    
    @property
    def error_message(self) -> Optional[str]:
        """Get error message."""
        return self._error
    
    @property
    def is_cancelled(self) -> bool:
        """Check if cancelled."""
        return self._cancel_event.is_set()


class CancelledError(Exception):
    """Raised when operation is cancelled."""
    pass


class ProgressReporter:
    """Helper for reporting progress from any thread."""
    
    def __init__(self, callback: Callable[[int, str], None]):
        self.callback = callback
    
    def report(self, percent: int, message: str = ""):
        """Report progress."""
        self.callback(percent, message)


__all__ = [
    'BaseWorker',
    'CancelledError',
    'ProgressReporter',
]