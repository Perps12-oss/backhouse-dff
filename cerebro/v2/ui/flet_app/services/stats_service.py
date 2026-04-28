"""StatsService — cached aggregate dashboard stats, computed off the UI thread."""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, Dict, Optional

_log = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 30.0


class StatsService:
    """Cache for dashboard aggregate stats. Refreshes in a background thread."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cache: Dict[str, Any] = {}
        self._cache_ts: float = 0.0
        self._dirty: bool = True
        self._refreshing: bool = False
        self._on_refresh: Optional[Callable[[Dict[str, Any]], None]] = None

    def set_on_refresh(self, cb: Callable[[Dict[str, Any]], None]) -> None:
        """Callback fired (from a worker thread) when a background refresh completes."""
        self._on_refresh = cb

    def invalidate(self) -> None:
        """Mark cache dirty. Next get_stats() will start a background refresh."""
        with self._lock:
            self._dirty = True

    def get_stats(self) -> Dict[str, Any]:
        """Return cached stats immediately; kick off a background refresh if stale."""
        with self._lock:
            age = time.monotonic() - self._cache_ts
            is_stale = self._dirty or age > _CACHE_TTL_SECONDS
            current = dict(self._cache)
            should_refresh = is_stale and not self._refreshing
            if should_refresh:
                self._refreshing = True

        if should_refresh:
            threading.Thread(target=self._refresh_worker, daemon=True).start()

        return current if current else {"scans": 0, "dupes": 0, "bytes_reclaimed": 0}

    def _refresh_worker(self) -> None:
        result: Optional[Dict[str, Any]] = None
        try:
            from cerebro.v2.core.deletion_history_db import get_default_history_manager
            from cerebro.v2.core.scan_history_db import get_scan_history_db

            entries = get_scan_history_db().get_recent(100_000)
            scans = len(entries)
            dupes = sum(max(0, e.files_found - e.groups_found) for e in entries)
            bytes_reclaimed = 0
            for row in get_default_history_manager().get_recent_history(100_000):
                try:
                    bytes_reclaimed += int(row[3])
                except (IndexError, TypeError, ValueError):
                    continue
            result = {"scans": scans, "dupes": dupes, "bytes_reclaimed": bytes_reclaimed}
        except Exception:
            _log.exception("StatsService background refresh failed")
        finally:
            with self._lock:
                self._refreshing = False
            if result is not None:
                with self._lock:
                    self._cache = result
                    self._cache_ts = time.monotonic()
                    self._dirty = False
                if self._on_refresh:
                    try:
                        self._on_refresh(result)
                    except Exception:
                        _log.exception("StatsService on_refresh callback failed")


_DEFAULT: Optional[StatsService] = None


def get_stats_service() -> StatsService:
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = StatsService()
    return _DEFAULT
