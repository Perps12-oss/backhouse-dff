"""
test_deletion_gate_integration.py — Integration: real issue_token() on same pipeline instance.
"""
from __future__ import annotations

import pytest

from cerebro.core.pipeline import CerebroPipeline
from cerebro.core.safety.deletion_gate import DeletionGateError


def test_pipeline_gate_is_instance_scoped():
    """Each CerebroPipeline gets its own DeletionGate (Decision A)."""
    p1 = CerebroPipeline()
    p2 = CerebroPipeline()
    assert p1.gate is not p2.gate


def test_permanent_delete_requires_token_from_same_gate(tmp_path):
    """execute_delete_plan with permanent mode must reject tokens from a different gate."""
    from cerebro.core.pipeline import ExecutableDeletePlan

    f = tmp_path / "a.txt"
    f.write_text("data")

    p1 = CerebroPipeline()
    p2 = CerebroPipeline()

    token = p2.gate.issue_token(reason="wrong gate")

    plan = p1.build_explicit_paths_plan([str(f)], mode="permanent")
    # Inject the wrong gate's token.
    import dataclasses
    plan = dataclasses.replace(plan, policy={"mode": "permanent", "token": token})

    with pytest.raises(DeletionGateError):
        p1.execute_delete_plan(plan)


def test_permanent_delete_succeeds_with_correct_gate_token(tmp_path):
    """Full round trip: issue token on pipeline gate, execute permanent delete."""
    f = tmp_path / "a.txt"
    f.write_text("data")

    pipeline = CerebroPipeline()
    token = pipeline.gate.issue_token(reason="integration test")

    plan = pipeline.build_explicit_paths_plan([str(f)], mode="permanent")
    import dataclasses
    plan = dataclasses.replace(plan, policy={"mode": "permanent", "token": token})

    result = pipeline.execute_delete_plan(plan)
    assert len(result.deleted) == 1
    assert not f.exists()
