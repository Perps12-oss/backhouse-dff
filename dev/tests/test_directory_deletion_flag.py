"""
test_directory_deletion_flag.py — C-3: directory deletion requires allow_directory_delete=True.
EmptyFolderEngine and SimilarFolderEngine results (directories) must be deletable when the flag is set.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from cerebro.core.deletion import (
    DeletionEngine,
    DeletionPolicy,
    DeletionRequest,
    DirectoryDeletionAdapter,
)
from cerebro.core.fs_policy import HardlinkPolicy, should_block_delete


def test_should_block_delete_blocks_directory_by_default(tmp_path):
    d = tmp_path / "emptydir"
    d.mkdir()
    reason = should_block_delete(
        d,
        hardlink_policy=HardlinkPolicy(allow_hardlink_deletes=False),
        allow_directory_delete=False,
    )
    assert reason == "is_directory"


def test_should_block_delete_allows_directory_when_flag_set(tmp_path):
    d = tmp_path / "emptydir"
    d.mkdir()
    reason = should_block_delete(
        d,
        hardlink_policy=HardlinkPolicy(allow_hardlink_deletes=False),
        allow_directory_delete=True,
    )
    assert reason is None


def test_engine_deletes_directory_with_flag(tmp_path):
    d = tmp_path / "todelete"
    d.mkdir()

    engine = DeletionEngine()
    req = DeletionRequest(policy=DeletionPolicy.PERMANENT, allow_directory_delete=True)
    result = engine.delete_one(d, req)

    assert result.success is True
    assert not d.exists()


def test_engine_blocks_directory_without_flag(tmp_path):
    d = tmp_path / "shouldstay"
    d.mkdir()

    engine = DeletionEngine()
    req = DeletionRequest(policy=DeletionPolicy.PERMANENT, allow_directory_delete=False)
    result = engine.delete_one(d, req)

    assert result.success is False
    assert d.exists()


def test_directory_adapter_requires_flag(tmp_path):
    d = tmp_path / "dir"
    d.mkdir()

    adapter = DirectoryDeletionAdapter()
    req_blocked = DeletionRequest(policy=DeletionPolicy.PERMANENT, allow_directory_delete=False)
    result = adapter.delete(d, req_blocked)
    assert result.success is False
    assert d.exists()

    req_allowed = DeletionRequest(policy=DeletionPolicy.PERMANENT, allow_directory_delete=True)
    result = adapter.delete(d, req_allowed)
    assert result.success is True
    assert not d.exists()
