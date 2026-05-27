"""Review session JSON schema validation."""

from __future__ import annotations

from cerebro.v2.session_schema import validate_review_session_payload


def test_valid_session() -> None:
    ok, err, norm = validate_review_session_payload(
        {
            "version": 1,
            "active_screen": "browse",
            "marked_paths": ["C:\\a.txt"],
            "selected_set_ids": [1, 2],
            "inspect_layout_by_set": {"1": [0, 1, False]},
        }
    )
    assert ok is True
    assert err == ""
    assert norm["active_screen"] == "browse"


def test_rejects_invalid_screen() -> None:
    ok, err, _ = validate_review_session_payload(
        {"version": 1, "active_screen": "hacked", "marked_paths": []}
    )
    assert ok is False
    assert "active_screen" in err
