"""
test_cli_restore_trash.py — M-2: cerebro restore-trash command restores from manifest.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest


def test_restore_trash_basic(tmp_path, monkeypatch):
    """restore-trash moves a file back to its original path."""
    original = tmp_path / "original.txt"
    dest = tmp_path / "trash" / "original.txt"
    dest.parent.mkdir(parents=True)
    dest.write_text("data")

    manifest = tmp_path / "manifest.jsonl"
    entry = {
        "id": "abc123",
        "original_path": str(original),
        "dest_path": str(dest),
        "timestamp": time.time(),
        "size": 4,
    }
    manifest.write_text(json.dumps(entry) + "\n", encoding="utf-8")

    import cerebro.core.deletion as mod
    import cerebro.cli as cli_mod

    # Patch the manifest path in cli.
    original_func = cli_mod._cmd_restore_trash

    import argparse

    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))

    # The CLI reads from Path.home() / ".cerebro" / "trash" / "manifest.jsonl".
    # Replicate the manifest there.
    cerebro_trash = tmp_path / ".cerebro" / "trash"
    cerebro_trash.mkdir(parents=True)
    (cerebro_trash / "manifest.jsonl").write_text(json.dumps(entry) + "\n", encoding="utf-8")

    args = argparse.Namespace(id=None, all_since=None)
    rc = cli_mod._cmd_restore_trash(args)

    assert original.exists(), "File should be restored to original path"
    assert rc == 0


def test_restore_trash_conflict_renames(tmp_path, monkeypatch):
    """If original path already exists, restore to a timestamped name."""
    original = tmp_path / "original.txt"
    original.write_text("existing")
    dest = tmp_path / "trash" / "original.txt"
    dest.parent.mkdir(parents=True)
    dest.write_text("from trash")

    cerebro_trash = tmp_path / ".cerebro" / "trash"
    cerebro_trash.mkdir(parents=True)
    ts = int(time.time())
    entry = {
        "id": "xyz",
        "original_path": str(original),
        "dest_path": str(dest),
        "timestamp": float(ts),
        "size": 9,
    }
    (cerebro_trash / "manifest.jsonl").write_text(json.dumps(entry) + "\n", encoding="utf-8")

    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))

    import argparse
    import cerebro.cli as cli_mod

    rc = cli_mod._cmd_restore_trash(argparse.Namespace(id=None, all_since=None))
    restored = tmp_path / f"original.restored_{ts}.txt"
    assert restored.exists(), f"Expected conflict file at {restored}"
    assert original.read_text() == "existing", "Existing file must not be overwritten"
