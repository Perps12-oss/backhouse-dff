"""
Declarative state transitions. UI and coordinator dispatch; reducer applies.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple, Union

from cerebro.engines.base_engine import DuplicateGroup


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
]
