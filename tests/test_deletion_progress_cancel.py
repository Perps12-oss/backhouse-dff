"""
test_deletion_progress_cancel.py — Progress callback returning False cancels deletion.
"""
from __future__ import annotations

from pathlib import Path

from cerebro.core.pipeline import CerebroPipeline


def test_progress_cancel_stops_deletion(tmp_path):
    """If the progress callback returns False, deletion should stop mid-batch."""
    files = []
    for i in range(5):
        f = tmp_path / f"dup_{i}.txt"
        f.write_text(f"content {i}")
        files.append(str(f))

    keeper = tmp_path / "keeper.txt"
    keeper.write_text("keep")

    pipeline = CerebroPipeline()
    plan = pipeline.build_explicit_paths_plan(files, mode="permanent")

    # Issue token for permanent delete.
    token = pipeline.gate.issue_token(reason="cancel test")
    import dataclasses
    plan = dataclasses.replace(plan, policy={"mode": "permanent", "token": token})

    # Cancel after first deletion.
    call_count = [0]

    def _progress(current, total, name):
        call_count[0] += 1
        return call_count[0] < 2  # cancel after 1

    result = pipeline.execute_delete_plan(plan, progress_cb=_progress)

    # At least one file deleted, but not all 5.
    assert len(result.deleted) < 5, "Cancellation must stop deletion before all files"
    assert len(result.deleted) >= 1, "At least one file must have been deleted before cancel"
