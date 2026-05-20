"""
test_history_store_write_lock.py — M-4: concurrent HistoryStore.record_deletion() calls
must not corrupt JSONL output.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path


def test_concurrent_jsonl_writes_intact(tmp_path):
    from cerebro.history.store import HistoryStore

    store = HistoryStore(base_dir=tmp_path)

    errors: list[Exception] = []

    def _write(i: int):
        try:
            store.record_deletion(
                scan_id=f"scan-{i}",
                mode="trash",
                groups=1,
                deleted=1,
                failed=0,
                bytes_reclaimed=1024,
                source="test",
            )
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=_write, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)

    assert not errors, f"record_deletion raised: {errors}"

    # Every line in each audit file must be valid JSON.
    audit_dir = tmp_path / "audit"
    for jsonl_file in audit_dir.glob("deletions_*.jsonl"):
        lines = jsonl_file.read_text(encoding="utf-8").splitlines()
        for line_no, line in enumerate(lines, 1):
            try:
                obj = json.loads(line)
                assert "scan_id" in obj
            except json.JSONDecodeError as exc:
                raise AssertionError(
                    f"Corrupted JSONL line {line_no} in {jsonl_file}: {exc!r}\n  Line: {line!r}"
                ) from exc
