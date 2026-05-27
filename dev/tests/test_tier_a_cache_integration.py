"""End-to-end: Tier-A prefix cache makes a repeat pass skip reads, same results."""
from __future__ import annotations

from pathlib import Path

import pytest

from cerebro.core.scanners.turbo_scanner import TurboScanner, TurboScanConfig


def _make_same_size_files(tmp_path: Path) -> tuple[int, list[Path]]:
    """4 files of identical size: a==b (dup), c and d unique."""
    a = tmp_path / "a.bin"; a.write_bytes(b"A" * 1000)
    b = tmp_path / "b.bin"; b.write_bytes(b"A" * 1000)  # dup of a
    c = tmp_path / "c.bin"; c.write_bytes(b"B" * 1000)  # unique
    d = tmp_path / "d.bin"; d.write_bytes(b"C" * 1000)  # unique
    files = [a, b, c, d]
    return 1000, files


def _size_groups(size: int, files: list[Path]) -> dict:
    return {size: [(p, p.stat().st_mtime) for p in files]}


def _run(cache_dir: Path, size: int, files: list[Path], *, adaptive: bool):
    cfg = TurboScanConfig(
        use_cache=True,
        cache_dir=cache_dir,
        hash_workers=2,
        use_quick_hash=True,
        enable_tier_a_adaptive=adaptive,
    )
    sc = TurboScanner(cfg)
    out, cin, cout = sc._apply_tier_a_filter(
        _size_groups(size, files), "xxhash", None, discovered_count=len(files)
    )
    hits = sc.stats["tier_a_cache_hits"]
    misses = sc.stats["tier_a_cache_misses"]
    sc.close()
    return out, cin, cout, hits, misses


@pytest.mark.parametrize("adaptive", [False, True])
def test_second_pass_hits_cache_same_results(tmp_path, adaptive):
    cache_dir = tmp_path / "cache"
    size, files = _make_same_size_files(tmp_path)

    # Pass 1: cold cache — all misses, hashes written.
    out1, cin1, cout1, hits1, misses1 = _run(cache_dir, size, files, adaptive=adaptive)
    assert hits1 == 0
    assert misses1 == len(files)
    assert cout1 == 2  # a,b survive; c,d rejected

    # Pass 2: warm cache — all hits, no reads, identical survivors.
    out2, cin2, cout2, hits2, misses2 = _run(cache_dir, size, files, adaptive=adaptive)
    assert hits2 == len(files), "every unchanged file should be served from cache"
    assert misses2 == 0
    assert cout2 == cout1
    # Same survivor set (a,b).
    surv1 = {p.name for v in out1.values() for p, _ in v}
    surv2 = {p.name for v in out2.values() for p, _ in v}
    assert surv1 == surv2 == {"a.bin", "b.bin"}


def test_changed_file_invalidates_cache(tmp_path):
    cache_dir = tmp_path / "cache"
    size, files = _make_same_size_files(tmp_path)
    _run(cache_dir, size, files, adaptive=False)  # warm

    # Modify one file's content+mtime → its cache entry must invalidate (miss).
    import os, time
    files[2].write_bytes(b"B" * 1000)  # same size, new mtime
    os.utime(files[2], (time.time() + 5, time.time() + 5))

    _, _, _, hits, misses = _run(cache_dir, size, files, adaptive=False)
    assert misses >= 1, "changed file must be re-read, not served stale"
    assert hits == len(files) - misses
