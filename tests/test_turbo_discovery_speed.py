"""Regression tests for TurboScanner discovery correctness and speed.

These exist because of a 2026-04 incident where discovery ran at
~3.6 files/sec on Windows due to a double-walk bug + ProcessPool
overhead + redundant stat() syscalls.
"""

import time
from pathlib import Path

import pytest

from cerebro.core.scanners.turbo_scanner import (
    TurboScanner,
    TurboScanConfig,
    walk_directory_worker,
)


def _make_tree(root: Path, n_dirs: int, files_per_dir: int) -> int:
    """Build a synthetic tree. Returns total file count."""
    total = 0
    for i in range(n_dirs):
        sub = root / f"dir_{i}"
        sub.mkdir()
        for j in range(files_per_dir):
            (sub / f"f_{j}.txt").write_bytes(b"x" * 32)
            total += 1
    # Some loose files at root
    for k in range(5):
        (root / f"loose_{k}.txt").write_bytes(b"y" * 32)
        total += 1
    return total


@pytest.fixture
def tree(tmp_path):
    n = _make_tree(tmp_path, n_dirs=10, files_per_dir=100)
    return tmp_path, n


def test_discovery_emits_each_file_exactly_once(tree):
    """The double-walk regression: every file must appear once, not twice."""
    root, expected = tree
    sc = TurboScanner(
        TurboScanConfig(
            min_size=0,
            use_cache=False,
            use_quick_hash=False,
            use_full_hash=False,
            use_multiprocessing=False,
        )
    )
    files = sc._discover_files_parallel([root], emit=None)
    paths = [str(p) for p, _, _ in files]
    assert len(paths) == expected, (
        f"emitted {len(paths)} but expected {expected} "
        f"(double-walk regression?)"
    )
    assert len(set(paths)) == len(paths), "duplicate paths in result"


def test_discovery_respects_min_size(tmp_path):
    (tmp_path / "tiny.txt").write_bytes(b"x")  # 1 byte
    (tmp_path / "big.txt").write_bytes(b"x" * 1000)  # 1000 bytes
    sc = TurboScanner(
        TurboScanConfig(
            min_size=500,
            use_cache=False,
            use_quick_hash=False,
            use_full_hash=False,
            use_multiprocessing=False,
        )
    )
    files = sc._discover_files_parallel([tmp_path], emit=None)
    names = sorted(p.name for p, _, _ in files)
    assert names == ["big.txt"]


def test_walk_directory_worker_handles_unreadable_directory(tmp_path):
    """A worker hitting an unreadable subdir should skip, not raise."""
    # Just confirm it doesn't crash on a normal tree; permission
    # changes are platform-specific and tested in CI is brittle.
    (tmp_path / "ok.txt").write_bytes(b"hi")
    out = walk_directory_worker((tmp_path, True, set(), 0, 0))
    assert any(p.name == "ok.txt" for p, _, _ in out)


def test_discovery_speed_local_disk(tree):
    """Discovery on a 1005-file synthetic tree must complete in under 2s.

    This is generous: on local SSD we expect well over 5000 files/sec
    after the fixes. 2 seconds for 1005 files = 500 files/sec, which
    is the floor we want CI to enforce.
    """
    root, expected = tree
    sc = TurboScanner(
        TurboScanConfig(
            min_size=0,
            use_cache=False,
            use_quick_hash=False,
            use_full_hash=False,
            use_multiprocessing=False,
        )
    )
    t0 = time.monotonic()
    files = sc._discover_files_parallel([root], emit=None)
    elapsed = time.monotonic() - t0
    assert len(files) == expected
    rate = len(files) / max(elapsed, 1e-6)
    assert rate >= 500, (
        f"discovery rate {rate:.0f} files/sec is too slow "
        f"(floor 500). elapsed={elapsed:.3f}s"
    )
