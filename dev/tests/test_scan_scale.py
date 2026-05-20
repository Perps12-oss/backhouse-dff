"""Scale-oriented tests for TurboScanner (1M-file plan)."""

from __future__ import annotations

from pathlib import Path

import pytest

from cerebro.core.scanners.turbo_scanner import (
    TurboScanConfig,
    TurboScanner,
    effective_exclude_dirs,
    walk_directory_worker,
)
from cerebro.engines.scan_stage import ScanStage
from cerebro.engines.turbo_file_engine import TurboFileEngine
from cerebro.engines.base_engine import ScanState
from cerebro.v2.core.checkpoint_db import CheckpointDB
from cerebro.v2.ui.flet_app.components.scan.scan_hud import ScanHUD


def test_walk_directory_worker_nine_tuple_is_skip_system_not_cancel(tmp_path: Path) -> None:
    """MP discovery passes 9 args ending with skip_system; must not call bool.is_set()."""
    (tmp_path / "a.txt").write_bytes(b"x")
    args = (
        tmp_path,
        True,
        set(),
        set(),
        True,
        0,
        0,
        False,
        True,
    )
    found = walk_directory_worker(args)
    assert any(p.name == "a.txt" for p, _, _ in found)


def test_walk_skips_windows_when_skip_system_true(tmp_path: Path) -> None:
    root = tmp_path / "drive"
    root.mkdir(parents=True)
    (root / "Windows").mkdir()
    (root / "Windows" / "setuperr.log").write_text("x", encoding="utf-8")
    (root / "Users").mkdir(parents=True)
    (root / "Users" / "doc.txt").write_text("y", encoding="utf-8")

    args = (
        root,
        True,
        set(),
        set(),
        True,
        0,
        0,
        False,
        True,
        None,
    )
    found = walk_directory_worker(args)
    paths = {p.name for p, _, _ in found}
    assert "doc.txt" in paths
    assert "setuperr.log" not in paths


def test_effective_exclude_dirs_includes_defaults_when_skip_system() -> None:
    cfg = TurboScanConfig(skip_system=True, exclude_dirs=set())
    ex = effective_exclude_dirs(cfg)
    assert "Windows" in ex
    assert "node_modules" in ex


def test_turbo_engine_verify_duplicates_controls_full_hash(tmp_path: Path) -> None:
    (tmp_path / "a.bin").write_bytes(b"same" * 32)
    (tmp_path / "b.bin").write_bytes(b"same" * 32)

    engine = TurboFileEngine()
    engine.configure(
        folders=[tmp_path],
        protected=[],
        options={
            "min_size_bytes": 0,
            "hash_algorithm": "sha256",
            "verify_duplicates": False,
            "incremental_scan": False,
        },
    )
    engine.start(lambda _p: None)
    assert engine.get_progress().state == ScanState.COMPLETED
    assert len(engine.get_results()) >= 1

    cfg_quick = TurboScanConfig(use_quick_hash=True, use_full_hash=False)
    cfg_full = TurboScanConfig(use_quick_hash=True, use_full_hash=True)
    assert cfg_quick.use_full_hash is False
    assert cfg_full.use_full_hash is True


def test_grouping_from_checkpoint_matches_in_memory(tmp_path: Path) -> None:
    db_path = tmp_path / "ckpt.db"
    ckpt = CheckpointDB(db_path)
    scan_id = ckpt.create_manifest([str(tmp_path)], {"min_size": 0})
    rows = []
    for i in range(6):
        size = 100 if i < 4 else 200
        p = tmp_path / f"f_{i}.txt"
        p.write_text("x" * size, encoding="utf-8")
        rows.append((str(p), size, p.stat().st_mtime))
    ckpt.insert_pending_files(scan_id, rows)

    cfg = TurboScanConfig()
    scanner = TurboScanner(cfg)

    mem_files = [(Path(p), s, m) for p, s, m in rows]

    def _noop_emit(*_a, **_k):
        pass

    mem_groups = scanner._group_files_by_size(
        discovered_files=mem_files,
        ckpt=None,
        scan_id=None,
        use_db_grouping=False,
        scope_total=len(mem_files),
        emit=_noop_emit,
        cancel_event=None,
    )
    db_groups = scanner._group_files_by_size(
        discovered_files=[],
        ckpt=ckpt,
        scan_id=scan_id,
        use_db_grouping=True,
        scope_total=len(rows),
        emit=_noop_emit,
        cancel_event=None,
    )
    assert set(mem_groups.keys()) == set(db_groups.keys())
    for k in mem_groups:
        assert len(mem_groups[k]) == len(db_groups[k])


def test_checkpoint_streaming_batch_insert(tmp_path: Path) -> None:
    ckpt = CheckpointDB(tmp_path / "c.db")
    scan_id = ckpt.create_manifest(["/tmp"], {})
    batch = [(f"/tmp/f{i}.txt", 10 + i, 1.0) for i in range(12000)]
    ckpt.insert_pending_files_batch(scan_id, batch)
    assert ckpt.count_files(scan_id) == 12000


def test_scan_hud_normalizes_tier_a_stage() -> None:
    assert ScanHUD._normalize_scan_stage_for_ui("tier_a_prefilter") == ScanStage.TIER_A_PREFILTER


def test_whole_scan_bar_ratio_tier_a_advances() -> None:
    from cerebro.engines.scan_stage import ScanStage

    r0 = ScanHUD._whole_scan_bar_ratio(ScanStage.TIER_A_PREFILTER, 0, 100_000)
    r1 = ScanHUD._whole_scan_bar_ratio(ScanStage.TIER_A_PREFILTER, 50_000, 100_000)
    r2 = ScanHUD._whole_scan_bar_ratio(ScanStage.TIER_A_PREFILTER, 100_000, 100_000)
    assert 0.15 < r0 < 0.2
    assert r0 < r1 < r2 < 0.95


@pytest.mark.slow
def test_synthetic_100k_grouping_db_path(tmp_path: Path) -> None:
    """Optional nightly: DB grouping over 100k rows stays bounded in memory."""
    ckpt = CheckpointDB(tmp_path / "big.db")
    scan_id = ckpt.create_manifest([str(tmp_path)], {"min_size": 0})
    batch = []
    for i in range(100_000):
        size = i % 50
        batch.append((str(tmp_path / f"f_{i:06d}.dat"), size, 1.0))
    for off in range(0, len(batch), 10_000):
        ckpt.insert_pending_files_batch(scan_id, batch[off : off + 10_000], update_total=True)
    cfg = TurboScanConfig()
    scanner = TurboScanner(cfg)
    groups = scanner._group_files_by_size(
        discovered_files=[],
        ckpt=ckpt,
        scan_id=scan_id,
        use_db_grouping=True,
        scope_total=100_000,
        emit=lambda *_a, **_k: None,
        cancel_event=None,
    )
    assert ckpt.count_files(scan_id) == 100_000
    assert len(groups) > 0
