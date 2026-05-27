"""Flet API compatibility helpers for supported version ranges.

Supported for production installs: 0.84.x (see pyproject.toml / requirements.txt).
CI also exercises 0.80.x to validate dropdown event shims.
"""

from __future__ import annotations

from typing import Any, Callable

import flet as ft

# Declared support band (inclusive min, exclusive max).
SUPPORTED_FLET_MIN = (0, 84, 0)
SUPPORTED_FLET_MAX = (0, 85, 0)

# Dropdown selection event renamed in newer Flet control APIs.
_DROPDOWN_ON_SELECT_MIN = (0, 80, 0)


def parse_flet_version(version: str) -> tuple[int, ...]:
    """Parse ``'0.84.0'`` / ``'0.84.0+local'`` into a numeric tuple."""
    parts: list[int] = []
    for piece in (version or "0").strip().split("."):
        if not piece:
            continue
        head = piece.split("-", 1)[0].split("+", 1)[0]
        try:
            parts.append(int(head))
        except ValueError:
            break
    return tuple(parts) if parts else (0,)


def flet_version_string() -> str:
    """Installed Flet version string."""
    try:
        from flet.version import version as v

        return str(v)
    except Exception:
        return str(getattr(ft, "__version__", "0.0.0"))


def version_in_range(
    version: tuple[int, ...],
    *,
    min_version: tuple[int, ...],
    max_version: tuple[int, ...],
) -> bool:
    return min_version <= version < max_version


def assert_supported_flet() -> None:
    """Raise ``RuntimeError`` when the installed Flet is outside the declared band."""
    v = parse_flet_version(flet_version_string())
    if not version_in_range(v, min_version=SUPPORTED_FLET_MIN, max_version=SUPPORTED_FLET_MAX):
        raise RuntimeError(
            "Unsupported Flet version "
            f"{'.'.join(map(str, v)) or 'unknown'}; "
            f"requires >= {'.'.join(map(str, SUPPORTED_FLET_MIN))} "
            f"and < {'.'.join(map(str, SUPPORTED_FLET_MAX))}."
        )


def dropdown_uses_on_select(version: str | None = None) -> bool:
    """Return True when ``ft.Dropdown`` should use ``on_select`` (Flet >= 0.80)."""
    v = parse_flet_version(version or flet_version_string())
    return v >= _DROPDOWN_ON_SELECT_MIN


def dropdown_handler_kwargs(
    handler: Callable[..., Any],
    *,
    version: str | None = None,
) -> dict[str, Callable[..., Any]]:
    """Keyword args for wiring a Dropdown change handler across Flet versions."""
    if dropdown_uses_on_select(version):
        return {"on_select": handler}
    return {"on_change": handler}


def bind_dropdown(
    dropdown: ft.Dropdown,
    handler: Callable[..., Any],
    *,
    version: str | None = None,
) -> ft.Dropdown:
    """Attach a change handler using the correct event name for the installed Flet."""
    name = "on_select" if dropdown_uses_on_select(version) else "on_change"
    setattr(dropdown, name, handler)
    return dropdown
