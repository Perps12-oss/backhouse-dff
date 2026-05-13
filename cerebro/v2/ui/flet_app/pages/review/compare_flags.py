"""Feature flags for review compare mode."""

from __future__ import annotations

import os

# Side-by-side compare is off by default on Flet desktop; set CEREBRO_ENABLE_COMPARE=1 to try it.
COMPARE_SIDE_BY_SIDE_ENABLED = os.getenv("CEREBRO_ENABLE_COMPARE", "").strip().lower() in (
    "1",
    "true",
    "yes",
)
