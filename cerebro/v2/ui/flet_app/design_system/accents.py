"""Semantic accent colors — resolved from the active palette when available."""

from __future__ import annotations

_FALLBACK_PRIMARY = "#BB86FC"
_FALLBACK_WARNING = "#FBBF24"
_FALLBACK_METADATA = "#A78BFA"
_FALLBACK_SUCCESS = "#34D399"
_FALLBACK_DANGER = "#F87171"


def _from_preset(attr: str, fallback: str) -> str:
    from cerebro.v2.ui.flet_app.theme import get_active_preset

    preset = get_active_preset()
    if preset is None:
        return fallback
    return str(getattr(preset, attr, fallback) or fallback)


def accent_primary() -> str:
    return _from_preset("primary", _FALLBACK_PRIMARY)


def accent_warning() -> str:
    return _from_preset("warning", _FALLBACK_WARNING)


def accent_metadata() -> str:
    return accent_primary()


def accent_success() -> str:
    return _from_preset("success", _FALLBACK_SUCCESS)


def accent_danger() -> str:
    return _from_preset("danger", _FALLBACK_DANGER)


def __getattr__(name: str) -> str:
    if name == "PRIMARY":
        return accent_primary()
    if name == "WARNING":
        return accent_warning()
    if name == "METADATA":
        return accent_metadata()
    if name == "SUCCESS":
        return accent_success()
    if name == "DANGER":
        return accent_danger()
    raise AttributeError(name)
