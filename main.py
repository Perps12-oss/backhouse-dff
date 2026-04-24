"""CEREBRO v2 launcher — Flet (Flutter) UI."""

from __future__ import annotations

import sys

from cerebro.runtime_deps import ensure_runtime_dependencies


def main() -> int:
    ensure_runtime_dependencies()
    from cerebro.v2.ui.flet_app.main import run_flet_app

    run_flet_app()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
