"""
test_directory_deletion_flag.py — C-3: directory deletion requires allow_directory_delete=True.
EmptyFolderEngine and SimilarFolderEngine results (directories) must be deletable when the flag is set.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

import shutil

from cerebro.core.deletion import (
    DeletionEngine,
    DeletionPolicy,
    DeletionRequest,
    DirectoryDeletionAdapter,
    TrashDeletionAdapter,
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


def test_directory_adapter_trash_delegates_to_trash_adapter(tmp_path, monkeypatch):
    """TRASH policy must not call shutil.rmtree; it uses TrashDeletionAdapter."""
    d = tmp_path / "dir_trash"
    d.mkdir()
    rmtree_calls: list[object] = []
    delegated: list[tuple[Path, DeletionPolicy]] = []

    monkeypatch.setattr(shutil, "rmtree", lambda *a, **k: rmtree_calls.append(a))

    def _fake_trash_delete(self, path, request):
        delegated.append((path, request.policy))
        from cerebro.core.deletion import SingleDeletionResult

        return SingleDeletionResult(success=True, path=path, policy=request.policy)

    monkeypatch.setattr(TrashDeletionAdapter, "delete", _fake_trash_delete)

    adapter = DirectoryDeletionAdapter()
    req = DeletionRequest(policy=DeletionPolicy.TRASH, allow_directory_delete=True)
    result = adapter.delete(d, req)

    assert result.success is True
    assert delegated == [(d, DeletionPolicy.TRASH)]
    assert rmtree_calls == []
    assert d.exists()
