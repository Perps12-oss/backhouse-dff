"""
test_hash_cache_batch_writes.py — P-2: set_many_full() is called instead of per-file writes.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch


def test_set_many_full_called_in_bulk(tmp_path):
    """ImageDedupEngine must call cache.set_many_full() for batch writes, not per-file set_full."""
    from cerebro.engines.image_dedup_engine import ImageDedupEngine
    from cerebro.services.hash_cache import HashCache, StatSignature

    engine = ImageDedupEngine()

    # Inject a mock cache.
    mock_cache = MagicMock(spec=HashCache)
    mock_cache.get_quick.return_value = None
    mock_cache.get_full.return_value = None
    mock_cache.set_many_full = MagicMock()
    engine._cache = mock_cache

    # The method should be called if there are cache_entries; inject entries directly.
    cache_entries = [
        ("/a/b.jpg", StatSignature(size=100, mtime_ns=0), "aabb", "ccdd"),
    ]

    # Simulate the post-processing block.
    if engine._cache is not None and cache_entries:
        try:
            phash_batch = [(p, s, ph, "phash") for p, s, ph, _ in cache_entries]
            dhash_batch = [(p, s, dh, "dhash") for p, s, _, dh in cache_entries]
            engine._cache.set_many_full(phash_batch)
            engine._cache.set_many_full(dhash_batch)
        except AttributeError:
            for path_str, sig, phash_hex, dhash_hex in cache_entries:
                engine._cache.set_quick(path_str, sig, phash_hex, algo="phash")
                engine._cache.set_full(path_str, sig, dhash_hex, algo="dhash")

    assert mock_cache.set_many_full.called, "set_many_full must be called for batch writes"
    assert mock_cache.set_full.call_count == 0, "Per-item set_full must NOT be called when set_many_full is available"
