"""Tests for the isolated Tier-A prefix cache."""
from __future__ import annotations

from cerebro.services.hash_cache import TierAPrefixCache


def _open(tmp_path):
    c = TierAPrefixCache(tmp_path / "tier_a.sqlite")
    c.open()
    return c


def test_set_then_get_roundtrip(tmp_path):
    c = _open(tmp_path)
    try:
        c.set_many([("C:/a.jpg", 747, 1000, 4096, "xxhash", "deadbeef")])
        got = c.get_many([("C:/a.jpg", 747, 1000, 4096, "xxhash")])
        assert got == {"C:/a.jpg": "deadbeef"}
    finally:
        c.close()


def test_miss_on_changed_mtime(tmp_path):
    c = _open(tmp_path)
    try:
        c.set_many([("C:/a.jpg", 747, 1000, 4096, "xxhash", "deadbeef")])
        # Same path, different mtime → invalidated → miss.
        assert c.get_many([("C:/a.jpg", 747, 2000, 4096, "xxhash")]) == {}
    finally:
        c.close()


def test_miss_on_changed_size_or_algo_or_nbytes(tmp_path):
    c = _open(tmp_path)
    try:
        c.set_many([("C:/a.jpg", 747, 1000, 4096, "xxhash", "deadbeef")])
        assert c.get_many([("C:/a.jpg", 748, 1000, 4096, "xxhash")]) == {}   # size
        assert c.get_many([("C:/a.jpg", 747, 1000, 4096, "sha256")]) == {}   # algo
        assert c.get_many([("C:/a.jpg", 747, 1000, 8192, "xxhash")]) == {}   # nbytes
    finally:
        c.close()


def test_upsert_overwrites(tmp_path):
    c = _open(tmp_path)
    try:
        c.set_many([("C:/a.jpg", 1, 1, 4096, "xxhash", "old")])
        c.set_many([("C:/a.jpg", 1, 1, 4096, "xxhash", "new")])
        assert c.get_many([("C:/a.jpg", 1, 1, 4096, "xxhash")]) == {"C:/a.jpg": "new"}
    finally:
        c.close()


def test_batch_over_sqlite_var_limit(tmp_path):
    c = _open(tmp_path)
    try:
        rows = [(f"C:/f{i}.bin", 100, 5, 4096, "xxhash", f"h{i}") for i in range(2500)]
        c.set_many(rows)
        keys = [(f"C:/f{i}.bin", 100, 5, 4096, "xxhash") for i in range(2500)]
        got = c.get_many(keys)
        assert len(got) == 2500
        assert got["C:/f1234.bin"] == "h1234"
    finally:
        c.close()


def test_clear_all(tmp_path):
    c = _open(tmp_path)
    try:
        c.set_many([("C:/a.jpg", 1, 1, 4096, "xxhash", "x")])
        c.clear_all()
        assert c.get_many([("C:/a.jpg", 1, 1, 4096, "xxhash")]) == {}
    finally:
        c.close()


def test_mtime_to_ns_deterministic():
    assert TierAPrefixCache.mtime_to_ns(1.5) == TierAPrefixCache.mtime_to_ns(1.5)
    assert TierAPrefixCache.mtime_to_ns(1.5) == 1_500_000_000
