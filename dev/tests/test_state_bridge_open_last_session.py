"""Unit tests for :meth:`StateBridge.open_last_session` (memory vs ``last.json`` fallback)."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from cerebro.engines.base_engine import DuplicateFile, DuplicateGroup
from cerebro.v2.state import StateStore, create_initial_state
from cerebro.v2.ui.flet_app.services.state_bridge import StateBridge


def _one_group() -> DuplicateGroup:
    f1 = DuplicateFile(
        path=Path("/tmp/a.txt"),
        size=1,
        modified=0.0,
        extension=".txt",
    )
    f2 = DuplicateFile(
        path=Path("/tmp/b.txt"),
        size=1,
        modified=0.0,
        extension=".txt",
    )
    return DuplicateGroup(group_id=1, files=[f1, f2])


@pytest.fixture
def bridge_and_snacks(monkeypatch) -> tuple[StateBridge, list[tuple[str, dict[str, Any]]]]:
    store = StateStore(create_initial_state())
    coord = MagicMock()
    backend = MagicMock()
    page = MagicMock()
    br = StateBridge(page, store, coord, backend)
    snacks: list[tuple[str, dict[str, Any]]] = []

    def _record(msg: str, **kw: Any) -> None:
        snacks.append((msg, dict(kw)))

    monkeypatch.setattr(br, "show_snackbar", _record)
    return br, snacks


def test_open_last_session_from_memory_when_backend_has_results(
    bridge_and_snacks: tuple[StateBridge, list[tuple[str, dict[str, Any]]]],
) -> None:
    bridge, snacks = bridge_and_snacks
    g = _one_group()
    bridge.backend.get_results.return_value = [g]
    bridge.open_last_session()
    bridge.coordinator.scan_completed.assert_called_once_with([g], "files")
    bridge.coordinator.set_active_tab.assert_called_once_with("review")
    assert len(snacks) == 1
    assert "memory" in snacks[0][0].lower()
    assert snacks[0][1].get("success") is True


def test_open_last_session_from_disk_when_memory_empty(
    bridge_and_snacks: tuple[StateBridge, list[tuple[str, dict[str, Any]]]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bridge, snacks = bridge_and_snacks
    g = _one_group()

    def _fake_load():
        return ([g], "photos", 1_700_000_000.0)

    monkeypatch.setattr(
        "cerebro.v2.persistence.scan_snapshot.load_last_scan_snapshot",
        _fake_load,
    )
    bridge.backend.get_results.return_value = []
    bridge.open_last_session()
    bridge.coordinator.scan_completed.assert_called_once_with([g], "photos")
    bridge.coordinator.set_active_tab.assert_called_once_with("review")
    assert len(snacks) == 1
    assert "disk" in snacks[0][0].lower()
    assert "last.json" in snacks[0][0]
    assert snacks[0][1].get("success") is True


def test_open_last_session_info_when_no_snapshot(
    bridge_and_snacks: tuple[StateBridge, list[tuple[str, dict[str, Any]]]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bridge, snacks = bridge_and_snacks
    monkeypatch.setattr(
        "cerebro.v2.persistence.scan_snapshot.load_last_scan_snapshot",
        lambda: None,
    )
    bridge.backend.get_results.return_value = []
    bridge.open_last_session()
    bridge.coordinator.scan_completed.assert_not_called()
    bridge.coordinator.set_active_tab.assert_not_called()
    assert len(snacks) == 1
    assert snacks[0][1].get("info") is True


def test_open_last_session_info_when_snapshot_has_empty_groups(
    bridge_and_snacks: tuple[StateBridge, list[tuple[str, dict[str, Any]]]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bridge, snacks = bridge_and_snacks
    monkeypatch.setattr(
        "cerebro.v2.persistence.scan_snapshot.load_last_scan_snapshot",
        lambda: ([], "files", 1.0),
    )
    bridge.backend.get_results.return_value = []
    bridge.open_last_session()
    bridge.coordinator.scan_completed.assert_not_called()
    assert len(snacks) == 1
    assert snacks[0][1].get("info") is True
