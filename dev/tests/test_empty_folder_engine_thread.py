"""
test_empty_folder_engine_thread.py — H-2: EmptyFolderEngine.start() is non-blocking.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path


def test_empty_folder_start_nonblocking(tmp_path):
    from cerebro.engines.empty_folder_engine import EmptyFolderEngine
    from cerebro.engines.base_engine import ScanState

    empty = tmp_path / "empty_dir"
    empty.mkdir()

    engine = EmptyFolderEngine()
    engine.configure(folders=[tmp_path], protected=[], options={})

    started_event = threading.Event()
    original_run = engine._run_scan_inner

    def _patched_inner(cb):
        started_event.set()
        original_run(cb)

    engine._run_scan_inner = _patched_inner

    t_start = time.monotonic()
    engine.start(lambda p: None)
    elapsed = time.monotonic() - t_start

    # start() must return in well under 1 second.
    assert elapsed < 1.0, f"start() blocked for {elapsed:.2f}s"
    assert started_event.wait(timeout=10), "Scan thread never started"

    if engine._scan_thread:
        engine._scan_thread.join(timeout=30)
    assert len(engine.get_results()) >= 1


def test_empty_folder_cancel_respected(tmp_path):
    from cerebro.engines.empty_folder_engine import EmptyFolderEngine
    from cerebro.engines.base_engine import ScanState

    for i in range(5):
        d = tmp_path / f"sub{i}"
        d.mkdir()

    engine = EmptyFolderEngine()
    engine.configure(folders=[tmp_path], protected=[], options={})
    engine.start(lambda p: None)
    engine.cancel()

    if engine._scan_thread:
        engine._scan_thread.join(timeout=10)

    assert engine._state in (ScanState.CANCELLED, ScanState.COMPLETED)
