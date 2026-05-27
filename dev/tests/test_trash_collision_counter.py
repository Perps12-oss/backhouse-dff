"""
test_trash_collision_counter.py — H-5: managed-trash collision counter prevents overwrite.
Two files with the same name in the same second must both be preserved.
"""
from __future__ import annotations

from pathlib import Path

from cerebro.core.deletion import DeletionPolicy
from cerebro.v2.ui.flet_app.services.delete_service import DeleteService


def test_two_same_name_files_both_trashed(tmp_path):
    src_a = tmp_path / "src_a" / "photo.jpg"
    src_b = tmp_path / "src_b" / "photo.jpg"
    src_a.parent.mkdir(parents=True)
    src_b.parent.mkdir(parents=True)
    src_a.write_bytes(b"aaa")
    src_b.write_bytes(b"bbb")

    svc = DeleteService()
    result_a = svc.delete_files([str(src_a)], DeletionPolicy.TRASH)
    result_b = svc.delete_files([str(src_b)], DeletionPolicy.TRASH)

    assert result_a.deleted_count == 1
    assert result_b.deleted_count == 1

    # Find the tx_roots used.
    history = svc._trash_history
    assert len(history) >= 2
    destinations = []
    for tx in history:
        for _, dst in tx.moved:
            destinations.append(dst)

    # Both destination paths must exist and be distinct.
    dest_paths = [Path(d) for d in destinations[-2:]]
    assert all(p.exists() for p in dest_paths), "One or both trashed files are missing"
    assert dest_paths[0] != dest_paths[1], "Both files landed on the same destination path — collision!"
