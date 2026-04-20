from __future__ import annotations

import time
from pathlib import Path

from cerebro.engines.orchestrator import ScanOrchestrator
from cerebro.engines.turbo_file_engine import TurboFileEngine
from cerebro.engines.base_engine import ScanProgress, ScanState


def test_orchestrator_can_open_files_mode() -> None:
    orchestrator = ScanOrchestrator()

    options = orchestrator.set_mode("files")

    assert isinstance(options, list)
    assert isinstance(orchestrator.get_active_engine(), TurboFileEngine)
    # "files_classic" (FileDedupEngine) was removed in the post-v1 audit Cut 3.
    # Single-entrance invariant: only "files" is registered for file scans.
    assert "files_classic" not in orchestrator.get_available_modes()
    assert orchestrator.get_active_engine().state == ScanState.IDLE


def test_turbo_file_engine_small_scan_state_and_results(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("same-content", encoding="utf-8")
    (tmp_path / "b.txt").write_text("same-content", encoding="utf-8")
    (tmp_path / "c.txt").write_text("different-content", encoding="utf-8")

    engine = TurboFileEngine()
    assert engine.state == ScanState.IDLE

    seen_states: list[ScanState] = []

    engine.configure(
        folders=[tmp_path],
        protected=[],
        options={
            "min_size_bytes": 0,
            "max_size_bytes": 0,
            "include_hidden": False,
            "hash_algorithm": "sha256",
        },
    )

    engine.start(lambda progress: seen_states.append(progress.state))

    deadline = time.time() + 20
    while engine.state in (ScanState.IDLE, ScanState.SCANNING) and time.time() < deadline:
        time.sleep(0.05)

    assert engine.state == ScanState.COMPLETED
    assert ScanState.SCANNING in seen_states
    assert ScanState.COMPLETED in seen_states

    results = engine.get_results()
    assert len(results) == 1
    assert len(results[0].files) == 2
    assert {f.path.name for f in results[0].files} == {"a.txt", "b.txt"}


def test_turbo_progress_total_never_drops_below_scanned_across_phases() -> None:
    """Hash phases report batch totals; denominator must stay >= files_scanned."""
    engine = TurboFileEngine()
    engine._progress = ScanProgress(state=ScanState.SCANNING)
    engine._on_turbo_progress("discovering", 22487, 22487)
    assert engine._progress.files_scanned == 22487
    assert engine._progress.files_total == 22487
    engine._on_turbo_progress("hashing_full", 5000, 22080)
    assert engine._progress.files_scanned >= 22487
    assert engine._progress.files_total >= engine._progress.files_scanned
