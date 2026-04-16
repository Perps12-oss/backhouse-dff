import pytest

from cerebro.core.pipeline import CerebroPipeline, ExecutableDeletePlan
from cerebro.core.safety.deletion_gate import DeletionGateError


class _NoopHistory:
    def record_deletion(self, **_kwargs):
        return None


def test_pipeline_blocks_permanent_delete_without_token():
    pipe = CerebroPipeline(history_store=_NoopHistory())
    plan = ExecutableDeletePlan(
        scan_id="scan_x",
        mode="permanent",
        operations=[],
        policy={"mode": "permanent"},
        source="test",
    )

    with pytest.raises(DeletionGateError):
        pipe.execute_delete_plan(plan)


def test_pipeline_allows_permanent_delete_with_uuid_hex_token():
    pipe = CerebroPipeline(history_store=_NoopHistory())
    plan = ExecutableDeletePlan(
        scan_id="scan_x",
        mode="permanent",
        operations=[],
        policy={"mode": "permanent", "token": "0123456789abcdef0123456789abcdef"},
        source="test",
    )

    res = pipe.execute_delete_plan(plan)
    assert res.scan_id == "scan_x"
    assert res.mode == "permanent"
    assert res.deleted == []
