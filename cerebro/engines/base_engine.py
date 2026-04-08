"""
Base Engine Interface

All scan engines must inherit from BaseEngine and implement its abstract methods.
This provides a unified interface for the orchestrator to interact with any scan type.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, List, Optional
from pathlib import Path


class ScanState(Enum):
    """State of a scan operation."""
    IDLE = "idle"
    SCANNING = "scanning"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    ERROR = "error"


@dataclass
class ScanProgress:
    """Snapshot of scan progress for UI updates."""
    state: ScanState
    files_scanned: int = 0
    files_total: int = 0  # 0 if unknown
    duplicates_found: int = 0
    groups_found: int = 0
    bytes_reclaimable: int = 0
    elapsed_seconds: float = 0.0
    current_file: str = ""  # path of file currently being processed
    eta_seconds: Optional[float] = None  # estimated time to completion


@dataclass
class DuplicateFile:
    """A single file within a duplicate group."""
    path: Path
    size: int
    modified: float  # timestamp
    extension: str
    is_keeper: bool = False  # True = auto-selected to keep
    similarity: float = 1.0  # 0.0-1.0, 1.0 = exact match
    metadata: dict = field(default_factory=dict)  # engine-specific data


@dataclass
class DuplicateGroup:
    """A group of duplicate/similar files."""
    group_id: int
    files: List[DuplicateFile] = field(default_factory=list)
    total_size: int = 0  # sum of all file sizes in group
    reclaimable: int = 0  # total_size minus the kept file
    similarity_type: str = "exact"  # exact, visual, audio, etc.

    def __post_init__(self):
        """Calculate derived fields after initialization."""
        if self.files:
            self.total_size = sum(f.size for f in self.files)
            keepers = [f for f in self.files if f.is_keeper]
            if keepers:
                keeper_size = sum(f.size for f in keepers)
            else:
                keeper_size = max(f.size for f in self.files)
            self.reclaimable = self.total_size - keeper_size

    @property
    def file_count(self) -> int:
        """Number of files in this group."""
        return len(self.files)

    def get_keeper_index(self) -> int:
        """Return the index of the keeper file (largest by size, or flagged is_keeper)."""
        if not self.files:
            return 0
        keepers = [i for i, f in enumerate(self.files) if f.is_keeper]
        if keepers:
            return keepers[0]
        return max(range(len(self.files)), key=lambda i: self.files[i].size)


@dataclass
class EngineOption:
    """Configurable option for an engine."""
    name: str  # internal key
    display_name: str  # human-readable label
    type: str  # "int", "float", "str", "bool", "choice"
    default: any
    choices: Optional[List[str]] = None  # for type="choice"
    min_value: Optional[float] = None  # for int/float
    max_value: Optional[float] = None  # for int/float
    tooltip: str = ""


class BaseEngine(ABC):
    """
    Abstract base class that all scan engines must implement.

    Engines are responsible for detecting duplicates of their specific type
    and reporting progress/results through the defined interface.
    """

    def __init__(self):
        """Initialize the engine."""
        self._state = ScanState.IDLE
        self._folders: List[Path] = []
        self._protected: List[Path] = []
        self._options: dict = {}

    @property
    def state(self) -> ScanState:
        """Current scan state."""
        return self._state

    @abstractmethod
    def get_name(self) -> str:
        """Return human-readable engine name."""
        pass

    @abstractmethod
    def get_mode_options(self) -> List[EngineOption]:
        """
        Return list of configurable options for the left panel UI.

        Returns:
            List of EngineOption objects describing available settings.
        """
        pass

    @abstractmethod
    def configure(self, folders: List[Path], protected: List[Path],
                 options: dict) -> None:
        """
        Set scan parameters before starting.

        Args:
            folders: List of directory paths to scan.
            protected: List of directory paths to protect from deletion.
            options: Dict of engine-specific option values from get_mode_options().
        """
        pass

    @abstractmethod
    def start(self, progress_callback: Callable[[ScanProgress], None]) -> None:
        """
        Begin scanning in a background thread. Non-blocking.

        Args:
            progress_callback: Function called with ScanProgress updates.
        """
        pass

    @abstractmethod
    def pause(self) -> None:
        """Pause the current scan. Should be resumable."""
        pass

    @abstractmethod
    def resume(self) -> None:
        """Resume a paused scan."""
        pass

    @abstractmethod
    def cancel(self) -> None:
        """Cancel the current scan. Not resumable."""
        pass

    @abstractmethod
    def get_results(self) -> List[DuplicateGroup]:
        """
        Return grouped results after scan completes.

        Returns:
            List of DuplicateGroup objects containing duplicate files.
        """
        pass

    @abstractmethod
    def get_progress(self) -> ScanProgress:
        """
        Return current progress snapshot.

        Returns:
            ScanProgress object with current scan state.
        """
        pass

    def _set_state(self, new_state: ScanState) -> None:
        """Update internal state (thread-safe wrapper)."""
        self._state = new_state
