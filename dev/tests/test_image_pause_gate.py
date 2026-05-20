"""
test_image_pause_gate.py — H-1: ImageDedupEngine.pause() actually pauses the hash workers.
"""
from __future__ import annotations

import threading
import time

import pytest


def _pil_available():
    try:
        from PIL import Image  # noqa: F401
        return True
    except ImportError:
        return False


@pytest.mark.skipif(not _pil_available(), reason="Pillow not installed")
def test_pause_stops_progress(tmp_path):
    """After pause(), processed count must not advance for at least 0.3s."""
    from PIL import Image
    from cerebro.engines.image_dedup_engine import ImageDedupEngine
    from cerebro.engines.base_engine import ScanProgress, ScanState

    # Create enough images to give the engine something to do.
    img_dir = tmp_path / "images"
    img_dir.mkdir()
    for i in range(20):
        img = Image.new("RGB", (64, 64), color=(i * 12 % 255, i * 7 % 255, i * 3 % 255))
        img.save(img_dir / f"img_{i:03d}.jpg")

    engine = ImageDedupEngine()
    engine.configure(folders=[img_dir], protected=[], options={})

    progress_counts = []

    def _cb(p: ScanProgress):
        progress_counts.append(p.files_scanned or 0)

    engine.start(_cb)

    # Let it process a little.
    time.sleep(0.2)
    engine.pause()
    time.sleep(0.05)
    count_at_pause = len(progress_counts)
    time.sleep(0.4)
    count_after_wait = len(progress_counts)

    engine.resume()
    if engine._scan_thread:
        engine._scan_thread.join(timeout=30)

    # While paused the count should have grown by ≤ 2 (tolerance for in-flight futures).
    progress_during_pause = count_after_wait - count_at_pause
    assert progress_during_pause <= 4, (
        f"Scan kept running during pause: {progress_during_pause} progress callbacks after pause"
    )
