import time

import pytest

from cerebro.core.safety.deletion_gate import DeletionGate, DeletionGateConfig, DeletionGateError


def test_issue_token_is_secure_and_verifiable():
    gate = DeletionGate(DeletionGateConfig(require_token=True))

    tok1 = gate.issue_token("test")
    tok2 = gate.issue_token("test2")

    assert isinstance(tok1, str) and tok1
    assert isinstance(tok2, str) and tok2
    assert tok1 != tok2
    assert len(tok1) >= 16

    # Latest issued token should verify
    assert gate.verify_token(tok2) is True
    assert gate.verify_token("not-a-token") is False


def test_verify_token_accepts_uuid_hex_when_configured():
    gate = DeletionGate(DeletionGateConfig(allow_plan_uuid_token=True))

    # No internal token issued; should accept pipeline plan.token (uuid hex)
    assert gate.verify_token("0123456789abcdef0123456789abcdef") is True
    assert gate.verify_token("0123456789abcdef0123456789abcde") is False


def test_assert_allowed_consumes_internal_token():
    gate = DeletionGate(DeletionGateConfig(require_token=True))
    tok = gate.issue_token("one-shot")

    gate.assert_allowed(validation_mode=True, token=tok)

    with pytest.raises(DeletionGateError):
        gate.assert_allowed(validation_mode=True, token=tok)


def test_verify_token_expires():
    gate = DeletionGate(DeletionGateConfig(require_token=True, token_ttl_seconds=900))
    tok = gate.issue_token("expiry")

    # Force expiry without sleeping
    gate._token_expires_at = time.time() - 1  # noqa: SLF001 (test)
    assert gate.verify_token(tok) is False
