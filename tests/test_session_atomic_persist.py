"""
test_session_atomic_persist.py — L-3: Session persistence uses atomic write.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest


def _has_session_manager():
    try:
        from cerebro.core.session import SessionManager  # noqa: F401
        return True
    except (ImportError, AttributeError):
        return False


@pytest.mark.skipif(not _has_session_manager(), reason="SessionManager not available")
def test_persist_uses_atomic_write(tmp_path, monkeypatch):
    """_persist_record must use a temp file + os.replace, not open(..., 'w') directly."""
    from cerebro.core.session import SessionManager

    replaces = []
    original_replace = os.replace

    def _tracking_replace(src, dst):
        replaces.append((src, dst))
        return original_replace(src, dst)

    monkeypatch.setattr(os, "replace", _tracking_replace)

    mgr = SessionManager.__new__(SessionManager)
    mgr._persist_path = tmp_path

    # Build a minimal ScanRecord stub.
    import types
    from cerebro.engines.base_engine import ScanState
    record = types.SimpleNamespace(
        scan_id="test_scan",
        to_dict=lambda: {"scan_id": "test_scan", "version": 1},
    )
    mgr._persist_record(record)

    assert any(str(record.scan_id) in str(dst) for _, dst in replaces), \
        "Atomic os.replace must be called with the target scan file path"

    written = (tmp_path / "test_scan.json").read_text(encoding="utf-8")
    assert "test_scan" in written
