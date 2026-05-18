from cerebro.core.session import SessionManager


def test_build_effective_plan_no_self_generated_token(tmp_path):
    """H-4: without a pipeline, permanent plan token must be None, not a self-generated string.
    Self-generated tokens would never be accepted by any DeletionGate instance.
    """
    sm = SessionManager(persist_path=tmp_path / "sessions")
    scan_id = "scan_1"

    sm.begin_scan(scan_id, [tmp_path], {"mode": "files"})
    sm.set_groups(scan_id, groups=[{"group_id": 1}])
    sm.set_delete_intent(scan_id, tmp_path / "a.txt")

    plan = sm.build_effective_plan(scan_id, policy="permanent")
    assert plan is not None
    # Token must be None — no pipeline was provided, so no registered token exists.
    assert plan["token"] is None


def test_build_effective_plan_respects_supplied_token(tmp_path):
    sm = SessionManager(persist_path=tmp_path / "sessions")
    scan_id = "scan_2"

    sm.begin_scan(scan_id, [tmp_path], {"mode": "files"})
    sm.set_groups(scan_id, groups=[{"group_id": 1}])
    sm.set_delete_intent(scan_id, tmp_path / "b.txt")

    plan = sm.build_effective_plan(scan_id, token="ui_custom_token")
    assert plan is not None
    assert plan["token"] == "ui_custom_token"
