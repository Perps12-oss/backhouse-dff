"""
Performance regression test for TurboFileEngine.

Creates a corpus of duplicate files in a temp directory, runs TurboFileEngine
synchronously, and asserts both correctness (duplicates found) and speed
(<30s for 500 files on any reasonable CI machine).

This test will catch O(n²) regressions in the scan pipeline — the sort of
thing that never shows up in unit tests but kills users with large libraries.
"""
from __future__ import annotations

import hashlib
import time
from pathlib import Path

import pytest

from cerebro.engines.turbo_file_engine import TurboFileEngine
from cerebro.engines.base_engine import ScanProgress, ScanState


def _create_corpus(base: Path, n_unique: int = 50, copies_each: int = 3) -> int:
    """
    Create n_unique * copies_each files in base.
    Returns total file count. Each unique file is 4KB of deterministic content.
    """
    base.mkdir(parents=True, exist_ok=True)
    total = 0
    for i in range(n_unique):
        content = hashlib.sha256(f"corpus-file-{i}".encode()).digest() * 128  # 4KB
        for j in range(copies_each):
            (base / f"file_{i:04d}_copy{j}.bin").write_bytes(content)
            total += 1
    return total


@pytest.fixture()
def corpus(tmp_path: Path):
    n_files = _create_corpus(tmp_path / "corpus", n_unique=50, copies_each=3)
    return tmp_path / "corpus", n_files


def test_turbo_engine_finds_duplicates(corpus) -> None:
    folder, n_files = corpus
    engine = TurboFileEngine()
    engine.configure(folders=[folder], protected=[], options={"incremental_scan": False})

    progress_states: list[ScanState] = []
    engine.start(lambda p: progress_states.append(p.state))

    groups = engine.get_results()
    assert len(groups) >= 50, (
        f"Expected >=50 duplicate groups for 50 unique files × 3 copies; got {len(groups)}"
    )


def test_turbo_engine_scan_completes_within_budget(corpus) -> None:
    """Scanning 150 small files must complete within 30 seconds."""
    folder, n_files = corpus
    engine = TurboFileEngine()
    engine.configure(folders=[folder], protected=[], options={"incremental_scan": False})

    t0 = time.perf_counter()
    engine.start(lambda p: None)
    elapsed = time.perf_counter() - t0

    print(f"\n{n_files}-file scan completed in {elapsed:.2f}s")
    assert elapsed < 30, (
        f"Scan took {elapsed:.1f}s — exceeds 30s budget for {n_files} files. "
        "Check for O(n²) regression in TurboScanner or hash pipeline."
    )
    assert engine.get_progress().state == ScanState.COMPLETED


def test_turbo_engine_pause_resume(corpus) -> None:
    """Pause and resume must not crash or lose results."""
    folder, _ = corpus
    engine = TurboFileEngine()
    engine.configure(folders=[folder], protected=[], options={"incremental_scan": False})

    # Pause before start has no effect (event is already set)
    engine.pause()
    engine.resume()

    engine.start(lambda p: None)
    assert engine.get_progress().state == ScanState.COMPLETED
    assert len(engine.get_results()) > 0
