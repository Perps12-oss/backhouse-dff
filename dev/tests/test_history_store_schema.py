"""
test_history_store_schema.py — H-3: from_dict forward + backward compat.
"""
from __future__ import annotations

import pytest

from cerebro.history.store import DeletionAuditRecord


def _base_dict() -> dict:
    return {
        "scan_id": "s1",
        "timestamp": 1234567890.0,
        "mode": "trash",
        "groups": 2,
        "deleted": 5,
        "failed": 0,
        "bytes_reclaimed": 1024,
        "source": "review_page",
        "policy": {"mode": "trash"},
        "details": [],
        "schema_version": 1,
    }


def test_from_dict_valid():
    rec = DeletionAuditRecord.from_dict(_base_dict())
    assert rec is not None
    assert rec.scan_id == "s1"


def test_from_dict_extra_fields_ignored():
    """Forward compat: unknown fields in future schema versions are ignored."""
    d = _base_dict()
    d["future_field_xyz"] = "value"
    rec = DeletionAuditRecord.from_dict(d)
    assert rec is not None, "Extra fields must not crash from_dict"


def test_from_dict_missing_required_field_returns_none():
    """Backward compat: records missing required fields return None instead of crashing."""
    d = _base_dict()
    del d["scan_id"]
    rec = DeletionAuditRecord.from_dict(d)
    assert rec is None, "Missing required field must return None, not raise"


def test_from_dict_schema_version_stripped():
    """schema_version must not be passed to the dataclass constructor."""
    d = _base_dict()
    rec = DeletionAuditRecord.from_dict(d)
    assert not hasattr(rec, "schema_version"), "schema_version must not be on the dataclass"


def test_to_dict_roundtrip():
    rec = DeletionAuditRecord.from_dict(_base_dict())
    assert rec is not None
    d2 = rec.to_dict()
    rec2 = DeletionAuditRecord.from_dict(d2)
    assert rec2 is not None
    assert rec2.scan_id == rec.scan_id
