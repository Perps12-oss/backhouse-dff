"""
Single source of truth for the CEREBRO v2 shell (FINAL PLAN v2.0 §2).

State-driven architecture:
  - State is the single source of truth
  - UI never mutates data directly
  - All behavior predictable and reversible where possible
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set

from cerebro.engines.base_engine import DuplicateGroup

VALID_MAIN_TAB_KEYS: frozenset[str] = frozenset(
    ("dashboard", "duplicates", "history", "settings")
)


class AppMode(str, Enum):
    """High-level application phase (FINAL PLAN §2.1)."""

    IDLE = "idle"
    SCANNING = "scanning"
    RESULTS = "results"
    REVIEW = "review"


@dataclass
class AppState:
    mode: AppMode
    """App phase: includes ``AppMode.SCANNING`` while a job is in flight."""
    theme: str = "system"
    """Active theme: 'light', 'dark', or 'system' (FINAL PLAN §2.1, §3)."""
    groups: List[DuplicateGroup] = field(default_factory=list)
    """Latest duplicate groups from the last successful scan (canonical list)."""
    selected_files: Set[str] = field(default_factory=set)
    """Stable file IDs currently selected for deletion (FINAL PLAN §5.5, §13)."""
    filters: Dict[str, Any] = field(default_factory=dict)
    scan_progress: Dict[str, Any] = field(default_factory=dict)
    """Last engine snapshot from :class:`cerebro.engines.base_engine.ScanProgress`."""
    history: List[Dict[str, Any]] = field(default_factory=list)
    """Scan history entries (FINAL PLAN §7)."""
    ui: Dict[str, Any] = field(
        default_factory=lambda: {"history_subtab": "scan"},
    )
    """View chrome: e.g. ``history_subtab`` (``scan`` | ``deletion``)."""
    scan_mode: str = "files"
    """Active engine mode key (``files`` / ``photos`` / ...)."""
    active_tab: str = "dashboard"
    """Top-level tab bar key (FINAL PLAN §1.1: dashboard/duplicates/history/settings)."""
    review_unlocked: bool = False
    """True after a scan has completed; required before review is available."""
    dry_run: bool = False
    """Dry-run deletion toggle (FINAL PLAN §6.5)."""
    advanced_mode: bool = False
    """Global advanced toggle — controls visibility of advanced features (FINAL PLAN §1.2)."""
    selected_group_id: Optional[int] = None
    """When in Review, which group is focused; ``None`` when not in compare flow."""
    # --- Scan History grid (FINAL PLAN §7)
    history_scan_rows: List[Dict[str, Any]] = field(default_factory=list)
    history_sort_column: str = "date"
    history_sort_asc: bool = False
    history_filter: str = ""
    history_page: int = 0
    history_page_size: int = 30
    # Duplicates — file-type filter + text search (FINAL PLAN §5.3)
    results_file_filter: str = "all"
    results_text_filter: str = ""
    # Group grid sort
    results_group_sort_column: str = "reclaimable"
    results_group_sort_asc: bool = False
    # Review file-type filter
    review_file_filter: str = "all"
    # Deletion History sub-tab
    history_deletion_rows: List[Dict[str, Any]] = field(default_factory=list)
    # --- Scan profiles (FINAL PLAN §4.3, advanced)
    scan_profiles: List[Dict[str, Any]] = field(default_factory=list)
    # --- Scan lifecycle (FINAL PLAN §9)
    scan_can_pause: bool = False
    scan_can_resume: bool = False
    scan_is_cancelled: bool = False


def create_initial_state() -> AppState:
    return AppState(
        mode=AppMode.IDLE,
    )
