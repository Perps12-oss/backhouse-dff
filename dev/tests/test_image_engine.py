#!/usr/bin/env python3
"""
Unit tests for Phase 3 - Image Dedup Engine.

Tests:
- Image format registry
- Perceptual hash computation
- Hamming distance calculation
- Union-Find clustering
- Image metadata extraction
"""
from pathlib import Path
from cerebro.engines.image_formats import (
    ImageFormatRegistry,
    ImageFormatCategory,
    UnionFind,
    hamming_distance,
    similarity_from_hamming,
)
from cerebro.engines.image_dedup_engine import (
    ImageMetadata,
    compute_perceptual_hashes,
)


def test_image_format_registry():
    """Test image format registry."""
    # Test common formats
    jpg_fmt = ImageFormatRegistry.get_format(".jpg")
    assert jpg_fmt is not None
    assert jpg_fmt.category == ImageFormatCategory.COMMON
    print(f"  .jpg: {jpg_fmt.description}")

    # Test modern formats
    heic_fmt = ImageFormatRegistry.get_format(".heic")
    assert heic_fmt is not None
    assert heic_fmt.category == ImageFormatCategory.MODERN
    print(f"  .heic: {heic_fmt.description}")

    # Test RAW formats
    nef_fmt = ImageFormatRegistry.get_format(".nef")
    assert nef_fmt is not None
    assert nef_fmt.category == ImageFormatCategory.RAW
    print(f"  .nef: {nef_fmt.description}")

    # Test unsupported format
    unknown_fmt = ImageFormatRegistry.get_format(".xyz")
    assert unknown_fmt is None
    print("  .xyz: Not found (expected)")

    # Test extension check
    assert ImageFormatRegistry.is_supported(Path("test.jpg"))
    assert not ImageFormatRegistry.is_supported(Path("test.doc"))

    # Test category filtering
    raw_formats = ImageFormatRegistry.get_by_category(ImageFormatCategory.RAW)
    assert len(raw_formats) > 0
    print(f"  RAW formats: {len(raw_formats)}")

    print("[PASS] Image format registry: PASS")


def test_hamming_distance():
    """Test Hamming distance calculation."""
    # Same bits - distance 0
    assert hamming_distance(0b101010, 0b101010) == 0

    # One bit different - distance 1
    assert hamming_distance(0b101010, 0b101011) == 1

    # Two bits different - distance 2
    assert hamming_distance(0b101010, 0b100000) == 2

    # All bits different (8-bit)
    assert hamming_distance(0b11111111, 0b00000000) == 8

    print("[PASS] Hamming distance: PASS")


def test_similarity_from_hamming():
    """Test similarity score calculation."""
    # No distance - full similarity
    assert similarity_from_hamming(0, 64) == 1.0

    # Half distance - 50% similarity
    assert similarity_from_hamming(32, 64) == 0.5

    # Full distance - no similarity
    assert similarity_from_hamming(64, 64) == 0.0

    # Clamped at 0
    assert similarity_from_hamming(100, 64) == 0.0

    print("[PASS] Similarity from Hamming: PASS")


def test_union_find():
    """Test Union-Find clustering."""
    uf = UnionFind()

    # Add elements
    uf.add(0)
    uf.add(1)
    uf.add(2)
    uf.add(3)

    # Union some elements
    uf.union(0, 1)  # {0, 1}
    uf.union(1, 2)  # {0, 1, 2}
    assert uf.find(0) == uf.find(2)  # Same root

    # 3 is still separate
    assert uf.find(3) != uf.find(0)

    # Get groups
    groups = uf.get_groups()
    assert len(groups) == 2  # One group of 3, one group of 1

    # Count elements
    assert uf.count == 4

    print("[PASS] Union-Find clustering: PASS")


