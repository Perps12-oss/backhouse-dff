"""
test_permanent_deletion_no_rmtree.py — C-1: PermanentDeletionAdapter never escalates to shutil.rmtree.
If a path is substituted with a directory between calls, it returns an error instead of wiping the tree.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from cerebro.core.deletion import DeletionPolicy, DeletionRequest, PermanentDeletionAdapter


def test_permanent_adapter_deletes_file(tmp_path):
    f = tmp_path / "target.txt"
    f.write_text("data")

    adapter = PermanentDeletionAdapter()
    req = DeletionRequest(policy=DeletionPolicy.PERMANENT)
    result = adapter.delete(f, req)

    assert result.success is True
    assert not f.exists()


def test_permanent_adapter_rejects_directory(tmp_path):
    """C-1: directory path must fail with an error, never wipe via shutil.rmtree."""
    d = tmp_path / "mydir"
    d.mkdir()
    (d / "important.txt").write_text("keep me")

    adapter = PermanentDeletionAdapter()
    req = DeletionRequest(policy=DeletionPolicy.PERMANENT)
    result = adapter.delete(d, req)

    assert result.success is False
    assert "is_directory" in (result.error or "")
    # Critical: directory and its contents must remain intact.
    assert d.exists()
    assert (d / "important.txt").exists()


def test_permanent_adapter_missing_file_fails_gracefully(tmp_path):
    f = tmp_path / "gone.txt"
    adapter = PermanentDeletionAdapter()
    req = DeletionRequest(policy=DeletionPolicy.PERMANENT)
    result = adapter.delete(f, req)
    assert result.success is False
