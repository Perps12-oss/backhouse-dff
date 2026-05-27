"""BackendService must drive coordinator scan lifecycle."""

from __future__ import annotations

from unittest.mock import MagicMock

from cerebro.engines.base_engine import ScanProgress, ScanState
from cerebro.v2.coordinator import CerebroCoordinator
from cerebro.v2.state import StateStore
from cerebro.v2.state.app_state import create_initial_state
from cerebro.v2.ui.flet_app.services.backend_service import BackendService


def test_handle_progress_dispatches_to_coordinator() -> None:
    store = StateStore(create_initial_state())
    coord = CerebroCoordinator(store)
    backend = BackendService(page=None, coordinator=coord)
    backend._handle_progress(
        ScanProgress(state=ScanState.SCANNING, files_scanned=1, files_total=10, stage="discovering")
    )
    snap = store.get_state().scan_progress
    assert snap is not None
    assert int(snap.get("files_scanned", 0) or 0) == 1


def test_scan_started_dispatched_from_worker_entry() -> None:
    store = StateStore(create_initial_state())
    coord = MagicMock(spec=CerebroCoordinator)
    backend = BackendService(page=None, coordinator=coord)
    backend._coordinator.scan_started("files")  # type: ignore[union-attr]
    coord.scan_started.assert_called_once_with("files")
