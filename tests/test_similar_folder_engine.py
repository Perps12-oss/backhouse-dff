"""
Tests for SimilarFolderEngine.

Covers:
1. Engine instantiation and get_name()
2. Two identical folders -> 1 group
3. Two completely different folders -> 0 groups
4. Partial overlap (50% same files) -> respects threshold
5. Folders below min_files are skipped
"""

from pathlib import Path


from cerebro.engines.similar_folder_engine import SimilarFolderEngine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_file(path: Path, size: int = 0) -> None:
    """Create a file with `size` zero bytes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x00" * size)


def _run_engine(folders, options=None, protected=None):
    """Configure and run the engine synchronously, return results."""
    engine = SimilarFolderEngine()
    engine.configure(
        folders=[Path(f) for f in folders],
        protected=protected or [],
        options=options or {},
    )
    progress_events = []
    engine.start(lambda p: progress_events.append(p))
    return engine.get_results(), progress_events


# ---------------------------------------------------------------------------
# Test 1: Engine instantiation and get_name
# ---------------------------------------------------------------------------

def test_engine_name():
    """Engine instantiates successfully and returns the expected name."""
    engine = SimilarFolderEngine()
    assert engine.get_name() == "Similar Folders"


# ---------------------------------------------------------------------------
# Test 2: Two identical folders -> 1 group
# ---------------------------------------------------------------------------

def test_identical_folders_produce_one_group(tmp_path):
    """Two folders containing the same filenames and sizes are grouped together."""
    folder_a = tmp_path / "folder_a"
    folder_b = tmp_path / "folder_b"

    # Create identical sets of files (same name, same size)
    for name, size in [("alpha.txt", 100), ("beta.txt", 200), ("gamma.txt", 300)]:
        _make_file(folder_a / name, size)
        _make_file(folder_b / name, size)

    results, _ = _run_engine(
        [tmp_path],
        options={"similarity_threshold": 0.7, "min_files": 3},
    )

    assert len(results) == 1, f"Expected 1 group, got {len(results)}"
    group = results[0]
    assert group.similarity_type == "similar_folder"
    assert len(group.files) == 2

    paths_in_group = {f.path for f in group.files}
    assert folder_a in paths_in_group
    assert folder_b in paths_in_group


# ---------------------------------------------------------------------------
# Test 3: Two completely different folders -> 0 groups
# ---------------------------------------------------------------------------

def test_different_folders_produce_no_groups(tmp_path):
    """Folders with no file overlap do not get grouped."""
    folder_a = tmp_path / "folder_a"
    folder_b = tmp_path / "folder_b"

    for name, size in [("file1.txt", 10), ("file2.txt", 20), ("file3.txt", 30)]:
        _make_file(folder_a / name, size)

    for name, size in [("other1.txt", 11), ("other2.txt", 22), ("other3.txt", 33)]:
        _make_file(folder_b / name, size)

    results, _ = _run_engine(
        [tmp_path],
        options={"similarity_threshold": 0.7, "min_files": 3},
    )

    assert len(results) == 0, f"Expected 0 groups, got {len(results)}"


# ---------------------------------------------------------------------------
# Test 4: Partial overlap respects similarity threshold
# ---------------------------------------------------------------------------

def test_partial_overlap_respects_threshold(tmp_path):
    """Folders sharing 50% of files: grouped at threshold=0.3, not at threshold=0.7."""
    folder_a = tmp_path / "folder_a"
    folder_b = tmp_path / "folder_b"

    # 2 shared + 2 unique each -> Jaccard = 2/(2+2+2) = 2/6 ≈ 0.33
    shared = [("shared1.txt", 100), ("shared2.txt", 200)]
    unique_a = [("only_a1.txt", 300), ("only_a2.txt", 400)]
    unique_b = [("only_b1.txt", 500), ("only_b2.txt", 600)]

    for name, size in shared + unique_a:
        _make_file(folder_a / name, size)
    for name, size in shared + unique_b:
        _make_file(folder_b / name, size)

    # Should NOT group at threshold=0.7 (jaccard ~0.33 < 0.7)
    results_strict, _ = _run_engine(
        [tmp_path],
        options={"similarity_threshold": 0.7, "min_files": 3},
    )
    assert len(results_strict) == 0, (
        f"Expected 0 groups at strict threshold, got {len(results_strict)}"
    )

    # Should group at threshold=0.3 (jaccard ~0.33 >= 0.3)
    results_loose, _ = _run_engine(
        [tmp_path],
        options={"similarity_threshold": 0.3, "min_files": 3},
    )
    assert len(results_loose) == 1, (
        f"Expected 1 group at loose threshold, got {len(results_loose)}"
    )


# ---------------------------------------------------------------------------
# Test 5: Folders below min_files are skipped
# ---------------------------------------------------------------------------

def test_min_files_skips_small_folders(tmp_path):
    """Folders with fewer files than min_files are excluded from comparison."""
    folder_a = tmp_path / "folder_a"
    folder_b = tmp_path / "folder_b"

    # Both folders are identical but each has only 2 files (< min_files=3)
    for name, size in [("x.txt", 50), ("y.txt", 60)]:
        _make_file(folder_a / name, size)
        _make_file(folder_b / name, size)

    results, _ = _run_engine(
        [tmp_path],
        options={"similarity_threshold": 0.5, "min_files": 3},
    )

    assert len(results) == 0, (
        f"Expected 0 groups (folders too small), got {len(results)}"
    )
