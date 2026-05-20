"""
test_platform_hardlink_threshold.py — H-7: platform_hardlink_threshold() and
should_block_delete() nlink threshold behaviour.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from cerebro.core.safety.deletion_gate import DeletionGateConfig, platform_hardlink_threshold
from cerebro.core.fs_policy import HardlinkPolicy, should_block_delete


def test_default_threshold_windows():
    """On Windows the default threshold must be 3 (NTFS guard)."""
    config = DeletionGateConfig()
    with patch.object(sys, "platform", "win32"):
        import importlib
        import cerebro.core.safety.deletion_gate as _mod
        with patch.object(_mod.sys, "platform", "win32"):
            assert platform_hardlink_threshold(config) == 3


def test_default_threshold_linux():
    config = DeletionGateConfig()
    with patch.object(sys, "platform", "linux"):
        import cerebro.core.safety.deletion_gate as _mod
        with patch.object(_mod.sys, "platform", "linux"):
            assert platform_hardlink_threshold(config) == 1


def test_explicit_threshold_overrides_platform():
    """hardlink_nlink_threshold != 1 is always used as-is, regardless of platform."""
    config = DeletionGateConfig(hardlink_nlink_threshold=2)
    assert platform_hardlink_threshold(config) == 2


def test_should_block_with_high_threshold_allows_ntfs_file(tmp_path):
    """With threshold=3, a file with st_nlink=2 should NOT be blocked (NTFS system link)."""
    f = tmp_path / "regular.txt"
    f.write_text("data")

    # Simulate st_nlink = 2 (common NTFS metadata link scenario).
    class _FakeStat:
        st_nlink = 2
        st_size = 4
        st_dev = 0
        st_ino = 0

    # fs_policy uses lstat (follow_symlinks=False default).
    with patch.object(Path, "lstat", return_value=_FakeStat()):
        reason = should_block_delete(
            f,
            hardlink_policy=HardlinkPolicy(allow_hardlink_deletes=False),
            hardlink_nlink_threshold=3,
        )
    # Should not be blocked with threshold=3 because 2 <= 3.
    assert reason is None, f"Expected no block, got: {reason}"


def test_should_block_with_low_threshold_blocks_hardlink(tmp_path):
    f = tmp_path / "hardlinked.txt"
    f.write_text("data")

    class _FakeStat:
        st_nlink = 2
        st_size = 4
        st_dev = 0
        st_ino = 0

    # fs_policy uses lstat (follow_symlinks=False default).
    with patch.object(Path, "lstat", return_value=_FakeStat()):
        reason = should_block_delete(
            f,
            hardlink_policy=HardlinkPolicy(allow_hardlink_deletes=False),
            hardlink_nlink_threshold=1,
        )
    assert reason is not None
    assert "hardlink_protected" in reason
