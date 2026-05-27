"""Checkpoint facade — UI and coordinator import from here, not engine internals."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from cerebro.engines.base_engine import DuplicateGroup
from cerebro.v2.persistence.scan_snapshot import (
    load_last_scan_snapshot,
    save_scan_results_snapshot,
)


def save_results(groups: List[DuplicateGroup], scan_mode: str, session_ts: float) -> None:
    save_scan_results_snapshot(groups, scan_mode, session_ts)


def load_results() -> Optional[tuple[List[DuplicateGroup], str, float]]:
    return load_last_scan_snapshot()
