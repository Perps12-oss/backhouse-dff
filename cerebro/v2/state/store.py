"""
Synchronous store: dispatch -> reducer -> listeners (CEREBRO rules §2, §7).

All listeners run on the thread that called :meth:`dispatch` — the UI root must
schedule ``dispatch`` from the main thread after scan/worker work (see ScanPage
``after(0, ...)`` pattern for progress).

MC-1 / LT-1 — Listener contract:
  Listeners MUST treat the ``old`` AppState argument as read-only.  Mutating it
  (e.g. ``old.selected_files.add(...)`` ) has no effect on the store but causes
  confusing bugs when subsequent listeners receive a dirtied object.

  In debug builds (CEREBRO_DEBUG=1) a shallow copy of mutable sets is passed as
  ``old`` so mutations are silently discarded; this makes contract violations
  visible without crashing production.
"""

from __future__ import annotations

import dataclasses
import os
import threading
from typing import Callable, List

from cerebro.v2.state.actions import Action
from cerebro.v2.state.app_state import AppState
from cerebro.v2.state.reducer import reduce

Listener = Callable[[AppState, AppState, Action], None]

_DEBUG = os.environ.get("CEREBRO_DEBUG", "0") == "1"


def _safe_old(state: AppState) -> AppState:
    """In debug builds, return a shallow copy with mutable sets cloned."""
    if not _DEBUG:
        return state
    try:
        selected = frozenset(state.selected_files)
        marked = frozenset(state.marked_paths) if hasattr(state, "marked_paths") else None
        kwargs: dict = {"selected_files": set(selected)}
        if marked is not None:
            kwargs["marked_paths"] = set(marked)
        return dataclasses.replace(state, **kwargs)
    except Exception:  # noqa: BLE001
        return state


class StateStore:
    def __init__(self, initial: AppState) -> None:
        self._state: AppState = initial
        self._listeners: List[Listener] = []
        # H-3: serialise concurrent dispatch calls (progress callbacks from scan
        # threads, UI events from main thread) so no action is silently lost.
        self._lock = threading.Lock()

    def get_state(self) -> AppState:
        return self._state

    def subscribe(self, fn: Listener) -> Callable[[], None]:
        if fn not in self._listeners:
            self._listeners.append(fn)
        return lambda: self._unsubscribe(fn)

    def _unsubscribe(self, fn: Listener) -> None:
        try:
            self._listeners.remove(fn)
        except ValueError:
            pass

    def dispatch(self, action: Action) -> None:
        with self._lock:
            old: AppState = self._state
            self._state = reduce(self._state, action)
            current: AppState = self._state
        safe_old = _safe_old(old)
        for fn in list(self._listeners):
            fn(current, safe_old, action)

    def __repr__(self) -> str:
        return f"StateStore({self._state!r})"
