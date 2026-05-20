"""Orchestrator must wait for engine work before returning results."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from cerebro.engines.orchestrator import ScanOrchestrator


@pytest.mark.parametrize(
    "mode",
    [
        "files",
        "large_files",
        "empty_folders",
        "burst",
    ],
)
def test_orchestrator_wait_returns_terminal_state(mode: str) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "a.txt").write_text("hello", encoding="utf-8")
        (root / "b.txt").write_text("hello", encoding="utf-8")
        orch = ScanOrchestrator()
        orch.set_mode(mode)
        progress_states: list[str] = []

        def on_progress(p) -> None:
            progress_states.append(str(p.state))

        orch.start_scan(
            folders=[root],
            protected=[],
            options={},
            progress_callback=on_progress,
        )
        assert orch.wait_for_completion(timeout=120.0) is True
        results = orch.get_results()
        assert orch.get_progress().state.value in (
            "completed",
            "cancelled",
            "error",
        )
        # large_files / empty may return informational groups; files should find dupes
        if mode == "files":
            assert len(results) >= 1
