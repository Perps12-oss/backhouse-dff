from __future__ import annotations

import threading
import time
from pathlib import Path

from cerebro.engines.orchestrator import ScanOrchestrator
from cerebro.engines.turbo_file_engine import TurboFileEngine
from cerebro.engines.base_engine import ScanProgress, ScanState
from cerebro.core.scanners.turbo_scanner import TurboScanner, TurboScanConfig


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


def test_turbo_cache_invalidates_when_scan_scope_options_change(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    scan_root = tmp_path / "scan"
    scan_root.mkdir()
    (scan_root / "a.txt").write_text("same-content", encoding="utf-8")
    (scan_root / "b.txt").write_text("same-content", encoding="utf-8")

    scanner_a = TurboScanner(
        TurboScanConfig(
            cache_dir=cache_dir,
            use_cache=True,
            incremental=True,
            min_size=0,
            exclude_paths=set(),
            hash_algorithm="sha256",
        )
    )
    list(scanner_a.scan([scan_root]))
    assert scanner_a.hash_cache is not None
    assert scanner_a.hash_cache.get_stats()["total_entries"] > 0

    scanner_b = TurboScanner(
        TurboScanConfig(
            cache_dir=cache_dir,
            use_cache=True,
            incremental=True,
            min_size=10 * 1024 * 1024,
            exclude_paths={str(scan_root)},
            hash_algorithm="sha256",
        )
    )
    list(scanner_b.scan([scan_root]))
    assert scanner_b.hash_cache is not None
    assert scanner_b.hash_cache.get_stats()["total_entries"] == 0


def test_correctness_parity_same_scan_twice(tmp_path: Path) -> None:
    """Same directory scanned twice must produce identical duplicate groups."""
    scan_root = tmp_path / "scan"
    scan_root.mkdir()
    (scan_root / "a.txt").write_bytes(b"hello duplicate" * 100)
    (scan_root / "b.txt").write_bytes(b"hello duplicate" * 100)
    (scan_root / "c.txt").write_bytes(b"unique content 1" * 50)
    (scan_root / "d.txt").write_bytes(b"unique content 2" * 50)

    def _run_scan(scan_root: Path) -> list[frozenset[str]]:
        scanner = TurboScanner(TurboScanConfig(
            min_size=0,
            hash_algorithm="sha256",
            use_cache=False,
        ))
        list(scanner.scan([scan_root]))  # exhaust; groups land in scanner.last_groups
        groups = [frozenset(g["paths"]) for g in scanner.last_groups]
        return sorted(groups, key=lambda g: min(g))

    first = _run_scan(scan_root)
    second = _run_scan(scan_root)
    assert first == second, (
        f"Correctness parity violation: scan 1 groups={first}, scan 2 groups={second}"
    )
    assert len(first) == 1
    assert frozenset([str(scan_root / "a.txt"), str(scan_root / "b.txt")]) in first


def test_terminal_state_monotonicity_cancelled_stays_cancelled(tmp_path: Path) -> None:
    """Once CANCELLED is emitted it must never be followed by COMPLETED."""
    scan_root = tmp_path / "scan"
    scan_root.mkdir()
    for i in range(20):
        (scan_root / f"f{i}.bin").write_bytes(bytes(range(256)) * 8)

    engine = TurboFileEngine()
    states_seen: list[str] = []

    def _cb(progress: ScanProgress) -> None:
        states_seen.append(progress.state.value if hasattr(progress.state, "value") else str(progress.state))

    engine.configure(
        folders=[scan_root],
        protected=[],
        options={"min_size_bytes": 0, "hash_algorithm": "sha256"},
    )
    engine.start(_cb)

    # Cancel after a short delay — scan may not have started yet, that's fine.
    time.sleep(0.05)
    engine.cancel()

    deadline = time.time() + 15
    while engine.state in (ScanState.IDLE, ScanState.SCANNING) and time.time() < deadline:
        time.sleep(0.05)

    # Terminal state must be either CANCELLED or COMPLETED (not an infinite loop).
    assert engine.state in (ScanState.CANCELLED, ScanState.COMPLETED)

    # If cancel was acknowledged: COMPLETED must never follow CANCELLED in the stream.
    if ScanState.CANCELLED in [
        s for s in states_seen if s in ("cancelled", ScanState.CANCELLED.value if hasattr(ScanState.CANCELLED, "value") else "cancelled")
    ]:
        cancelled_idx = next(
            (i for i, s in enumerate(states_seen) if "cancelled" in str(s).lower()), None
        )
        if cancelled_idx is not None:
            after_cancel = states_seen[cancelled_idx + 1:]
            assert not any("completed" in str(s).lower() for s in after_cancel), (
                f"Terminal state regression: COMPLETED after CANCELLED. states={states_seen}"
            )


def test_progress_monotonicity_across_all_phase_transitions(tmp_path: Path) -> None:
    """files_scanned must never decrease and files_total must always >= files_scanned."""
    scan_root = tmp_path / "scan"
    scan_root.mkdir()
    content = b"dup content" * 200
    for i in range(6):
        (scan_root / f"dup{i}.bin").write_bytes(content)
    (scan_root / "unique.bin").write_bytes(b"uniqueXYZ" * 200)

    engine = TurboFileEngine()
    snap_lock = threading.Lock()
    snapshots: list[tuple[int, int, str]] = []

    def _cb(progress: ScanProgress) -> None:
        with snap_lock:
            snapshots.append((
                progress.files_scanned,
                progress.files_total,
                str(progress.stage or ""),
            ))

    engine.configure(
        folders=[scan_root],
        protected=[],
        options={"min_size_bytes": 0, "hash_algorithm": "sha256"},
    )
    engine.start(_cb)

    deadline = time.time() + 30
    while engine.state in (ScanState.IDLE, ScanState.SCANNING) and time.time() < deadline:
        time.sleep(0.05)

    with snap_lock:
        snaps = list(snapshots)

    # files_total >= files_scanned at every point.
    for scanned, total, stage in snaps:
        assert total >= scanned, (
            f"Progress invariant violated at stage={stage!r}: "
            f"files_total={total} < files_scanned={scanned}"
        )

    # files_scanned must never decrease.
    for i in range(1, len(snaps)):
        prev_scanned = snaps[i - 1][0]
        cur_scanned = snaps[i][0]
        assert cur_scanned >= prev_scanned, (
            f"Monotonicity violated: files_scanned dropped from {prev_scanned} → "
            f"{cur_scanned} at stage={snaps[i][2]!r}"
        )
