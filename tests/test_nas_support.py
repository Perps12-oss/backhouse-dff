"""
NAS / Network Path Support Tests

Tests:
1. validate_scan_path returns (True, "") for an existing temp directory.
2. validate_scan_path returns (False, ...) for a non-existent path.
3. validate_scan_path handles OSError gracefully (monkeypatched Path.exists).
4. TurboFileEngine with a non-existent path doesn't crash — emits error/completed progress.
5. NetworkPathDialog can be instantiated headlessly (no display required).
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import List

import pytest

from cerebro.utils.paths import validate_scan_path
from cerebro.engines.turbo_file_engine import TurboFileEngine
from cerebro.engines.base_engine import ScanProgress, ScanState


# ---------------------------------------------------------------------------
# 1. validate_scan_path — existing directory
# ---------------------------------------------------------------------------

def test_validate_scan_path_existing_dir(tmp_path: Path) -> None:
    ok, reason = validate_scan_path(str(tmp_path))
    assert ok is True
    assert reason == ""


# ---------------------------------------------------------------------------
# 2. validate_scan_path — non-existent path
# ---------------------------------------------------------------------------

def test_validate_scan_path_nonexistent() -> None:
    ok, reason = validate_scan_path("/this/path/definitely/does/not/exist/cerebro_test")
    assert ok is False
    assert reason != ""


# ---------------------------------------------------------------------------
# 3. validate_scan_path — OSError via monkeypatch
# ---------------------------------------------------------------------------

def test_validate_scan_path_oserror(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise_oserror(self: object) -> bool:
        raise OSError("Network unreachable")

    monkeypatch.setattr(Path, "exists", _raise_oserror)
    ok, reason = validate_scan_path(r"\\server\share")
    assert ok is False
    assert "Cannot reach path" in reason


# ---------------------------------------------------------------------------
# 4. TurboFileEngine with a non-existent path — must not crash
# ---------------------------------------------------------------------------

def test_turbo_file_engine_nonexistent_path_no_crash(tmp_path: Path) -> None:
    """Engine with a non-existent root must complete without raising."""
    ghost = tmp_path / "nonexistent_nas_share"
    # Do NOT create this directory — it must not exist.

    engine = TurboFileEngine()
    engine.configure(
        folders=[ghost],
        protected=[],
        options={
            "min_size_bytes": 0,
            "max_size_bytes": 0,
            "include_hidden": False,
            "hash_algorithm": "sha256",
        },
    )

    seen_progresses: List[ScanProgress] = []
    engine.start(lambda p: seen_progresses.append(p))

    deadline = time.time() + 15
    while engine.state in (ScanState.IDLE, ScanState.SCANNING) and time.time() < deadline:
        time.sleep(0.05)

    # Must not be stuck; must reach a terminal state
    assert engine.state in (ScanState.COMPLETED, ScanState.ERROR, ScanState.CANCELLED)
    # At least one progress event must have been emitted
    assert len(seen_progresses) >= 1


# ---------------------------------------------------------------------------
# 5. NetworkPathDialog instantiation (headless — no display)
# ---------------------------------------------------------------------------

def test_network_path_dialog_instantiation() -> None:
    """NetworkPathDialog can be imported and instantiated without a running display."""
    from cerebro.v2.ui.folder_panel import NetworkPathDialog

    # Instantiate with a mock parent that satisfies tkinter type hints but
    # never actually creates a window.
    class _FakeParent:
        pass

    dlg = NetworkPathDialog(_FakeParent())  # type: ignore[arg-type]
    assert dlg.result is None
    # show() is NOT called — that would require a live Tk root.
    # We only verify the class has the expected interface.
    assert hasattr(dlg, "show")
    assert hasattr(dlg, "result")
