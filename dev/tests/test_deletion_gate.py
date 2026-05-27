"""
test_deletion_gate.py — C-1: Gate security: hex token rejected; proper token consumed once.
"""
from __future__ import annotations

import threading
import time

import pytest

from cerebro.core.safety.deletion_gate import DeletionGate, DeletionGateConfig, DeletionGateError


def test_default_config_disallows_uuid_hex():
    """32-hex UUID strings must NOT be accepted by default (allow_plan_uuid_token=False)."""
    gate = DeletionGate()
    assert not gate.verify_token("a" * 32), "UUID hex must be rejected by default"


def test_issue_and_verify():
    gate = DeletionGate()
    token = gate.issue_token(reason="test")
    assert gate.verify_token(token), "Issued token should verify"


def test_assert_allowed_consumes_token():
    """Token must be consumed (one-time) after assert_allowed()."""
    gate = DeletionGate()
    token = gate.issue_token()
    gate.assert_allowed(validation_mode=True, token=token)
    # Second call must fail.
    with pytest.raises(DeletionGateError):
        gate.assert_allowed(validation_mode=True, token=token)


def test_assert_allowed_missing_token_raises():
    gate = DeletionGate()
    with pytest.raises(DeletionGateError):
        gate.assert_allowed(validation_mode=True, token=None)


def test_expired_token_rejected():
    cfg = DeletionGateConfig(token_ttl_seconds=1)
    gate = DeletionGate(cfg)
    token = gate.issue_token()
    time.sleep(1.2)
    assert not gate.verify_token(token), "Expired token must be rejected"


def test_concurrent_token_issue():
    """Concurrent token issuance must not corrupt gate state."""
    gate = DeletionGate()
    tokens = {}
    errors = []

    def _issue(thread_id):
        try:
            tokens[thread_id] = gate.issue_token(reason=f"t{thread_id}")
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=_issue, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Concurrent issue errors: {errors}"
    # At least one token was issued.
    assert len(tokens) == 20


def test_allow_plan_uuid_token_false_by_default():
    gate = DeletionGate()
    assert not gate.config.allow_plan_uuid_token


def test_allow_plan_uuid_token_true_accepts_hex():
    cfg = DeletionGateConfig(allow_plan_uuid_token=True)
    gate = DeletionGate(cfg)
    assert gate.verify_token("a" * 32)
