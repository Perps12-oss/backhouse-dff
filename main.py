"""CEREBRO v2 launcher — Flet (Flutter) UI."""

from __future__ import annotations

import multiprocessing

from cerebro.runtime_deps import ensure_runtime_dependencies


def main() -> int:
    ensure_runtime_dependencies()
    try:
        from cerebro.v2.observability import init_sentry_if_configured

        init_sentry_if_configured()
    except Exception:
        pass
    from cerebro.v2.ui.flet_app.main import run_flet_app

    run_flet_app()
    return 0


if __name__ == "__main__":
    # Required for PyInstaller + multiprocessing on Windows: without this,
    # spawned child processes re-execute the entry point and hang.
    multiprocessing.freeze_support()
    raise SystemExit(main())
