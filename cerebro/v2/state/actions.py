"""
Declarative state transitions. UI and coordinator dispatch; reducer applies.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple, Union

from cerebro.engines.base_engine import DuplicateGroup

# ---------------------------------------------------------------------------
# History — scan history grid (Blueprint Sprint 2)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HistoryDataLoaded:
    """Replace in-memory scan history rows (from DB) and reset to page 0."""

    rows: Tuple[Dict[str, Any], ...]


@dataclass(frozen=True)
class HistoryGridSortChanged:
    """Sort key is a display column id: date | mode | folders | ..."""

    column: str
    sort_asc: bool


@dataclass(frozen=True)
class HistoryGridFilterChanged:
    text: str


@dataclass(frozen=True)
class HistoryGridPageChanged:
    page_index: int


@dataclass(frozen=True)
class ResultsViewSortChanged:
    """File list column: Name | Size | Date | Folder (matches :class:`VirtualFileGrid`)."""

    column: str
    sort_asc: bool


@dataclass(frozen=True)
class ResultsViewFilterChanged:
    """``all`` | ``pictures`` | ``music`` | ``videos`` | ``documents`` | ``archives`` | ``other``"""

    filter_key: str


@dataclass(frozen=True)
class ResultsFilesRemoved:
    """Paths no longer present on disk (batch delete or move). Updates ``AppState.groups``."""

    paths: Tuple[str, ...]


@dataclass(frozen=True)
class DeletionHistoryDataLoaded:
    """Rows from the deletion history DB snapshot (dicts, see ``deletion_history_view``)."""

    rows: Tuple[Dict[str, Any], ...]


@dataclass(frozen=True)
class HistorySubTabChanged:
    """History page sub-tab: ``scan`` | ``deletion`` (stored in ``AppState.ui``)."""

    key: str


@dataclass(frozen=True)
class ReviewViewFilterChanged:
    """Review thumb grid file-type bucket (same keys as :class:`ResultsViewFilterChanged`)."""

    filter_key: str


@dataclass(frozen=True)
class ScanStarted:
    """Background scan is running; UI mode becomes ``scanning``."""

    scan_mode: str = "files"


@dataclass(frozen=True)
class ScanProgressSnapshot:
    """Latest engine progress; merged into ``AppState.scan_progress``."""

    data: Dict[str, Any]


@dataclass(frozen=True)
class ScanEnded:
    """Scan finished without a successful result payload (cancelled or error)."""

    reason: str  # "cancelled" | "error"


@dataclass(frozen=True)
class SetActiveTab:
    """User or shell requests a top-level main tab; reducer owns validation."""

    key: str


@dataclass(frozen=True)
class ScanCompleted:
    """Engine finished successfully; full group list and mode for downstream UI."""

    groups: List[DuplicateGroup]
    scan_mode: str = "files"


@dataclass(frozen=True)
class ReviewNavigate:
    """Open the Review page for a group. Optional ``groups`` is a snapshot from Results."""

    group_id: int
    groups: Optional[Tuple[DuplicateGroup, ...]] = None


Action = Union[
    SetActiveTab,
    ScanStarted,
    ScanProgressSnapshot,
    ScanEnded,
    ScanCompleted,
    ReviewNavigate,
    HistoryDataLoaded,
    HistoryGridSortChanged,
    HistoryGridFilterChanged,
    HistoryGridPageChanged,
    ResultsViewSortChanged,
    ResultsViewFilterChanged,
    ResultsFilesRemoved,
    DeletionHistoryDataLoaded,
    HistorySubTabChanged,
    ReviewViewFilterChanged,
]
