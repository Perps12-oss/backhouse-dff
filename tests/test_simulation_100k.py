"""
Stress simulation: 100 000 duplicate groups end-to-end.

Covers the full logical pipeline without a live Flet page:
  scan → state dispatch → results filtering → select-all → delete & prune

Run with:
    pytest tests/test_simulation_100k.py -v
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import List

import pytest

from cerebro.engines.base_engine import DuplicateFile, DuplicateGroup
from cerebro.v2.state import StateStore
from cerebro.v2.state.actions import ResultsFilesRemoved, ScanCompleted
from cerebro.v2.state.app_state import AppMode, create_initial_state
from cerebro.v2.state.groups_prune import prune_paths_from_groups
from cerebro.v2.coordinator import CerebroCoordinator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_EXTENSIONS = [".jpg", ".png", ".mp3", ".mp4", ".pdf", ".zip", ".txt", ".docx"]
_FILTER_EXTS = {
    "pictures": {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff"},
    "music": {".mp3", ".flac", ".ogg", ".wav", ".aac", ".m4a"},
    "videos": {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv"},
    "documents": {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".txt", ".odt"},
    "archives": {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2"},
}


def _make_groups(n: int, files_per_group: int = 2) -> List[DuplicateGroup]:
    """Create *n* duplicate groups with *files_per_group* files each."""
    groups = []
    ext_cycle = _EXTENSIONS * (n // len(_EXTENSIONS) + 1)
    for i in range(n):
        ext = ext_cycle[i]
        size_base = (i % 500 + 1) * 1024  # 1 KB – 500 KB
        files = [
            DuplicateFile(
                path=Path(f"/fake/dir_{i}/copy_{j}/file_{i}{ext}"),
                size=size_base + j * 100,
                modified=float(1_700_000_000 + i * 10 + j),
                extension=ext,
            )
            for j in range(files_per_group)
        ]
        groups.append(DuplicateGroup(group_id=i, files=files))
    return groups


def _classify(ext: str) -> str:
    for bucket, exts in _FILTER_EXTS.items():
        if ext.lower() in exts:
            return bucket
    return "other"


def _filtered(groups: List[DuplicateGroup], key: str) -> List[DuplicateGroup]:
    if key == "all":
        return groups
    if key == "other":
        return [g for g in groups if _classify(g.files[0].extension) == "other"]
    exts = _FILTER_EXTS.get(key, set())
    return [g for g in groups if g.files[0].extension.lower() in exts]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSimulation100k:

    @pytest.fixture(scope="class")
    def groups(self) -> List[DuplicateGroup]:
        t0 = time.perf_counter()
        g = _make_groups(100_000, files_per_group=2)
        elapsed = time.perf_counter() - t0
        print(f"\n  Built 100k groups in {elapsed:.2f}s")
        return g

    # -- State dispatch -------------------------------------------------

    def test_scan_completed_state(self, groups):
        """ScanCompleted reducer stores all 100k groups and flips active_tab."""
        store = StateStore(create_initial_state())
        coordinator = CerebroCoordinator(store)

        t0 = time.perf_counter()
        coordinator.scan_completed(groups, scan_mode="files")
        elapsed = time.perf_counter() - t0

        state = store.get_state()
        assert state.mode == AppMode.RESULTS
        assert state.active_tab == "duplicates"
        assert len(state.groups) == 100_000
        print(f"\n  ScanCompleted dispatch: {elapsed*1000:.1f}ms")

    # -- Summary stats --------------------------------------------------

    def test_total_reclaimable(self, groups):
        """Reclaimable bytes sum must be > 0 for all groups."""
        total = sum(g.reclaimable for g in groups)
        assert total > 0, "Expected non-zero reclaimable bytes"
        total_files = sum(len(g.files) for g in groups)
        assert total_files == 200_000
        print(f"\n  Total reclaimable: {total / 1024**2:.1f} MB across {total_files:,} files")

    # -- Filtering ------------------------------------------------------

    @pytest.mark.parametrize("key", ["all", "pictures", "music", "videos", "documents", "archives", "other"])
    def test_filter_bucket(self, groups, key):
        t0 = time.perf_counter()
        result = _filtered(groups, key)
        elapsed = time.perf_counter() - t0

        assert isinstance(result, list)
        if key == "all":
            assert len(result) == 100_000
        else:
            assert len(result) <= 100_000
        print(f"\n  filter={key!r}: {len(result):,} groups in {elapsed*1000:.1f}ms")

    def test_filter_coverage(self, groups):
        """Every group appears in exactly one non-'all' bucket (or 'other')."""
        buckets = ["pictures", "music", "videos", "documents", "archives", "other"]
        seen = set()
        for key in buckets:
            for g in _filtered(groups, key):
                seen.add(g.group_id)
        assert len(seen) == 100_000, f"Only {len(seen)} groups covered by buckets"

    # -- Select-all (keep largest) logic --------------------------------

    def test_select_all_except_largest(self, groups):
        """select_all selects the smaller copy in every 2-file group."""
        t0 = time.perf_counter()
        selected = set()
        for g in groups:
            if len(g.files) < 2:
                continue
            largest = max(g.files, key=lambda f: f.size)
            for f in g.files:
                if f is not largest:
                    selected.add(str(f.path))
        elapsed = time.perf_counter() - t0

        assert len(selected) == 100_000, f"Expected 100k selected, got {len(selected)}"
        print(f"\n  select_all on 100k groups: {elapsed*1000:.1f}ms, {len(selected):,} files selected")

    # -- Prune (delete) -------------------------------------------------

    def test_prune_half(self, groups):
        """Pruning one file from each of 50k groups eliminates those groups (< 2 files → dropped)."""
        paths_to_delete = [str(g.files[1].path) for g in groups[:50_000]]

        t0 = time.perf_counter()
        pruned = prune_paths_from_groups(groups, paths_to_delete)
        elapsed = time.perf_counter() - t0

        # Groups with only 1 file remaining are dropped (no longer duplicates).
        assert len(pruned) == 50_000, f"Expected 50k untouched groups, got {len(pruned)}"
        assert all(len(g.files) == 2 for g in pruned), "Untouched groups must still have 2 files"
        print(f"\n  prune_paths_from_groups (50k paths): {elapsed*1000:.1f}ms")

    def test_prune_all_files_in_group_removes_group(self, groups):
        """Pruning ALL files in a group removes that group entirely."""
        all_paths = [str(f.path) for g in groups[:1000] for f in g.files]
        pruned = prune_paths_from_groups(groups, all_paths)
        assert len(pruned) == 99_000

    # -- ResultsFilesRemoved state action -------------------------------

    def test_results_files_removed_action(self, groups):
        """ResultsFilesRemoved correctly updates state.groups via reducer."""
        store = StateStore(create_initial_state())
        coordinator = CerebroCoordinator(store)
        coordinator.scan_completed(groups, scan_mode="files")

        paths = [str(g.files[1].path) for g in groups[:10_000]]

        t0 = time.perf_counter()
        coordinator.results_files_removed(paths)
        elapsed = time.perf_counter() - t0

        state = store.get_state()
        # 10k groups had one file deleted → only 1 file left → dropped (not duplicates).
        assert len(state.groups) == 90_000, f"Expected 90k groups, got {len(state.groups)}"
        assert all(len(g.files) == 2 for g in state.groups)
        print(f"\n  ResultsFilesRemoved (10k paths via state): {elapsed*1000:.1f}ms")

    # -- Full round-trip performance ------------------------------------

    def test_full_roundtrip_timing(self, groups):
        """End-to-end: build → dispatch → filter → select → prune, under 5 seconds."""
        t_start = time.perf_counter()

        # 1. State dispatch
        store = StateStore(create_initial_state())
        CerebroCoordinator(store).scan_completed(groups, "files")
        state = store.get_state()

        # 2. Filter (all)
        filtered = list(state.groups)

        # 3. Select all except largest
        selected = set()
        for g in filtered:
            if len(g.files) >= 2:
                largest = max(g.files, key=lambda f: f.size)
                for f in g.files:
                    if f is not largest:
                        selected.add(str(f.path))

        # 4. Prune
        pruned = prune_paths_from_groups(state.groups, list(selected))

        elapsed = time.perf_counter() - t_start
        print(f"\n  Full round-trip (100k groups): {elapsed:.2f}s")
        assert elapsed < 5.0, f"Round-trip took {elapsed:.2f}s — too slow"
        # After deleting every duplicate copy (keeping the largest), each group
        # has exactly 1 file left → all groups are dropped (no remaining duplicates).
        assert len(pruned) == 0, f"Expected 0 remaining groups after full dedup, got {len(pruned)}"
        assert len(selected) == 100_000