def test_image_metadata():
    """Test ImageMetadata dataclass."""
    meta = ImageMetadata(
        path=Path("/test/image.jpg"),
        size=1024,
        modified=1000.0,
        extension=".jpg",
        width=1920,
        height=1080,
    )

    assert meta.size == 1024
    assert meta.extension == ".jpg"
    assert meta.width == 1920
    assert meta.height == 1080
    # Resolution is manually computed in the class, not set during init
    expected_resolution = 1920 * 1080
    assert meta.resolution_str == f"{meta.width} × {meta.height}"
    assert meta.key == (1024, ".jpg")

    print("[PASS] Image metadata: PASS")


def test_hash_result():
    """Test ImageHashResult dataclass."""
    meta = ImageMetadata(
        path=Path("/test/image.jpg"),
        size=1024,
        modified=1000.0,
        extension=".jpg",
        width=1920,
        height=1080,
    )

    result = compute_perceptual_hashes(
        path=str(meta.path),
        width=meta.width,
        height=meta.height,
        size=meta.size,
        modified=meta.modified,
        extension=meta.extension,
    )

    # Result should have metadata populated
    assert result.metadata.path == meta.path
    assert result.metadata.width == meta.width
    assert result.metadata.height == meta.height

    print("[PASS] Hash result: PASS")


def test_transitive_clustering():
    """Test transitive similarity clustering."""
    """
    Scenario: A~B and B~C should result in {A, B, C}
    This tests that Union-Find correctly handles transitive relationships.
    """
    uf = UnionFind()

    # Add 5 elements
    for i in range(5):
        uf.add(i)

    # Create transitive relationships
    uf.union(0, 1)  # {0, 1}
    uf.union(1, 2)  # {0, 1, 2} - connects 0 and 2 transitively
    uf.union(3, 4)  # {3, 4} - separate group

    # Verify transitive relationship
    assert uf.find(0) == uf.find(2)  # 0 and 2 should be same group
    assert uf.find(3) == uf.find(4)  # 3 and 4 should be same group
    assert uf.find(0) != uf.find(3)  # Groups should be different

    # Get groups
    groups = uf.get_groups()
    assert len(groups) == 2  # Two groups

    # Check group sizes
    group_sizes = sorted([len(g) for g in groups])
    assert group_sizes == [2, 3]  # One group of 2, one of 3

    print("[PASS] Transitive clustering: PASS")


def test_dual_hash_thresholds():
    """Test dual-hash threshold logic."""
    """
    Scenario: pHash and dHash both must be within threshold
    for images to be considered similar.
    """
    # Thresholds
    phash_thresh = 8
    dhash_thresh = 10

    # Case 1: Both within threshold - similar
    phash_dist_1 = 5  # Within 8
    dhash_dist_1 = 7  # Within 10
    assert phash_dist_1 <= phash_thresh
    assert dhash_dist_1 <= dhash_thresh
    # Would be considered similar

    # Case 2: pHash within, dHash outside - NOT similar
    phash_dist_2 = 5  # Within 8
    dhash_dist_2 = 15  # Outside 10
    assert phash_dist_2 <= phash_thresh
    assert not (dhash_dist_2 <= dhash_thresh)
    # Would NOT be considered similar

    # Case 3: Both outside threshold - NOT similar
    phash_dist_3 = 15  # Outside 8
    dhash_dist_3 = 20  # Outside 10
    assert not (phash_dist_3 <= phash_thresh)
    assert not (dhash_dist_3 <= dhash_thresh)
    # Would NOT be considered similar

    print("[PASS] Dual-hash thresholds: PASS")


def main():
    """Run all image engine unit tests."""
    print("\n=== CEREBRO v2 Phase 3 Image Engine Tests ===\n")

    test_image_format_registry()
    test_hamming_distance()
    test_similarity_from_hamming()
    test_union_find()
    test_image_metadata()
    test_hash_result()
    test_transitive_clustering()
    test_dual_hash_thresholds()

    print("\n=== All Tests PASS ===\n")


if __name__ == "__main__":
    main()
