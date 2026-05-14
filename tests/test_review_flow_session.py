from __future__ import annotations

import json
from pathlib import Path

from cerebro.v2.ui.flet_app.pages.review_flow.state import ReviewFlowState


def test_session_payload_roundtrip_fields(tmp_path: Path) -> None:
    state = ReviewFlowState()
    state.marked_paths = {"x"}
    state.selected_set_ids = {1}
    payload = {
        "version": 1,
        "active_screen": "browse",
        "marked_paths": sorted(state.marked_paths),
        "selected_set_ids": sorted(state.selected_set_ids),
    }
    path = tmp_path / "review_session.v1.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["marked_paths"] == ["x"]
    assert loaded["selected_set_ids"] == [1]
