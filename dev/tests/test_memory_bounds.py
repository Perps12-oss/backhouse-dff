"""
Memory bounds tests — run with pytest-memray:
  pytest tests/test_memory_bounds.py --memray

Each test is decorated with @pytest.mark.limit_memory to assert a ceiling.
Without --memray the decorator is a no-op so these tests also run in regular CI.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest


@pytest.fixture()
def fresh_cerebro_import():
    """Snapshot sys.modules and restore after the test.

    These tests pop ``cerebro.*`` from sys.modules to measure the heap delta
    of a fresh import. Without this fixture, a later test that imported a
    cerebro symbol at module-collection time (e.g. ``from cerebro.engines.
    turbo_file_engine import TurboFileEngine``) would still hold a reference
    to the *old* class object, while ``isinstance`` checks created via a
    *new* import would fail. Restoring sys.modules to its pre-test state
    keeps test ordering hermetic.
    """
    snapshot = {k: v for k, v in sys.modules.items() if k.startswith("cerebro")}
    yield
    # Drop anything imported during the test, then restore originals.
    for k in [k for k in sys.modules if k.startswith("cerebro")]:
        sys.modules.pop(k, None)
    sys.modules.update(snapshot)


# ---------------------------------------------------------------------------
# Import footprint
# ---------------------------------------------------------------------------

@pytest.mark.limit_memory("50 MB")
def test_cerebro_import_memory_footprint(fresh_cerebro_import) -> None:
    """Importing the cerebro package uses less than 50 MB of heap."""
    for k in [k for k in sys.modules if k.startswith("cerebro")]:
        sys.modules.pop(k, None)

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
def test_hash_cache_import_footprint(fresh_cerebro_import) -> None:
    """Hash cache module import stays under 50 MB."""
    for k in [k for k in sys.modules if "hash_cache" in k]:
        sys.modules.pop(k, None)

    from cerebro.services import hash_cache  # noqa: F401
