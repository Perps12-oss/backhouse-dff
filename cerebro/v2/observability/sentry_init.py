"""Optional Sentry crash reporting (opt-in via environment)."""

from __future__ import annotations

import logging
import os

_log = logging.getLogger(__name__)


def init_sentry_if_configured() -> bool:
    """Initialize Sentry when ``CEREBRO_SENTRY_DSN`` is set. Returns True if initialized."""
    dsn = os.environ.get("CEREBRO_SENTRY_DSN", "").strip()
    if not dsn:
        return False
    try:
        import sentry_sdk
    except ImportError:
        _log.warning("CEREBRO_SENTRY_DSN set but sentry-sdk is not installed")
        return False

    def _before_send(event, hint):  # noqa: ANN001
        # Scrub common path prefixes from exception messages.
        try:
            for exc in (event.get("exception") or {}).get("values") or []:
                val = exc.get("value")
                if isinstance(val, str) and len(val) > 4096:
                    exc["value"] = val[:4096] + "…"
        except Exception:
            pass
        return event

    sentry_sdk.init(
        dsn=dsn,
        traces_sample_rate=float(os.environ.get("CEREBRO_SENTRY_TRACES_SAMPLE_RATE", "0")),
        before_send=_before_send,
        send_default_pii=False,
    )
    _log.info("Sentry initialized (crash reporting enabled)")
    return True
