"""
Memory bounds tests — run with pytest-memray:
  pytest tests/test_memory_bounds.py --memray

Each test is decorated with @pytest.mark.limit_memory to assert a ceiling.
Without --memray the decorator is a no-op so these tests also run in regular CI.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Import footprint
# ---------------------------------------------------------------------------

@pytest.mark.limit_memory("50 MB")
def test_cerebro_import_memory_footprint() -> None:
    """Importing the cerebro package uses less than 50 MB of heap."""
    # Force a fresh import by removing from sys.modules if already present
    # (only matters when running this file in isolation)
    mods_to_remove = [k for k in sys.modules if k.startswith("cerebro")]
    for m in mods_to_remove:
        sys.modules.pop(m, None)

    import cerebro  # noqa: F401


# ---------------------------------------------------------------------------
# History store
# ---------------------------------------------------------------------------

@pytest.mark.limit_memory("50 MB")
def test_history_store_1000_appends_memory(tmp_path: Path) -> None:
    """Appending 1000 audit records stays under 50 MB."""
    from cerebro.history.store import HistoryStore

    store = HistoryStore(base_dir=tmp_path / "history")
    for i in range(1_000):
        store.record_deletion(
            scan_id=f"mem-{i}",
            mode="trash",
            groups=1,
            deleted=2,
            failed=0,
            bytes_reclaimed=4096,
            source="memory_test",
            policy={},
            details=[],
        )


# ---------------------------------------------------------------------------
# Hash cache (SQLite)
# ---------------------------------------------------------------------------

@pytest.mark.limit_memory("50 MB")
def test_hash_cache_import_footprint() -> None:
    """Hash cache module import stays under 50 MB."""
    mods = [k for k in sys.modules if "hash_cache" in k]
    for m in mods:
        sys.modules.pop(m, None)

    from cerebro.services import hash_cache  # noqa: F401
