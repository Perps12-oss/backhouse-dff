"""Run CEREBRO v2 with `python -m cerebro.v2`."""

from __future__ import annotations

from cerebro.runtime_deps import ensure_runtime_dependencies

ensure_runtime_dependencies()

from .ui.app_shell import run_app


if __name__ == "__main__":
    run_app()
