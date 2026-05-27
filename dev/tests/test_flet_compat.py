from __future__ import annotations

import pytest

from cerebro.v2.ui.flet_app import flet_compat


def test_parse_flet_version() -> None:
    assert flet_compat.parse_flet_version("0.84.0") == (0, 84, 0)
    assert flet_compat.parse_flet_version("0.80.1+local") == (0, 80, 1)


@pytest.mark.parametrize(
    ("version", "expected_key"),
    [
        ("0.79.0", "on_change"),
        ("0.80.0", "on_select"),
        ("0.84.0", "on_select"),
    ],
)
def test_dropdown_handler_kwargs_by_version(version: str, expected_key: str) -> None:
    kwargs = flet_compat.dropdown_handler_kwargs(lambda e: None, version=version)
    assert expected_key in kwargs
    assert len(kwargs) == 1


def test_supported_version_band() -> None:
    assert flet_compat.version_in_range(
        (0, 84, 0),
        min_version=flet_compat.SUPPORTED_FLET_MIN,
        max_version=flet_compat.SUPPORTED_FLET_MAX,
    )
    assert not flet_compat.version_in_range(
        (0, 85, 0),
        min_version=flet_compat.SUPPORTED_FLET_MIN,
        max_version=flet_compat.SUPPORTED_FLET_MAX,
    )


def test_assert_supported_flet_accepts_current(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(flet_compat, "flet_version_string", lambda: "0.84.0")
    flet_compat.assert_supported_flet()


def test_assert_supported_flet_rejects_old(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(flet_compat, "flet_version_string", lambda: "0.25.0")
    with pytest.raises(RuntimeError, match="Unsupported Flet"):
        flet_compat.assert_supported_flet()
