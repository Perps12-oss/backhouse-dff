from __future__ import annotations

from pathlib import Path

from cerebro.engines.base_engine import DuplicateFile, DuplicateGroup
from cerebro.v2.ui.flet_app.pages.review_flow.state import ReviewFlowState, SetSelection


def test_cart_buckets_group_delete_and_keep() -> None:
    g = DuplicateGroup(
        group_id=1,
        files=[
            DuplicateFile(path=Path("/a/one.jpg"), size=10, modified=1.0, extension="jpg"),
            DuplicateFile(path=Path("/a/two.jpg"), size=20, modified=1.0, extension="jpg"),
        ],
    )
    state = ReviewFlowState(scan_results=[g])
    state.set_selections[1] = SetSelection(kept_paths={"/a/one.jpg"}, deleted_paths={"/a/two.jpg"})
    state.marked_paths = {"/a/two.jpg"}
    buckets = state.cart_buckets()
    assert len(buckets["delete"]) == 1
    assert len(buckets["keep"]) == 1
