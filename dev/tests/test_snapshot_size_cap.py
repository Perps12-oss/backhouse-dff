"""Snapshot writer respects group count caps."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from cerebro.engines.base_engine import DuplicateFile, DuplicateGroup
from cerebro.v2.persistence import scan_snapshot as snap


def test_snapshot_caps_groups_written(monkeypatch) -> None:
    monkeypatch.setattr(snap, "_SNAPSHOT_MAX_GROUPS", 2)

    def _group(i: int) -> DuplicateGroup:
        return DuplicateGroup(
            group_id=i,
            files=[
                DuplicateFile(
                    path=Path(f"C:\\dup{i}a.txt"), size=10, modified=0.0, extension=".txt"
                ),
                DuplicateFile(
                    path=Path(f"C:\\dup{i}b.txt"), size=10, modified=0.0, extension=".txt"
                ),
            ],
        )

    groups = [_group(i) for i in range(5)]
    with tempfile.TemporaryDirectory() as tmp:
        snap_dir = Path(tmp)

        def _snap_dir() -> Path:
            return snap_dir

        with patch.object(snap, "_snap_dir", _snap_dir):
            with patch("cerebro.v2.persistence.results_store.get_results_store") as store:
                store.return_value.import_groups.return_value = None
                snap.save_scan_results_snapshot(groups, session_ts=1.0, scan_mode="files")

        last = snap_dir / snap._LAST_NAME
        assert last.is_file()
        payload = json.loads(last.read_text(encoding="utf-8"))
        assert len(payload["groups"]) == 2
        assert payload.get("results_store_session")
