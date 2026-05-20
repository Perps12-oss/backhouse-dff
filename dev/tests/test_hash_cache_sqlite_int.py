"""StatSignature values must fit SQLite INTEGER."""

from __future__ import annotations

import tempfile
from pathlib import Path

from cerebro.services.hash_cache import HashCache, StatSignature, _SQLITE_INT_MAX


def test_oversized_stat_fields_clamp_for_sqlite() -> None:
    sig = StatSignature(
        size=_SQLITE_INT_MAX + 1,
        mtime_ns=_SQLITE_INT_MAX + 99,
        dev=_SQLITE_INT_MAX + 2,
        inode=_SQLITE_INT_MAX + 3,
    )
    assert sig.size == _SQLITE_INT_MAX
    assert sig.mtime_ns == _SQLITE_INT_MAX
    assert sig.dev == _SQLITE_INT_MAX
    assert sig.inode == _SQLITE_INT_MAX

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        file_path = tmp_path / "sample.txt"
        file_path.write_text("x", encoding="utf-8")
        cache = HashCache(tmp_path / "hash_cache.sqlite")
        cache.open()
        try:
            cache.set_quick(file_path, sig, "deadbeef", algo="sha256", quick_bytes=4096)
            row = cache._get_row(file_path)
            assert row is not None
            assert row[0] == _SQLITE_INT_MAX
        finally:
            cache.close()
