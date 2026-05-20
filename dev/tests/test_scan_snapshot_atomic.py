"""
test_scan_snapshot_atomic.py — M-7: Snapshot writes are atomic (mkstemp + os.replace).
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from cerebro.v2.persistence.scan_snapshot import _atomic_write_text, save_scan_results_snapshot


def test_atomic_write_text_success(tmp_path):
    dest = tmp_path / "out.json"
    _atomic_write_text(dest, '{"ok": true}')
    assert dest.read_text(encoding="utf-8") == '{"ok": true}'


def test_atomic_write_text_no_partial_file_on_error(tmp_path):
    """On error during write, no partial file should remain at destination."""
    dest = tmp_path / "out.json"

    import os as _os
    original_fsync = _os.fsync

    def _bad_fsync(fd):
        raise OSError("simulated disk error")

    with patch.object(_os, "fsync", side_effect=_bad_fsync):
        with pytest.raises(OSError):
            _atomic_write_text(dest, '{"bad": true}')

    assert not dest.exists(), "Destination must not exist after failed atomic write"


def test_save_scan_results_snapshot_atomic(tmp_path, monkeypatch):
    """save_scan_results_snapshot uses atomic writes (no .write_text calls)."""
    import cerebro.v2.persistence.scan_snapshot as mod

    written = []
    original = mod._atomic_write_text

    def _recording_write(path, data):
        written.append(str(path))
        original(path, data)

    monkeypatch.setattr(mod, "_atomic_write_text", _recording_write)
    monkeypatch.setattr(mod, "_snap_dir", lambda: tmp_path)

    from cerebro.engines.base_engine import DuplicateFile, DuplicateGroup
    f = DuplicateFile(path=tmp_path / "a.txt", size=100, modified=0.0, extension=".txt")
    g = DuplicateGroup(group_id=1, files=[f])

    save_scan_results_snapshot([g], "files", 1234567890.0)
    assert any("last.json" in w for w in written), "last.json must be written atomically"
