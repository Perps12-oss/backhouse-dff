"""
test_deletion_history_singleton_race.py — M-1: get_default_history_manager() is thread-safe.
"""
from __future__ import annotations

import importlib
import threading


def test_singleton_double_checked_lock():
    """Multiple threads calling get_default_history_manager() concurrently must all get the same instance."""
    import cerebro.v2.core.deletion_history_db as mod

    # Reset the singleton.
    mod._DEFAULT_MANAGER = None

    results = []

    def _call():
        results.append(id(mod.get_default_history_manager()))

    threads = [threading.Thread(target=_call) for _ in range(30)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # All threads must receive the same instance (same id).
    assert len(set(results)) == 1, f"Multiple singleton instances created: {set(results)}"
