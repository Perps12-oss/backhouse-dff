"""
test_deletion_toctou.py — M-3: TOCTOU-safe permanent deletion error handling.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from cerebro.core.deletion import PermanentDeletionAdapter, DeletionRequest, DeletionPolicy


def test_permanent_delete_handles_is_directory_error(tmp_path):
    """os.remove raising IsADirectoryError must fall back to shutil.rmtree."""
    import os, shutil
    d = tmp_path / "mydir"
    d.mkdir()

    adapter = PermanentDeletionAdapter()
    request = DeletionRequest(policy=DeletionPolicy.PERMANENT)

    # We need to bypass the should_block_delete in DeletionEngine; call adapter directly.
    # The adapter's delete() calls os.remove first, then catches IsADirectoryError.
    # Since we pass a directory, os.remove should raise IsADirectoryError on non-Windows.
    import sys
    if sys.platform == "win32":
        pytest.skip("Windows raises PermissionError for directories, not IsADirectoryError")

    result = adapter.delete(d, request)
    assert result.success
    assert not d.exists()


def test_permanent_delete_regular_file(tmp_path):
    """Regular files are deleted via os.remove."""
    f = tmp_path / "file.txt"
    f.write_text("hello")

    adapter = PermanentDeletionAdapter()
    request = DeletionRequest(policy=DeletionPolicy.PERMANENT)
    result = adapter.delete(f, request)
    assert result.success
    assert not f.exists()
