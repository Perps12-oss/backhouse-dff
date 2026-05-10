"""Shared interpretation of ``StateBridge.app_theme`` for review UI (glass, headers, cards).

``StateBridge`` documents ``light`` / ``dark`` today; we still normalize with a substring
check so future values like ``system-light`` or ``Light`` do not silently fall back to
dark glass (see review refactor regression notes).
"""


def app_theme_is_light(bridge) -> bool:
    """Return True when the active app theme should use light-scheme overlays."""
    v = getattr(bridge, "app_theme", None)
    if v is None:
        return False
    return "light" in str(v).lower()
