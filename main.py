"""CEREBRO v2 launcher (CustomTkinter)."""

from __future__ import annotations

import sys

from cerebro.runtime_deps import ensure_runtime_dependencies


def main() -> int:
    ensure_runtime_dependencies()
    # Import UI only after optional bootstrap (so pip can install CustomTkinter first).
    from cerebro.v2.ui.app_shell import run_app

    run_app()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
