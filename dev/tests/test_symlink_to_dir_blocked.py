"""
test_symlink_to_dir_blocked.py — should_block_delete() on a symlink-to-directory.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from cerebro.core.fs_policy import HardlinkPolicy, should_block_delete


@pytest.mark.skipif(os.name == "nt", reason="Requires unprivileged symlink support")
def test_symlink_to_dir_blocked_by_default(tmp_path):
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    link = tmp_path / "link_to_dir"
    link.symlink_to(real_dir)

    reason = should_block_delete(
        link,
        hardlink_policy=HardlinkPolicy(allow_hardlink_deletes=False),
        allow_directory_delete=False,
    )
    # symlink-to-dir: is_dir(follow_symlinks=True) is True, but at this point
    # we hit the "is_directory" path because allow_directory_delete=False.
    # This confirms the file engine never accidentally deletes symlink-to-dir targets.
    assert reason == "is_directory"
