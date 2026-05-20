"""
test_scan_history_db_singleton_concurrent.py — M-1: ScanHistoryDB singleton is thread-safe.
"""
from __future__ import annotations

import threading
from typing import List


def test_concurrent_singleton_init():
    """Two threads racing at first call must both get the same ScanHistoryDB instance."""
    import importlib
    import cerebro.v2.core.scan_history_db as mod

    # Reset singleton.
    mod._DEFAULT_DB = None

    instances: List[object] = []
    lock = threading.Lock()

    def _get():
        db = mod.get_scan_history_db()
        with lock:
            instances.append(db)

    threads = [threading.Thread(target=_get) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert len(instances) == 10
    first = instances[0]
    assert all(i is first for i in instances), "Multiple ScanHistoryDB instances created under concurrency"
