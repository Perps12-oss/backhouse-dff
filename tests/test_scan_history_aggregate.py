"""Tests for scan history aggregates (Phase 1)."""

from __future__ import annotations

import tempfile
import time
from pathlib import Path

from cerebro.v2.core.scan_history_db import ScanHistoryDB


def test_aggregate_since_sums_recent_rows() -> None:
    with tempfile.TemporaryDirectory() as td:
        db = ScanHistoryDB(Path(td) / "h.db")
        now = time.time()
        db.record_scan("files", ["/a"], 2, 10, 100, 1.0, timestamp=now - 86400 * 10)
        db.record_scan("files", ["/b"], 3, 20, 200, 2.0, timestamp=now - 86400 * 2)
        db.record_scan("photos", ["/c"], 1, 5, 50, 0.5, timestamp=now - 3600)

        since = now - 86400 * 7
        n, g, f, b = db.aggregate_since(since)
        assert n == 2
        assert g == 4
        assert f == 25
        assert b == 250
        db._conn.close()
