# cerebro/core/safety/deletion_gate.py
from __future__ import annotations

import re
import secrets
import time
from dataclasses import dataclass
from typing import Optional

_UUID_HEX_RE = re.compile(r"^[0-9a-fA-F]{32}$")


@dataclass(frozen=True, slots=True)
class DeletionGateConfig:
    enabled: bool = True
    # UI should not require "validation mode" for safe operations.
    require_validation_mode: bool = False
    require_token: bool = True
    token_ttl_seconds: int = 900  # 15 minutes
    # Accept the pipeline plan.token (uuid4 hex) even if we didn't issue an internal token.
    allow_plan_uuid_token: bool = True


class DeletionGateError(RuntimeError):
    pass


class DeletionGate:
    """
    Central deletion safety lattice.

    Notes:
    - The pipeline already validates plan.token. This gate is an extra safety latch, used primarily for PERMANENT deletes.
    - If allow_plan_uuid_token=True, a UUID-hex token is accepted even without an internally issued token.
    """

    def __init__(self, config: Optional[DeletionGateConfig] = None):
        self.config = config or DeletionGateConfig()
        self._active_token: Optional[str] = None
        self._token_expires_at: float = 0.0
        self._token_reason: str = ""

    def issue_token(self, reason: str = "") -> str:
        token = secrets.token_hex(3).upper()  # short, human-typable
        self._active_token = token
        self._token_expires_at = time.time() + max(10, int(self.config.token_ttl_seconds))
        self._token_reason = (reason or "").strip()
        return token

    def token_status(self) -> dict:
        now = time.time()
        valid = bool(self._active_token) and now < self._token_expires_at
        return {
            "has_token": bool(self._active_token),
            "valid": valid,
            "expires_in": max(0, int(self._token_expires_at - now)) if valid else 0,
            "reason": self._token_reason,
        }

    def verify_token(self, token: Optional[str]) -> bool:
        if not token:
            return False

        t = token.strip()
        now = time.time()

        # First: explicit internal token (if present)
        if self._active_token:
            if now >= self._token_expires_at:
                return False
            return t.upper() == self._active_token

        # Fallback: accept pipeline plan.token (uuid hex)
        if self.config.allow_plan_uuid_token and _UUID_HEX_RE.match(t):
            return True

        return False

    def clear_token(self) -> None:
        self._active_token = None
        self._token_expires_at = 0.0
        self._token_reason = ""

    def assert_allowed(self, *, validation_mode: bool, token: Optional[str]) -> None:
        if not self.config.enabled:
            return

        if self.config.require_validation_mode and not validation_mode:
            raise DeletionGateError("Deletion blocked: validation mode is OFF.")

        if self.config.require_token and not self.verify_token(token):
            raise DeletionGateError("Deletion blocked: invalid or expired token.")

        # One-time token consumption only for internally issued tokens
        if self.config.require_token and self._active_token:
            self.clear_token()
