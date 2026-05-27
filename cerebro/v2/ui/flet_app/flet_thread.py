"""
cerebro/v2/ui/flet_app/flet_thread.py — Flet threading enforcement (LT-1 / IS-3).

Flet page operations (adding controls, calling page.update(), page.snack_bar = ...)
must run on the thread that owns the Flet page event loop.  Calling them from
background threads causes subtle glitches or hard crashes.

Usage in state_bridge / controller methods that touch `page`:

    from cerebro.v2.ui.flet_app.flet_thread import assert_flet_thread
    assert_flet_thread()  # at the top of any method that touches page

In production this is a no-op unless CEREBRO_DEBUG=1.
In debug mode it raises AssertionError when called from a non-main thread.
"""

from __future__ import annotations

import os
import threading

_DEBUG = os.environ.get("CEREBRO_DEBUG", "0") == "1"


def assert_flet_thread(*, msg: str = "") -> None:
    """
    Assert that the calling code runs on the Flet main thread.

    In production (CEREBRO_DEBUG != "1"): no-op.
    In debug builds: raises AssertionError if called from a worker thread.
    """
    if not _DEBUG:
        return
    is_main = threading.current_thread() is threading.main_thread()
    if not is_main:
        caller = msg or "Flet page operation"
        raise AssertionError(
            f"{caller} called from thread '{threading.current_thread().name}' — "
            "must run on the Flet main thread. "
            "Use page.run_task() or page.call_on_main_thread() to schedule from workers."
        )
