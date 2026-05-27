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
import threading
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
    """Pause and resume before start must not crash or lose results."""
    folder, _ = corpus
    engine = TurboFileEngine()
    engine.configure(folders=[folder], protected=[], options={"incremental_scan": False})

    # Pause before start: start() resets pause to "set", so this is a smoke
    # test, not a starvation test. The mid-scan starvation case is covered
    # by test_turbo_engine_pause_during_hashing below.
    engine.pause()
    engine.resume()

    engine.start(lambda p: None)
    assert engine.get_progress().state == ScanState.COMPLETED
    assert len(engine.get_results()) > 0


def _create_pausable_corpus(base: Path, n_files: int = 500, file_size: int = 65536) -> int:
    """Build a corpus large enough that hashing dominates wall time, so a
    mid-scan pause has a real window. ~32 MB by default."""
    base.mkdir(parents=True, exist_ok=True)
    payload = (b"deadbeef" * 8192)[:file_size]
    for i in range(n_files):
        if i % 2 == 0:
            content = payload
        else:
            content = payload[:-1] + bytes([i % 256])
        (base / f"f_{i:04d}.bin").write_bytes(content)
    return n_files


def test_turbo_engine_pause_during_hashing(tmp_path: Path) -> None:
    """Pause mid-hashing must actually halt progress (per-file gate).

    Regression guard for the starvation bug where pause()/resume() lived in
    the engine's outer loop only — TurboScanner.scan() did not yield until
    after Phases 1–4 (discovery + hashing) were done, so pause was a no-op
    during the wall-time-dominant hashing phase. The TurboScanConfig.pause_event
    plumbed into hash_worker fixes that.

    We count progress callbacks during a 0.5-second pause hold. The engine
    fires one progress callback per ~50 files hashed; if pause is honored
    the count stops climbing (the small handful of in-flight workers drain
    then block). If pause is a no-op the entire phase finishes inside the
    hold window and we see >>1 extra callbacks.
    """
    folder = tmp_path / "pause_corpus"
    n_files = _create_pausable_corpus(folder, n_files=500, file_size=65536)

    engine = TurboFileEngine()
    engine.configure(folders=[folder], protected=[], options={"incremental_scan": False})

    paused_once = threading.Event()
    cb_count_lock = threading.Lock()
    cb_count = {"total": 0, "after_pause": 0}

    def cb(p: ScanProgress) -> None:
        with cb_count_lock:
            cb_count["total"] += 1
            if paused_once.is_set():
                cb_count["after_pause"] += 1
        if (
            p.stage in ("hashing_partial", "hashing_full")
            and p.files_scanned > 0
            and not paused_once.is_set()
        ):
            engine.pause()
            paused_once.set()

    scan_thread = threading.Thread(target=engine.start, args=(cb,))
    scan_thread.start()
    try:
        assert paused_once.wait(timeout=15), (
            "Hashing phase never started — corpus may be too small or scanner skipped hashing."
        )
        time.sleep(0.1)  # let in-flight workers reach the pause gate
        with cb_count_lock:
            settled = cb_count["after_pause"]

        assert engine.get_progress().state == ScanState.PAUSED
        assert scan_thread.is_alive(), "scan thread exited while paused"

        time.sleep(0.5)  # if pause is a no-op, the rest of hashing finishes here
        with cb_count_lock:
            after_hold = cb_count["after_pause"]

        drift = after_hold - settled
        # Across a 0.5-second hold, pause-honored gives ~0 new callbacks
        # (workers blocked, no progress emits). Pause-broken finishes both
        # hashing phases (~10–20 emits at one per 50 files × 2 phases).
        assert drift <= 2, (
            f"Pause did not halt hashing: {drift} new progress callbacks during "
            f"a 0.5s hold. TurboScanConfig.pause_event is not gating hash_worker."
        )

        engine.resume()
        scan_thread.join(timeout=30)
        assert not scan_thread.is_alive(), "scan did not complete after resume"
        assert engine.get_progress().state == ScanState.COMPLETED
        assert len(engine.get_results()) > 0
    finally:
        engine.resume()
        engine.cancel()
        scan_thread.join(timeout=5)
