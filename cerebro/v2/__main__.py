"""Run CEREBRO v2 with `python -m cerebro.v2`."""

from __future__ import annotations

from cerebro.runtime_deps import ensure_runtime_dependencies

ensure_runtime_dependencies()

from cerebro.v2.ui.flet_app.main import run_flet_app


if __name__ == "__main__":
    run_flet_app()
