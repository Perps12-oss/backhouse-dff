"""
test_large_file_reclaimable.py — L-1: LargeFileEngine reclaimable survives snapshot round-trip.
"""
from __future__ import annotations

import json
from pathlib import Path


def test_reclaimable_set_at_construction(tmp_path):
    from cerebro.engines.large_file_engine import LargeFileEngine
    from cerebro.engines.base_engine import ScanState

    f = tmp_path / "bigfile.bin"
    f.write_bytes(b"x" * 4096)

    engine = LargeFileEngine()
    engine.configure(folders=[tmp_path], protected=[], options={"min_size_mb": 0})
    engine.start(lambda p: None)
    if engine._scan_thread:
        engine._scan_thread.join(timeout=15)

    results = engine.get_results()
    assert results, "No results returned"

    for grp in results:
        if str(f) in [str(fi.path) for fi in grp.files]:
            assert grp.reclaimable == f.stat().st_size, (
                f"reclaimable={grp.reclaimable} but file size={f.stat().st_size}"
            )
            return

    pytest.fail(f"File {f} not found in results")


def test_reclaimable_survives_json_roundtrip(tmp_path):
    """reclaimable must not drop to 0 after __post_init__ is called on deserialization."""
    from cerebro.engines.base_engine import DuplicateGroup, DuplicateFile

    f = DuplicateFile(path=Path("/fake/large.mov"), size=100_000_000, modified=0.0, extension=".mov")
    grp = DuplicateGroup(group_id=0, files=[f], reclaimable=100_000_000)

    # Simulate snapshot serialise → deserialise.
    data = {"group_id": grp.group_id, "files": [{"path": str(f.path), "size": f.size}],
            "reclaimable": grp.reclaimable, "similarity_type": grp.similarity_type}
    restored = DuplicateGroup(
        group_id=data["group_id"],
        files=[DuplicateFile(path=Path(fi["path"]), size=fi["size"], modified=0.0, extension="")
               for fi in data["files"]],
        reclaimable=data["reclaimable"],
    )
    assert restored.reclaimable == 100_000_000
