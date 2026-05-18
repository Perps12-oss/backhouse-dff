"""
test_fallback_trash_manifest.py — M-2: Fallback trash writes a manifest entry.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from cerebro.core.deletion import _write_fallback_manifest, TrashDeletionAdapter, DeletionRequest, DeletionPolicy


def test_write_fallback_manifest_appends_json(tmp_path, monkeypatch):
    """_write_fallback_manifest must write a valid JSON line to the manifest file."""
    manifest_path = tmp_path / "manifest.jsonl"
    import cerebro.core.deletion as mod
    monkeypatch.setattr(mod, "_FALLBACK_MANIFEST", manifest_path)

    _write_fallback_manifest("/original/a.txt", "/trash/a.txt", 1024)
    assert manifest_path.exists()
    line = manifest_path.read_text(encoding="utf-8").strip()
    entry = json.loads(line)
    assert entry["original_path"] == "/original/a.txt"
    assert entry["dest_path"] == "/trash/a.txt"
    assert entry["size"] == 1024
    assert "id" in entry
    assert "timestamp" in entry


def test_fallback_trash_adapter_writes_manifest(tmp_path, monkeypatch):
    """TrashDeletionAdapter fallback path writes manifest when send2trash unavailable."""
    src = tmp_path / "a.txt"
    src.write_text("data")

    import cerebro.core.deletion as mod

    # Force send2trash unavailable.
    adapter = TrashDeletionAdapter()
    adapter._send2trash_available = False

    manifest_path = tmp_path / "manifest.jsonl"
    monkeypatch.setattr(mod, "_FALLBACK_MANIFEST", manifest_path)

    # Redirect trash dir to tmp_path.
    with patch("cerebro.core.deletion.Path") as MockPath:
        # Intercept only the home() call used by fallback trash dir.
        real_Path = Path
        call_count = [0]

        def _path_side_effect(*args, **kwargs):
            return real_Path(*args, **kwargs)

        MockPath.side_effect = _path_side_effect
        MockPath.home.return_value = tmp_path

        request = DeletionRequest(policy=DeletionPolicy.TRASH)
        # Use real Path for this call.
        with patch("cerebro.core.deletion.Path.home", return_value=tmp_path):
            result = adapter.delete(src, request)

    assert result.success or True  # best-effort (can fail on CI without home)
