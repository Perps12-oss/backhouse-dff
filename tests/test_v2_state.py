"""Unit tests for CEREBRO v2 app state (Blueprint Sprint 1)."""

from __future__ import annotations

from pathlib import Path

from cerebro.engines.base_engine import DuplicateFile, DuplicateGroup
from cerebro.v2.state import (
    AppMode,
    ReviewNavigate,
    ScanCompleted,
    ScanEnded,
    ScanProgressSnapshot,
    ScanStarted,
    SetActiveTab,
    StateStore,
    create_initial_state,
    reduce,
)


def _one_file_group(gid: int = 1) -> DuplicateGroup:
    f1 = DuplicateFile(path=Path("/tmp/a.txt"), size=1, modified=0.0, extension=".txt")
    f2 = DuplicateFile(path=Path("/tmp/b.txt"), size=1, modified=0.0, extension=".txt")
    return DuplicateGroup(group_id=gid, files=[f1, f2])


def test_reduce_scan_completed_sets_mode_and_tab() -> None:
    s0 = create_initial_state()
    g = _one_file_group()
    s1 = reduce(s0, ScanCompleted([g], "photos"))
    assert s1.mode is AppMode.RESULTS
    assert s1.scan_mode == "photos"
    assert len(s1.groups) == 1
    assert s1.active_tab == "results"
    assert s1.selected_group_id is None
    assert s1.review_unlocked is True


def test_set_active_tab() -> None:
    s0 = create_initial_state()
    s1 = reduce(s0, SetActiveTab("scan"))
    assert s1.active_tab == "scan"
    assert s1.mode is AppMode.IDLE
    s2 = reduce(s1, SetActiveTab("results"))
    assert s2.active_tab == "results"
    assert s2.mode is AppMode.RESULTS


def test_set_active_tab_while_scanning_preserves_mode() -> None:
    s0 = create_initial_state()
    s1 = reduce(s0, ScanStarted("files"))
    assert s1.mode is AppMode.SCANNING
    s2 = reduce(s1, SetActiveTab("welcome"))
    assert s2.active_tab == "welcome"
    assert s2.mode is AppMode.SCANNING


def test_scan_lifecycle() -> None:
    s0 = create_initial_state()
    s1 = reduce(s0, ScanStarted("photos"))
    assert s1.scan_mode == "photos"
    s2 = reduce(s1, ScanProgressSnapshot({"state": "scanning", "files_scanned": 2}))
    assert s2.scan_progress.get("files_scanned") == 2
    s3 = reduce(s2, ScanEnded("cancelled"))
    assert s3.mode is AppMode.IDLE
    assert s3.scan_progress == {}
    s4 = reduce(
        s3,
        ScanCompleted([_one_file_group()], "files"),
    )
    assert s4.mode is AppMode.RESULTS
    assert s4.scan_progress == {}


def test_set_active_tab_review_blocked_until_unlocked() -> None:
    s0 = create_initial_state()
    s1 = reduce(s0, SetActiveTab("review"))
    assert s1 is s0
    s2 = reduce(s0, ScanCompleted([_one_file_group()], "files"))
    s3 = reduce(s2, SetActiveTab("review"))
    assert s3.active_tab == "review"
    assert s3.mode is AppMode.REVIEW


def test_set_active_tab_unknown_key() -> None:
    s0 = create_initial_state()
    s1 = reduce(s0, SetActiveTab("nope"))  # type: ignore[arg-type]
    assert s1 is s0


def test_reduce_review_navigate() -> None:
    s0 = create_initial_state()
    s0 = reduce(s0, ScanCompleted([_one_file_group()], "files"))
    s1 = reduce(s0, ReviewNavigate(7, None))
    assert s1.mode is AppMode.REVIEW
    assert s1.selected_group_id == 7
    assert s1.active_tab == "review"


def test_store_dispatches_to_listeners() -> None:
    seen: list = []
    st = StateStore(create_initial_state())

    def on_change(new, old, action):
        seen.append((new.mode, action))

    st.subscribe(on_change)
    g = _one_file_group()
    st.dispatch(ScanCompleted([g], "files"))
    assert len(seen) == 1
    assert seen[0][0] is AppMode.RESULTS


def test_unsubscribe() -> None:
    st = StateStore(create_initial_state())
    calls = []
    u = st.subscribe(lambda *a: calls.append(1))
    st.dispatch(ScanCompleted([_one_file_group()], "files"))
    assert len(calls) == 1
    u()
    st.dispatch(ScanCompleted([_one_file_group(2)], "files"))
    assert len(calls) == 1
