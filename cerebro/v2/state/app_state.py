"""
Single source of truth for the CEREBRO v2 shell (Blueprints §0.1, Sprint 1).

The desktop UI and a future web layer must be able to read the same structure;
engine types stay in `cerebro.engines` — this module only holds references
to :class:`DuplicateGroup` in memory (JSON boundaries will map paths later).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from cerebro.engines.base_engine import DuplicateGroup

# Must match keys in `cerebro.v2.ui.tab_bar.TABS` (order not enforced here).
VALID_MAIN_TAB_KEYS: frozenset[str] = frozenset(
    ("welcome", "scan", "results", "review", "history", "diagnostics")
)


class AppMode(str, Enum):
    """High-level application phase (Cerebro_Blueprint_v2.0 §0.1)."""

    IDLE = "idle"
    SCANNING = "scanning"
    RESULTS = "results"
    REVIEW = "review"


@dataclass
class AppState:
    mode: AppMode
    """App phase: includes ``AppMode.SCANNING`` while a job is in flight."""
    groups: List[DuplicateGroup] = field(default_factory=list)
    """Latest duplicate groups from the last successful scan (canonical list)."""
    selected_group_id: Optional[int] = None
    """When in Review, which group is focused; ``None`` when not in compare flow."""
    filters: Dict[str, Any] = field(default_factory=dict)
    scan_progress: Dict[str, Any] = field(default_factory=dict)
    """Last engine snapshot from :class:`cerebro.engines.base_engine.ScanProgress`; cleared when idle or on results."""
    ui: Dict[str, Any] = field(
        default_factory=lambda: {"history_subtab": "scan"},
    )
    """View chrome: e.g. ``history_subtab`` (``scan`` | ``deletion``)."""
    scan_mode: str = "files"
    """Active engine mode key (``files`` / ``photos`` / ...)."""
    active_tab: str = "welcome"
    """Top-level tab bar key (``welcome`` / ``scan`` / ...). Kept in sync in Sprint 1+."""
    review_unlocked: bool = False
    """True after a scan has completed; required before ``active_tab`` may be ``review``."""
    dry_run: bool = False
    """Reserved: dry-run deletion (Blueprint §4)."""
    # --- Scan History grid (Sprint 2, Blueprint §3) — list[dict] rows from DB snapshot
    history_scan_rows: List[Dict[str, Any]] = field(default_factory=list)
    history_sort_column: str = "date"
    history_sort_asc: bool = False
    history_filter: str = ""
    history_page: int = 0
    history_page_size: int = 30
    # Results (duplicate file list) view — type filter + column sort
    results_file_filter: str = "all"
    results_file_sort_column: str = "Name"
    results_file_sort_asc: bool = True
    # Review page — file-type filter (same buckets as Results)
    review_file_filter: str = "all"
    # Deletion History sub-tab (mirrors ``HistoryDataLoaded`` for scan)
    history_deletion_rows: List[Dict[str, Any]] = field(default_factory=list)


def create_initial_state() -> AppState:
    return AppState(
        mode=AppMode.IDLE,
    )
