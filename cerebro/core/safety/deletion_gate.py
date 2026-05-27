# cerebro/core/safety/deletion_gate.py
from __future__ import annotations

import re
import secrets
import sys
import threading
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
    # UUID-hex fallback disabled by default — callers must use issue_token().
    allow_plan_uuid_token: bool = False
    # Platform-specific nlink threshold above which a file is treated as hardlinked.
    # On Windows NTFS, normal files can show st_nlink > 1 due to system metadata links.
    # Setting threshold=1 (Linux/macOS default) blocks on st_nlink > 1.
    # Setting threshold=3 (Windows default) avoids false-positives at the cost of
    # not detecting 1–2 user-created hardlinks on NTFS.
    # Override with 2 if you need strict Windows hardlink detection.
    hardlink_nlink_threshold: int = 1  # caller sets 3 for Windows; use platform_hardlink_threshold()


def platform_hardlink_threshold(config: "DeletionGateConfig") -> int:
    """Return the effective nlink threshold for the current platform.

    If the config overrides the default (1), that value is used as-is.
    Otherwise, returns 3 on Windows (NTFS false-positive guard) and 1 elsewhere.
    """
    if config.hardlink_nlink_threshold != 1:
        return config.hardlink_nlink_threshold
    return 3 if sys.platform == "win32" else 1


class DeletionGateError(RuntimeError):
    pass


class DeletionGate:
    """
    Central deletion safety lattice.

    Lifecycle:
    - One DeletionGate per CerebroPipeline instance (never construct fresh inside execute).
    - For PERMANENT deletes: caller must call issue_token() on this same instance, embed
      the returned string in plan.policy["token"], then call execute_delete_plan(plan).
    - assert_allowed() is the only authorised verification + consumption path.
    - verify_token() may be called for read-only checks (no consumption).
    - All token state mutations are protected by a threading.Lock.
    """

    def __init__(self, config: Optional[DeletionGateConfig] = None):
        self.config = config or DeletionGateConfig()
        self._lock = threading.Lock()
        self._active_token: Optional[str] = None
        self._token_expires_at: float = 0.0
        self._token_reason: str = ""

    def issue_token(self, reason: str = "") -> str:
        """Issue a new one-time deletion token. Thread-safe."""
        token = secrets.token_urlsafe(16)
        with self._lock:
            self._active_token = token
            self._token_expires_at = time.time() + max(1, int(self.config.token_ttl_seconds))
            self._token_reason = (reason or "").strip()
        return token

    def token_status(self) -> dict:
        with self._lock:
            now = time.time()
            valid = bool(self._active_token) and now < self._token_expires_at
            return {
                "has_token": bool(self._active_token),
                "valid": valid,
                "expires_in": max(0, int(self._token_expires_at - now)) if valid else 0,
                "reason": self._token_reason,
            }

    def verify_token(self, token: Optional[str]) -> bool:
        """Read-only check — does NOT consume the token. Thread-safe."""
        if not token:
            return False
        t = token.strip()
        with self._lock:
            now = time.time()
            if self._active_token:
                if now >= self._token_expires_at:
                    return False
                return secrets.compare_digest(t, self._active_token)
            # UUID-hex fallback only when explicitly enabled (default: False).
            if self.config.allow_plan_uuid_token and _UUID_HEX_RE.match(t):
                return True
        return False

    def clear_token(self) -> None:
        """Explicitly clear the active token. Thread-safe."""
        with self._lock:
            self._active_token = None
            self._token_expires_at = 0.0
            self._token_reason = ""

    def assert_allowed(self, *, validation_mode: bool, token: Optional[str]) -> None:
        """
        Verify and consume the token for a permanent deletion.
        Raises DeletionGateError on any failure. Thread-safe.
        """
        if not self.config.enabled:
            return

        if self.config.require_validation_mode and not validation_mode:
            raise DeletionGateError("Deletion blocked: validation mode is OFF.")

        if self.config.require_token:
            with self._lock:
                if not self._verify_token_locked(token):
                    raise DeletionGateError("Deletion blocked: invalid or expired token.")
                # One-time consumption of internally issued tokens.
                if self._active_token:
                    self._active_token = None
                    self._token_expires_at = 0.0
                    self._token_reason = ""

    def _verify_token_locked(self, token: Optional[str]) -> bool:
        """Internal — must be called while self._lock is held."""
        if not token:
            return False
        t = token.strip()
        now = time.time()
        if self._active_token:
            if now >= self._token_expires_at:
                return False
            return secrets.compare_digest(t, self._active_token)
        if self.config.allow_plan_uuid_token and _UUID_HEX_RE.match(t):
            return True
        return False
