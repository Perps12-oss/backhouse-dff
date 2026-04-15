"""CEREBRO v2 launcher (CustomTkinter)."""

from __future__ import annotations

import importlib.util
import sys

from cerebro.v2.ui.main_window import run_app


def _validate_environment() -> None:
    """Warn (non-fatal) when optional photo dependencies are missing."""
    missing = []
    for module_name in ("imagehash", "numpy"):
        if importlib.util.find_spec(module_name) is None:
            missing.append(module_name)
    if missing:
        print(
            "Note: missing optional image dependencies: "
            + ", ".join(missing)
            + ". Install with: pip install imagehash numpy",
            file=sys.stderr,
        )


def main() -> int:
    _validate_environment()
    run_app()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())