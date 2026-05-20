"""ResultsStore spill and reload."""

from __future__ import annotations

import tempfile
from pathlib import Path

from cerebro.engines.base_engine import DuplicateFile, DuplicateGroup
from cerebro.v2.persistence.results_store import ResultsStore


def test_results_store_roundtrip() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "results.db"
        store = ResultsStore(db_path=db)
        g = DuplicateGroup(
            group_id=1,
            files=[
                DuplicateFile(
                    path=Path("a.txt"),
                    size=5,
                    modified=0.0,
                    extension=".txt",
                ),
                DuplicateFile(
                    path=Path("b.txt"),
                    size=5,
                    modified=0.0,
                    extension=".txt",
                ),
            ],
        )
        sid = "test-session"
        n = store.import_groups(sid, [g], scan_mode="files", created_ts=1.0)
        assert n == 1
        assert store.count(sid) == 1
        loaded = store.load_all(sid)
        assert len(loaded) == 1
        assert loaded[0].file_count == 2
        store.close()
