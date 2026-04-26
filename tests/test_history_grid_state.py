"""History grid projection and reducer (Blueprint Sprint 2)."""

from __future__ import annotations

from cerebro.v2.state import (
    HistoryDataLoaded,
    create_initial_state,
    reduce,
)
from cerebro.v2.state.history_view import apply_scan_history_view, scan_entry_to_row


def _row(ts: float, mode: str = "files", groups: int = 1) -> dict:
    return {
        "ts": ts,
        "mode": mode,
        "folder_count": 1,
        "groups": groups,
        "files": 2,
        "bytes": 100,
        "duration": 1.0,
        "folders": ["/a"],
    }


def test_apply_filter_and_sort() -> None:
    rows = [_row(10.0, "a"), _row(20.0, "b"), _row(15.0, "c")]
    out, n, npages, page, total = apply_scan_history_view(
        rows, "date", False, "", 0, 10
    )
    assert total == 3
    assert n == 3
    assert [r["ts"] for r in out] == [20.0, 15.0, 10.0]
    out2, n2, _, _, _ = apply_scan_history_view(rows, "date", True, "", 0, 10)
    assert [r["ts"] for r in out2] == [10.0, 15.0, 20.0]
    out3, n3, _, _, _ = apply_scan_history_view(rows, "date", False, "b", 0, 10)
    assert n3 == 1 and out3[0]["mode"] == "b"


def test_apply_pagination() -> None:
    rows = [_row(float(i), "files", i) for i in range(25)]
    page0, n, npages, cpage, _ = apply_scan_history_view(
        rows, "date", False, "", 0, 10
    )
    assert n == 25
    assert npages == 3
    assert len(page0) == 10
    assert cpage == 0
    p2, _, _, c2, _ = apply_scan_history_view(
        rows, "date", False, "", 2, 10
    )
    assert len(p2) == 5
    assert c2 == 2


def test_reducer_history_data() -> None:
    s0 = create_initial_state()
    r0 = _row(1.0)
    t = (r0,)
    s1 = reduce(s0, HistoryDataLoaded(t))
    assert len(s1.history_scan_rows) == 1
    assert s1.history_page == 0


def test_scan_entry_to_row_roundtrip_keys() -> None:
    from cerebro.v2.core.scan_history_db import ScanHistoryEntry

    e = ScanHistoryEntry(
        timestamp=1.0,
        mode="files",
        folders=["/x"],
        groups_found=2,
        files_found=4,
        bytes_reclaimable=8,
        duration_seconds=1.5,
    )
    d = scan_entry_to_row(e)
    assert d["groups"] == 2
    assert d["bytes"] == 8
