"""Tests for :mod:`cerebro.v2.core.index_presence` (dashboard presence helpers)."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from cerebro.v2.core import index_presence as ip
from cerebro.v2.core.scan_history_db import ScanHistoryDB


class TestFormatRelativePast:
    """Fixed ``now`` avoids flake from wall clock."""

    NOW = 1_700_000_000.0

    def test_same_instant_is_today(self) -> None:
        assert ip.format_relative_past(self.NOW, now=self.NOW) == "today"

    def test_future_timestamp_treated_as_today(self) -> None:
        assert ip.format_relative_past(self.NOW + 86400, now=self.NOW) == "today"

    def test_eleven_hours_ago_still_today(self) -> None:
        ts = self.NOW - 11 * 3600
        assert ip.format_relative_past(ts, now=self.NOW) == "today"

    def test_thirteen_hours_ago_is_yesterday(self) -> None:
        ts = self.NOW - 13 * 3600
        assert ip.format_relative_past(ts, now=self.NOW) == "yesterday"

    def test_one_day_bucket(self) -> None:
        ts = self.NOW - 26 * 3600  # > 36h from now-26h? 26*3600=93600, 36h=129600 -> still yesterday
        assert ip.format_relative_past(ts, now=self.NOW) == "yesterday"

    def test_two_days_ago(self) -> None:
        ts = self.NOW - 2 * 86400 - 1  # just over 2 full days
        assert ip.format_relative_past(ts, now=self.NOW) == "2 days ago"

    def test_one_day_ago_singular(self) -> None:
        ts = self.NOW - 42 * 3600  # between 36h and 48h wall → one calendar-day bucket
        assert ip.format_relative_past(ts, now=self.NOW) == "1 day ago"

    def test_seven_days_ago_is_one_week(self) -> None:
        ts = self.NOW - 7 * 86400
        assert ip.format_relative_past(ts, now=self.NOW) == "1 week ago"

    def test_four_weeks_ago(self) -> None:
        ts = self.NOW - 28 * 86400
        assert ip.format_relative_past(ts, now=self.NOW) == "4 weeks ago"

    def test_fifty_six_days_uses_month_branch(self) -> None:
        ts = self.NOW - 56 * 86400
        assert ip.format_relative_past(ts, now=self.NOW) == "1 month ago"

    def test_two_months_plural(self) -> None:
        ts = self.NOW - 65 * 86400  # weeks >= 8; 65 // 30 == 2
        assert ip.format_relative_past(ts, now=self.NOW) == "2 months ago"


def test_count_files_newer_than_counts_only_matching_files(tmp_path: Path) -> None:
    base = 1_650_000_000.0
    since = base + 50.0
    old = tmp_path / "old.txt"
    new = tmp_path / "new.txt"
    old.write_text("a")
    new.write_text("b")
    os.utime(old, (base, base))
    os.utime(new, (base + 100.0, base + 100.0))
    count, truncated = ip.count_files_newer_than([tmp_path], since, budget_seconds=5.0)
    assert truncated is False
    assert count == 1


def test_count_files_newer_than_nested(tmp_path: Path) -> None:
    since = 1_640_000_000.0
    sub = tmp_path / "sub"
    sub.mkdir()
    f = sub / "x.dat"
    f.write_bytes(b"0")
    mt = since + 10.0
    os.utime(f, (mt, mt))
    count, truncated = ip.count_files_newer_than([tmp_path], since, budget_seconds=5.0)
    assert truncated is False
    assert count == 1


def test_count_files_newer_than_respects_max_files(tmp_path: Path) -> None:
    since = 1_630_000_000.0
    d = tmp_path / "many"
    d.mkdir()
    mt = since + 1.0
    for i in range(3):
        p = d / f"f{i}.txt"
        p.write_text("x")
        os.utime(p, (mt, mt))
    count, truncated = ip.count_files_newer_than(
        [d], since, budget_seconds=5.0, max_files=2
    )
    assert count == 2
    assert truncated is True


def test_count_files_newer_than_missing_root(tmp_path: Path) -> None:
    missing = tmp_path / "nope"
    count, truncated = ip.count_files_newer_than([missing], 0.0, budget_seconds=1.0)
    assert count == 0
    assert truncated is False


def test_count_files_newer_than_zero_budget_may_truncate(tmp_path: Path) -> None:
    """Tight budget should exit quickly without hanging."""
    p = tmp_path / "solo.txt"
    p.write_text("z")
    os.utime(p, (time.time(), time.time()))
    count, truncated = ip.count_files_newer_than(
        [tmp_path], 0.0, budget_seconds=0.0, max_files=10_000
    )
    assert isinstance(count, int)
    assert isinstance(truncated, bool)


def test_latest_scan_entry_none_when_empty(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    db = ScanHistoryDB(tmp_path / "presence.db")
    monkeypatch.setattr(ip, "get_scan_history_db", lambda: db)
    try:
        assert ip.latest_scan_entry() is None
    finally:
        db._conn.close()


def test_latest_scan_entry_returns_newest_row(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db = ScanHistoryDB(tmp_path / "presence.db")
    monkeypatch.setattr(ip, "get_scan_history_db", lambda: db)
    try:
        t_old = 1_000.0
        t_new = 2_000.0
        db.record_scan("files", ["/a"], 1, 2, 3, 1.0, timestamp=t_old)
        db.record_scan("photos", ["/b"], 4, 5, 6, 2.0, timestamp=t_new)
        row = ip.latest_scan_entry()
        assert row is not None
        assert row.timestamp == t_new
        assert row.mode == "photos"
        assert row.groups_found == 4
    finally:
        db._conn.close()
