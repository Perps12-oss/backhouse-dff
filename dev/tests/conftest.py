"""Shared pytest fixtures for CEREBRO."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


@pytest.fixture
def repo_root() -> Path:
    return _REPO_ROOT


@pytest.fixture
def tmp_cerebro_home(tmp_path, monkeypatch):
    """Isolate ~/.cerebro-style paths under a temp directory."""
    home = tmp_path / "cerebro_home"
    home.mkdir()
    monkeypatch.setenv("CEREBRO_HOME", str(home))
    return home
