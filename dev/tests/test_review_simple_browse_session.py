"""Phase 3 — simple mode browse session flag and sidebar labels."""

from __future__ import annotations

from cerebro.v2.ui.flet_app.pages.review_flow.progress_sidebar import ProgressSidebarRefs, update_progress_sidebar_refs
from cerebro.v2.ui.flet_app.pages.review_flow.state import ReviewFlowState


def _refs() -> ProgressSidebarRefs:
    import flet as ft

    return ProgressSidebarRefs(
        screen_label=ft.Text(""),
        groups_text=ft.Text(""),
        marked_text=ft.Text(""),
    )


def test_sidebar_details_label_when_simple_browse() -> None:
    state = ReviewFlowState()
    refs = _refs()
    update_progress_sidebar_refs(refs, "browse", state, simple_details=True)
    assert refs.screen_label.value == "Details"


def test_sidebar_browse_label_when_not_simple() -> None:
    state = ReviewFlowState()
    refs = _refs()
    update_progress_sidebar_refs(refs, "browse", state, simple_details=False)
    assert refs.screen_label.value == "Browse"
