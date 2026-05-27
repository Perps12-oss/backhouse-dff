"""Round-trip for :mod:`cerebro.v2.persistence.scan_snapshot`."""

from __future__ import annotations

from pathlib import Path

from cerebro.engines.base_engine import DuplicateFile, DuplicateGroup
from cerebro.v2.persistence.scan_snapshot import (
    load_last_scan_snapshot,
    load_scan_results_for_session_timestamp,
    save_scan_results_snapshot,
)


def _one_group() -> DuplicateGroup:
    f1 = DuplicateFile(
        path=Path("/tmp/a.txt"), size=1, modified=0.0, extension=".txt"
    )
    f2 = DuplicateFile(
        path=Path("/tmp/b.txt"), size=1, modified=0.0, extension=".txt"
    )
    return DuplicateGroup(group_id=1, files=[f1, f2])


def test_save_load_roundtrip(tmp_path, monkeypatch) -> None:
    import cerebro.v2.persistence.scan_snapshot as mod

    monkeypatch.setattr(mod, "cerebro_user_root", lambda: tmp_path)
    g = _one_group()
    ts = 1_700_000_000.123
    save_scan_results_snapshot([g], "files", ts)
    out = load_last_scan_snapshot()
    assert out is not None
    groups, mode, st = out
    assert mode == "files"
    assert abs(st - ts) < 0.001
    assert len(groups) == 1
    assert len(groups[0].files) == 2
    assert str(groups[0].files[0].path).endswith("a.txt")

    by_ts = load_scan_results_for_session_timestamp(ts)
    assert by_ts is not None
    assert len(by_ts[0]) == 1


def test_save_snapshot_writes_summary(tmp_path, monkeypatch) -> None:
    import cerebro.v2.persistence.scan_snapshot as mod

    monkeypatch.setattr(mod, "cerebro_user_root", lambda: tmp_path)
    from cerebro.v2.persistence.scan_snapshot import load_last_scan_summary, save_scan_results_snapshot

    g = _one_group()
    ts = 1_700_000_000.456
    save_scan_results_snapshot([g], "files", ts)
    summary_path = tmp_path / "scan_snapshots" / "last_summary.json"
    assert summary_path.is_file()
    s = load_last_scan_summary()
    assert s is not None
    assert int(s.get("groups_count", 0)) == 1
    assert isinstance(s.get("top_folders"), list)
    assert "age_buckets" in s
