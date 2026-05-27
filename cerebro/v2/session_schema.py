"""Validate persisted review session JSON before applying to UI state."""

from __future__ import annotations

from typing import Any, Dict, List, Set, Tuple

_ALLOWED_SCREENS = frozenset({"overview", "browse", "inspect"})


def validate_review_session_payload(payload: Any) -> Tuple[bool, str, Dict[str, Any]]:
    """Return (ok, error_message, normalized_payload)."""
    if not isinstance(payload, dict):
        return False, "session root must be an object", {}
    version = payload.get("version", 1)
    if version != 1:
        return False, f"unsupported session version {version!r}", {}

    screen = payload.get("active_screen")
    if screen == "cart":
        screen = "browse"
    if screen in {"execute", "report"}:
        screen = "browse"
    if screen not in _ALLOWED_SCREENS:
        return False, f"invalid active_screen {screen!r}", {}

    marked = payload.get("marked_paths", [])
    if not isinstance(marked, list) or not all(isinstance(p, str) for p in marked):
        return False, "marked_paths must be a list of strings", {}

    selected = payload.get("selected_set_ids", [])
    if not isinstance(selected, list):
        return False, "selected_set_ids must be a list", {}
    try:
        selected_ids: Set[int] = {int(x) for x in selected}
    except (TypeError, ValueError):
        return False, "selected_set_ids must be numeric", {}

    layout_raw = payload.get("inspect_layout_by_set", {})
    parsed_layout: Dict[int, Tuple[int, int, bool]] = {}
    if layout_raw is not None:
        if not isinstance(layout_raw, dict):
            return False, "inspect_layout_by_set must be an object", {}
        for k, v in layout_raw.items():
            try:
                gid = int(k)
                if isinstance(v, (list, tuple)) and len(v) >= 3:
                    parsed_layout[gid] = (int(v[0]), int(v[1]), bool(v[2]))
            except (TypeError, ValueError):
                continue
        while len(parsed_layout) > 200:
            oldest = next(iter(parsed_layout))
            del parsed_layout[oldest]

    normalized = {
        "version": 1,
        "active_screen": screen,
        "marked_paths": sorted({str(p) for p in marked}),
        "selected_set_ids": sorted(selected_ids),
        "inspect_layout_by_set": {
            str(gid): [ref, cmp_i, swap]
            for gid, (ref, cmp_i, swap) in sorted(parsed_layout.items())
        },
    }
    return True, "", normalized
