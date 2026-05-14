from __future__ import annotations

from typing import Callable, Dict, List, Optional

from cerebro.v2.ui.flet_app.pages.review_flow.state import ReviewFlowState, ReviewScreen

_BACK_TARGETS: Dict[ReviewScreen, Optional[ReviewScreen]] = {
    "overview": None,
    "browse": "overview",
    "inspect": "browse",
    "cart": "browse",
    "execute": "cart",
    "report": "overview",
}

_FORWARD_TRANSITIONS: Dict[ReviewScreen, List[ReviewScreen]] = {
    "overview": ["browse"],
    "browse": ["inspect", "cart"],
    "inspect": ["browse"],
    "cart": ["execute"],
    "execute": ["report"],
    "report": ["overview"],
}


class ReviewFlowRouter:
    def __init__(self, state: ReviewFlowState, on_screen_changed: Callable[[], None]) -> None:
        self._state = state
        self._on_screen_changed = on_screen_changed

    @property
    def state(self) -> ReviewFlowState:
        return self._state

    def active_screen(self) -> ReviewScreen:
        return self._state.active_screen

    def can_go_back(self) -> bool:
        return len(self._state.screen_stack) > 1

    def back_target(self) -> Optional[ReviewScreen]:
        return _BACK_TARGETS.get(self._state.active_screen)

    def navigate(self, screen: ReviewScreen, *, push: bool = True) -> None:
        if screen == self._state.active_screen:
            return
        if push:
            self._state.screen_stack.append(screen)
        else:
            if self._state.screen_stack:
                self._state.screen_stack[-1] = screen
            else:
                self._state.screen_stack = [screen]
        self._state.active_screen = screen
        self._on_screen_changed()

    def go_back(self) -> bool:
        if len(self._state.screen_stack) <= 1:
            return False
        self._state.screen_stack.pop()
        self._state.active_screen = self._state.screen_stack[-1]
        self._on_screen_changed()
        return True

    def reset_to_overview(self) -> None:
        self._state.screen_stack = ["overview"]
        self._state.active_screen = "overview"
        self._on_screen_changed()

    def allowed_forward(self, screen: ReviewScreen) -> bool:
        return screen in _FORWARD_TRANSITIONS.get(self._state.active_screen, [])
