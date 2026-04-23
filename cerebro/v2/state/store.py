"""
Synchronous store: dispatch -> reducer -> listeners (CEREBRO rules §2, §7).

All listeners run on the thread that called :meth:`dispatch` — the UI root must
schedule ``dispatch`` from the main thread after scan/worker work (see ScanPage
``after(0, ...)`` pattern for progress).
"""

from __future__ import annotations

from typing import Callable, List

from cerebro.v2.state.actions import Action
from cerebro.v2.state.app_state import AppState
from cerebro.v2.state.reducer import reduce

Listener = Callable[[AppState, AppState, Action], None]


class StateStore:
    def __init__(self, initial: AppState) -> None:
        self._state: AppState = initial
        self._listeners: List[Listener] = []

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
        old: AppState = self._state
        self._state = reduce(self._state, action)
        current: AppState = self._state
        for fn in list(self._listeners):
            fn(current, old, action)

    def __repr__(self) -> str:
        return f"StateStore({self._state!r})"
