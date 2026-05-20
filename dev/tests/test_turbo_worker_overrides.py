"""Tests for the Tier-A / hash worker env overrides and removable detection."""
from __future__ import annotations

import cerebro.engines.turbo_file_engine as tfe


def test_env_int_parsing(monkeypatch):
    monkeypatch.setenv("CEREBRO_TEST_WORKERS", "24")
    assert tfe._env_int("CEREBRO_TEST_WORKERS") == 24


def test_env_int_unset_is_zero(monkeypatch):
    monkeypatch.delenv("CEREBRO_TEST_WORKERS", raising=False)
    assert tfe._env_int("CEREBRO_TEST_WORKERS") == 0


def test_env_int_invalid_is_zero(monkeypatch):
    monkeypatch.setenv("CEREBRO_TEST_WORKERS", "not-a-number")
    assert tfe._env_int("CEREBRO_TEST_WORKERS") == 0


def test_env_int_negative_clamped_to_zero(monkeypatch):
    monkeypatch.setenv("CEREBRO_TEST_WORKERS", "-5")
    assert tfe._env_int("CEREBRO_TEST_WORKERS") == 0


def test_is_removable_drive_never_raises():
    # Must be safe on any platform / nonexistent drive (returns bool, no exception).
    assert isinstance(tfe._is_removable_drive("I"), bool)
