from __future__ import annotations

from cerebro.v2.ui.flet_app.pages.review_flow.mock_data import generate_mock_groups
from cerebro.v2.ui.flet_app.pages.review_flow.router import ReviewFlowRouter
from cerebro.v2.ui.flet_app.pages.review_flow.state import ReviewFlowState


def test_router_push_and_back() -> None:
    state = ReviewFlowState()
    events: list[str] = []
    router = ReviewFlowRouter(state, lambda: events.append(state.active_screen))
    router.navigate("browse")
    assert state.active_screen == "browse"
    assert state.screen_stack == ["overview", "browse"]
    assert router.go_back() is True
    assert state.active_screen == "overview"


def test_visible_groups_text_filter() -> None:
    state = ReviewFlowState(scan_results=generate_mock_groups(5, seed=1))
    state.text_filter = "vacation_0001"
    visible = state.visible_groups()
    assert visible
    assert all("vacation_0001" in str(f.path) for g in visible for f in g.files)


def test_tag_filter_limits_visible_groups() -> None:
    state = ReviewFlowState(scan_results=generate_mock_groups(3, seed=3))
    state.tags_by_set[1] = {"review-later"}
    state.active_tag_filter = "review-later"
    visible = state.visible_groups()
    assert visible
    assert all(g.group_id == 1 for g in visible)

    state = ReviewFlowState(scan_results=generate_mock_groups(3, seed=2))
    state.selected_set_ids = {1, 2}
    state.marked_paths = {str(state.scan_results[0].files[1].path)}
    assert state.selected_set_count() == 2
    assert state.marked_bytes() > 0
