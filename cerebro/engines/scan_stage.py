"""Stable scan phase identifiers — use these instead of ad-hoc string literals.

Wire-up (orchestrator → UI) must compare against these values exactly so phase
detection never silently breaks from typos or truncated strings.
"""

from __future__ import annotations


class ScanStage:
    DISCOVERING = "discovering"
    GROUPING_BY_SIZE = "grouping_by_size"
    HASHING_PARTIAL = "hashing_partial"
    HASHING_FULL = "hashing_full"
    COMPLETE = "complete"
    CANCELLED = "cancelled"
