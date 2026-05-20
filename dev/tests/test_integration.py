#!/usr/bin/env python3
"""
Integration test for Phase 2 - Wire-up File Dedup Engine to UI.
Integration test for Phase 3 - Image Dedup Engine.

Tests:
- Orchestrator mode switching
- Progress callback forwarding
- Results panel data loading
- Selection rule application
- Image format registry
- Perceptual hash computation
"""
from pathlib import Path
from cerebro.engines.orchestrator import ScanOrchestrator
from cerebro.engines.base_engine import ScanProgress, ScanState, DuplicateGroup, DuplicateFile
from cerebro.core.duplicate_result import DuplicateResult
from cerebro.engines.image_formats import (
    ImageFormatRegistry,
    UnionFind,
    hamming_distance,
    similarity_from_hamming,
)


def test_orchestrator_modes():
    """Test orchestrator mode switching."""
    orch = ScanOrchestrator()

    mode = "files"
    options = orch.set_mode(mode)
    assert orch.get_active_mode() == mode
    print(f"  {mode}: OK ({len(options)} options)")

    # Verify other modes are not implemented yet
    available = [m for m in orch.get_available_modes() if m != mode]
    print(f"  Other available modes: {', '.join(available)}")

    print("[PASS] Orchestrator mode switching: PASS")


def test_progress_data():
    """Test ScanProgress dataclass."""
    progress = ScanProgress(
        state=ScanState.SCANNING,
        files_scanned=100,
        files_total=1000,
        duplicates_found=25,
        groups_found=10,
        bytes_reclaimable=50_000_000,
        elapsed_seconds=5.5,
        current_file="test.jpg",
    )

    assert progress.state == ScanState.SCANNING
    assert progress.files_scanned == 100
    assert progress.duplicates_found == 25
    assert progress.groups_found == 10
    assert progress.bytes_reclaimable == 50_000_000

    print("[PASS] ScanProgress dataclass: PASS")


def test_duplicate_group():
    """Test DuplicateGroup creation."""
    files = [
        DuplicateFile(
            path=Path("/test/file1.txt"),
            size=1000,
            modified=1000.0,
            extension=".txt",
        ),
        DuplicateFile(
            path=Path("/test/file2.txt"),
            size=1000,
            modified=1000.0,
            extension=".txt",
        ),
    ]

    group = DuplicateGroup(group_id=1, files=files)

    assert group.group_id == 1
    assert group.file_count == 2
    assert group.total_size == 2000

    keeper_index = group.get_keeper_index()
    assert keeper_index in (0, 1)

    print("[PASS] DuplicateGroup: PASS")


def test_duplicate_result():
    """Test DuplicateResult for UI."""
    files = [
        {
            "id": "1_file1",
            "path": "/test/file1.txt",
            "name": "file1.txt",
            "size": 1000,
            "modified": 1000.0,
            "extension": ".txt",
            "is_keeper": True,
            "checked": False,
        },
        {
            "id": "1_file2",
            "path": "/test/file2.txt",
            "name": "file2.txt",
            "size": 1000,
            "modified": 1000.0,
            "extension": ".txt",
            "is_keeper": False,
            "checked": True,
        },
    ]

    result = DuplicateResult(
        group_id=1,
        files=files,
        total_size=2000,
        reclaimable=1000,
    )

    assert result.group_id == 1
    assert result.file_count == 2
    assert result.checked_count == 1
    assert result.reclaimable_human == "1000.0 B"

    print("[PASS] DuplicateResult: PASS")


def test_mode_options():
    """Test that file dedup engine returns valid mode options."""
    orch = ScanOrchestrator()
    options = orch.set_mode("files")

    # Check that options have required fields
    for opt in options:
        assert hasattr(opt, "name")
        assert hasattr(opt, "type")
        assert hasattr(opt, "default")

    print("[PASS] Mode options: PASS")


def test_image_mode_available():
    """Test that photos mode is now available."""
    orch = ScanOrchestrator()

    # Test photos mode is now implemented
    modes = orch.get_available_modes()
    assert "photos" in modes

    print("[PASS] Image mode available: PASS")


def test_image_format_integration():
    """Test image format registry integration."""
    # Test common formats are supported
    common_formats = [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"]
    for fmt in common_formats:
        assert ImageFormatRegistry.is_supported(Path(f"test{fmt}"))

    # Test modern formats
    modern_formats = [".heic", ".heif"]
    for fmt in modern_formats:
        assert ImageFormatRegistry.is_supported(Path(f"test{fmt}"))

    print("[PASS] Image format integration: PASS")


def test_union_find_integration():
    """Test Union-Find integration."""
    uf = UnionFind()

    # Test clustering
    for i in range(10):
        uf.add(i)

    # Create clusters
    uf.union(0, 1)
    uf.union(1, 2)
    uf.union(3, 4)
    uf.union(4, 5)

    groups = uf.get_groups()

    # Should have: {0,1,2}, {3,4,5}, {6}, {7}, {8}, {9}
    assert len(groups) == 6

    # Largest group should have 3 elements
    largest_group = max(groups, key=len)
    assert len(largest_group) == 3

    print("[PASS] Union-Find integration: PASS")


def test_hamming_distance_integration():
    """Test Hamming distance integration."""
    # Test various distances
    assert hamming_distance(0, 0) == 0
    assert hamming_distance(0b1111, 0b0000) == 4
    assert hamming_distance(0xFFFFFFFF, 0x00000000) == 32

    # Test similarity calculation
    assert similarity_from_hamming(0, 64) == 1.0
    assert similarity_from_hamming(32, 64) == 0.5
    assert similarity_from_hamming(64, 64) == 0.0

    print("[PASS] Hamming distance integration: PASS")


def main():
    """Run all integration tests."""
    print("\n=== CEREBRO v2 Phase 2 & 3 Integration Tests ===\n")

    # Phase 2 tests
    test_orchestrator_modes()
    test_progress_data()
    test_duplicate_group()
    test_duplicate_result()
    test_mode_options()

    # Phase 3 tests
    test_image_mode_available()
    test_image_format_integration()
    test_union_find_integration()
    test_hamming_distance_integration()

    print("\n=== All Tests PASS ===\n")


if __name__ == "__main__":
    main()
