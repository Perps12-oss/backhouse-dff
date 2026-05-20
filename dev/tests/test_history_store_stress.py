"""
Stress test for HistoryStore: 10,000 appends must average < 100ms per write.

With the old atomic-rewrite pattern this was O(n²) — file grew on each append,
meaning write N required reading N-1 lines first. True append is O(1) and
should comfortably meet the 100ms budget even on slow CI storage.
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from cerebro.history.store import DeletionAuditRecord, HistoryStore


@pytest.fixture()
def store(tmp_path: Path) -> HistoryStore:
    return HistoryStore(base_dir=tmp_path / "history")


def _make_record(i: int) -> dict:
    return dict(
        scan_id=f"stress-{i}",
        mode="trash",
        groups=1,
        deleted=2,
        failed=0,
        bytes_reclaimed=1024,
        source="stress_test",
        policy={},
        details=[],
    )


def test_10k_appends_within_budget(store: HistoryStore) -> None:
    n = 10_000
    times: list[float] = []

    for i in range(n):
        t0 = time.perf_counter()
        store.record_deletion(**_make_record(i))
        times.append(time.perf_counter() - t0)

    avg_ms = (sum(times) / len(times)) * 1000
    max_ms = max(times) * 1000
    print(f"\n10k appends: avg={avg_ms:.2f}ms  max={max_ms:.2f}ms")

    assert avg_ms < 100, (
        f"Average write time {avg_ms:.1f}ms exceeds 100ms budget. "
        "History store may have reverted to O(n²) atomic-rewrite pattern."
    )


def test_records_are_all_readable_after_stress(store: HistoryStore) -> None:
    """Verify data integrity — all 1000 appended records can be read back."""
    n = 1_000
    for i in range(n):
        store.record_deletion(**_make_record(i))

    records = store.get_deletion_history(limit=n + 100)
    assert len(records) == n, f"Expected {n} records, got {len(records)}"
    scan_ids = {r.scan_id for r in records}
    assert f"stress-0" in scan_ids
    assert f"stress-{n - 1}" in scan_ids
