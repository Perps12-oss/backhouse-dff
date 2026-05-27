"""Marshal callbacks onto the Flet UI asyncio loop (never worker threads)."""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

import flet as ft

_log = logging.getLogger(__name__)


def flet_page_session_alive(page: ft.Page) -> bool:
    """True if the Flet page still has a live transport (window not closed)."""
    try:
        sess = getattr(page, "session", None)
        if sess is None:
            return False
        _ = sess.connection  # noqa: SLF001
        return True
    except RuntimeError as exc:
        if "destroyed session" in str(exc).lower():
            return False
        raise


def run_on_ui_thread(
    page: Optional[ft.Page],
    fn: Callable[..., None],
    *args: Any,
    refresh_page: bool = True,
) -> None:
    """Schedule *fn* on the Flet session loop via ``page.run_task``.

    ``Page.run_thread`` must not be used for control mutations — it runs on a
    worker thread. This helper is the single supported path from scan/delete/
    stats worker threads back to UI code.
    """
    if page is None:
        fn(*args)
        return
    if not hasattr(page, "run_task"):
        fn(*args)
        return

    if not flet_page_session_alive(page):
        _log.debug(
            "Skipping UI marshal (Flet session ended): %s",
            getattr(fn, "__name__", repr(fn)),
        )
        return

    async def _run_ui() -> None:
        fn(*args)
        if not refresh_page:
            return
        try:
            if hasattr(page, "update_async"):
                await page.update_async()  # type: ignore[misc]
            else:
                page.update()
        except Exception:
            try:
                page.update()
            except Exception:
                pass

    try:
        page.run_task(_run_ui)
    except RuntimeError as exc:
        if "destroyed session" in str(exc).lower():
            _log.debug(
                "Skipping UI marshal (Flet session ended): %s",
                getattr(fn, "__name__", repr(fn)),
            )
            return
        _log.exception("Failed to schedule UI callback via page.run_task")
    except Exception:
        _log.exception("Failed to schedule UI callback via page.run_task")
        try:
            fn(*args)
        except Exception:
            _log.exception("Fallback UI callback failed")
