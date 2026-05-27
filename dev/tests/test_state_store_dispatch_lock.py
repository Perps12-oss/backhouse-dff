"""
test_state_store_dispatch_lock.py — H-3: concurrent StateStore.dispatch() from two threads
must not lose actions or corrupt state.
"""
from __future__ import annotations

import threading

import pytest

from cerebro.v2.state.store import StateStore
from cerebro.v2.state.app_state import AppState, AppMode
from cerebro.v2.state.actions import ScanStarted


def test_concurrent_dispatch_no_loss():
    """Dispatch 500 actions from two threads; none must be lost."""
    initial = AppState(mode=AppMode.IDLE)
    store = StateStore(initial)

    dispatch_log = []
    lock = threading.Lock()

    def _listener(current, old, action):
        with lock:
            dispatch_log.append(1)

    store.subscribe(_listener)

    N = 250

    def _dispatch_n():
        for _ in range(N):
            store.dispatch(ScanStarted())

    t1 = threading.Thread(target=_dispatch_n)
    t2 = threading.Thread(target=_dispatch_n)
    t1.start()
    t2.start()
    t1.join(timeout=15)
    t2.join(timeout=15)

    assert not t1.is_alive() and not t2.is_alive(), "Threads are still running — possible deadlock"
    assert len(dispatch_log) == N * 2, (
        f"Expected {N * 2} dispatches, got {len(dispatch_log)}"
    )
