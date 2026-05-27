"""Regression tests for the same-volume / read-only managed-trash fix.

The field bug: deleting a read-only file on an external drive failed with
``[WinError 5] Access is denied`` because a cross-volume ``shutil.move`` copies
then ``unlink``s the source, and unlink of a read-only file is denied on Windows.
The fix keeps the trash on the source volume (atomic rename) and, as a fallback,
clears the read-only attribute and retries once.
"""
from __future__ import annotations

import os
import stat

import pytest

import cerebro.v2.ui.flet_app.services.delete_service as ds_mod
from cerebro.v2.ui.flet_app.services.delete_service import DeleteService
from cerebro.core.deletion import DeletionPolicy


def test_delete_readonly_file_succeeds(tmp_path):
    """A read-only file must be trashable (the WinError 5 field case)."""
    f = tmp_path / "readonly.jpg"
    f.write_text("data")
    os.chmod(f, stat.S_IREAD)
    try:
        svc = DeleteService()
        result = svc.delete_files([str(f)], DeletionPolicy.TRASH)
        assert result.deleted_count == 1, result.failures
        assert not f.exists()
    finally:
        if f.exists():  # ensure tmp cleanup can remove it if the test failed
            os.chmod(f, stat.S_IWRITE)


def test_move_with_readonly_retry_clears_attribute(tmp_path, monkeypatch):
    """On Windows, a PermissionError move retries after clearing read-only."""
    src = tmp_path / "ro.jpg"
    src.write_text("x")
    dst = tmp_path / "trash" / "ro.jpg"
    dst.parent.mkdir(parents=True)

    calls = {"move": 0, "chmod": []}

    def fake_move(s, d):
        calls["move"] += 1
        if calls["move"] == 1:
            raise PermissionError("[WinError 5] Access is denied")
        os.replace(s, d)  # real move, not via the patched shutil.move

    monkeypatch.setattr(ds_mod.sys, "platform", "win32")
    monkeypatch.setattr(ds_mod.shutil, "move", fake_move)
    monkeypatch.setattr(ds_mod.os, "chmod", lambda p, mode: calls["chmod"].append((str(p), mode)))

    DeleteService._move_with_readonly_retry(src, dst)

    assert calls["move"] == 2, "must retry exactly once after clearing the attribute"
    assert calls["chmod"] and calls["chmod"][0][1] == stat.S_IWRITE
    assert dst.exists() and not src.exists()


def test_move_with_readonly_retry_no_chmod_on_posix(tmp_path, monkeypatch):
    """On POSIX the read-only clear is destructive, so it must re-raise instead."""
    src = tmp_path / "ro.txt"
    src.write_text("x")
    dst = tmp_path / "dst.txt"

    chmod_calls = []
    monkeypatch.setattr(ds_mod.sys, "platform", "linux")
    monkeypatch.setattr(ds_mod.shutil, "move", lambda s, d: (_ for _ in ()).throw(PermissionError("denied")))
    monkeypatch.setattr(ds_mod.os, "chmod", lambda p, mode: chmod_calls.append(p))

    with pytest.raises(PermissionError):
        DeleteService._move_with_readonly_retry(src, dst)
    assert chmod_calls == [], "must not strip POSIX write bits"


def test_same_volume_uses_home_trash(tmp_path):
    """When src shares the home volume, trash stays under the home managed dir
    (no per-drive scattering)."""
    from pathlib import Path

    f = tmp_path / "f.txt"
    f.write_text("x")
    svc = DeleteService()
    root = svc._managed_trash_root_for(f, "txid123")
    home_managed = Path.home() / ".cerebro" / "trash" / "managed"
    # tmp_path is normally on the same volume as home in CI/dev.
    if f.stat().st_dev == Path.home().stat().st_dev:
        assert str(root).startswith(str(home_managed))
