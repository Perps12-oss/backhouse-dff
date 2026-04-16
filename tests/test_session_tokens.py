import re

from cerebro.core.session import SessionManager


def test_build_effective_plan_generates_secure_default_token(tmp_path):
    sm = SessionManager(persist_path=tmp_path / "sessions")
    scan_id = "scan_1"

    sm.begin_scan(scan_id, [tmp_path], {"mode": "files"})
    sm.set_groups(scan_id, groups=[{"group_id": 1}])
    sm.set_delete_intent(scan_id, tmp_path / "a.txt")

    plan = sm.build_effective_plan(scan_id)
    assert plan is not None

    token = plan["token"]
    assert isinstance(token, str)
    assert token.startswith("ui_")
    assert len(token) >= 16
    assert re.match(r"^ui_[A-Za-z0-9_-]{10,}$", token)


def test_build_effective_plan_respects_supplied_token(tmp_path):
    sm = SessionManager(persist_path=tmp_path / "sessions")
    scan_id = "scan_2"

    sm.begin_scan(scan_id, [tmp_path], {"mode": "files"})
    sm.set_groups(scan_id, groups=[{"group_id": 1}])
    sm.set_delete_intent(scan_id, tmp_path / "b.txt")

    plan = sm.build_effective_plan(scan_id, token="ui_custom_token")
    assert plan is not None
    assert plan["token"] == "ui_custom_token"
