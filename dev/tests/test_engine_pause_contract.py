"""Pause event convention: set() means running."""

from __future__ import annotations

import threading

from cerebro.engines.base_engine import BaseEngine


def test_cooperative_pause_blocks_until_resume() -> None:
    cancel = threading.Event()
    pause = threading.Event()
    pause.set()
    assert BaseEngine.cooperative_pause_point(cancel, pause) is True
    pause.clear()
    done: list[bool] = []

    def worker() -> None:
        done.append(BaseEngine.cooperative_pause_point(cancel, pause))

    th = threading.Thread(target=worker, daemon=True)
    th.start()
    th.join(timeout=0.2)
    assert not done
    pause.set()
    th.join(timeout=1.0)
    assert done == [True]
