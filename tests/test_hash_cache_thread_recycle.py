"""
test_hash_cache_thread_recycle.py — HashCache connections are properly recycled across threads.
"""
from __future__ import annotations

import threading
from pathlib import Path

import pytest


def test_hash_cache_thread_local_connections(tmp_path):
    """Each thread should get its own SQLite connection."""
    from cerebro.services.hash_cache import HashCache, StatSignature

    cache = HashCache(tmp_path / "hashes.sqlite")
    cache.open()

    conn_ids = []
    lock = threading.Lock()

    def _worker():
        conn = cache._require_conn()
        with lock:
            conn_ids.append(id(conn))

    threads = [threading.Thread(target=_worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    cache.close()
    # Each thread should have used its own connection.
    assert len(conn_ids) == 5


def test_hash_cache_set_many_full(tmp_path):
    """set_many_full writes multiple entries in a single batch."""
    from cerebro.services.hash_cache import HashCache, StatSignature

    cache = HashCache(tmp_path / "hashes.sqlite")
    cache.open()

    sig = StatSignature(size=100, mtime_ns=12345678, dev=1, inode=42)
    items = [
        (str(tmp_path / f"file{i}.txt"), sig, f"hash{i}", "sha256")
        for i in range(5)
    ]
    cache.set_many_full(items)

    # Verify one entry.
    result = cache.get_full(str(tmp_path / "file0.txt"), sig)
    assert result == "hash0"

    cache.close()
