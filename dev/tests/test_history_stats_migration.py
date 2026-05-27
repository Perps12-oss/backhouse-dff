"""
test_history_stats_migration.py — P-3: JSONL records are migrated to the SQLite stats aggregate
on first HistoryStore open.
"""
from __future__ import annotations

import json
import time
from pathlib import Path


def test_stats_db_returns_aggregated_stats(tmp_path):
    """get_deletion_stats() must aggregate correctly from the SQLite table."""
    from cerebro.history.store import HistoryStore

    store = HistoryStore(base_dir=tmp_path)
    now = time.time()

    for i in range(5):
        store.record_deletion(
            scan_id=f"s{i}",
            mode="trash",
            groups=2,
            deleted=3,
            failed=0,
            bytes_reclaimed=1024,
            source="test",
        )

    stats = store.get_deletion_stats(days=1)
    assert stats["total_operations"] >= 5
    assert stats["total_deleted"] >= 15
    assert stats["total_bytes_reclaimed"] >= 5 * 1024


def test_jsonl_migration_populates_stats_db(tmp_path):
    """Pre-existing JSONL records must be migrated into the stats table on first open."""
    audit_dir = tmp_path / "audit"
    audit_dir.mkdir(parents=True)

    # Write synthetic JSONL record directly.
    from datetime import datetime
    today = datetime.now().strftime("%Y-%m-%d")
    record = {
        "scan_id": "old",
        "timestamp": time.time(),
        "mode": "permanent",
        "groups": 1,
        "deleted": 10,
        "failed": 0,
        "bytes_reclaimed": 512,
        "source": "migration_test",
        "policy": {},
        "details": [],
        "schema_version": 1,
    }
    (audit_dir / f"deletions_{today}.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")

    from cerebro.history.store import HistoryStore
    store = HistoryStore(base_dir=tmp_path)

    stats = store.get_deletion_stats(days=1)
    assert stats["total_deleted"] >= 10, "Migrated JSONL record must appear in stats"
