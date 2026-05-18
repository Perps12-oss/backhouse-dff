"""
test_engine_start_nonblocking.py — H-5: SimilarFolderEngine and LargeFileEngine
start() returns immediately (daemon thread).
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from cerebro.engines.base_engine import ScanState
from cerebro.engines.large_file_engine import LargeFileEngine
from cerebro.engines.similar_folder_engine import SimilarFolderEngine


def test_similar_folder_engine_start_nonblocking(tmp_path):
    """start() must return before _run_scan completes."""
    engine = SimilarFolderEngine()
    engine.configure(folders=[tmp_path], protected=[], options={})

    entry_event = threading.Event()
    original_run = engine._run_scan

    def _patched_run(cb):
        entry_event.set()
        time.sleep(0.3)  # simulate slow scan
        original_run(cb)

    engine._run_scan = _patched_run

    t0 = time.monotonic()
    engine.start(lambda p: None)
    elapsed = time.monotonic() - t0

    assert elapsed < 0.1, f"start() blocked for {elapsed:.3f}s — expected < 0.1s"
    assert entry_event.wait(timeout=5), "_run_scan never started"
    assert engine.get_progress().state != ScanState.COMPLETED


def test_large_file_engine_start_nonblocking(tmp_path):
    """start() must return before _run_scan completes."""
    engine = LargeFileEngine()
    engine.configure(folders=[tmp_path], protected=[], options={})

    entry_event = threading.Event()
    original_run = engine._run_scan

    def _patched_run(cb):
        entry_event.set()
        time.sleep(0.3)
        original_run(cb)

    engine._run_scan = _patched_run

    t0 = time.monotonic()
    engine.start(lambda p: None)
    elapsed = time.monotonic() - t0

    assert elapsed < 0.1, f"start() blocked for {elapsed:.3f}s — expected < 0.1s"
    assert entry_event.wait(timeout=5), "_run_scan never started"
