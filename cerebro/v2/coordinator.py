"""
Side-effect boundary for the v2 shell (Blueprints §0.3, Implementation Rules §3–4).

Sprint 1: forwards scan/review events into :class:`cerebro.v2.state.StateStore`
so the AppShell can react in one place. File I/O and the scan thread remain in
:mod:`cerebro.engines` and ``ScanPage``; later sprints can move more work here
without adding UI imports under ``cerebro.engines`` — see Blueprint §0.3 / §6.
"""

from __future__ import annotations

from typing import Iterable, Optional, Sequence, Tuple

from cerebro.engines.base_engine import DuplicateGroup
from cerebro.v2.state import ReviewNavigate, ScanCompleted, SetActiveTab, StateStore


class CerebroCoordinator:
    """Entry point for app-level side effects that should end in a state change."""

    def __init__(self, store: StateStore) -> None:
        self._store = store

    @property
    def store(self) -> StateStore:
        return self._store

    def set_active_tab(self, key: str) -> None:
        """Top-level main tab: single entry for shell + TabBar (Blueprint §0.1)."""
        self._store.dispatch(SetActiveTab(key))

    def scan_completed(
        self,
        groups: Iterable[DuplicateGroup],
        scan_mode: str = "files",
    ) -> None:
        """Call from the main thread when a scan finishes (ScanPage path)."""
        self._store.dispatch(ScanCompleted(list(groups), scan_mode or "files"))

    def review_open_group(
        self,
        group_id: int,
        groups: Optional[Sequence[DuplicateGroup]] = None,
    ) -> None:
        """Navigate to Review for a duplicate group (Results double-click path)."""
        snap: Optional[Tuple[DuplicateGroup, ...]] = (
            tuple(groups) if groups is not None else None
        )
        self._store.dispatch(ReviewNavigate(int(group_id), snap))
