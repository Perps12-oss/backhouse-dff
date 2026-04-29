# -*- coding: utf-8 -*-
"""
Declarative state transitions. UI and coordinator dispatch; reducer applies.
(FINAL PLAN v2.0 ?2.2: User Action -> Dispatch -> State Update -> Render)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple, Union

from cerebro.engines.base_engine import DuplicateGroup


# ---------------------------------------------------------------------------
# Global Advanced Toggle (FINAL PLAN ?1.2)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AdvancedModeToggled:
    """Toggle the global advanced mode (instant, no reload)."""
    value: Optional[bool] = None
    """None means flip current state; True/False forces it."""


# ---------------------------------------------------------------------------
# Theme (FINAL PLAN ?3)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ThemeChanged:
    """Theme selection: 'light', 'dark', or 'system'."""
    theme: str


# ---------------------------------------------------------------------------
# Selection (FINAL PLAN ?5.5)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FileSelectionChanged:
    """Stable file IDs currently selected for deletion."""
    file_ids: Tuple[str, ...]


@dataclass(frozen=True)
class FileSelectionCleared:
    """Clear all file selections."""


# ---------------------------------------------------------------------------
# Scan Lifecycle (FINAL PLAN ?9)
# ---------------------------------------------------------------------------

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
class ScanPaused:
    """Scan paused by user."""


@dataclass(frozen=True)
class ScanResumed:
    """Scan resumed by user."""


# ---------------------------------------------------------------------------
# Scan Completed (FINAL PLAN ?9)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ScanCompleted:
    """Engine finished successfully; full group list and mode for downstream UI."""
    groups: List[DuplicateGroup]
    scan_mode: str = "files"


# ---------------------------------------------------------------------------
# Tab Navigation (FINAL PLAN ?1.1)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SetActiveTab:
    """User or shell requests a top-level main tab; reducer owns validation."""
    key: str


# ---------------------------------------------------------------------------
# Review (FINAL PLAN ?5.8)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ReviewNavigate:
    """Open the Review for a group. Optional ``groups`` is a snapshot from Duplicates."""
    group_id: int
    groups: Optional[Tuple[DuplicateGroup, ...]] = None


@dataclass(frozen=True)
class ReviewViewFilterChanged:
    """Review file-type bucket (same keys as :class:`ResultsViewFilterChanged`)."""
    filter_key: str


# ---------------------------------------------------------------------------
# History ??? scan history grid (FINAL PLAN ?7)
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
class DeletionHistoryDataLoaded:
    """Rows from the deletion history DB snapshot (dicts, see ``deletion_history_view``)."""
    rows: Tuple[Dict[str, Any], ...]


@dataclass(frozen=True)
class HistorySubTabChanged:
    """History page sub-tab: ``scan`` | ``deletion`` (stored in ``AppState.ui``)."""
    key: str


# ---------------------------------------------------------------------------
# Duplicates / Results (FINAL PLAN ?5)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ResultsGroupGridSortChanged:
    """Duplicates page group rows: ``reclaimable`` | ``files`` | ``group_id`` | ``path``."""
    column: str
    sort_asc: bool


@dataclass(frozen=True)
class ResultsViewFilterChanged:
    """``all`` | ``pictures`` | ``music`` | ``videos`` | ``documents`` | ``archives`` | ``other``"""
    filter_key: str


@dataclass(frozen=True)
class ResultsViewTextFilterChanged:
    """Name/path substring filter for the Duplicates file list."""
    text: str


# ---------------------------------------------------------------------------
# Delete Flow (FINAL PLAN ?6)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SetDryRun:
    """``True`` = delete ceremony previews only (no filesystem changes)."""
    value: bool


@dataclass(frozen=True)
class ResultsFilesRemoved:
    """Paths no longer present on disk (batch delete or move). Updates ``AppState.groups``."""
    paths: Tuple[str, ...]


@dataclass(frozen=True)
class GroupsPruned:
    """Store-first prune action carrying already-pruned duplicate groups."""
    groups: Tuple[DuplicateGroup, ...]


# ---------------------------------------------------------------------------
# Action Union
# ---------------------------------------------------------------------------

Action = Union[
    SetActiveTab,
    AdvancedModeToggled,
    ThemeChanged,
    FileSelectionChanged,
    FileSelectionCleared,
    ScanStarted,
    ScanProgressSnapshot,
    ScanEnded,
    ScanPaused,
    ScanResumed,
    ScanCompleted,
    ReviewNavigate,
    ReviewViewFilterChanged,
    HistoryDataLoaded,
    HistoryGridSortChanged,
    HistoryGridFilterChanged,
    HistoryGridPageChanged,
    DeletionHistoryDataLoaded,
    HistorySubTabChanged,
    ResultsGroupGridSortChanged,
    ResultsViewFilterChanged,
    ResultsViewTextFilterChanged,
    SetDryRun,
    ResultsFilesRemoved,
    GroupsPruned,
]
