"""
test_session_manager_token.py — H-4: SessionManager.build_effective_plan() must use a token
issued by a real DeletionGate, not a self-generated one.
"""
from __future__ import annotations

import pytest

from cerebro.core.session import SessionManager


def _make_session_with_groups(tmp_path, session_manager):
    """Helper: add a fake scan record with groups and intents."""
    scan_id = "test-scan-01"
    session_manager._scans[scan_id] = type("Record", (), {
        "scan_id": scan_id,
        "groups": [object()],  # non-empty
        "delete_intents": {},
        "survivor_locks": {},
    })()
    return scan_id


def test_permanent_plan_without_pipeline_has_no_token(tmp_path):
    """H-4: without a pipeline, permanent plan token must be None (not self-generated)."""
    sm = SessionManager(persist_path=tmp_path)
    sm._scans["scan1"] = type("R", (), {
        "scan_id": "scan1",
        "groups": [object()],
        "delete_intents": {},
        "survivor_locks": {},
    })()

    plan = sm.build_effective_plan("scan1", policy="permanent")
    assert plan is not None
    # Token must be None — a self-generated token is never accepted by any gate.
    assert plan.get("token") is None


def test_permanent_plan_with_pipeline_gets_gate_token(tmp_path):
    """H-4: when a pipeline is provided, token is issued by pipeline.gate."""
    from cerebro.core.pipeline import CerebroPipeline

    sm = SessionManager(persist_path=tmp_path)
    sm._scans["scan2"] = type("R", (), {
        "scan_id": "scan2",
        "groups": [object()],
        "delete_intents": {},
        "survivor_locks": {},
    })()

    pipeline = CerebroPipeline()
    plan = sm.build_effective_plan("scan2", policy="permanent", pipeline=pipeline)

    assert plan is not None
    token = plan.get("token")
    assert token is not None
    # The token must be accepted by the pipeline's gate.
    assert pipeline.gate.verify_token(token) is True


def test_trash_plan_does_not_require_token(tmp_path):
    """Non-permanent plans should not require a gate token."""
    sm = SessionManager(persist_path=tmp_path)
    sm._scans["scan3"] = type("R", (), {
        "scan_id": "scan3",
        "groups": [object()],
        "delete_intents": {},
        "survivor_locks": {},
    })()

    plan = sm.build_effective_plan("scan3", policy="trash")
    assert plan is not None
    # Token may be None for trash — that is fine.
