"""
Entry point: ``python -m cerebro`` — proves the engine stack imports without the GUI (Blueprint §7).
"""

from __future__ import annotations


import cerebro
from cerebro.engines.base_engine import ScanState


def main() -> int:
    print(
        f"cerebro {cerebro.__version__} - engine: ScanState={ScanState.IDLE!r} "
        f"(import OK, no UI required)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
